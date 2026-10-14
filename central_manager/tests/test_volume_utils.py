import pytest

from app.nodes.utils import gb_to_bytes, is_network_path, normalize_volume_path, total_quota


@pytest.mark.parametrize("raw, expected", [
    (r"D:\ShahNVR\recordings\\", r"D:\ShahNVR\recordings"),
    ("d:/ShahNVR/recordings", r"d:\ShahNVR\recordings"),
    (r"D:\\", "D:\\"),
    (r"\\192.168.1.9\nvr", r"\\192.168.1.9\nvr"),
    (r"\\192.168.1.9\nvr\\cams\\", r"\\192.168.1.9\nvr\cams"),
    ("//192.168.1.9/nvr/cams", r"\\192.168.1.9\nvr\cams"),
    ('  "E:\\Video"  ', r"E:\Video"),
    ("/mnt/nvr/", "/mnt/nvr"),
])
def test_normalize_valid_paths(raw, expected):
    assert normalize_volume_path(raw) == expected


@pytest.mark.parametrize("raw", ["recordings", r"ShahNVR\rec", r"\\onlyhost", "C:", "", "  "])
def test_normalize_rejects_relative_or_incomplete(raw):
    with pytest.raises(ValueError):
        normalize_volume_path(raw)


def test_network_and_quota_helpers():
    assert is_network_path(r"\\nas\share") and not is_network_path(r"D:\x")
    assert gb_to_bytes(1.5) == int(1.5 * 1024**3) and gb_to_bytes(None) is None
    assert total_quota([10, 20]) == 30
    assert total_quota([10, None]) is None
    assert total_quota([]) is None
