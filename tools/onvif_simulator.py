"""Fake ONVIF cameras for development: answers WS-Discovery and the H1 SOAP calls for the camera simulator.

    py tools/camera_simulator.py --count 2          (RTSP: rtsp://127.0.0.1:8654/sim-1, sim-2)
    py tools/onvif_simulator.py --count 2           (ONVIF: http://127.0.0.2:8655, http://127.0.0.3:8655)

Camera N listens on 127.0.0.(N+1) (Windows/Linux route all of 127/8 to loopback), so each fake camera has its own
IP like on a real LAN. Login: admin / admin (WS-UsernameToken digest). Camera 2 starts with its clock 10 minutes
behind, to try "Sync time". Main profile = 1280x720, sub = 640x360 (both point at sim-N; the simulator has one
stream per camera). Snapshot = one frame grabbed from the RTSP stream with FFmpeg.
"""

import argparse
import base64
import hashlib
import socket
import struct
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.etree import ElementTree as ET

S = "http://www.w3.org/2003/05/soap-envelope"
NS = ('xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
      'xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema" '
      'xmlns:ter="http://www.onvif.org/ver10/error"')
WSSE = "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd}"
WSU = "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd}"
NO_AUTH = {"GetSystemDateAndTime"}


def envelope(body: str) -> bytes:
    return f'<?xml version="1.0" encoding="UTF-8"?><s:Envelope {NS}><s:Body>{body}</s:Body></s:Envelope>'.encode()


def fault(code: str, sub: str, reason: str) -> bytes:
    return envelope(f"<s:Fault><s:Code><s:Value>s:{code}</s:Value><s:Subcode><s:Value>ter:{sub}</s:Value></s:Subcode>"
                    f'</s:Code><s:Reason><s:Text xml:lang="en">{reason}</s:Text></s:Reason></s:Fault>')


def dt(ts: float) -> str:
    d = datetime.fromtimestamp(ts, timezone.utc)
    return (f"<tt:Date><tt:Year>{d.year}</tt:Year><tt:Month>{d.month}</tt:Month><tt:Day>{d.day}</tt:Day></tt:Date>"
            f"<tt:Time><tt:Hour>{d.hour}</tt:Hour><tt:Minute>{d.minute}</tt:Minute><tt:Second>{d.second}</tt:Second></tt:Time>")


