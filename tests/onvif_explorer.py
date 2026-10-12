#!/usr/bin/env python3
"""
ONVIF Camera Explorer
1. Discovers ONVIF cameras on the local network (WS-Discovery)
2. Lets you pick one
3. Dumps all information the camera exposes via ONVIF
"""

import json
import re
import socket
import uuid
import getpass
from datetime import datetime
from urllib.parse import urlparse

from onvif import ONVIFCamera
from zeep.helpers import serialize_object


# ----------------------------------------------------------------------
# 1. DISCOVERY (WS-Discovery multicast probe)
# ----------------------------------------------------------------------
PROBE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{msg_id}</w:MessageID>
    <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe>
  </e:Body>
</e:Envelope>"""


def discover_cameras(timeout=4):
    """Send a WS-Discovery probe and collect ONVIF camera responses."""
    print(f"[*] Searching for ONVIF cameras ({timeout}s)...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
    sock.settimeout(timeout)
    sock.bind(("", 0))

    probe = PROBE_TEMPLATE.format(msg_id=uuid.uuid4()).encode()
    for _ in range(2):  # send twice, UDP can drop packets
        sock.sendto(probe, ("239.255.255.250", 3702))

    cameras = {}
    try:
        while True:
            data, addr = sock.recvfrom(65535)
            text = data.decode(errors="ignore")

            xaddrs = re.search(r"XAddrs>([^<]+)<", text)
            scopes = re.search(r"Scopes>([^<]+)<", text)
            if not xaddrs:
                continue

            # A device can report several URLs; prefer the one matching sender IP
            urls = xaddrs.group(1).split()
            url = next((u for u in urls if addr[0] in u), urls[0])
            parsed = urlparse(url)
            ip = parsed.hostname or addr[0]
            port = parsed.port or 80

            name, hardware = "Unknown", "Unknown"
            if scopes:
                for s in scopes.group(1).split():
                    if "/name/" in s:
                        name = s.split("/name/")[-1].replace("%20", " ")
                    elif "/hardware/" in s:
                        hardware = s.split("/hardware/")[-1].replace("%20", " ")

            cameras[ip] = {"ip": ip, "port": port, "url": url,
                           "name": name, "hardware": hardware}
    except socket.timeout:
        pass
    finally:
        sock.close()

    return list(cameras.values())


def choose_camera(cameras):
    """Show the camera list and let the user select one (or enter IP manually)."""
    print("\n================ CAMERAS FOUND ================")
    if not cameras:
        print("  No cameras found by discovery.")
    for i, c in enumerate(cameras, 1):
        print(f"  [{i}] {c['ip']}:{c['port']}  |  {c['name']}  |  {c['hardware']}")
    print("  [M] Enter camera IP manually")
    print("  [Q] Quit")
    print("===============================================")

    while True:
        choice = input("Select a camera: ").strip().lower()
        if choice == "q":
            return None
        if choice == "m":
            ip = input("Camera IP: ").strip()
            port = input("ONVIF port [80]: ").strip() or "80"
            return {"ip": ip, "port": int(port), "name": "Manual", "hardware": "-"}
        if choice.isdigit() and 1 <= int(choice) <= len(cameras):
            return cameras[int(choice) - 1]
        print("Invalid choice, try again.")


# ----------------------------------------------------------------------
# 2. INFORMATION GATHERING
# ----------------------------------------------------------------------
def to_dict(obj):
    """Convert zeep objects into plain JSON-serialisable data."""
    return json.loads(json.dumps(serialize_object(obj), default=str))


def safe(results, section, key, func, *args):
    """Call an ONVIF method; store result or error without crashing."""
    try:
        results.setdefault(section, {})[key] = to_dict(func(*args))
    except Exception as e:
        results.setdefault(section, {})[key] = f"Not supported / error: {e}"


def collect_all_info(cam_info, user, password):
    print(f"\n[*] Connecting to {cam_info['ip']}:{cam_info['port']} ...")
    cam = ONVIFCamera(cam_info["ip"], cam_info["port"], user, password,
                      adjust_time=True)  # handles clock difference for auth
    r = {}

    # ---------- Device management ----------
    dev = cam.devicemgmt
    safe(r, "Device", "DeviceInformation", dev.GetDeviceInformation)
    safe(r, "Device", "Hostname", dev.GetHostname)
    safe(r, "Device", "SystemDateAndTime", dev.GetSystemDateAndTime)
    safe(r, "Device", "Scopes", dev.GetScopes)
    safe(r, "Device", "Users", dev.GetUsers)
    safe(r, "Device", "Capabilities", dev.GetCapabilities, {"Category": "All"})
    safe(r, "Device", "Services", dev.GetServices, {"IncludeCapability": False})

    # ---------- Network ----------
    safe(r, "Network", "NetworkInterfaces", dev.GetNetworkInterfaces)
    safe(r, "Network", "NetworkProtocols", dev.GetNetworkProtocols)
    safe(r, "Network", "DNS", dev.GetDNS)
    safe(r, "Network", "NTP", dev.GetNTP)
    safe(r, "Network", "DefaultGateway", dev.GetNetworkDefaultGateway)

    # ---------- Media ----------
    profiles = []
    try:
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        r["Media"] = {"Profiles": to_dict(profiles)}
        safe(r, "Media", "VideoSources", media.GetVideoSources)
        safe(r, "Media", "VideoEncoderConfigurations", media.GetVideoEncoderConfigurations)
        safe(r, "Media", "AudioSources", media.GetAudioSources)
        safe(r, "Media", "AudioEncoderConfigurations", media.GetAudioEncoderConfigurations)

        streams = {}
        for p in profiles:
            entry = {}
            try:
                entry["RTSP_Stream"] = media.GetStreamUri({
                    "StreamSetup": {"Stream": "RTP-Unicast",
                                    "Transport": {"Protocol": "RTSP"}},
                    "ProfileToken": p.token}).Uri
            except Exception as e:
                entry["RTSP_Stream"] = f"error: {e}"
            try:
                entry["Snapshot"] = media.GetSnapshotUri({"ProfileToken": p.token}).Uri
            except Exception as e:
                entry["Snapshot"] = f"error: {e}"
            streams[f"{p.Name} ({p.token})"] = entry
        r["Media"]["StreamAndSnapshotURIs"] = streams
    except Exception as e:
        r["Media"] = f"Media service not available: {e}"

    # ---------- PTZ ----------
    try:
        ptz = cam.create_ptz_service()
        safe(r, "PTZ", "Nodes", ptz.GetNodes)
        safe(r, "PTZ", "Configurations", ptz.GetConfigurations)
        for p in profiles:
            if getattr(p, "PTZConfiguration", None):
                safe(r, "PTZ", f"Status_{p.token}", ptz.GetStatus, {"ProfileToken": p.token})
                safe(r, "PTZ", f"Presets_{p.token}", ptz.GetPresets, {"ProfileToken": p.token})
    except Exception as e:
        r["PTZ"] = f"PTZ not supported: {e}"

    # ---------- Imaging ----------
    try:
        imaging = cam.create_imaging_service()
        for vs in cam.create_media_service().GetVideoSources():
            safe(r, "Imaging", f"Settings_{vs.token}", imaging.GetImagingSettings,
                 {"VideoSourceToken": vs.token})
            safe(r, "Imaging", f"Options_{vs.token}", imaging.GetOptions,
                 {"VideoSourceToken": vs.token})
    except Exception as e:
        r["Imaging"] = f"Imaging not supported: {e}"

    # ---------- Events ----------
    try:
        events = cam.create_events_service()
        safe(r, "Events", "EventProperties", events.GetEventProperties)
    except Exception as e:
        r["Events"] = f"Events not supported: {e}"

    return r


# ----------------------------------------------------------------------
# 3. OUTPUT
# ----------------------------------------------------------------------
def print_summary(r):
    print("\n================ QUICK SUMMARY ================")
    info = r.get("Device", {}).get("DeviceInformation", {})
    if isinstance(info, dict):
        for k in ("Manufacturer", "Model", "FirmwareVersion", "SerialNumber", "HardwareId"):
            print(f"  {k:16}: {info.get(k)}")
    streams = r.get("Media", {}).get("StreamAndSnapshotURIs", {}) \
        if isinstance(r.get("Media"), dict) else {}
    for name, s in streams.items():
        print(f"\n  Profile  : {name}")
        print(f"  RTSP     : {s.get('RTSP_Stream')}")
        print(f"  Snapshot : {s.get('Snapshot')}")
    print("===============================================")


def main():
    cameras = discover_cameras()
    selected = choose_camera(cameras)
    if not selected:
        return

    user = input("Username: ").strip()
    password = getpass.getpass("Password: ")

    try:
        result = collect_all_info(selected, user, password)
    except Exception as e:
        print(f"[!] Could not connect: {e}")
        return

    print("\n================ FULL CAMERA DATA ================")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print_summary(result)

    filename = f"camera_{selected['ip'].replace('.', '_')}_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Full report saved to: {filename}")


if __name__ == "__main__":
    main()