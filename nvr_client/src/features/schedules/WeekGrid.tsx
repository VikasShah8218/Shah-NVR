import { useMemo, useRef, useState } from "react"
import type { ScheduleBlock } from "@/api/types"
import {
  bitmapToBlocks,
  blocksToBitmap,
  cellCoverage,
  DAY_MIN,
  DAYS,
  dayRuns,
  fmtHHMM,
  SLOT_MIN,
  SLOTS,
} from "@/lib/schedule"
import { cn } from "@/lib/utils"

export type Brush = "on" | "off"
type Cell = { d: number; q: number }

const HOURS = [0, 3, 6, 9, 12, 15, 18, 21, 24]

function NowMarker({ minute }: { minute: number }) {
  return (
    <span
      className="pointer-events-none absolute inset-y-[-2px] z-10 w-0.5 rounded bg-danger"
      style={{ left: `${(minute / DAY_MIN) * 100}%` }}
      title={`Now (site time) ${fmtHHMM(minute)}`}
    />
  )
}

function HourAxis() {
  return (
    <div className="relative ml-11 h-4 text-[10px] text-muted-foreground">
      {HOURS.map((h) => (
        <span key={h} className="absolute -translate-x-1/2 tabular-nums" style={{ left: `${(h / 24) * 100}%` }}>
          {String(h).padStart(2, "0")}
        </span>
      ))}
    </div>
  )
}

/** The 7×24 week editor: drag a rectangle to paint Record / Off in 15-minute steps. Read-only without `onChange`. */
export function WeekGrid({
  blocks,
  onChange,
  brush = "on",
  now,
}: {
  blocks: ScheduleBlock[]
  onChange?: (blocks: ScheduleBlock[]) => void
  brush?: Brush
  now?: { day: number; minute: number }
}) {
  const bits = useMemo(() => blocksToBitmap(blocks), [blocks])
  const cov = useMemo(() => cellCoverage(bits), [bits])
  const area = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<{ a: Cell; b: Cell } | null>(null)
  const [hover, setHover] = useState<Cell | null>(null)

  const cellAt = (e: React.PointerEvent): Cell => {
    const r = area.current!.getBoundingClientRect()
    const x = Math.min(Math.max(e.clientX - r.left, 0), r.width - 1)
    const y = Math.min(Math.max(e.clientY - r.top, 0), r.height - 1)
    return { d: Math.floor((y / r.height) * 7), q: Math.floor((x / r.width) * SLOTS) }
  }

  const rect = drag && {
    d0: Math.min(drag.a.d, drag.b.d), d1: Math.max(drag.a.d, drag.b.d),
    q0: Math.min(drag.a.q, drag.b.q), q1: Math.max(drag.a.q, drag.b.q),
  }
  const inRect = (d: number, q: number) => !!rect && d >= rect.d0 && d <= rect.d1 && q >= rect.q0 && q <= rect.q1

  const commit = () => {
    if (!rect || !onChange) return
    const next = bits.slice()
    for (let d = rect.d0; d <= rect.d1; d++) {
      next.fill(brush === "on" ? 1 : 0, d * DAY_MIN + rect.q0 * SLOT_MIN, d * DAY_MIN + (rect.q1 + 1) * SLOT_MIN)
    }
    onChange(bitmapToBlocks(next))
  }

  const tip = rect
    ? `${rect.d0 === rect.d1 ? DAYS[rect.d0] : `${DAYS[rect.d0]}–${DAYS[rect.d1]}`} ${fmtHHMM(rect.q0 * SLOT_MIN)}–${fmtHHMM((rect.q1 + 1) * SLOT_MIN)} → ${brush === "on" ? "Record" : "Off"}`
    : hover
      ? `${DAYS[hover.d]} ${fmtHHMM(hover.q * SLOT_MIN)}–${fmtHHMM((hover.q + 1) * SLOT_MIN)}`
      : null

  return (
    <div className="select-none">
      <HourAxis />
      <div className="flex gap-1">
        <div className="grid w-10 shrink-0 grid-rows-7 text-xs text-muted-foreground">
          {DAYS.map((d) => <span key={d} className="flex h-7 items-center">{d}</span>)}
        </div>
        <div
          ref={area}
          className={cn("relative grid min-w-0 flex-1 grid-rows-7 overflow-hidden rounded-md border", onChange && "cursor-crosshair touch-none")}
          onPointerDown={onChange ? (e) => { e.currentTarget.setPointerCapture(e.pointerId); const c = cellAt(e); setDrag({ a: c, b: c }) } : undefined}
          onPointerMove={(e) => { const c = cellAt(e); setHover(c); if (drag) setDrag({ ...drag, b: c }) }}
          onPointerUp={() => { commit(); setDrag(null) }}
          onPointerCancel={() => setDrag(null)}
          onPointerLeave={() => setHover(null)}
        >
          {cov.map((row, d) => (
            <div key={d} className={cn("relative flex h-7", d > 0 && "border-t border-border/60")}>
              {row.map((c, q) => {
                const sel = inRect(d, q)
                return (
                  <span
                    key={q}
                    className={cn(
                      "h-full flex-1",
                      q % 4 === 0 && q > 0 && "border-l border-border/40",
                      q % 24 === 0 && q > 0 && "border-border",
                      sel
                        ? brush === "on" ? "bg-primary/70" : "bg-danger/25"
                        : c === 1 ? "bg-success/60" : c > 0 ? "bg-success/30" : "bg-muted/40",
                    )}
                  />
                )
              })}
              {now?.day === d && <NowMarker minute={now.minute} />}
            </div>
          ))}
        </div>
      </div>
      <div className="mt-1.5 flex min-h-5 flex-wrap items-center gap-x-4 gap-y-1 pl-11 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-success/60" /> Record</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm border bg-muted/40" /> Off</span>
        {now && <span className="flex items-center gap-1.5"><span className="h-2.5 w-0.5 bg-danger" /> Now</span>}
        {tip && <span className="ml-auto font-medium text-foreground tabular-nums">{tip}</span>}
      </div>
    </div>
  )
}

/** Small read-only week strip for the schedule list. */
export function WeekStrip({ blocks, className }: { blocks: ScheduleBlock[]; className?: string }) {
  const bits = useMemo(() => blocksToBitmap(blocks), [blocks])
  return (
    <div className={cn("grid w-40 grid-rows-7 gap-px", className)} title="Mon (top) to Sun, 00–24">
      {DAYS.map((d, i) => (
        <div key={d} className="relative h-1.5 overflow-hidden rounded-[1px] bg-muted">
          {dayRuns(bits, i).map(([s, e]) => (
            <span key={s} className="absolute inset-y-0 bg-success/70" style={{ left: `${(s / DAY_MIN) * 100}%`, width: `${((e - s) / DAY_MIN) * 100}%` }} />
          ))}
        </div>
      ))}
    </div>
  )
}