class Camera:
    def __init__(self, index: int, args):
        self.index, self.args = index, args
        self.ip = f"127.0.0.{index + 1}"
        self.url = f"http://{self.ip}:{args.http_port}/onvif/device_service"
        self.endpoint = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_DNS, f'shah-nvr-sim-{index}')}"
        self.skew = -600.0 if index == 2 else 0.0
        self.ntp_dhcp, self.ntp_servers, self.time_type = True, [], "Manual"

    def rtsp(self) -> str:
        return f"rtsp://127.0.0.1:{self.args.rtsp_port}/sim-{self.index}"

    def profile(self, token, w, h) -> str:
        return (f'<trt:Profiles token="{token}" fixed="true"><tt:Name>{token}</tt:Name>'
                f'<tt:VideoEncoderConfiguration token="enc_{token}"><tt:Name>{token}</tt:Name><tt:UseCount>1</tt:UseCount>'
                f"<tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>{w}</tt:Width><tt:Height>{h}</tt:Height></tt:Resolution>"
                "<tt:Quality>5</tt:Quality><tt:RateControl><tt:FrameRateLimit>25</tt:FrameRateLimit><tt:EncodingInterval>1"
                "</tt:EncodingInterval><tt:BitrateLimit>1500</tt:BitrateLimit></tt:RateControl></tt:VideoEncoderConfiguration>"
                "</trt:Profiles>")

    def handle(self, action: str, req: ET.Element) -> bytes:
        a = self
        if action == "GetSystemDateAndTime":
            return envelope("<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime>"
                            f"<tt:DateTimeType>{a.time_type}</tt:DateTimeType><tt:DaylightSavings>false</tt:DaylightSavings>"
                            f"<tt:TimeZone><tt:TZ>UTC0</tt:TZ></tt:TimeZone><tt:UTCDateTime>{dt(time.time() + a.skew)}</tt:UTCDateTime>"
                            "</tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>")
        if action == "GetDeviceInformation":
            return envelope("<tds:GetDeviceInformationResponse><tds:Manufacturer>Shah</tds:Manufacturer>"
                            f"<tds:Model>SimCam {a.index}</tds:Model><tds:FirmwareVersion>1.0.{a.index}</tds:FirmwareVersion>"
                            f"<tds:SerialNumber>SIM{a.index:04d}</tds:SerialNumber><tds:HardwareId>sim</tds:HardwareId>"
                            "</tds:GetDeviceInformationResponse>")
        if action == "GetServices":
            svc = "".join(f"<tds:Service><tds:Namespace>{ns}</tds:Namespace><tds:XAddr>{a.url}</tds:XAddr>"
                          "<tds:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tds:Version></tds:Service>"
                          for ns in ("http://www.onvif.org/ver10/device/wsdl", "http://www.onvif.org/ver10/media/wsdl"))
            return envelope(f"<tds:GetServicesResponse>{svc}</tds:GetServicesResponse>")
        if action == "GetProfiles":
            return envelope(f"<trt:GetProfilesResponse>{a.profile('main', 1280, 720)}{a.profile('sub', 640, 360)}</trt:GetProfilesResponse>")
        if action == "GetStreamUri":
            return envelope(f"<trt:GetStreamUriResponse><trt:MediaUri><tt:Uri>{a.rtsp()}</tt:Uri></trt:MediaUri></trt:GetStreamUriResponse>")
        if action == "GetSnapshotUri":
            return envelope(f"<trt:GetSnapshotUriResponse><trt:MediaUri><tt:Uri>http://{a.ip}:{a.args.http_port}/snapshot.jpg"
                            "</tt:Uri></trt:MediaUri></trt:GetSnapshotUriResponse>")
        if action == "GetNTP":
            manual = "".join(f"<tt:NTPManual><tt:Type>DNS</tt:Type><tt:DNSname>{s}</tt:DNSname></tt:NTPManual>" for s in a.ntp_servers)
            return envelope(f"<tds:GetNTPResponse><tds:NTPInformation><tt:FromDHCP>{str(a.ntp_dhcp).lower()}</tt:FromDHCP>"
                            f"{manual}</tds:NTPInformation></tds:GetNTPResponse>")
        if action == "GetHostname":
            return envelope(f"<tds:GetHostnameResponse><tds:HostnameInformation><tt:FromDHCP>false</tt:FromDHCP>"
                            f"<tt:Name>simcam-{a.index}</tt:Name></tds:HostnameInformation></tds:GetHostnameResponse>")
        if action == "GetNetworkInterfaces":
            return envelope('<tds:GetNetworkInterfacesResponse><tds:NetworkInterfaces token="eth0"><tt:Enabled>true</tt:Enabled>'
                            f"<tt:Info><tt:HwAddress>02:00:00:00:00:{a.index:02x}</tt:HwAddress></tt:Info><tt:IPv4><tt:Enabled>true</tt:Enabled>"
                            f"<tt:Config><tt:Manual><tt:Address>{a.ip}</tt:Address><tt:PrefixLength>8</tt:PrefixLength></tt:Manual>"
                            "<tt:DHCP>false</tt:DHCP></tt:Config></tt:IPv4></tds:NetworkInterfaces></tds:GetNetworkInterfacesResponse>")
        if action == "SetSystemDateAndTime":
            a.time_type = req.findtext(".//{http://www.onvif.org/ver10/device/wsdl}DateTimeType") or "Manual"
            a.skew = 0.0
            return envelope("<tds:SetSystemDateAndTimeResponse/>")
        if action == "SetNTP":
            a.ntp_dhcp = (req.findtext(".//{http://www.onvif.org/ver10/device/wsdl}FromDHCP") or "").lower() == "true"
            a.ntp_servers = [e.text for e in req.iter("{http://www.onvif.org/ver10/schema}DNSname")] + \
                            [e.text for e in req.iter("{http://www.onvif.org/ver10/schema}IPv4Address")]
            return envelope("<tds:SetNTPResponse/>")
        if action == "SystemReboot":
            print(f"  sim-{a.index}: reboot requested")
            return envelope("<tds:SystemRebootResponse><tds:Message>Rebooting in 30 seconds</tds:Message></tds:SystemRebootResponse>")
        return fault("Sender", "ActionNotSupported", f"{action} not supported by the simulator")

    def authorized(self, root: ET.Element) -> bool:
        token = root.find(f".//{WSSE}UsernameToken")
        if token is None:
            return False
        user = token.findtext(f"{WSSE}Username")
        digest = token.findtext(f"{WSSE}Password")
        nonce = base64.b64decode(token.findtext(f"{WSSE}Nonce") or "")
        created = token.findtext(f"{WSU}Created") or ""
        expect = base64.b64encode(hashlib.sha1(nonce + created.encode() + self.args.password.encode()).digest()).decode()
        try:  # like real cameras: the token time must match the camera clock (+-5 min)
            ts = datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            return False
        return user == self.args.user and digest == expect and abs(ts - (time.time() + self.skew)) < 300


