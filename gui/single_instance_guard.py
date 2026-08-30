#
# gui/single_instance_guard.py
# Single-instance guard for the config GUI, with bring-to-front on repeat launch.
#

"""
Mirrors service/single_instance.py's named-mutex approach (see that module's
docstring for why a mutex over a lock file), under its own mutex name so the
GUI and the service guard independently.

A second GUI launch should feel like clicking the taskbar icon: the second
process signals the first over a named pipe, and the first process raises
itself from within its own Tkinter event loop via window.after(). Because
the raise happens inside the process that owns the window, Windows grants
it foreground rights without the restrictions a background process would
hit calling SetForegroundWindow directly.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading

from service import single_instance

MUTEX_NAME = "VaderRemapperConfig"
PIPE_NAME = r"\\.\pipe\VaderRemapperConfigRaise"
RAISE_SIGNAL = b"RAISE"

# Delay before raising, after receiving the signal. The launch that
# triggers this (double-click, taskbar relaunch) may still have input
# in flight when the signal arrives; raising too early can let that
# stray click land on the now-foregrounded window.
RAISE_DELAY_MS = 250

try:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.SetForegroundWindow.restype = wt.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wt.HWND
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    user32.AttachThreadInput.restype = wt.BOOL

    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wt.DWORD
except AttributeError:
    user32 = None
    kernel32 = None


# ---------------------------------------------------------------------------
# Second-process side: signal the existing instance and exit.
# ---------------------------------------------------------------------------

def _signal_existing_instance() -> None:
    """Send the raise signal to the first instance's named pipe.
    Pure ctypes — no pywin32 dependency.
    """
    GENERIC_WRITE     = 0x40000000
    OPEN_EXISTING     = 3
    INVALID_HANDLE    = ctypes.c_void_p(-1).value

    kernel32 = ctypes.windll.kernel32

    handle = kernel32.CreateFileW(
        PIPE_NAME,
        GENERIC_WRITE,
        0,          # no sharing
        None,       # default security
        OPEN_EXISTING,
        0,          # default attributes
        None,       # no template
    )

    if handle == INVALID_HANDLE:
        # Pipe not ready yet or first instance not listening — silently do nothing.
        try:
            with open("gui_single_instance.log", "a", encoding="utf-8") as f:
                err = kernel32.GetLastError()
                f.write(f"_signal_existing_instance: CreateFileW failed, error={err}\n")
        except Exception:
            pass
        return

    try:
        data     = RAISE_SIGNAL
        written  = ctypes.c_ulong(0)
        kernel32.WriteFile(
            handle,
            data,
            len(data),
            ctypes.byref(written),
            None,
        )
    finally:
        kernel32.CloseHandle(handle)


# ---------------------------------------------------------------------------
# First-process side: listen on the named pipe and raise when signalled.
# ---------------------------------------------------------------------------

def _raise_window(window) -> None:
    """Bring the GUI window to the foreground. Runs on the Tkinter main
    thread via window.after(), so it's safe to touch widgets here.
    """
    try:
        hwnd = int(window.frame(), 16)
    except Exception:
        hwnd = None

    try:
        window.deiconify()
        window.attributes("-topmost", True)
        window.lift()
        window.focus_force()
    except Exception:
        pass

    # SetForegroundWindow alone is denied unless the calling thread
    # owns the current foreground. AttachThreadInput temporarily merges
    # input state with the foreground thread so the transfer succeeds -
    # safe here since we're on our own main thread, not an unrelated
    # background thread with a popup of its own in flight.
    if hwnd is not None and user32 is not None and kernel32 is not None:
        try:
            fg_hwnd = user32.GetForegroundWindow()
            our_tid = kernel32.GetCurrentThreadId()
            fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)

            attached = False
            if fg_tid and fg_tid != our_tid:
                attached = bool(user32.AttachThreadInput(fg_tid, our_tid, True))

            try:
                user32.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(fg_tid, our_tid, False)
        except Exception:
            pass

    try:
        window.after(100, lambda: window.attributes("-topmost", False))
    except Exception:
        pass


def _pipe_listener(window, stop_event: threading.Event) -> None:
    """Block on a named pipe server, raising the window each time a
    second instance connects and sends the raise signal.
    """
    PIPE_ACCESS_INBOUND = 0x00000001
    PIPE_TYPE_MESSAGE = 0x00000004
    PIPE_READMODE_MESSAGE = 0x00000002
    PIPE_WAIT = 0x00000000
    NMPWAIT_USE_DEFAULT_WAIT = 0
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    while not stop_event.is_set():
        pipe = kernel32.CreateNamedPipeW(
            PIPE_NAME,
            PIPE_ACCESS_INBOUND,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
            1,  # max instances
            512, 512,
            NMPWAIT_USE_DEFAULT_WAIT,
            None,
        )
        if pipe == INVALID_HANDLE_VALUE:
            break

        kernel32.ConnectNamedPipe(pipe, None)  # blocks until a client connects
        if stop_event.is_set():
            kernel32.CloseHandle(pipe)
            break

        buf = (ctypes.c_char * 512)()
        read = ctypes.c_ulong(0)
        ok = kernel32.ReadFile(pipe, buf, 512, ctypes.byref(read), None)
        kernel32.CloseHandle(pipe)

        if ok and buf.raw[: read.value] == RAISE_SIGNAL:
            try:
                window.after(RAISE_DELAY_MS, lambda: _raise_window(window))
            except Exception:
                pass


def start_pipe_listener(window) -> threading.Thread:
    """Start the background pipe-listener thread. Call once from
    MainPage.py after the Tkinter root window exists.
    """
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_pipe_listener,
        args=(window, stop_event),
        daemon=True,
        name="SingleInstancePipeListener",
    )
    thread.start()
    window._pipe_stop_event = stop_event  # keep alive, allow future cleanup
    return thread


# ---------------------------------------------------------------------------
# Entry point called before ctk.CTk() in MainPage.py
# ---------------------------------------------------------------------------

def ensure_single_instance() -> bool:
    """
    Returns True if this process should continue starting up.

    Returns False if another instance is already running — it has been
    signalled to raise itself, and the caller should exit immediately.
    """
    if single_instance.acquire(MUTEX_NAME):
        return True

    _signal_existing_instance()
    return False
