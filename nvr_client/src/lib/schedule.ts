/** Recording schedules in the browser (docs/RECORDING_SCHEDULES_PLAN.md). Same rules as
 * central_manager/app/schedules/utils.py: Mon = 0, `end <= start` runs past midnight, start == end = 24 h,
 * "24:00" = end of the day, a time no block covers is off. The grid editor works on a minute bitmap of the week. */
import type { ScheduleBlock } from "@/api/types"

export const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
export const DAY_MIN = 1440
export const WEEK_MIN = 7 * DAY_MIN
export const SLOT_MIN = 15 // grid snap
export const SLOTS = DAY_MIN / SLOT_MIN // 96 per day

export const parseHHMM = (v: string): number => {
  const [h, m] = v.split(":").map(Number)
  return h * 60 + m
}

export const fmtHHMM = (min: number): string =>
  `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`

/** One bit per minute of the week: recording on. "off" blocks never win over "continuous", so they add nothing. */
export function blocksToBitmap(blocks: ScheduleBlock[]): Uint8Array {
  const bits = new Uint8Array(WEEK_MIN)
  for (const b of blocks) {
    if (b.mode !== "continuous") continue
    const s = parseHHMM(b.start)
    const e = parseHHMM(b.end)
    const len = e > s ? e - s : DAY_MIN - s + e // e == s -> 24 h
    for (const d of b.days) {
      const base = d * DAY_MIN + s
      for (let i = 0; i < len; i++) bits[(base + i) % WEEK_MIN] = 1
    }
  }
  return bits
}

/** Minute bitmap -> the fewest readable blocks: runs split at midnight, except one overnight block
 * (e.g. 18:00-08:00) when the run ends the next morning; equal times on several days share one block. */
export function bitmapToBlocks(bits: Uint8Array): ScheduleBlock[] {
  const off = bits.indexOf(0)
  if (off < 0) return [{ days: [0, 1, 2, 3, 4, 5, 6], start: "00:00", end: "24:00", mode: "continuous" }]
  const chunks: { day: number; start: number; end: number }[] = []
  // walk the circular week starting at an "off" minute so no run is cut at the array end
  let i = 0
  while (i < WEEK_MIN) {
    const at = (off + i) % WEEK_MIN
    if (!bits[at]) { i++; continue }
    let len = 0
    while (len < WEEK_MIN && bits[(at + len) % WEEK_MIN]) len++
    i += len
    let s = at
    let left = len
    while (left > 0) {
      const day = Math.floor(s / DAY_MIN)
      const t = s % DAY_MIN
      const toMidnight = DAY_MIN - t
      let take: number
      if (left <= toMidnight) take = left
      else if (t > 0 && left - toMidnight < t) take = left // overnight block, ends before its start time
      else take = toMidnight
      chunks.push({ day, start: t, end: (t + take) % DAY_MIN === 0 && take === toMidnight ? DAY_MIN : (t + take) % DAY_MIN })
      s = (s + take) % WEEK_MIN
      left -= take
    }
  }
  const byTimes = new Map<string, number[]>()
  for (const c of chunks) {
    const key = `${c.start}-${c.end}`
    byTimes.set(key, [...(byTimes.get(key) ?? []), c.day])
  }
  return [...byTimes.entries()]
    .map(([key, days]) => {
      const [s, e] = key.split("-").map(Number)
      return { days: [...new Set(days)].sort((a, b) => a - b), start: fmtHHMM(s), end: fmtHHMM(e), mode: "continuous" as const }
    })
    .sort((a, b) => a.days[0] - b.days[0] || a.start.localeCompare(b.start))
}

/** Share of each 15-min cell that records (0..1), per day: [7][96]. */
export function cellCoverage(bits: Uint8Array): number[][] {
  return DAYS.map((_, d) =>
    Array.from({ length: SLOTS }, (_, q) => {
      let n = 0
      const base = d * DAY_MIN + q * SLOT_MIN
      for (let m = 0; m < SLOT_MIN; m++) n += bits[base + m]
      return n / SLOT_MIN
    }),
  )
}

