"""Native window chrome styling.

Qt owns the window frame, but on Windows the caption itself is drawn by DWM.  Keep
the native minimise/maximise/close controls and ask DWM to match the application
theme instead of showing the default light caption.
"""

from __future__ import annotations

import sys


def _colorref(hex_color: str) -> int:
    """Convert ``#RRGGBB`` to the BGR COLORREF representation used by Win32."""
    value = hex_color.removeprefix("#")
    if len(value) != 6:
        raise ValueError("A #RRGGBB color is required")
    red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    return red | (green << 8) | (blue << 16)


def apply_window_chrome(window) -> None:
    """Apply Shah-NVR colors to a native Windows title bar, when supported."""
    if sys.platform != "win32":
        return

    # Imported lazily so this module remains harmless and importable on Linux/macOS.
    import ctypes
    from ctypes import wintypes

    hwnd = wintypes.HWND(int(window.winId()))
    set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute

    def set_int(attribute: int, value: int) -> None:
        data = ctypes.c_int(value)
        set_attribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))

    def set_color(attribute: int, color: str) -> None:
        data = wintypes.DWORD(_colorref(color))
        set_attribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))

    # 20 is the public DWMWA_USE_IMMERSIVE_DARK_MODE value on current Windows.
    # Attribute 19 supports older Windows 10 builds and is safe to attempt.
    set_int(20, 1)
    set_int(19, 1)

    # Windows 11 caption, text and frame colors. Unsupported attributes are simply
    # ignored by older DWM versions, leaving immersive dark mode in effect.
    # set_color(35, "#303744")  # DWMWA_CAPTION_COLOR / distinct dark slate
    set_color(35, "#272b33")  # DWMWA_CAPTION_COLOR / distinct dark slate
    set_color(36, "#eceff4")  # DWMWA_TEXT_COLOR / Theme.foreground
    set_color(34, "#4c566a")  # DWMWA_BORDER_COLOR / Theme.border
