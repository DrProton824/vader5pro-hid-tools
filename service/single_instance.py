#
# service/single_instance.py
# Single-instance guard using a named Win32 mutex.
#

"""
Why a mutex and not a lock file / PID file?
─────────────────────────────────────────────
A named kernel mutex is owned by the OS, not by us. If the process is
killed, crashes, or the machine loses power, Windows releases the mutex
automatically the instant the process handle table is torn down – there
is no stale-lock-file cleanup logic to get wrong, and no race window
where a crashed process leaves a lock file behind and blocks all future
launches.

Usage
─────
    from service import single_instance

    if not single_instance.acquire("VaderRemapperService"):
        # another copy is already running – bail out
        sys.exit(0)

    # ... normal startup, mutex is held for the lifetime of the process ...

Call ``acquire()`` once, as early as possible in ``main()``. There is no
``release()`` – the mutex is released automatically on process exit.
"""

from __future__ import annotations

import ctypes

ERROR_ALREADY_EXISTS = 183

# Keep the handle alive for the lifetime of the process – if this gets
# garbage collected / closed, the mutex is released and a second copy
# of the app could start.
_handle = None


def acquire(name: str) -> bool:
    """
    Try to become the one-and-only instance identified by ``name``.

    Returns True if this process now owns the lock (i.e. it's the first
    and only instance). Returns False if another instance already holds
    it – the caller should exit without doing any further startup work.

    Fails "open" (returns True) if the mutex API itself is unavailable,
    e.g. when imported on a non-Windows platform during development –
    a single-instance guard should never be the reason the app can't
    start at all.
    """
    global _handle

    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError:
        return True

    # "Local\\" scopes the mutex to the current login session, which is
    # what we want – two different users on the same machine should each
    # be able to run their own copy.
    mutex_name = f"Local\\{name}"

    handle = kernel32.CreateMutexW(None, False, mutex_name)
    if not handle:
        # Could not create the mutex at all (unexpected) – don't block
        # the app from starting over an OS-level surprise.
        return True

    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False

    _handle = handle  # keep alive
    return True
