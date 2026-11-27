/**
 * Timeline markers: one generic overlay for anything that happened at a time (or over a range).
 * Bookmarks feed it now; motion and ONVIF events feed the same shape later. Pure (unit-tested).
 */
export type TimelineMarker = {
  id: string | number
  /** start, ms epoch */
  t: number
  /** end, ms epoch; null/undefined = a point in time */
  endT?: number | null
  /** "bookmark" or "event" */
  kind: string
  /** where a click plays from (default `t`): an event plays from its pre-event seconds */
  seekT?: number
  label?: string
  color?: string
}

/** A marker positioned on the visible window: x and width in percent of the timeline width. */
export type PlacedMarker = TimelineMarker & { x: number; width: number | null }

/** Ranges narrower than this (percent) are still drawn wide enough to see and click. */
export const MIN_RANGE_WIDTH = 0.4

/** Markers visible in [viewStart, viewEnd], with their x / width in percent. */
export function placeMarkers(markers: TimelineMarker[], viewStart: number, viewEnd: number): PlacedMarker[] {
  const span = viewEnd - viewStart
  if (span <= 0) return []
  const pct = (t: number) => ((t - viewStart) / span) * 100
  const out: PlacedMarker[] = []
  for (const m of markers) {
    if (m.endT != null && m.endT > m.t) {
      if (m.endT <= viewStart || m.t >= viewEnd) continue
      const x = Math.max(0, pct(m.t))
      const right = Math.min(100, pct(m.endT))
      out.push({ ...m, x, width: Math.max(MIN_RANGE_WIDTH, right - x) })
    } else {
      if (m.t < viewStart || m.t > viewEnd) continue
      out.push({ ...m, x: pct(m.t), width: null })
    }
  }
  return out
}

/** Bookmark (from the API) -> timeline marker. */
export function bookmarkMarker(b: {
  id: number
  start_time: string
  end_time?: string | null
  note: string
  label?: string | null
  color?: string | null
}): TimelineMarker {
  return {
    id: `bookmark-${b.id}`,
    t: new Date(b.start_time).getTime(),
    endT: b.end_time ? new Date(b.end_time).getTime() : null,
    kind: "bookmark",
    label: b.label ? `${b.label}: ${b.note}` : b.note,
    color: b.color ?? undefined,
  }
}

/** Colours of event types (docs/EVENT_RECORDING_PLAN.md §10); unknown types are grey. */
export const EVENT_COLORS: Record<string, string> = {
  manual: "#3b82f6",
  api: "#8b5cf6",
  video_loss: "#ef4444",
  motion: "#f59e0b",
  tamper: "#f97316",
  digital_input: "#14b8a6",
  onvif: "#94a3b8",
  // camera analytics (docs/ONVIF_ANALYTICS_EVENTS_PLAN.md §1)
  line_crossing: "#d946ef",
  intrusion: "#e11d48",
  loitering: "#0ea5e9",
  object_left: "#84cc16",
  person: "#22c55e",
  face: "#ec4899",
  counting: "#64748b",
  audio_alarm: "#eab308",
}
export const EVENT_LABELS: Record<string, string> = {
  manual: "Marked",
  api: "External",
  video_loss: "Video loss",
  motion: "Motion",
  tamper: "Tamper",
  digital_input: "Input",
  onvif: "Camera event",
  line_crossing: "Line crossing",
  intrusion: "Intrusion",
  loitering: "Loitering",
  object_left: "Object left",
  person: "Person",
  face: "Face",
  counting: "People counting",
  audio_alarm: "Audio alarm",
}
/** Groups of the Events page type filter (central `group=`). */
export const EVENT_TYPE_GROUPS: { group: "camera" | "analytics" | "operator"; title: string; types: string[] }[] = [
  { group: "camera", title: "Camera", types: ["motion", "tamper", "digital_input", "video_loss", "onvif"] },
  { group: "analytics", title: "Analytics", types: ["line_crossing", "intrusion", "loitering", "object_left", "person", "face", "counting", "audio_alarm"] },
  { group: "operator", title: "Operator", types: ["manual", "api"] },
]

/** "Line crossing: Gate line" text for an event; analytics labels already start with their type title. */
export function eventText(e: { type: string; label?: string | null }): string {
  const title = eventTypeLabel(e.type)
  if (!e.label) return title
  return e.label.startsWith(title) ? e.label : `${title}: ${e.label}`
}
export const eventColor = (type: string) => EVENT_COLORS[type] ?? "#94a3b8"
export const eventTypeLabel = (type: string) => EVENT_LABELS[type] ?? type.replace(/[_.:-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase())

/** Event (from the API) -> timeline marker: a moment is a pin, a range a band; an open event runs to `now`. */
export function eventMarker(
  e: { id: number; type: string; start_time: string; end_time?: string | null; label?: string | null; pre_seconds: number },
  now = Date.now(),
): TimelineMarker {
  const t = new Date(e.start_time).getTime()
  const end = e.end_time ? new Date(e.end_time).getTime() : now
  return {
    id: `event-${e.id}`,
    t,
    endT: end > t ? end : null,
    kind: "event",
    label: `${eventText(e)}${e.end_time ? "" : " (ongoing)"}`,
    color: eventColor(e.type),
    seekT: t - e.pre_seconds * 1000,
  }
}
