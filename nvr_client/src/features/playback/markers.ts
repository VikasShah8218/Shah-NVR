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
  /** "bookmark" today; "motion", "event"... later */
  kind: string
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
