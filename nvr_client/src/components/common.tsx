import type { LucideIcon } from "lucide-react"
import { AlertTriangle, Inbox, Loader2 } from "lucide-react"
import type { ReactNode } from "react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function KpiCard({
  icon: Icon,
  label,
  value,
  hint,
  tone = "info",
}: {
  icon: LucideIcon
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: "info" | "success" | "warning" | "danger"
}) {
  const toneClass = { info: "text-info bg-info/12", success: "text-success bg-success/12", warning: "text-warning bg-warning/12", danger: "text-danger bg-danger/12" }[tone]
  return (
    <Card className="gap-0 py-4">
      <CardContent className="flex items-center gap-3 px-4">
        <div className={cn("grid size-10 shrink-0 place-items-center rounded-lg", toneClass)}>
          <Icon className="size-5" />
        </div>
        <div className="min-w-0">
          <div className="text-xs text-muted-foreground">{label}</div>
          <div className="text-xl font-semibold tabular-nums leading-tight">{value}</div>
          {hint && <div className="truncate text-xs text-muted-foreground">{hint}</div>}
        </div>
      </CardContent>
    </Card>
  )
}

export function Loading({ label = "Loading…", className }: { label?: string; className?: string }) {
  return (
    <div className={cn("flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground", className)}>
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  )
}

export function EmptyState({ icon: Icon = Inbox, title, children }: { icon?: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed py-12 text-center">
      <Icon className="size-8 text-muted-foreground" />
      <div className="font-medium">{title}</div>
      {children && <div className="max-w-md text-sm text-muted-foreground">{children}</div>}
    </div>
  )
}

export function ErrorState({ error, className }: { error: unknown; className?: string }) {
  return (
    <div className={cn("flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm", className)}>
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" />
      <span>{error instanceof Error ? error.message : String(error)}</span>
    </div>
  )
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  destructive,
  onConfirm,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: ReactNode
  confirmLabel?: string
  destructive?: boolean
  onConfirm: () => void
  children?: ReactNode
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description && <AlertDialogDescription>{description}</AlertDialogDescription>}
        </AlertDialogHeader>
        {children}
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className={cn(destructive && "bg-danger text-white hover:bg-danger/90")}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/** Small label/value row used in detail panels. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5 text-sm">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 text-right">{children}</span>
    </div>
  )
}
