"""Makes libmpv-2.dll loadable before `import mpv`.

python-mpv looks for mpv-2.dll / libmpv-2.dll on PATH at import time, so the folder holding the DLL
(nvr_desktop/bin by default) is put first on PATH and registered as a DLL search directory.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DLL_NAMES = ("libmpv-2.dll", "mpv-2.dll")


class LibmpvMissingError(RuntimeError):
    pass


def prepare_libmpv(dll_dir: Path) -> None:
    """Call once, before anything imports `mpv`."""
    if os.name != "nt":
        return  # Linux/macOS: libmpv comes from the system package manager.
    if not any((dll_dir / name).exists() for name in DLL_NAMES):
        raise LibmpvMissingError(
            f"libmpv-2.dll not found in {dll_dir}. Download an 'mpv-dev-x86_64-*.7z' build "
            "(https://github.com/zhongfly/mpv-winbuild/releases) and copy libmpv-2.dll there."
        )
    os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(str(dll_dir))
    logger.info("libmpv loaded from %s", dll_dir)
