"""SSH broker for the jk-1 test PC. The password is read from the JK1_PASS environment variable once, by `serve`,
and kept only in memory (never written to disk). Other calls talk to the broker over 127.0.0.1.

  serve                      start the broker (foreground; run it in the background)
  run "<command>" [timeout]  run a command on jk-1 (cmd.exe), print stdout/stderr, exit with its code
  put <local> <remote>       copy a file to jk-1 (SFTP)
  get <remote> <local>       copy a file from jk-1
  stop                       stop the broker
"""
import json
import os
import socket
import socketserver
import sys
import threading

import os as _os

HOST = _os.environ.get("SSH_HOST", "jk-1")
USER = _os.environ.get("SSH_USER", "CCTV")
PORT = int(_os.environ.get("BROKER_PORT", "47811"))


def _send(sock, obj):
    data = json.dumps(obj).encode()
    sock.sendall(len(data).to_bytes(8, "big") + data)


def _recv(sock):
    n = int.from_bytes(_read(sock, 8), "big")
    return json.loads(_read(sock, n))


def _read(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def serve():
    import paramiko

    password = os.environ.pop("JK1_PASS")
    lock = threading.Lock()
    state = {}

    def client():
        c = state.get("c")
        if c is None or c.get_transport() is None or not c.get_transport().is_active():
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(HOST, username=USER, password=password, timeout=15, allow_agent=False, look_for_keys=False)
            c.get_transport().set_keepalive(30)
            state["c"] = c
        return c

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            req = _recv(self.request)
            try:
                if req["op"] == "stop":
                    _send(self.request, {"ok": True})
                    threading.Thread(target=server.shutdown).start()
                    return
                with lock:
                    c = client()
                if req["op"] == "run":
                    _, out, err = c.exec_command(req["cmd"], timeout=req.get("timeout", 600))
                    o = out.read().decode("utf-8", "replace")
                    e = err.read().decode("utf-8", "replace")
                    _send(self.request, {"ok": True, "out": o, "err": e, "code": out.channel.recv_exit_status()})
                elif req["op"] == "put":
                    with c.open_sftp() as s:
                        s.put(req["local"], req["remote"])
                    _send(self.request, {"ok": True})
                elif req["op"] == "get":
                    with c.open_sftp() as s:
                        s.get(req["remote"], req["local"])
                    _send(self.request, {"ok": True})
            except Exception as exc:  # noqa: BLE001
                state.pop("c", None)
                _send(self.request, {"ok": False, "err": f"{type(exc).__name__}: {exc}"})

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler)
    with lock:
        client()  # fail fast on a wrong password
    print("broker ready", flush=True)
    server.serve_forever()


def call(req):
    # wait as long as the remote command may run (plus a margin), never less than 15 min
    with socket.create_connection(("127.0.0.1", PORT), timeout=max(900, req.get("timeout", 0) + 120)) as s:
        _send(s, req)
        return _recv(s)


if __name__ == "__main__":
    op = sys.argv[1]
    if op == "serve":
        serve()
    elif op == "run":
        r = call({"op": "run", "cmd": sys.argv[2], "timeout": int(sys.argv[3]) if len(sys.argv) > 3 else 600})
        if not r["ok"]:
            print(r["err"], file=sys.stderr)
            sys.exit(255)
        sys.stdout.write(r["out"])
        sys.stderr.write(r["err"])
        sys.exit(r["code"])
    elif op in ("put", "get"):
        key = ("local", "remote") if op == "put" else ("remote", "local")
        r = call({"op": op, key[0]: sys.argv[2], key[1]: sys.argv[3]})
        print("ok" if r["ok"] else r["err"])
        sys.exit(0 if r["ok"] else 1)
    elif op == "ps":  # upload a local .ps1 to the work folder and run it
        import os.path
        remote = "C:/Users/CCTV/snvr-onvif-lab/_" + os.path.basename(sys.argv[2])
        call({"op": "run", "cmd": 'if not exist C:\\Users\\CCTV\\snvr-onvif-lab mkdir C:\\Users\\CCTV\\snvr-onvif-lab'})
        r = call({"op": "put", "local": sys.argv[2], "remote": remote})
        if not r["ok"]:
            print(r["err"], file=sys.stderr)
            sys.exit(255)
        r = call({"op": "run", "cmd": f'powershell -NoProfile -ExecutionPolicy Bypass -File "{remote}" ' + " ".join(sys.argv[3:]),
                  "timeout": 1800})
        sys.stdout.write(r.get("out", ""))
        sys.stderr.write(r.get("err", ""))
        sys.exit(r.get("code", 255))
    elif op == "stop":
        print(call({"op": "stop"}))
