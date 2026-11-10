"""Seed many fake cameras into central to test pagination, search and alerts at scale (docs/PAGINATION_PLAN.md).

    py tools/seed_cameras.py --count 2000                      # 2,000 DISABLED cameras "Seed 0001".. (safe)
    py tools/seed_cameras.py --count 300 --enabled             # enabled: the scheduler will try to place them!
    py tools/seed_cameras.py --delete                          # remove every "Seed ####" camera again
    py tools/seed_cameras.py --central http://192.168.1.3:8000 --count 1000

Cameras are created through the normal API (POST /api/v1/cameras), so central stays consistent.
They point at rtsp://127.0.0.1:8654/sim-N (tools/camera_simulator.py) and are DISABLED by default:
disabled cameras are never assigned to a media node, so a real node is not flooded with 2,000 pulls.
Enabled seeds with no free node capacity show up as "not assigned" danger alerts (good for the alert pages).
"""

import argparse
import sys
import time

import httpx

PREFIX = "Seed "


def seed(client: httpx.Client, count: int, enabled: bool, start: int) -> None:
    t0 = time.monotonic()
    for i in range(start, start + count):
        body = {
            "name": f"{PREFIX}{i:04d}",
            "description": "pagination test camera (tools/seed_cameras.py)",
            "enabled": enabled,
            "streams": [{"profile": "main", "source_url": f"rtsp://127.0.0.1:8654/sim-{i}", "record": True}],
        }
        r = client.post("/api/v1/cameras", json=body)
        r.raise_for_status()
        if (i - start + 1) % 100 == 0:
            print(f"  {i - start + 1}/{count} created", flush=True)
    print(f"Created {count} cameras in {time.monotonic() - t0:.1f} s")


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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--central", default="http://127.0.0.1:8000")
    ap.add_argument("--count", type=int, default=2000)
    ap.add_argument("--start", type=int, default=1, help="first number (to add more later)")
    ap.add_argument("--enabled", action="store_true", help="create them enabled (the scheduler assigns them)")
    ap.add_argument("--delete", action="store_true", help="delete every 'Seed ####' camera")
    args = ap.parse_args()
    with httpx.Client(base_url=args.central.rstrip("/"), timeout=30) as client:
        if args.delete:
            delete(client)
        else:
            seed(client, args.count, args.enabled, args.start)


if __name__ == "__main__":
    main()
