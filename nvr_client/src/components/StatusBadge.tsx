import { cn } from "@/lib/utils"

type Tone = "success" | "info" | "warning" | "danger" | "muted"

const TONE: Record<string, Tone> = {
  // camera streams
  RECORDING: "success",
  STREAMING: "info",
  IDLE: "info",
  CONNECTING: "warning",
  ASSIGNED: "warning",
  NOT_RECORDING: "danger",
  UNKNOWN: "danger",
  UNASSIGNED: "muted",
  DISABLED: "muted",
  // media nodes
  ACTIVE: "success",
  READY: "info",
  CORDONED: "warning",
  DRAINING: "warning",
  UNREACHABLE: "danger",
  OFFLINE: "muted",
  // segments
  AVAILABLE: "success",
  DELETING: "warning",
}

const TONE_CLASS: Record<Tone, string> = {
  success: "bg-success/15 text-success ring-success/30",
  info: "bg-info/15 text-info ring-info/30",
  warning: "bg-warning/15 text-warning ring-warning/30",
  danger: "bg-danger/15 text-danger ring-danger/40",
  muted: "bg-muted text-muted-foreground ring-border",
}

const DOT_CLASS: Record<Tone, string> = {
  success: "bg-success",
  info: "bg-info",
  warning: "bg-warning",
  danger: "bg-danger",
  muted: "bg-muted-foreground",
}

export const toneOf = (status: string): Tone => TONE[status] ?? "muted"

const label = (status: string) => status.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase())

export function StatusBadge({ status, className, title }: { status: string; className?: string; title?: string }) {
  const tone = toneOf(status)
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap",
        TONE_CLASS[tone],
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", DOT_CLASS[tone], status === "RECORDING" && "animate-pulse")} />
      {label(status)}
    </span>
  )
}

export function StatusDot({ status, className }: { status: string; className?: string }) {
  const tone = toneOf(status)
  return <span className={cn("inline-block size-2 rounded-full", DOT_CLASS[tone], className)} title={label(status)} />
}
