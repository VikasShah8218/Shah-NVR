import { cn } from "@/lib/utils"

/** Horizontal usage bar; turns amber above `warnAt` and red above `dangerAt` percent. */
export function UsageBar({
  percent,
  warnAt = 75,
  dangerAt = 90,
  className,
}: {
  percent: number | null | undefined
  warnAt?: number
  dangerAt?: number
  className?: string
}) {
  const p = percent == null ? 0 : Math.max(0, Math.min(100, percent))
  const color = percent == null ? "bg-muted-foreground/40" : p >= dangerAt ? "bg-danger" : p >= warnAt ? "bg-warning" : "bg-info"
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}>
      <div className={cn("h-full rounded-full transition-[width] duration-500", color)} style={{ width: `${p}%` }} />
    </div>
  )
}

/** Label + value line above a usage bar. */
export function UsageMeter({
  label,
  value,
  percent,
  hint,
  warnAt,
  dangerAt,
}: {
  label?: string
  value: string
  percent: number | null | undefined
  hint?: string
  warnAt?: number
  dangerAt?: number
}) {
  return (
    <div className="min-w-0 space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        {label && <span className="text-muted-foreground">{label}</span>}
        <span className="truncate font-medium tabular-nums">{value}</span>
      </div>
      <UsageBar percent={percent} warnAt={warnAt} dangerAt={dangerAt} />
      {hint && <div className="truncate text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  )
}
