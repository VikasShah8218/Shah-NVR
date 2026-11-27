/** Camera events from ONVIF (docs/ONVIF_EVENTS_PLAN.md §7, docs/ONVIF_ANALYTICS_EVENTS_PLAN.md §7): kinds, labels
 * and the status line. */

/** The basic kinds: what "all kinds" (null) means. */
export const CAMERA_EVENT_KINDS = ["motion", "tamper", "digital_input"] as const
/** The camera's own analytics: opt-in per kind (null never includes them). */
export const ANALYTICS_KINDS = [
  "line_crossing", "intrusion", "loitering", "object_left", "person", "face", "counting", "audio_alarm",
] as const
export const ALL_CAMERA_EVENT_KINDS = [...CAMERA_EVENT_KINDS, ...ANALYTICS_KINDS] as const
export type BasicEventKind = (typeof CAMERA_EVENT_KINDS)[number]
export type AnalyticsKind = (typeof ANALYTICS_KINDS)[number]
export type CameraEventKind = BasicEventKind | AnalyticsKind

export const CAMERA_EVENT_LABELS: Record<CameraEventKind, { title: string; hint: string }> = {
  motion: { title: "Motion", hint: "The camera's own motion detection" },
  tamper: { title: "Tamper", hint: "Lens covered, blurred or camera turned" },
  digital_input: { title: "Digital inputs", hint: "Door contacts, alarm panels, buttons wired to the camera" },
  line_crossing: { title: "Line crossing", hint: "An object crossed a virtual line" },
  intrusion: { title: "Intrusion", hint: "An object is inside a zone" },
  loitering: { title: "Loitering", hint: "An object stays in a zone too long" },
  object_left: { title: "Object left", hint: "An object was left behind or removed" },
  person: { title: "Person", hint: "A person is detected" },
  face: { title: "Face", hint: "A face is detected" },
  counting: { title: "People counting", hint: "In / out counts (can be noisy)" },
  audio_alarm: { title: "Audio alarm", hint: "The camera's audio analytics (scream, glass break…)" },
}

export const isAnalyticsKind = (k: string): k is AnalyticsKind => (ANALYTICS_KINDS as readonly string[]).includes(k)

/** Saved kinds of a camera: null = the basic three. */
export const savedKinds = (kinds: readonly string[] | null | undefined): CameraEventKind[] =>
  ((kinds ?? CAMERA_EVENT_KINDS) as CameraEventKind[]).filter((k) => k in CAMERA_EVENT_LABELS)

/** Kinds in the canonical order, with `k` switched on or off. */
export const withKind = (cur: readonly CameraEventKind[], k: CameraEventKind, on: boolean): CameraEventKind[] =>
  ALL_CAMERA_EVENT_KINDS.filter((x) => (x === k ? on : cur.includes(x)))

/** What to send: null when exactly the basic three are on (keeps "all kinds" for old cameras). */
export const kindsBody = (kinds: readonly CameraEventKind[]): CameraEventKind[] | null =>
  kinds.length === CAMERA_EVENT_KINDS.length && CAMERA_EVENT_KINDS.every((k) => kinds.includes(k)) ? null : [...kinds]

/** An analytics kind the camera offers, with its configured rules (Detect; read-only). */
export type AnalyticsOffer = { kind: string; topics?: string[]; rules?: { name: string; type?: string | null }[] }

/** What the node (or a Detect) reported: see CameraOut.onvif_events_status. */
export type CameraEventsStatus = {
  state?: string
  topics?: Record<string, string> | null
  offered?: string[] | null
  detail?: string | null
  last_event_at?: string | null
  since?: string | null
  detected_at?: string | null
  analytics?: AnalyticsOffer[] | null
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
      if (status.detail?.startsWith("busy")) {
        return { tone: "warning", text: `Receiving events, ${status.detail}. Narrow the camera's rules or switch noisy kinds off.` }
      }
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
