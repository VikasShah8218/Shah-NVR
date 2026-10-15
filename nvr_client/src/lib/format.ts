import { formatDistanceToNowStrict } from "date-fns"

const UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]

export function formatBytes(bytes: number | null | undefined, digits = 1): string {
  if (bytes == null || Number.isNaN(bytes)) return "—"
  if (bytes === 0) return "0 B"
  const i = Math.min(UNITS.length - 1, Math.floor(Math.log(Math.abs(bytes)) / Math.log(1024)))
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : digits)} ${UNITS[i]}`
}

export function formatMbps(mbps: number | null | undefined): string {
  if (mbps == null) return "—"
  return mbps >= 1000 ? `${(mbps / 1000).toFixed(2)} Gb/s` : `${mbps.toFixed(mbps < 10 ? 2 : 1)} Mb/s`
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  return value == null ? "—" : `${value.toFixed(digits)}%`
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—"
  const total = Math.round(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h) return `${h}h ${m}m`
  if (m) return `${m}m ${s}s`
  return `${s}s`
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never"
  return `${formatDistanceToNowStrict(new Date(iso))} ago`
}

export function ratio(used: number | null | undefined, total: number | null | undefined): number | null {
  if (used == null || !total) return null
  return Math.max(0, Math.min(100, (used / total) * 100))
}

/** A camera's retention for display: "7 days" or "Until full" (null = keep until storage is full). */
export function retentionLabel(days: number | null | undefined): string {
  return days == null ? "Until full" : `${days} day${days === 1 ? "" : "s"}`
}
