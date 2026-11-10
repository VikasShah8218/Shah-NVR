"""Camera groups (docs/GROUPING_PLAN.md): lazy tree, sibling names, depth limit, move (cycle + subtree path rewrite),
delete (refused / move up), assign, roll-up counts and the camera filters. Real app on in-memory SQLite."""

from fastapi.testclient import TestClient

STREAM = [{"profile": "main", "source_url": "rtsp://1.2.3.4/x", "record": True}]


def _client():
    import main

    return TestClient(main.app)


def _group(client, name, parent_id=None, expect=201):
    r = client.post("/api/v1/groups", json={"name": name, "parent_id": parent_id})
    assert r.status_code == expect, r.text
    return r.json()


def _camera(client, name, group_id=None):
    r = client.post("/api/v1/cameras", json={"name": name, "streams": STREAM, "group_id": group_id})
    assert r.status_code == 201, r.text
    return r.json()


def _names(page):
    return [x["name"] for x in page["items"]]


def test_tree_is_listed_one_level_at_a_time_with_counts():
    with _client() as c:
        a = _group(c, "Anantnag")
        j = _group(c, "Jammu")
        b = _group(c, "Bijbehara", a["id"])
        p = _group(c, "Pahalgam", a["id"])
        assert b["path"] == f"/{a['id']}/{b['id']}/" and b["depth"] == 1
        assert b["path_label"] == "Anantnag › Bijbehara" and b["breadcrumb"] == [{"id": a["id"], "name": "Anantnag"}]
        _camera(c, "HQ", a["id"])
        _camera(c, "Gate", b["id"])
        _camera(c, "Bus", b["id"])
        _camera(c, "Loose")
        top = c.get("/api/v1/groups").json()
        assert _names(top) == ["Anantnag", "Jammu"] and top["total"] == 2
        an = top["items"][0]
        assert (an["child_groups"], an["cameras_direct"], an["cameras_total"], an["online_total"]) == (2, 1, 3, 0)
        assert top["items"][1]["cameras_total"] == 0 and top["items"][1]["child_groups"] == 0
        sub = c.get("/api/v1/groups", params={"parent_id": a["id"]}).json()
        assert _names(sub) == ["Bijbehara", "Pahalgam"] and sub["items"][0]["cameras_direct"] == 2
        assert c.get("/api/v1/groups", params={"parent_id": 999}).status_code == 404
        assert c.get("/api/v1/groups", params={"limit": 1, "offset": 1}).json()["items"][0]["id"] == j["id"]
        found = c.get("/api/v1/groups/search", params={"q": "gam"}).json()
        assert found["items"][0]["path_label"] == "Anantnag › Pahalgam" and p["id"] == found["items"][0]["id"]


def test_camera_filters_direct_recursive_ungrouped_and_group_path():
    with _client() as c:
        a = _group(c, "Anantnag")
        b = _group(c, "Bijbehara", a["id"])
        hq = _camera(c, "HQ", a["id"])
        _camera(c, "Gate", b["id"])
        _camera(c, "Loose")
        assert hq["group_id"] == a["id"] and hq["group_path"] == "Anantnag"
        opts = lambda **p: c.get("/api/v1/cameras/options", params=p).json()
        assert _names(opts(group_id=a["id"])) == ["HQ"]
        assert _names(opts(group_id=a["id"], recursive=True)) == ["Gate", "HQ"]
        assert _names(opts(ungrouped=True)) == ["Loose"]
        assert opts(group_id=b["id"])["items"][0]["group_path"] == "Anantnag › Bijbehara"
        assert _names(c.get("/api/v1/cameras", params={"group_id": a["id"], "recursive": True}).json()) == ["Gate", "HQ"]
        assert c.get("/api/v1/cameras/options", params={"group_id": 999, "recursive": True}).status_code == 404
        assert c.post("/api/v1/cameras", json={"name": "X", "streams": STREAM, "group_id": 999}).status_code == 422
        assert c.patch(f"/api/v1/cameras/{hq['id']}", json={"group_id": None}).json()["group_path"] is None
        assert c.patch(f"/api/v1/cameras/{hq['id']}", json={"group_id": 999}).status_code == 422


def test_sibling_names_are_unique_per_parent_and_depth_is_limited():
    with _client() as c:
        a = _group(c, "Anantnag")
        _group(c, "anantnag ", expect=409)  # case-insensitive, trimmed, at the top level too
        b = _group(c, "Gandhi Nagar", a["id"])
        j = _group(c, "Jammu")
        _group(c, "Gandhi Nagar", j["id"])  # same name under another parent is fine
        assert c.patch(f"/api/v1/groups/{j['id']}", json={"name": "ANANTNAG"}).status_code == 409
        assert c.patch(f"/api/v1/groups/{b['id']}", json={"parent_id": j["id"]}).status_code == 409  # name clash
        parent = None
        for depth in range(8):
            parent = _group(c, f"L{depth}", parent and parent["id"])
        _group(c, "too deep", parent["id"], expect=422)
        _group(c, "x", 999, expect=404)
        assert c.post("/api/v1/groups", json={"name": "   "}).status_code == 422


