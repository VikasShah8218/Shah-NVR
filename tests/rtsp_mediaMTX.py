
# import subprocess
# import sys

# video = "1.mkv"

# server = subprocess.Popen(["mediamtx"])

# try:
#     subprocess.run([
#         "ffmpeg", "-re", "-stream_loop", "-1",
#         "-i", video,
#         "-c:v", "libx264", "-preset", "ultrafast",
#         "-tune", "zerolatency", "-an",
#         "-f", "rtsp", "-rtsp_transport", "tcp",
#         "rtsp://127.0.0.1:8554/live"
#     ])
# finally:
#     server.terminate()



import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
VIDEO = BASE / "1.mkv"
MEDIAMTX = BASE / "mediamtx.exe"

server = subprocess.Popen(
    [str(MEDIAMTX), str(BASE / "mediamtx.yml")],
    cwd=BASE
)

try:
    subprocess.run([
        "ffmpeg",
        "-re",
        "-stream_loop", "-1",
        "-i", str(VIDEO),
        "-map", "0:v:0",
        "-c:v", "copy",
        "-an",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        "rtsp://127.0.0.1:8554/live"
    ], check=True)
finally:
    server.terminate()
