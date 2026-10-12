import { format } from "date-fns"

/** The API works in UTC ISO strings; the UI shows the browser's local time. */
export const toIso = (d: Date): string => d.toISOString()

export const startOfLocalDay = (d: Date): Date => new Date(d.getFullYear(), d.getMonth(), d.getDate())

export const addMs = (d: Date, ms: number): Date => new Date(d.getTime() + ms)

export const HOUR = 3_600_000
export const DAY = 24 * HOUR

export const fmtTime = (d: Date | number): string => format(d, "HH:mm:ss")
export const fmtDateTime = (d: Date | number): string => format(d, "dd MMM yyyy, HH:mm:ss")
export const fmtDay = (d: Date | number): string => format(d, "dd MMM yyyy")

export function clampDate(d: Date, min: Date, max: Date): Date {
  return new Date(Math.min(max.getTime(), Math.max(min.getTime(), d.getTime())))
}
