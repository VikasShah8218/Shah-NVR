import { format } from "date-fns"
import { useEffect, useMemo, useRef, useState } from "react"
import type { Segment } from "@/api/types"
import { cn } from "@/lib/utils"
import { placeMarkers, type TimelineMarker } from "./markers"
import { THUMB_DEBOUNCE_MS } from "./thumbs"

const MIN = 60_000

/** Tick spacing for a visible span, aiming for ~8-14 labels. */
function tickStep(spanMs: number): number {
  const steps = [MIN, 2 * MIN, 5 * MIN, 10 * MIN, 15 * MIN, 30 * MIN, 60 * MIN, 120 * MIN, 180 * MIN]
  return steps.find((s) => spanMs / s <= 14) ?? 240 * MIN
}

/** Merge touching/overlapping segments into continuous recorded ranges (ms epoch). */
export function mergeRanges(segments: Segment[], toleranceMs = 2000): [number, number][] {
  const sorted = segments
    .map((s) => [new Date(s.start_time).getTime(), new Date(s.end_time).getTime()] as [number, number])
    .sort((a, b) => a[0] - b[0])
  const out: [number, number][] = []
  for (const r of sorted) {
    const last = out[out.length - 1]
    if (last && r[0] <= last[1] + toleranceMs) last[1] = Math.max(last[1], r[1])
    else out.push([...r])
  }
  return out
}

/**
 * Recording timeline: recorded ranges vs gaps for the visible window, hour/minute ticks,
 * a playhead and a "now" marker. Click to seek, drag to pan.
 */
