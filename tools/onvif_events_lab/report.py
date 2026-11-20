"""Markdown report from lab results (probe JSON, listen JSON, limits JSON). No credentials are in the inputs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

KINDS = ["motion", "tamper", "digital_input", "video_loss", "line_crossing", "intrusion", "object", "face", "vehicle",
         "people_count", "audio", "relay", "ptz", "storage", "system", "other"]
NVR_KINDS = KINDS[:11]  # what Shah-NVR would store as events


def _vendor(r: dict) -> str:
    i = r.get("identity") or {}
    c = r["camera"]
    return f"{i.get('Manufacturer') or c.get('manufacturer') or '?'} {i.get('Model') or c.get('model') or ''}".strip()


def _kinds(r: dict) -> Counter:
    return Counter(t["kind"] for t in r.get("topics") or [])


def _yes(v) -> str:
    return "✓" if v else ("✗" if v is False else "–")


def probe_section(probe: dict) -> list[str]:
    cams = sorted(probe["cameras"], key=lambda r: (_vendor(r), r["camera"]["id"]))
    L = [f"## Probe ({probe['at']})", ""]
    reach = [r for r in cams if r.get("reachable")]
    with_ev = [r for r in reach if r["stages"].get("event_properties", {}).get("ok")]
    pp = [r for r in reach if r.get("pullpoint") and r["stages"].get("subscribe", {}).get("ok")]
    L += [f"- Cameras probed: **{len(cams)}**; ONVIF reachable: **{len(reach)}**; event topics readable: "
          f"**{len(with_ev)}**; PullPoint works: **{len(pp)}**.", ""]

    L += ["### Per camera", "",
          "| # | Camera | Make / model | FW | Clock offset | Topics | PullPoint | Granted | Sync | Renew | "
          "Event kinds offered (NVR-relevant) | Analytics rules | DI / relays |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in cams:
        c, i = r["camera"], r.get("identity") or {}
        if not r.get("reachable"):
            err = next((s for s in r["stages"].values() if not s.get("ok")), {})
            L.append(f"| {c['id']} | {c['name']} | {_vendor(r)} | | | – | not reachable ({err.get('kind')}) "
                     f"| | | | | | |")
            continue
        p = r.get("pullpoint") or {}
        kinds = _kinds(r)
        offered = ", ".join(f"{k}" + (f"×{kinds[k]}" if kinds[k] > 1 else "") for k in NVR_KINDS if kinds[k])
        an = r.get("analytics") or {}
        rules = sorted({x for cfg in an.get("configs") or [] for x in cfg.get("supported_rules") or []
                        if not str(x).startswith("error")} |
                       {x["type"].split(":")[-1] for cfg in an.get("configs") or [] for x in cfg.get("rules") or []
                        if x.get("type")})
        io = r.get("io") or {}
        di = len(io["inputs"]) if isinstance(io.get("inputs"), list) else "–"
        ro = len(io["relays"]) if isinstance(io.get("relays"), list) else "–"
        sub_ok = r["stages"].get("subscribe", {})
        pp_txt = "✓" if sub_ok.get("ok") else f"✗ {sub_ok.get('kind', '')}"
        off = (r.get("clock") or {}).get("offset_s")
        L.append(f"| {c['id']} | {c['name']} | {_vendor(r)} | {i.get('FirmwareVersion') or ''} | "
                 f"{'' if off is None else f'{off:+.0f} s'} | {len(r.get('topics') or [])} | {pp_txt} | "
                 f"{'' if p.get('granted_s') is None else f'{p['granted_s']:.0f} s'} | {_yes(p.get('sync_point'))} | "
                 f"{_yes(p.get('renew'))} | {offered or '–'} | {', '.join(rules) or '–'} | {di} / {ro} |")
    L.append("")

    # capability matrix by make/model
    groups = defaultdict(list)
    for r in reach:
        groups[_vendor(r)].append(r)
    L += ["### Capability matrix (by make / model)", "",
          "| Make / model | Cameras | " + " | ".join(NVR_KINDS) + " |",
          "|---|---|" + "---|" * len(NVR_KINDS)]
    for g, rs in sorted(groups.items()):
        row = []
        for k in NVR_KINDS:
            n = sum(1 for r in rs if _kinds(r)[k])
            row.append("✓" if n == len(rs) else (f"{n}/{len(rs)}" if n else ""))
        L.append(f"| {g} | {len(rs)} | " + " | ".join(row) + " |")
    L.append("")

    # topic catalogue
    cat = defaultdict(lambda: {"cams": set(), "kind": "", "prop": None, "data": set(), "source": set()})
    for r in reach:
        for t in r.get("topics") or []:
            e = cat[t["path"]]
            e["cams"].add(r["camera"]["id"])
            e["kind"], e["prop"] = t["kind"], t["is_property"]
            e["data"] |= {d["name"] for d in t["data"]}
            e["source"] |= {d["name"] for d in t["source"]}
    L += ["### Topic catalogue", "",
          "Every topic any camera advertises, with the kind we classify it as. *State* = property topic (camera sends "
          "the current value on subscribe and on every change); *pulse* = one message per occurrence.", "",
          "| Topic | Kind | State/pulse | Cameras | Source items | Data items |", "|---|---|---|---|---|---|"]
    for path, e in sorted(cat.items(), key=lambda kv: (KINDS.index(kv[1]["kind"]), kv[0])):
        L.append(f"| `{path}` | {e['kind']} | {'state' if e['prop'] else 'pulse'} | {len(e['cams'])} | "
                 f"{', '.join(sorted(e['source']))} | {', '.join(sorted(e['data']))} |")
    L.append("")

    # initial states seen in the probe pull
    L += ["### Initial states (after SetSynchronizationPoint)", ""]
    any_msgs = False
    for r in cams:
        msgs = (r.get("pullpoint") or {}).get("messages") or []
        if not msgs:
            continue
        any_msgs = True
        kinds = Counter(m["kind"] for m in msgs)
        L.append(f"- **{r['camera']['name']}** ({_vendor(r)}): {len(msgs)} messages: "
                 + ", ".join(f"{k} {n}" for k, n in kinds.most_common()))
    if not any_msgs:
        L.append("- No camera sent messages during the probe pull.")
    L.append("")

    # errors
    errs = Counter()
    examples = {}
    for r in cams:
        for stage, s in r["stages"].items():
            if not s.get("ok"):
                key = (stage, s.get("kind"), (s.get("fault") or "")[:80])
                errs[key] += 1
                examples.setdefault(key, f"{r['camera']['name']}: {s.get('message', '')[:120]}")
    if errs:
        L += ["### Errors by stage", "", "| Stage | Kind | Fault code | Cameras | Example |", "|---|---|---|---|---|"]
        for (stage, kind, fault), n in errs.most_common():
            L.append(f"| {stage} | {kind} | {fault} | {n} | {examples[(stage, kind, fault)]} |")
        L.append("")
    return L


def listen_section(listen: dict) -> list[str]:
    L = [f"## Listen ({listen['minutes']:g} min, events file `{listen['events_file']}`)", "",
         "| Camera | Messages | Kinds seen (changes) | Activations (state → on) | Latency p50 / p95 | "
         "Subscriptions | Renew fails | Errors |", "|---|---|---|---|---|---|---|---|"]
    for s in sorted(listen["cameras"], key=lambda s: -s["messages"]):
        lat = s.get("latency")
        L.append(f"| {s['camera']['name']} | {s['messages']} | "
                 f"{', '.join(f'{k} {n}' for k, n in sorted(s['changes'].items(), key=lambda kv: -kv[1])) or '–'} | "
                 f"{', '.join(f'{k} {n}' for k, n in s['activations'].items()) or '–'} | "
                 f"{f'{lat['p50']:.2f} / {lat['p95']:.2f} s' if lat else '–'} | {s['subscriptions']} | "
                 f"{s['renew_failures']} | {', '.join(f'{k}×{n}' for k, n in s['errors'].items()) or '–'} |")
    L.append("")
    return L


def limits_section(items: list[dict]) -> list[str]:
    L = ["## Subscription slots", "", "| Camera | Tried | Accepted | Usable | Removed | Refusal |",
         "|---|---|---|---|---|---|"]
    for x in items:
        ref = x.get("refused") or {}
        L.append(f"| {x['camera']['name']} | {x['maximum_tried']} | {x['accepted']} | {x.get('usable_after')} | "
                 f"{x.get('unsubscribed')} | {ref.get('kind', '')} {ref.get('message', '')[:80]} |")
    L.append("")
    return L


def trigger_section(nudges: list[dict], events_file: Path | None) -> list[str]:
    """Controlled triggers (ptz-nudge) matched to the messages the listener received from that camera."""
    from datetime import datetime

    rows = [json.loads(x) for x in events_file.read_text(encoding="utf-8").splitlines()] if events_file else []
    L = ["## Controlled triggers (PTZ nudge, AXIS virtual input)", "",
         "Each mark is when the lab sent the command (our clock). *First message* = the first message of that kind "
         "from the camera received after the mark, and the delay from the mark to its arrival.", "",
         "| Camera | Mark | Kind | First message (topic) | Delay | State |", "|---|---|---|---|---|---|"]
    for nudge in nudges:
        for cid, n in nudge.items():
            marks = [(m["what"], datetime.fromisoformat(m["at"])) for m in n.get("events", [])]
            for i, (what, at) in enumerate(marks[:-1]):
                until = marks[i + 1][1]
                mine = [r for r in rows if str(r["camera_id"]) == str(cid)
                        and at <= datetime.fromisoformat(r["recv"]) < until]
                firsts = {}
                for r in sorted(mine, key=lambda r: r["recv"]):
                    firsts.setdefault(r["kind"], r)
                if not firsts:
                    L.append(f"| {n['camera']} | {what} | – | no message | | |")
                for kind, r in firsts.items():
                    delay = (datetime.fromisoformat(r["recv"]) - at).total_seconds()
                    L.append(f"| {n['camera']} | {what} | {kind} | `{r['topic']}` | {delay:.2f} s | {r.get('state')} |")
            L.append(f"| {n['camera']} | back to start | | {n.get('back_to_start')} | | |")
    L.append("")
    return L


def build(results_dir: Path, title: str = "ONVIF events lab results") -> str:
    def latest(pattern):
        files = sorted(p for p in results_dir.glob(pattern) if not p.name.endswith(".jsonl")
                       and not p.name.endswith("-run.log"))
        return json.loads(files[-1].read_text(encoding="utf-8")) if files else None

    L = [f"# {title}", "", "Generated by `python -m onvif_events_lab report`. No credentials are included.", ""]
    if (p := latest("probe-*.json")):
        L += probe_section(p)
    if (s := latest("listen-*.json")):
        L += listen_section(s)
    nudges = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(results_dir.glob("ptz-nudge-*.json"))]
    if nudges:
        ev = sorted(results_dir.glob("listen-*.jsonl"))
        L += trigger_section(nudges, ev[-1] if ev else None)
    lim = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(results_dir.glob("limits-*.json"))]
    if lim:
        L += limits_section(lim)
    return "\n".join(L)
