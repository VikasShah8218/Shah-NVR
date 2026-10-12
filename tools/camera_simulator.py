"""Fake IP cameras for development: publishes N RTSP streams with a moving test pattern + clock.

    py tools/camera_simulator.py --count 2
    -> rtsp://127.0.0.1:8654/sim-1 , rtsp://127.0.0.1:8654/sim-2

    py tools/camera_simulator.py --count 4 --file sample.mp4   (loops a real video, no re-encode)

Uses the MediaMTX binary from media_node/bin and FFmpeg from PATH. Ctrl+C to stop.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIAMTX = ROOT / "media_node" / "bin" / ("mediamtx.exe" if os.name == "nt" else "mediamtx")

FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]

CONFIG = """logLevel: warn
api: false
metrics: false
playback: false
rtsp: true
rtspTransports: [tcp]
rtspAddress: :{port}
rtmp: false
hls: false
webrtc: false
srt: false
moq: false
paths:
  all_others:
"""


def ffmpeg_cmd(args, index: int) -> list[str]:
    url = f"rtsp://127.0.0.1:{args.port}/sim-{index}"
    if args.file:
        source = ["-re", "-stream_loop", "-1", "-i", args.file, "-map", "0:v:0", "-c:v", "copy"]
    else:
        overlay = []
        font = next((f for f in FONT_CANDIDATES if Path(f).exists()), None)
        if font:  # FFmpeg filter syntax needs the drive colon escaped (C\:/Windows/...)
            fontfile = font.replace("\\", "/").replace(":", "\\:")
            text = f"text='SIM-{index}  %{{localtime}}':x=20:y=20:fontsize=36:fontcolor=white:box=1:boxcolor=black@0.6"
            overlay = ["-vf", f"drawtext=fontfile='{fontfile}':{text}"]
        source = [
            "-re", "-f", "lavfi", "-i", f"testsrc2=size={args.size}:rate={args.fps}",
            *overlay,
            "-c:v", "libx265" if args.codec == "h265" else "libx264",
            "-preset", "ultrafast", "-tune", "zerolatency",
            "-g", str(args.fps), "-keyint_min", str(args.fps), "-b:v", args.bitrate,
            "-pix_fmt", "yuv420p",
        ]
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", *source, "-f", "rtsp", "-rtsp_transport", "tcp", url]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--port", type=int, default=8654)
    p.add_argument("--size", default="1280x720")
    p.add_argument("--fps", type=int, default=25)
    p.add_argument("--bitrate", default="1500k")
    p.add_argument("--codec", choices=["h264", "h265"], default="h264")
    p.add_argument("--file", help="loop this video file instead of a test pattern (stream copy)")
    args = p.parse_args()

    if not MEDIAMTX.exists():
        sys.exit(f"MediaMTX not found at {MEDIAMTX}")
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found in PATH")

    cfg = Path(tempfile.gettempdir()) / "shah_nvr_camera_sim.yml"
    cfg.write_text(CONFIG.format(port=args.port), encoding="utf-8")
    procs = [subprocess.Popen([str(MEDIAMTX), str(cfg)])]
    time.sleep(1.5)
    for i in range(1, args.count + 1):
        procs.append(subprocess.Popen(ffmpeg_cmd(args, i)))
        print(f"camera sim-{i}: rtsp://127.0.0.1:{args.port}/sim-{i}")
    print("Running. Ctrl+C to stop.")
    try:
        while all(pr.poll() is None for pr in procs):
            time.sleep(1)
        print("A simulator process exited; stopping.")
    except KeyboardInterrupt:
        pass
    finally:
        for pr in reversed(procs):
            pr.terminate()


if __name__ == "__main__":
    main()
