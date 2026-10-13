from app.features.dashboard.alerts import build_alerts
from app.features.nodes.resources import cluster_totals, is_healthy, node_resources

GB = 1024**3


def make_node(**overrides):
    node = {
        "id": 1, "name": "node-1", "state": "ACTIVE", "assigned_cameras": 2, "capacity_cameras": 10,
        "storage_quota_bytes": 100 * GB, "last_heartbeat_at": None,
        "metrics": {
            "cpu_percent": 20.0, "cpu_count": 8, "memory_used_bytes": 4 * GB, "memory_total_bytes": 16 * GB,
            "disk": {"total_bytes": 500 * GB, "free_bytes": 300 * GB, "used_percent": 40.0},
            "recordings_bytes": 30 * GB, "net_rx_mbps": 12.0, "net_tx_mbps": 3.0,
        },
    }
    node.update(overrides)
    return node


def test_node_resources_with_quota():
    r = node_resources(make_node())
    assert r["storagePercent"] == 30          # recordings vs quota
    assert r["remaining"] == 70 * GB          # limited by the quota, not by the free disk
    assert r["usable"] == 100 * GB
    assert r["memPercent"] == 25
    assert r["camerasPercent"] == 20


def test_node_resources_disk_limits_remaining():
    node = make_node()
    node["metrics"]["disk"]["free_bytes"] = 10 * GB
    r = node_resources(node)
    assert r["remaining"] == 10 * GB
    assert r["usable"] == 40 * GB


def test_node_resources_without_quota_uses_disk():
    r = node_resources(make_node(storage_quota_bytes=None))
    assert r["storagePercent"] == 40.0
    assert r["remaining"] == 300 * GB


def test_node_resources_without_metrics():
    r = node_resources(make_node(metrics=None))
    assert r["cpuPercent"] is None and r["usable"] is None and r["gpus"] == []


def test_cluster_totals():
    nodes = [make_node(), make_node(id=2, state="UNREACHABLE", metrics={"cpu_percent": 60.0})]
    t = cluster_totals(nodes)
    assert t["nodes"] == 2 and t["healthy"] == 1
    assert t["cpuAverage"] == 40
    assert t["cameras"] == 4 and t["capacity"] == 20
    assert is_healthy(nodes[0]) and not is_healthy(nodes[1])


def test_alerts_rules_and_order():
    node = make_node(state="UNREACHABLE")
    node["metrics"]["recordings_bytes"] = 90 * GB  # 90% of quota
    cameras = [
        {"id": 1, "name": "Gate", "enabled": True, "assignment": {"node_id": 1},
         "streams": [{"profile": "main", "record": True, "status": "NOT_RECORDING", "status_detail": "timeout"}]},
        {"id": 2, "name": "Lobby", "enabled": True, "assignment": None, "streams": []},
        {"id": 3, "name": "Off", "enabled": False, "assignment": None, "streams": []},
        {"id": 4, "name": "Fine", "enabled": True, "assignment": {"node_id": 1},
         "streams": [{"profile": "main", "record": True, "status": "RECORDING"}]},
    ]
    alerts = build_alerts(cameras, [node])
    titles = [a["title"] for a in alerts]
    assert "node-1 is unreachable" in titles
    assert "node-1: 90% of storage quota used" in titles
    assert "Gate (main) is not recording" in titles
    assert "Lobby is not assigned to any node" in titles
    assert not any("Off" in t or "Fine" in t for t in titles)
    levels = [a["level"] for a in alerts]
    assert levels == sorted(levels, key=lambda lv: 0 if lv == "danger" else 1)  # danger first
    assert [a["key"] for a in alerts] == list(range(len(alerts)))
