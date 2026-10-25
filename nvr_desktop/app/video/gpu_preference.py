"""Which graphics card Windows runs this app on (laptops / PCs with two GPUs).

Windows decides per executable, from Settings -> System -> Display -> Graphics, which stores
`GpuPreference=N;` under HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences with the full .exe path
as the value name (0 = let Windows decide, 1 = power saving, 2 = high performance). This module reads
and writes that same value for the running interpreter (`sys.executable`), so the app's Settings and
Windows' Settings always agree. It applies from the next start.

Why it matters (measured 2026-10-25, Ryzen 5600H + RTX 3050 laptop, 16 tiles of 1080p30 H.264):
* Windows default put the app on the integrated AMD GPU. mpv's zero-copy decoders (d3d11va / dxva2)
  have no OpenGL interop there, so "auto-safe" fell back to d3d11va-copy: the iGPU's video decoder hit
  100 % and tiles dropped to ~18 fps at ~30 % CPU.
* High performance (NVIDIA) gave nvdec with CUDA-OpenGL interop: 30 fps on every tile at ~6 % CPU.
Note: on a venv the running .exe is `<venv>\\Scripts\\python.exe`, not the base Python; a preference set
for the base Python in Windows Settings does not apply to the app.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
CHOICES = {"default": 0, "power": 1, "high": 2}
_NAMES = {v: k for k, v in CHOICES.items()}


def supported() -> bool:
    return os.name == "nt"


def executable() -> str:
    return sys.executable


def parse(data: str | None) -> str:
    """Registry data ("SwapEffectUpgradeEnable=1;GpuPreference=2;") -> "default" | "power" | "high"."""
    for part in (data or "").split(";"):
        key, _, value = part.partition("=")
        if key.strip() == "GpuPreference":
            try:
                return _NAMES.get(int(value), "default")
            except ValueError:
                return "default"
    return "default"


def update(data: str | None, choice: str) -> str:
    """New registry data with GpuPreference set (or removed for "default"), other entries kept."""
    parts = [p for p in (data or "").split(";") if p.strip() and p.partition("=")[0].strip() != "GpuPreference"]
    if choice != "default":
        parts.append(f"GpuPreference={CHOICES[choice]}")
    return "".join(p + ";" for p in parts)


def read(exe: str | None = None) -> str:
    if not supported():
        return "default"
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            data, _ = winreg.QueryValueEx(key, exe or executable())
    except OSError:
        return "default"
    return parse(data)


def write(choice: str, exe: str | None = None) -> None:
    """Store the preference for the next start. Raises OSError if the registry refuses."""
    if choice not in CHOICES:
        raise ValueError(f"unknown GPU preference {choice!r}")
    if not supported():
        return
    import winreg

    exe = exe or executable()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
        try:
            old, _ = winreg.QueryValueEx(key, exe)
        except OSError:
            old = ""
        new = update(old, choice)
        if new:
            winreg.SetValueEx(key, exe, 0, winreg.REG_SZ, new)
        elif old:
            winreg.DeleteValue(key, exe)
    logger.info("GPU preference for %s set to %s (applies after a restart)", exe, choice)