export function Timeline({
  segments,
  viewStart,
  viewEnd,
  bounds,
  playhead,
  onSeek,
  onPan,
  markers = [],
  thumbAt,
  height = 56,
}: {
  segments: Segment[]
  viewStart: number
  viewEnd: number
  bounds: [number, number]
  playhead: number | null
  onSeek: (t: number) => void
  onPan?: (newViewStart: number) => void
  /** Bookmarks today; motion / ONVIF events later. Clicking one seeks to its start. */
  markers?: TimelineMarker[]
  /** Hover preview: picture URL + the time it shows for a hovered time, or null (gap / unknown node). */
  thumbAt?: (t: number) => { url: string; at: number } | null
  height?: number
}) {
  const ref = useRef<SVGSVGElement>(null)
  const drag = useRef<{ x: number; start: number; moved: boolean } | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  // Debounced hover time for the preview picture (see thumbs.ts).
  const [settled, setSettled] = useState<number | null>(null)
  const [dragging, setDragging] = useState(false)
  useEffect(() => {
    if (hover == null || !thumbAt) return
    const id = window.setTimeout(() => setSettled(hover), THUMB_DEBOUNCE_MS)
    return () => window.clearTimeout(id)
  }, [hover, thumbAt])
  const thumb = hover != null && settled != null && !dragging ? thumbAt?.(settled) ?? null : null
  const span = viewEnd - viewStart
  const ranges = useMemo(() => mergeRanges(segments.filter((segment) => segment.origin !== "CAMERA_SD")), [segments])
  const backfillRanges = useMemo(() => mergeRanges(segments.filter((segment) => segment.origin === "CAMERA_SD")), [segments])
  const placed = useMemo(() => placeMarkers(markers, viewStart, viewEnd), [markers, viewStart, viewEnd])
  const now = Date.now()

  const pct = (t: number) => ((t - viewStart) / span) * 100
  const timeAt = (clientX: number) => {
    const rect = ref.current!.getBoundingClientRect()
    return viewStart + ((clientX - rect.left) / rect.width) * span
  }

  const step = tickStep(span)
  const ticks: number[] = []
  // Align ticks to local clock time (e.g. 00:00, 02:00 in UTC+05:30), not to UTC multiples.
  const tz = new Date(viewStart).getTimezoneOffset() * MIN
  for (let t = Math.ceil((viewStart - tz) / step) * step + tz; t <= viewEnd; t += step) ticks.push(t)

  const onPointerDown = (e: React.PointerEvent) => {
    ;(e.target as Element).setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, start: viewStart, moved: false }
  }
  const onPointerMove = (e: React.PointerEvent) => {
    setHover(timeAt(e.clientX))
    const d = drag.current
    if (!d || !onPan) return
    const dx = e.clientX - d.x
    if (Math.abs(dx) > 3 && !d.moved) { d.moved = true; setDragging(true) }
    if (d.moved) {
      const width = ref.current!.getBoundingClientRect().width
      const next = d.start - (dx / width) * span
      onPan(Math.max(bounds[0], Math.min(bounds[1] - span, next)))
    }
  }
  const onPointerUp = (e: React.PointerEvent) => {
    const d = drag.current
    drag.current = null
    setDragging(false)
    if (!d || d.moved) return
    // A click on a marker seeks exactly to its start, not to the pixel under the pointer.
    const markerT = (e.target as Element).closest?.("[data-marker-t]")?.getAttribute("data-marker-t")
    const t = markerT != null ? Number(markerT) : timeAt(e.clientX)
    onSeek(Math.max(bounds[0], Math.min(bounds[1], t)))
  }

  return (
    <div className="relative select-none py-1">
      {thumb && hover != null && <ThumbPopover key={thumb.url} url={thumb.url} at={thumb.at} x={pct(hover)} />}
      <svg
        ref={ref}
        className={cn("w-full touch-none", onPan ? "cursor-grab active:cursor-grabbing" : "cursor-pointer")}
        style={{ height }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => { drag.current = null; setDragging(false) }}
        onPointerLeave={() => { setHover(null); setSettled(null) }}
      >
        <defs>
          <pattern id="camera-sd-backfill" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="8" height="8" fill="var(--info)" opacity="0.45" />
            <rect width="3" height="8" fill="var(--info)" opacity="0.9" />
          </pattern>
        </defs>
        {/* gaps (background) */}
        <rect x="0" y="18" width="100%" height={height - 26} rx="4" fill="var(--muted)" />
        {/* future */}
        {now < viewEnd && (
          <rect x={`${Math.max(0, pct(now))}%`} y="18" width={`${100 - Math.max(0, pct(now))}%`} height={height - 26} fill="var(--background)" opacity="0.6" />
        )}
        {/* recorded */}
        {ranges
          .filter(([a, b]) => b > viewStart && a < viewEnd)
          .map(([a, b], i) => (
            <rect
              key={i}
              x={`${Math.max(0, pct(a))}%`}
              y="18"
              width={`${Math.max(0.15, pct(Math.min(b, viewEnd)) - Math.max(0, pct(a)))}%`}
              height={height - 26}
              fill="var(--success)"
              opacity="0.75"
            />
          ))}
        {/* footage recovered from camera edge storage */}
        {backfillRanges
          .filter(([a, b]) => b > viewStart && a < viewEnd)
          .map(([a, b], i) => (
            <rect key={`sd-${i}`} x={`${Math.max(0, pct(a))}%`} y="18"
              width={`${Math.max(0.15, pct(Math.min(b, viewEnd)) - Math.max(0, pct(a)))}%`}
              height={height - 26} fill="url(#camera-sd-backfill)">
              <title>Filled from camera SD storage</title>
            </rect>
          ))}
        {/* ticks */}
        {ticks.map((t) => (
          <g key={t}>
            <line x1={`${pct(t)}%`} x2={`${pct(t)}%`} y1="14" y2={height - 8} stroke="var(--border)" strokeWidth="1" />
            <text
              x={`${pct(t)}%`}
              y="10"
              fontSize="10"
              fill="var(--muted-foreground)"
              textAnchor={pct(t) < 2 ? "start" : pct(t) > 98 ? "end" : "middle"}
            >
              {format(t, "HH:mm")}
            </text>
          </g>
        ))}
        {/* markers (bookmarks, later events): ranges as a band under the bar, points as a pin */}
        {placed.map((m) => {
          const color = m.color ?? "var(--primary)"
          return (
            <g key={m.id} data-marker-t={m.t} className="cursor-pointer">
              <title>{m.label ?? m.kind}</title>
              {m.width != null ? (
                <rect x={`${m.x}%`} y={height - 12} width={`${m.width}%`} height="5" rx="2" fill={color} opacity="0.85" />
              ) : (
                <>
                  <line x1={`${m.x}%`} x2={`${m.x}%`} y1="16" y2={height - 6} stroke={color} strokeWidth="2" />
                  <circle cx={`${m.x}%`} cy={height - 7} r="3.5" fill={color} />
                  {/* wider invisible hit area so a 2px pin is easy to click */}
                  <line x1={`${m.x}%`} x2={`${m.x}%`} y1="14" y2={height} stroke="transparent" strokeWidth="10" />
                </>
              )}
            </g>
          )
        })}
        {/* now */}
        {now > viewStart && now < viewEnd && (
          <line x1={`${pct(now)}%`} x2={`${pct(now)}%`} y1="14" y2={height - 4} stroke="var(--info)" strokeDasharray="3 3" />
        )}
        {/* hover */}
        {hover != null && (
          <g pointerEvents="none">
            <line x1={`${pct(hover)}%`} x2={`${pct(hover)}%`} y1="14" y2={height - 4} stroke="var(--foreground)" strokeOpacity="0.4" />
          </g>
        )}
        {/* playhead */}
        {playhead != null && playhead >= viewStart && playhead <= viewEnd && (
          <g pointerEvents="none">
            <line x1={`${pct(playhead)}%`} x2={`${pct(playhead)}%`} y1="12" y2={height} stroke="var(--warning)" strokeWidth="2" />
            <circle cx={`${pct(playhead)}%`} cy="13" r="4" fill="var(--warning)" />
          </g>
        )}
      </svg>
      <div className="mt-1 flex justify-between text-[11px] text-muted-foreground tabular-nums">
        <span>{format(viewStart, "dd MMM HH:mm")}</span>
        <span>{hover != null ? format(hover, "HH:mm:ss") : ""}</span>
        <span>{format(viewEnd, "dd MMM HH:mm")}</span>
      </div>
    </div>
  )
}

/** Small preview frame above the timeline. Keyed by URL, so a new slot starts in the loading state. */
function ThumbPopover({ url, at, x }: { url: string; at: number; x: number }) {
  const [state, setState] = useState<"loading" | "ok" | "error">("loading")
  const shift = x < 12 ? "0%" : x > 88 ? "-100%" : "-50%"
  return (
    <div className="pointer-events-none absolute bottom-full z-20 mb-1 w-40 overflow-hidden rounded-md border bg-card shadow-lg"
      style={{ left: `${x}%`, transform: `translateX(${shift})` }}>
      <div className="grid aspect-video place-items-center bg-video text-[11px] text-muted-foreground">
        {state !== "error" && (
          <img src={url} alt="" className={cn("size-full object-cover", state === "loading" && "opacity-0")}
            onLoad={() => setState("ok")} onError={() => setState("error")} />
        )}
        {state === "loading" && <span className="absolute">Loading…</span>}
        {state === "error" && <span>No preview</span>}
      </div>
      <div className="px-1.5 py-0.5 text-center text-[11px] tabular-nums text-muted-foreground">{format(at, "HH:mm:ss")}</div>
    </div>
  )
}
