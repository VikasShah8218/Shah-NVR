/** Camera events from ONVIF (docs/ONVIF_EVENTS_PLAN.md §7): kinds, labels and the status line. */

export const CAMERA_EVENT_KINDS = ["motion", "tamper", "digital_input"] as const
export type CameraEventKind = (typeof CAMERA_EVENT_KINDS)[number]

export const CAMERA_EVENT_LABELS: Record<CameraEventKind, { title: string; hint: string }> = {
  motion: { title: "Motion", hint: "The camera's own motion detection" },
  tamper: { title: "Tamper", hint: "Lens covered, blurred or camera turned" },
  digital_input: { title: "Digital inputs", hint: "Door contacts, alarm panels, buttons wired to the camera" },
}

/** What the node (or a Detect) reported: see CameraOut.onvif_events_status. */
export type CameraEventsStatus = {
  state?: string
  topics?: Record<string, string> | null
  offered?: string[] | null
  detail?: string | null
  last_event_at?: string | null
  since?: string | null
  detected_at?: string | null
}

export type StatusLine = { tone: "success" | "warning" | "danger" | "muted"; text: string }

/** One line for the camera's event state; `agoText` turns an ISO time into "3 min ago". */
export function cameraEventsStatusLine(
  enabled: boolean,
  kinds: readonly string[],
  status: CameraEventsStatus | null | undefined,
  agoText: (iso: string) => string,
): StatusLine {
  const offered = status?.offered ?? null
  const missing = offered ? kinds.filter((k) => !offered.includes(k)) : []
  const missingText = missing.length
    ? ` ${missing.map((k) => CAMERA_EVENT_LABELS[k as CameraEventKind]?.title ?? k).join(", ")} not offered by the camera.`
    : ""
  if (!enabled) {
    if (offered) return { tone: "muted", text: `Off. The camera offers: ${offered.length ? offered.map(kindTitle).join(", ") : "none of these events"}.` }
    return { tone: "muted", text: "Off. Press Detect to see what the camera offers." }
  }
  switch (status?.state) {
    case "ok":
      return {
        tone: missing.length ? "warning" : "success",
        text: (status.last_event_at ? `Receiving events (last ${agoText(status.last_event_at)}).` : "Receiving events; none yet.")
          + missingText,
      }
    case "auth_failed":
      return { tone: "danger", text: "Login failed: check the camera's username and password. Retried when they change or after 30 min." }
    case "no_topics":
      return { tone: "warning", text: "The camera offers none of the chosen events. Enable motion detection (or the event) in the camera's own web page, then press Detect." }
    case "unsupported":
      return { tone: "danger", text: "This camera has no ONVIF event service." }
    case "unreachable":
      return { tone: "danger", text: `Camera not answering${status.detail ? ` (${status.detail})` : ""}. Retrying.` }
    case "error":
      return { tone: "danger", text: `Error: ${status.detail ?? "unknown"}. Retrying.` }
    default:
      return { tone: "muted", text: "Starting: the recording node subscribes within a few seconds." + missingText }
  }
}

export const kindTitle = (k: string) => CAMERA_EVENT_LABELS[k as CameraEventKind]?.title ?? k

/** Remount key for the camera events form: saved changes reset its draft. */
export const cameraEventsKey = (c: { id: number; onvif_events_enabled?: boolean; onvif_event_kinds?: string[] | null; onvif_events_store_other?: boolean }) =>
  `${c.id}-${c.onvif_events_enabled}-${(c.onvif_event_kinds ?? []).join()}-${c.onvif_events_store_other}`