def make_handler(cam: Camera):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                root = ET.fromstring(data)
                action = next(iter(root.find(f"{{{S}}}Body"))).tag.split("}")[-1]
            except (ET.ParseError, StopIteration, TypeError):
                return self._send(400, fault("Sender", "WellFormed", "bad request"))
            if action not in NO_AUTH and not cam.authorized(root):
                print(f"  sim-{cam.index}: {action} refused (wrong login)")
                return self._send(400, fault("Sender", "NotAuthorized", "Sender not authorized"))
            body = cam.handle(action, root)
            self._send(500 if b"ActionNotSupported" in body else 200, body)

        def do_GET(self):
            if self.path != "/snapshot.jpg":
                return self._send(404, b"", "text/plain")
            out = subprocess.run(["ffmpeg", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", cam.rtsp(),
                                  "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "-"], capture_output=True, timeout=15)
            self._send(200 if out.stdout else 503, out.stdout, "image/jpeg")

        def _send(self, status: int, body: bytes, ctype: str = "application/soap+xml; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def discovery_responder(cams: list[Camera]) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", 3702))
    for ip in {"0.0.0.0", *_local_ips()}:  # join on every interface the node may probe from
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                            struct.pack("4s4s", socket.inet_aton("239.255.255.250"), socket.inet_aton(ip)))
        except OSError:
            pass
    while True:
        data, addr = sock.recvfrom(65535)
        if b"Probe" not in data or b"ProbeMatches" in data:
            continue
        try:
            rel = ET.fromstring(data).findtext(".//{http://schemas.xmlsoap.org/ws/2004/08/addressing}MessageID") or ""
        except ET.ParseError:
            continue
        for cam in cams:
            reply = (f'<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="{S}" '
                     'xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
                     'xmlns:dn="http://www.onvif.org/ver10/network/wsdl"><s:Header>'
                     "<a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</a:Action>"
                     f"<a:MessageID>uuid:{uuid.uuid4()}</a:MessageID><a:RelatesTo>{rel}</a:RelatesTo></s:Header><s:Body>"
                     f"<d:ProbeMatches><d:ProbeMatch><a:EndpointReference><a:Address>{cam.endpoint}</a:Address></a:EndpointReference>"
                     "<d:Types>dn:NetworkVideoTransmitter</d:Types><d:Scopes>onvif://www.onvif.org/Profile/Streaming "
                     f"onvif://www.onvif.org/name/SimCam%20{cam.index} onvif://www.onvif.org/hardware/SimCam "
                     f"onvif://www.onvif.org/location/Lab</d:Scopes><d:XAddrs>{cam.url}</d:XAddrs>"
                     "<d:MetadataVersion>1</d:MetadataVersion></d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>")
            sock.sendto(reply.encode(), addr)


def _local_ips() -> list[str]:
    try:
        return [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        return []


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--count", type=int, default=2)
    p.add_argument("--http-port", type=int, default=8655)
    p.add_argument("--rtsp-port", type=int, default=8654)
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default="admin")
    args = p.parse_args()

    cams = [Camera(i, args) for i in range(1, args.count + 1)]
    for cam in cams:
        server = ThreadingHTTPServer((cam.ip, args.http_port), make_handler(cam))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"sim-{cam.index}: ONVIF {cam.url}  RTSP {cam.rtsp()}" + ("  (clock 10 min behind)" if cam.skew else ""))
    threading.Thread(target=discovery_responder, args=(cams,), daemon=True).start()
    print(f"WS-Discovery on udp/3702. Login {args.user}/{args.password}. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