/** Recording runs of one day as [startMin, endMin) for drawing a compact strip. */
export function dayRuns(bits: Uint8Array, day: number): [number, number][] {
  const runs: [number, number][] = []
  let start = -1
  for (let m = 0; m <= DAY_MIN; m++) {
    const on = m < DAY_MIN && bits[day * DAY_MIN + m] === 1
    if (on && start < 0) start = m
    if (!on && start >= 0) { runs.push([start, m]); start = -1 }
  }
  return runs
}

export const recordedHours = (bits: Uint8Array) => bits.reduce((a, b) => a + b, 0) / 60

export const TEMPLATES: { key: string; label: string; hint: string; blocks: ScheduleBlock[] }[] = [
  { key: "always", label: "Always", hint: "24 × 7", blocks: [{ days: [0, 1, 2, 3, 4, 5, 6], start: "00:00", end: "24:00", mode: "continuous" }] },
  { key: "office", label: "Office hours", hint: "Mon–Fri 08:00–18:00", blocks: [{ days: [0, 1, 2, 3, 4], start: "08:00", end: "18:00", mode: "continuous" }] },
  { key: "nights", label: "Nights", hint: "Every day 18:00–08:00", blocks: [{ days: [0, 1, 2, 3, 4, 5, 6], start: "18:00", end: "08:00", mode: "continuous" }] },
  { key: "weekends", label: "Weekends", hint: "Sat–Sun all day", blocks: [{ days: [5, 6], start: "00:00", end: "24:00", mode: "continuous" }] },
]

/** "Mon–Fri", "Sat, Sun", "Every day". */
export function daysLabel(days: number[]): string {
  const d = [...days].sort((a, b) => a - b)
  if (d.length === 7) return "Every day"
  const consecutive = d.length > 2 && d.every((x, i) => i === 0 || x === d[i - 1] + 1)
  return consecutive ? `${DAYS[d[0]]}–${DAYS[d[d.length - 1]]}` : d.map((x) => DAYS[x]).join(", ")
}

export function blockLabel(b: ScheduleBlock): string {
  const all = b.start === "00:00" && (b.end === "24:00" || b.end === "00:00")
  return `${daysLabel(b.days)} ${all ? "all day" : `${b.start}–${b.end}`}${parseHHMM(b.end) <= parseHHMM(b.start) && !all ? " (next day)" : ""}`
}

/** Wall clock of an ISO time that carries the site offset ("2026-11-16T18:00:00+05:30"), not the browser's zone. */
export function siteWall(iso: string): { day: number; minute: number; date: string } {
  const [date, rest] = iso.split("T")
  const [y, mo, d] = date.split("-").map(Number)
  const day = (new Date(Date.UTC(y, mo - 1, d)).getUTCDay() + 6) % 7 // Mon = 0
  return { day, minute: parseHHMM(rest.slice(0, 5)), date }
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

/** "Mon 18:00", or "Mon 23 Nov 18:00" when 6 days or more away (same as the node's log line). */
export function fmtChange(iso: string): string {
  const w = siteWall(iso)
  const far = new Date(iso).getTime() - Date.now() >= 6 * 86_400_000
  const [, mo, d] = w.date.split("-").map(Number)
  return `${DAYS[w.day]}${far ? ` ${d} ${MONTHS[mo - 1]}` : ""} ${fmtHHMM(w.minute)}`
}

/** "Recording now, until Mon 18:00" / "Off now, recording from Tue 08:00" / "Recording all the time". */
export function nowText(recordingNow: boolean, nextChange: string | null | undefined): string {
  if (!nextChange) return recordingNow ? "Recording all the time" : "Never records"
  return recordingNow ? `Recording now, until ${fmtChange(nextChange)}` : `Off now, recording from ${fmtChange(nextChange)}`
}
