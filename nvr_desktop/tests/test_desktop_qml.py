import subprocess
import sys

import pytest

from settings.settings import BASE_DIR, settings


def test_real_qml_pages_with_onvif_and_manual_cameras(tmp_path):
    if not (settings.MPV_DLL_DIR / "libmpv-2.dll").exists():
        pytest.skip("Desktop QML smoke requires libmpv (see README)")
    result = subprocess.run([sys.executable, "-m", "tests.qml_smoke", str(tmp_path)],
                            cwd=BASE_DIR, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