def test_move_rewrites_the_subtree_and_refuses_cycles():
    with _client() as c:
        a = _group(c, "A")
        b = _group(c, "B", a["id"])
        cc = _group(c, "C", b["id"])
        j = _group(c, "J")
        assert c.patch(f"/api/v1/groups/{a['id']}", json={"parent_id": cc["id"]}).status_code == 409
        assert c.patch(f"/api/v1/groups/{a['id']}", json={"parent_id": a["id"]}).status_code == 409
        moved = c.patch(f"/api/v1/groups/{b['id']}", json={"parent_id": j["id"]}).json()
        assert moved["path"] == f"/{j['id']}/{b['id']}/" and moved["path_label"] == "J › B"
        leaf = c.get(f"/api/v1/groups/{cc['id']}").json()
        assert leaf["path"] == f"/{j['id']}/{b['id']}/{cc['id']}/" and leaf["depth"] == 2
        assert [x["name"] for x in leaf["breadcrumb"]] == ["J", "B"]
        top = c.patch(f"/api/v1/groups/{b['id']}", json={"parent_id": None}).json()
        assert top["depth"] == 0 and top["path"] == f"/{b['id']}/"
        assert c.get(f"/api/v1/groups/{cc['id']}").json()["depth"] == 1
        # a deep subtree cannot be moved where it would exceed the limit
        parent = None
        for depth in range(7):
            parent = _group(c, f"D{depth}", parent and parent["id"])
        assert c.patch(f"/api/v1/groups/{b['id']}", json={"parent_id": parent["id"]}).status_code == 422


def test_delete_refused_when_not_empty_or_moves_contents_up():
    with _client() as c:
        a = _group(c, "A")
        b = _group(c, "B", a["id"])
        cc = _group(c, "C", b["id"])
        cam = _camera(c, "Gate", b["id"])
        r = c.delete(f"/api/v1/groups/{b['id']}")
        assert r.status_code == 409 and "1 sub-groups, 1 cameras" in r.json()["detail"]
        assert c.delete(f"/api/v1/groups/{b['id']}", params={"move_children": "parent"}).status_code == 204
        assert c.get(f"/api/v1/groups/{cc['id']}").json()["path"] == f"/{a['id']}/{cc['id']}/"
        assert c.get(f"/api/v1/cameras/{cam['id']}").json()["group_id"] == a["id"]
        # contents of a top-level group go to the top level / no group
        assert c.delete(f"/api/v1/groups/{a['id']}", params={"move_children": "parent"}).status_code == 204
        assert c.get(f"/api/v1/groups/{cc['id']}").json()["parent_id"] is None
        assert c.get(f"/api/v1/cameras/{cam['id']}").json()["group_id"] is None
        assert c.delete(f"/api/v1/groups/{cc['id']}").status_code == 204  # empty: deleted
        assert c.delete("/api/v1/groups/999").status_code == 404


def test_delete_move_up_refuses_name_clash():
    with _client() as c:
        a = _group(c, "A")
        _group(c, "Dup", a["id"])
        b = _group(c, "B", a["id"])
        _group(c, "Dup", b["id"])
        r = c.delete(f"/api/v1/groups/{b['id']}", params={"move_children": "parent"})
        assert r.status_code == 409 and "Dup" in r.json()["detail"]


def test_assign_moves_cameras_and_deleted_camera_leaves_group():
    with _client() as c:
        a = _group(c, "A")
        b = _group(c, "B")
        ids = [_camera(c, f"Cam {i}")["id"] for i in range(3)]
        assert c.post("/api/v1/groups/assign", json={"camera_ids": ids, "group_id": a["id"]}).json() == {"updated": 3}
        assert c.post("/api/v1/groups/assign", json={"camera_ids": ids[:1], "group_id": b["id"]}).json()["updated"] == 1
        top = {g["name"]: g["cameras_total"] for g in c.get("/api/v1/groups").json()["items"]}
        assert top == {"A": 2, "B": 1}
        assert c.post("/api/v1/groups/assign", json={"camera_ids": ids, "group_id": None}).json()["updated"] == 3
        assert c.post("/api/v1/groups/assign", json={"camera_ids": ids, "group_id": 999}).status_code == 404
        assert c.post("/api/v1/groups/assign", json={"camera_ids": [], "group_id": None}).status_code == 422
        c.post("/api/v1/groups/assign", json={"camera_ids": ids[:1], "group_id": a["id"]})
        assert c.delete(f"/api/v1/cameras/{ids[0]}").status_code == 204
        assert c.get(f"/api/v1/groups/{a['id']}").json()["cameras_total"] == 0


def test_online_count_uses_streaming_state():
    with _client() as c:
        a = _group(c, "A")
        cam = _camera(c, "Gate", a["id"])
        _camera(c, "Off", a["id"])

        async def mark():
            from app.cameras.models import CameraStream, StreamStatus

            await CameraStream.filter(camera_id=cam["id"]).update(status=StreamStatus.RECORDING)

        c.portal.call(mark)
        g = c.get(f"/api/v1/groups/{a['id']}").json()
        assert (g["online_total"], g["cameras_total"]) == (1, 2)
