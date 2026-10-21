import { ApiError } from "@/api/client"
import type { OnvifProfile } from "@/api/types"

/** Camera clock drift above this is flagged (dashboard alert, Device tab). */
export const CLOCK_DRIFT_ALERT_SECONDS = 10

/** Friendly text for ONVIF errors ({"code", "message"} from central). */
export function onvifErrorText(err: unknown): string {
  const code = err instanceof ApiError ? err.code : undefined
  switch (code) {
    case "not_authorized":
      return "Wrong username or password. Not retried automatically: many cameras lock the account after a few wrong logins."
    case "unreachable":
      return "The camera did not answer (wrong address, port or camera offline)."
    case "not_supported":
      return "The camera does not support this ONVIF function."
    case "node_offline":
    case "node_unreachable":
    case "node_timeout":
    case "no_node_online":
      return err instanceof Error ? err.message : "Media node not reachable"
    default:
      return err instanceof Error ? err.message : String(err)
  }
}

/** "Streaming" in discovery scopes is Profile S. */
export const profileLabels = (profiles: string[]) =>
  profiles.map((p) => (p.toLowerCase() === "streaming" ? "S" : p)).filter((p, i, a) => a.indexOf(p) === i)

export const profileSummary = (p: OnvifProfile) =>
  [p.encoding, p.width && p.height ? `${p.width}×${p.height}` : null, p.fps ? `${p.fps} fps` : null,
    p.bitrate_kbps ? `${p.bitrate_kbps} kbps` : null,
    p.has_audio ? `Audio ${p.audio_codec?.toUpperCase() ?? p.audio_encoding ?? "detected"}` : "No audio"]
    .filter(Boolean).join(" · ")

export const isVideoProfile = (p: OnvifProfile) => (p.encoding === "H264" || p.encoding === "H265") && !!p.rtsp

/** "+3 s", "−9 min 23 s", "−26.5 years". */
export function formatOffset(seconds: number | null | undefined): string {
  if (seconds == null) return "unknown"
  const sign = seconds > 0 ? "+" : seconds < 0 ? "−" : ""
  const s = Math.abs(seconds)
  if (s < 1) return "in sync"
  if (s < 60) return `${sign}${Math.round(s)} s`
  if (s < 3600) return `${sign}${Math.floor(s / 60)} min ${Math.round(s % 60)} s`
  if (s < 86400) return `${sign}${(s / 3600).toFixed(1)} h`
  if (s < 86400 * 365) return `${sign}${Math.round(s / 86400)} days`
  return `${sign}${(s / (86400 * 365.25)).toFixed(1)} years`
}

export const driftTone = (seconds: number | null | undefined) =>
  seconds == null ? "muted" : Math.abs(seconds) > CLOCK_DRIFT_ALERT_SECONDS ? "warning" : "success"

/** Short names for ONVIF service namespaces (what the camera can do). */
export function serviceNames(namespaces: string[] | null | undefined): string[] {
  const map: [RegExp, string][] = [
    [/ver20\/media/, "Media2"], [/ver10\/media/, "Media"], [/events/, "Events"], [/ptz/, "PTZ"],
    [/imaging/, "Imaging"], [/deviceIO/i, "I/O"], [/recording/, "Recording"], [/replay/, "Replay"],
    [/search/, "Search"], [/analytics/, "Analytics"],
  ]
  const out: string[] = []
  for (const ns of namespaces ?? []) {
    const hit = map.find(([re]) => re.test(ns))
    if (hit && !out.includes(hit[1])) out.push(hit[1])
  }
  return out
}

/** "AXIS M1125" (model already names the maker) or "Hanwha SNV-L6014RM". */
export function deviceLabel(manufacturer: string | null | undefined, model: string | null | undefined): string {
  if (!model) return manufacturer ?? ""
  return manufacturer && !model.toLowerCase().includes(manufacturer.toLowerCase()) ? `${manufacturer} ${model}` : model
}
