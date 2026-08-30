def bind_hotkey_capture(window, entry, on_captured=None) -> None:
    """Live hotkey combo capture: click to start, keys fill as held, capture ends
    _CAPTURE_FINALIZE_DELAY_MS after the last key event once nothing is held.
    Fires `on_captured(text)` when done.

    Finalizing on a short idle gap (rather than the instant `held` hits zero)
    tolerates a single dropped or reordered KeyRelease — a fast press+release
    can otherwise leave `held` never fully clearing, silently freezing capture
    until the field is re-armed and tried again more slowly.
    """
    state = {"active": False, "held": set(), "peak": set(), "finalize_job": None}

    def _render() -> str:
        return "+".join(_hotkey_label(k) for k in sorted(state["peak"], key=_hotkey_sort_key))

    def _update_entry() -> None:
        entry.delete(0, "end")
        entry.insert(0, _render())

    def _cancel_finalize() -> None:
        if state["finalize_job"] is not None:
            window.after_cancel(state["finalize_job"])
            state["finalize_job"] = None

    def _finalize() -> None:
        state["finalize_job"] = None
        if not state["active"] or not state["peak"]:
            state["active"] = False
            return
        state["active"] = False
        # Use on_captured when the field has no separate Save button and needs to persist immediately
        # (mapping.py does this; profiles.py doesn't, since fcpeh_save reads the entry directly).
        if on_captured:
            on_captured(_render())
        # Release focus once captured so arrow keys/Backspace/Delete
        # can't then edit the result as ordinary text.
        window.focus_set()

    def _schedule_finalize() -> None:
        _cancel_finalize()
        state["finalize_job"] = window.after(_CAPTURE_FINALIZE_DELAY_MS, _finalize)

    # held/peak sets prevent a key released and pressed again mid-combo from appearing twice.
    def _on_press(event):
        if not state["active"]:
            return "break" # focused without a click (e.g. pre-filled for editing) — stay read-only
        _cancel_finalize()  # another key joined the combo — not done yet
        state["held"].add(event.keysym)
        state["peak"].add(event.keysym)
        _update_entry()
        return "break"

    def _on_release(event):
        if not state["active"]:
            return None
        state["held"].discard(event.keysym)
        if not state["held"]:
            _schedule_finalize()
        return "break"

    def _on_focus_out(_event=None) -> None:
        # Focus lost mid-capture — KeyRelease events for still-held keys
        # will never arrive (shell intercepted them, window minimized, etc.).
        # If we have something in peak, finalize it now rather than leaving
        # capture frozen. Use a short after() so the focus change fully
        # settles before we call on_captured (which may itself shift focus).
        if state["active"] and state["peak"]:
            _schedule_finalize()
        elif state["active"] and not state["peak"]:
            # Focused and lost focus before pressing anything — just disarm.
            state["active"] = False
            _cancel_finalize()
    def _start(_event=None) -> None:
        _cancel_finalize()
        state["active"] = True
        state["held"] = set()
        state["peak"] = set()
        entry.delete(0, "end")
        entry.focus_set()

    def _swallow_navigation(_event=None):
        # Tab (and Shift-Tab) trigger Tk's focus-traversal via a
        # separate binding path from generic <KeyPress>, so "break"
        # from _on_press alone doesn't stop focus jumping mid-capture.
        if state["active"]:
            return "break"
        return None

    entry.bind("<Button-1>", _start)
    entry.bind("<KeyPress>", _on_press)
    entry.bind("<KeyRelease>", _on_release)
    entry.bind("<FocusOut>", _on_focus_out)
    # ISO_Left_Tab (the X11/Linux keysym for Shift+Tab some window
    # managers send) isn't included — Tk on Windows raises TclError at
    # bind time for it. <Shift-Tab> alone already covers Windows.
    for sequence in ("<Tab>", "<Shift-Tab>"):
        try:
            entry.bind(sequence, _swallow_navigation, add="+")
        except tk.TclError:
            pass
