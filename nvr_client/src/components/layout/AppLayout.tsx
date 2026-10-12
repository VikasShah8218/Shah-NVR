import {
  ArrowLeftRight,
  Camera,
  Clock,
  Gauge,
  History,
  MonitorPlay,
  PanelLeftClose,
  PanelLeftOpen,
  Server,
  Settings,
  Video,
} from "lucide-react"
import { Suspense, useEffect, useState } from "react"
import { NavLink, Outlet } from "react-router"
import { useClusterHealth } from "@/api/queries"
import { Loading } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { readStored, useSettings, writeStored } from "@/lib/settings"
import { fmtTime } from "@/lib/time"
import { cn } from "@/lib/utils"

const NAV = [
  { to: "/", label: "Dashboard", icon: Gauge, end: true },
  { to: "/live", label: "Live View", icon: MonitorPlay },
  { to: "/playback", label: "Playback", icon: History },
  { to: "/cameras", label: "Cameras", icon: Camera },
  { to: "/nodes", label: "Media Nodes", icon: Server },
  { to: "/assignments", label: "Assignments", icon: ArrowLeftRight },
  { to: "/settings", label: "Settings", icon: Settings },
]

const COLLAPSE_KEY = "shah-nvr.sidebar"

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(() => readStored(COLLAPSE_KEY, { collapsed: false }).collapsed)
  const toggle = () =>
    setCollapsed((c: boolean) => {
      writeStored(COLLAPSE_KEY, { collapsed: !c })
      return !c
    })

  return (
    <div className="flex h-dvh overflow-hidden">
      <aside
        className={cn(
          "flex shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200",
          collapsed ? "w-16" : "w-56",
        )}
      >
        <div className="flex h-14 items-center gap-2 px-4">
          <div className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground">
            <Video className="size-4.5" />
          </div>
          {!collapsed && <span className="font-semibold tracking-tight">Shah-NVR</span>}
        </div>
        <nav className="flex-1 space-y-1 px-2 py-2">
          {NAV.map(({ to, label, icon: Icon, end }) => {
            const link = (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    "flex h-9 items-center gap-3 rounded-md px-3 text-sm transition-colors",
                    isActive
                      ? "bg-sidebar-accent font-medium text-sidebar-primary"
                      : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
                    collapsed && "justify-center px-0",
                  )
                }
              >
                <Icon className="size-4.5 shrink-0" />
                {!collapsed && label}
              </NavLink>
            )
            return collapsed ? (
              <Tooltip key={to}>
                <TooltipTrigger asChild>{link}</TooltipTrigger>
                <TooltipContent side="right">{label}</TooltipContent>
              </Tooltip>
            ) : (
              link
            )
          })}
        </nav>
        <div className="p-2">
          <Button variant="ghost" size="sm" className="w-full justify-center text-muted-foreground" onClick={toggle}>
            {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
            {!collapsed && "Collapse"}
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main className="min-h-0 flex-1 overflow-auto p-5">
          <Suspense fallback={<Loading />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  )
}

function Topbar() {
  const { settings } = useSettings()
  const health = useClusterHealth()
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const h = health.data
  const online = health.isSuccess && !health.isError
  const nodesTotal = h ? Object.values(h.nodes_by_state).reduce((a, b) => a + b, 0) : 0
  const nodesHealthy = h ? (h.nodes_by_state.ACTIVE ?? 0) + (h.nodes_by_state.READY ?? 0) : 0
  const recording = h?.streams_by_status.RECORDING ?? 0

  return (
    <header className="flex h-14 shrink-0 items-center gap-5 border-b bg-card/40 px-5 text-sm">
      <Pill ok={online} label={online ? "Central online" : health.isLoading ? "Connecting…" : "Central offline"} title={settings.centralUrl} />
      {h && (
        <>
          <span className="text-muted-foreground">
            Nodes <span className={cn("font-medium", nodesHealthy < nodesTotal ? "text-warning" : "text-foreground")}>{nodesHealthy}/{nodesTotal}</span> healthy
          </span>
          <span className="text-muted-foreground">
            Cameras <span className="font-medium text-foreground">{recording}</span> recording of {h.cameras_enabled}
          </span>
        </>
      )}
      <div className="ml-auto flex items-center gap-2 tabular-nums text-muted-foreground">
        <Clock className="size-4" /> {fmtTime(now)}
      </div>
    </header>
  )
}

function Pill({ ok, label, title }: { ok: boolean; label: string; title?: string }) {
  return (
    <span title={title} className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs">
      <span className={cn("size-2 rounded-full", ok ? "bg-success" : "bg-danger animate-pulse")} />
      {label}
    </span>
  )
}
