"""Compatibility shim for windows exported from CTk Maker (github.com/kandelucky/ctk_maker).

CTk Maker builds against its own CustomTkinter fork, "ctkmaker-core", which
adds a handful of widget options (``full_circle``, ``pressed_color``,
``image_color``, ``unified_bind``, ``font_wrap``) and four module-level
helpers (``bind_var_to_widget``, ``balance_pack``, ``bind_var_to_image_color``,
``register_project_fonts``) that the official ``customtkinter`` package on
PyPI does not know about. Exported code fails immediately against a plain
install, e.g. ``CTkButton() got an unexpected keyword argument 'full_circle'``.

``ctkmaker-core`` is still a pre-1.0 fork, so this module re-implements the
missing surface on top of stock ``customtkinter`` instead of depending on it.
Call ``patch()`` once, before building any window.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

import customtkinter as ctk
from PIL import Image


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


def _resolve_color(color: Any) -> str:
    """CTk colors may be a (light, dark) tuple; pick the mode CTk is using."""
    if isinstance(color, (tuple, list)):
        return color[0] if ctk.get_appearance_mode() == "Light" else color[-1]
    return color


def _full_circle_radius(kwargs: dict) -> int:
    dims = [d for d in (kwargs.get("width"), kwargs.get("height")) if isinstance(d, (int, float))]
    return int(min(dims) // 2) if dims else 999


# ── module-level helpers ────────────────────────────────────────────────────

def bind_var_to_widget(var: tk.Variable, widget, attr: str) -> None:
    """Keep *widget*'s *attr* option mirrored to *var*'s value."""
    def _apply(*_a) -> None:
        try:
            widget.configure(**{attr: var.get()})
        except Exception:
            pass
    _apply()
    var.trace_add("write", _apply)


def bind_var_to_image_color(var: tk.Variable, widget) -> None:
    """Keep a button's tinted icon in sync with a color variable."""
    def _apply(*_a) -> None:
        _retint(widget, var.get())
    _apply()
    var.trace_add("write", _apply)


def balance_pack(container, dimension: str) -> None:
    """Distribute *container*'s pack-managed children along *dimension*.

    Children flagged ``_ctkmaker_fixed`` keep their configured minimum size
    (``_ctkmaker_min``); the rest share whatever space is left, never
    shrinking below their own minimum.
    """
    children = container.pack_slaves()
    if not children:
        return
    total = container.winfo_height() if dimension == "height" else container.winfo_width()
    if total <= 1:
        return

    fixed_total = 0
    flexible = []
    for w in children:
        min_size = getattr(w, "_ctkmaker_min", 0)
        if getattr(w, "_ctkmaker_fixed", False):
            fixed_total += min_size
        else:
            flexible.append((w, min_size))
    if not flexible:
        return

    remaining = max(total - fixed_total, 0)
    share = remaining // len(flexible)
    for w, min_size in flexible:
        try:
            w.configure(**{dimension: max(share, min_size)})
        except Exception:
            pass


def register_project_fonts(window, fonts_dir) -> None:
    """Load .ttf/.otf files from *fonts_dir* so CTkFont can reference them by
    family name. No-op if the folder or the optional ``tkextrafont`` loader
    is missing.
    """
    fonts_dir = Path(fonts_dir)
    if not fonts_dir.is_dir():
        return
    try:
        from tkextrafont import Font as _ExtraFont
    except ImportError:
        return
    for font_file in list(fonts_dir.glob("*.ttf")) + list(fonts_dir.glob("*.otf")):
        try:
            _ExtraFont(file=str(font_file))
        except Exception:
            pass


# ── widget-option shims ─────────────────────────────────────────────────────

def _retint(widget, color) -> None:
    """Recolor a monochrome CTkImage using its alpha channel as a mask."""
    try:
        image = widget.cget("image")
    except Exception:
        return
    if not isinstance(image, ctk.CTkImage):
        return

    light = getattr(image, "_light_image", None)
    dark = getattr(image, "_dark_image", None)
    if light is None or dark is None:
        return

    rgb = _hex_to_rgb(_resolve_color(color))

    def _tint(pil_img):
        pil_img = pil_img.convert("RGBA")
        alpha = pil_img.split()[-1]
        solid = Image.new("RGBA", pil_img.size, (*rgb, 255))
        solid.putalpha(alpha)
        return solid

    size = getattr(image, "_size", None)
    tinted = ctk.CTkImage(light_image=_tint(light), dark_image=_tint(dark), size=size)
    widget.configure(image=tinted)
    widget._ctkmaker_tinted_image = tinted  # keep a reference alive


def _bind_pressed_color(button, pressed_color) -> None:
    normal = button.cget("fg_color")
    button.bind("<ButtonPress-1>", lambda _e: button.configure(fg_color=pressed_color), add="+")
    button.bind("<ButtonRelease-1>", lambda _e: button.configure(fg_color=normal), add="+")


def _patched_button_init(self, *args, **kwargs):
    full_circle = kwargs.pop("full_circle", False)
    pressed_color = kwargs.pop("pressed_color", None)
    image_color = kwargs.pop("image_color", None)
    if full_circle:
        kwargs["corner_radius"] = _full_circle_radius(kwargs)
    _orig_button_init(self, *args, **kwargs)
    if pressed_color is not None:
        _bind_pressed_color(self, pressed_color)
    if image_color is not None:
        _retint(self, image_color)


def _patched_label_init(self, *args, **kwargs):
    kwargs.pop("unified_bind", None)
    kwargs.pop("font_wrap", None)
    if kwargs.pop("full_circle", False):
        kwargs["corner_radius"] = _full_circle_radius(kwargs)
    _orig_label_init(self, *args, **kwargs)


_orig_button_init = ctk.CTkButton.__init__
_orig_label_init = ctk.CTkLabel.__init__


def patch() -> None:
    """Install the shim. Safe to call more than once."""
    if getattr(ctk, "_ctkmaker_compat_patched", False):
        return
    ctk.bind_var_to_widget = bind_var_to_widget
    ctk.bind_var_to_image_color = bind_var_to_image_color
    ctk.balance_pack = balance_pack
    ctk.register_project_fonts = register_project_fonts
    ctk.CTkButton.__init__ = _patched_button_init
    ctk.CTkLabel.__init__ = _patched_label_init
    ctk._ctkmaker_compat_patched = True
