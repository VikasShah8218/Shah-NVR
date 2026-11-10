"""Seed many fake cameras (and optionally a group tree) into central to test pagination, search, alerts and camera
groups at scale (docs/PAGINATION_PLAN.md, docs/GROUPING_PLAN.md).

    py tools/seed_cameras.py --count 2000                      # 2,000 DISABLED cameras "Seed 0001".. (safe)
    py tools/seed_cameras.py --count 2000 --groups 10x10       # + 10 regions x 10 sites, cameras spread over them
    py tools/seed_cameras.py --count 300 --enabled             # enabled: the scheduler will try to place them!
    py tools/seed_cameras.py --delete                          # remove every "Seed ####" camera and "Seed" group
    py tools/seed_cameras.py --central http://192.168.1.3:8000 --count 1000

Cameras are created through the normal API (POST /api/v1/cameras), so central stays consistent.
They point at rtsp://127.0.0.1:8654/sim-N (tools/camera_simulator.py) and are DISABLED by default:
disabled cameras are never assigned to a media node, so a real node is not flooded with 2,000 pulls.
Enabled seeds with no free node capacity show up as "not assigned" danger alerts (good for the alert pages).

With --groups RxS: R top groups "Seed Region NN", each with S sub-groups "Seed Site NN-MM". The new cameras are
spread round-robin over the sites, except every 10th camera, which stays ungrouped.
"""

import argparse
import sys
import time

import httpx

PREFIX = "Seed "


def seed(client: httpx.Client, count: int, enabled: bool, start: int) -> list[int]:
    t0 = time.monotonic()
    ids = []
    for i in range(start, start + count):
        body = {
            "name": f"{PREFIX}{i:04d}",
            "description": "pagination test camera (tools/seed_cameras.py)",
            "enabled": enabled,
            "streams": [{"profile": "main", "source_url": f"rtsp://127.0.0.1:8654/sim-{i}", "record": True}],
        }
        r = client.post("/api/v1/cameras", json=body)
        r.raise_for_status()
        ids.append(r.json()["id"])
        if (i - start + 1) % 100 == 0:
            print(f"  {i - start + 1}/{count} created", flush=True)
    print(f"Created {count} cameras in {time.monotonic() - t0:.1f} s")
    return ids


def seed_groups(client: httpx.Client, spec: str, camera_ids: list[int]) -> None:
    try:
        regions, sites = (int(x) for x in spec.lower().split("x"))
    except ValueError:
        sys.exit("--groups must look like 10x10")
    t0 = time.monotonic()
    leaves = []
    for r in range(1, regions + 1):
        top = client.post("/api/v1/groups", json={"name": f"{PREFIX}Region {r:02d}"})
        top.raise_for_status()
        for s in range(1, sites + 1):
            leaf = client.post("/api/v1/groups", json={"name": f"{PREFIX}Site {r:02d}-{s:02d}", "parent_id": top.json()["id"]})
            leaf.raise_for_status()
            leaves.append(leaf.json()["id"])
    grouped = [cid for n, cid in enumerate(camera_ids) if n % 10 != 9]  # every 10th stays ungrouped
    per_leaf: dict[int, list[int]] = {}
    for n, cid in enumerate(grouped):
        per_leaf.setdefault(leaves[n % len(leaves)], []).append(cid)
    for leaf, ids in per_leaf.items():
        for k in range(0, len(ids), 500):
            client.post("/api/v1/groups/assign", json={"camera_ids": ids[k:k + 500], "group_id": leaf}).raise_for_status()
    print(f"Created {regions} x {sites} groups, {len(grouped)} cameras grouped, "
          f"{len(camera_ids) - len(grouped)} ungrouped, in {time.monotonic() - t0:.1f} s")


def delete(client: httpx.Client) -> None:
    removed = 0
    while True:
        page = client.get("/api/v1/cameras/options", params={"q": PREFIX, "limit": 200}).json()
        seeds = [c for c in page["items"] if c["name"].startswith(PREFIX)]
        if not seeds:
            break
        for c in seeds:
            r = client.delete(f"/api/v1/cameras/{c['id']}")
            if r.status_code not in (204, 404):
                print(f"  could not delete {c['name']}: {r.status_code} {r.text}", file=sys.stderr)
                return
            removed += 1
    print(f"Deleted {removed} seed cameras")
    groups = 0
    while True:
        r = client.get("/api/v1/groups/search", params={"q": PREFIX.strip(), "limit": 200})
        if r.status_code == 404:  # central without groups
            break
        seeds = [g for g in r.json()["items"] if g["name"].startswith(PREFIX)]
        if not seeds:
            break
        for g in sorted(seeds, key=lambda g: -g["depth"]):  # deepest first: parents are empty by then
            d = client.delete(f"/api/v1/groups/{g['id']}", params={"move_children": "parent"})
            if d.status_code not in (204, 404):
                print(f"  could not delete group {g['name']}: {d.status_code} {d.text}", file=sys.stderr)
                return
            groups += d.status_code == 204
    print(f"Deleted {groups} seed groups")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--central", default="http://127.0.0.1:8000")
    ap.add_argument("--count", type=int, default=2000)
    ap.add_argument("--start", type=int, default=1, help="first number (to add more later)")
    ap.add_argument("--enabled", action="store_true", help="create them enabled (the scheduler assigns them)")
    ap.add_argument("--groups", metavar="RxS", help="also build R regions x S sites and spread the cameras over them")
    ap.add_argument("--delete", action="store_true", help="delete every 'Seed ####' camera and 'Seed' group")
    args = ap.parse_args()
    with httpx.Client(base_url=args.central.rstrip("/"), timeout=30) as client:
        if args.delete:
            delete(client)
        else:
            ids = seed(client, args.count, args.enabled, args.start)
            if args.groups:
                seed_groups(client, args.groups, ids)


if __name__ == "__main__":
    main()
