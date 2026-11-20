"""Copy tools/onvif_events_lab to jk-1 (C:/Users/CCTV/snvr-onvif-lab/onvif_events_lab) through the jk1 broker."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))  # jk1.py next to this file
import jk1  # noqa: E402

SRC = pathlib.Path(__file__).resolve().parents[1]  # tools/onvif_events_lab
DST = "C:/Users/CCTV/snvr-onvif-lab/onvif_events_lab"
jk1.call({"op": "run", "cmd": r"if not exist C:\Users\CCTV\snvr-onvif-lab\onvif_events_lab\tests mkdir "
                              r"C:\Users\CCTV\snvr-onvif-lab\onvif_events_lab\tests"})
n = 0
for f in SRC.rglob("*.py"):
    rel = f.relative_to(SRC).as_posix()
    if rel.startswith("remote/"):  # dev-PC helpers only
        continue
    r = jk1.call({"op": "put", "local": str(f), "remote": f"{DST}/{rel}"})
    if not r["ok"]:
        print("FAILED", rel, r["err"])
        sys.exit(1)
    n += 1
print(f"copied {n} files")
