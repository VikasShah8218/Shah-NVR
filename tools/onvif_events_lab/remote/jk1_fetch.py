"""Copy lab results (no credentials) from jk-1 to docs/onvif_lab_results/ (git-ignored)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))  # jk1.py next to this file
import jk1  # noqa: E402

DST = pathlib.Path(__file__).resolve().parents[3] / "docs" / "onvif_lab_results"  # repo/docs (git-ignored)
DST.mkdir(parents=True, exist_ok=True)
r = jk1.call({"op": "run", "cmd": r"dir /b C:\Users\CCTV\snvr-onvif-lab\results"})
for name in r["out"].split():
    if name.endswith("-raw"):
        continue
    g = jk1.call({"op": "get", "remote": f"C:/Users/CCTV/snvr-onvif-lab/results/{name}", "local": str(DST / name)})
    print(name, "ok" if g["ok"] else g["err"])
