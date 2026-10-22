import {
  ArrowLeftRight,
  Camera,
  Clock,
  Gauge,
  History,
  Menu,
  MoreHorizontal,
  MonitorPlay,
  PanelLeftClose,
  PanelLeftOpen,
  Radar,
  Server,
  Settings,
} from "lucide-react"
import { Suspense, useEffect, useState } from "react"
import { NavLink, Outlet, useLocation } from "react-router"
import { useClusterHealth } from "@/api/queries"
import { Loading } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { PRODUCT_LOGO, PRODUCT_NAME } from "@/lib/branding"
import { readStored, useSettings, writeStored } from "@/lib/settings"
import { fmtTime } from "@/lib/time"
import { cn } from "@/lib/utils"

const NAV = [
  { to: "/", label: "Dashboard", icon: Gauge, end: true },
  { to: "/live", label: "Live View", icon: MonitorPlay },
  { to: "/playback", label: "Playback", icon: History },
  { to: "/cameras", label: "Cameras", icon: Camera },
  { to: "/discover", label: "Discover", icon: Radar },
  { to: "/nodes", label: "Media Nodes", icon: Server },
  { to: "/assignments", label: "Assignments", icon: ArrowLeftRight },
  { to: "/settings", label: "Settings", icon: Settings },
]

const COLLAPSE_KEY = "shah-nvr.sidebar"
const PRIMARY_MOBILE = NAV.slice(0, 4)
const SECONDARY_MOBILE = NAV.slice(4)

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(() => readStored(COLLAPSE_KEY, { collapsed: false }).collapsed)
  const [mobileMenu, setMobileMenu] = useState(false)
  const location = useLocation()
  const toggle = () =>
    setCollapsed((c: boolean) => {
      writeStored(COLLAPSE_KEY, { collapsed: !c })
      return !c
    })

  return (
    <div className="flex h-dvh min-h-0 overflow-hidden">
      <aside
        className={cn(
          "hidden shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200 lg:flex",
          collapsed ? "w-16" : "w-56",
        )}
      >
        <div className="flex h-14 items-center gap-2 px-4">
          <img src={PRODUCT_LOGO} alt="" className="size-8 shrink-0 object-contain" />
          {!collapsed && <span className="font-semibold tracking-tight">{PRODUCT_NAME}</span>}
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
        <Topbar onMenu={() => setMobileMenu(true)} />
        <main className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto p-3 pb-[calc(4.5rem+env(safe-area-inset-bottom))] sm:p-4 sm:pb-[calc(4.5rem+env(safe-area-inset-bottom))] lg:p-5 lg:pb-5">
          <Suspense fallback={<Loading />}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <nav aria-label="Primary navigation" className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-sidebar-border bg-sidebar/95 pb-[env(safe-area-inset-bottom)] text-sidebar-foreground shadow-[0_-8px_30px_rgba(0,0,0,.18)] backdrop-blur lg:hidden">
        {PRIMARY_MOBILE.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => cn("flex min-h-14 flex-col items-center justify-center gap-0.5 px-1 text-[10px]", isActive ? "text-sidebar-primary" : "text-sidebar-foreground/75")}>
            <Icon className="size-5" />
            <span>{label === "Live View" ? "Live" : label}</span>
          </NavLink>
        ))}
        <button type="button" onClick={() => setMobileMenu(true)} className={cn("flex min-h-14 flex-col items-center justify-center gap-0.5 px-1 text-[10px]", SECONDARY_MOBILE.some((item) => location.pathname.startsWith(item.to)) ? "text-sidebar-primary" : "text-sidebar-foreground/75")}>
          <MoreHorizontal className="size-5" />
          <span>More</span>
        </button>
      </nav>

      <Sheet open={mobileMenu} onOpenChange={setMobileMenu}>
        <SheetContent side="left" className="w-[min(88vw,22rem)] overflow-y-auto p-0 pb-[env(safe-area-inset-bottom)] lg:hidden">
          <SheetHeader className="border-b pt-[calc(1rem+env(safe-area-inset-top))]">
            <SheetTitle className="flex items-center gap-2">
              <img src={PRODUCT_LOGO} alt="" className="size-9 shrink-0 object-contain" />
              {PRODUCT_NAME}
            </SheetTitle>
            <SheetDescription>Monitoring and administration</SheetDescription>
          </SheetHeader>
          <nav className="space-y-1 p-3">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end} onClick={() => setMobileMenu(false)} className={({ isActive }) => cn("flex min-h-12 items-center gap-3 rounded-lg px-3 text-sm", isActive ? "bg-accent font-medium text-primary" : "text-foreground/85")}>
                <Icon className="size-5" /> {label}
              </NavLink>
            ))}
          </nav>
        </SheetContent>
      </Sheet>
    </div>
  )
}

function Topbar({ onMenu }: { onMenu: () => void }) {
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
    <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-card/40 px-3 text-sm sm:px-4 lg:gap-5 lg:px-5">
      <Button variant="ghost" size="icon" className="-ml-1 size-10 lg:hidden" onClick={onMenu} aria-label="Open navigation">
        <Menu className="size-5" />
      </Button>
      <div className="flex min-w-0 items-center gap-2 lg:hidden">
        <img src={PRODUCT_LOGO} alt="" className="size-8 shrink-0 object-contain" />
        <span className="truncate font-semibold">{PRODUCT_NAME}</span>
      </div>
      <div className="hidden lg:block"><Pill ok={online} label={online ? "Central online" : health.isLoading ? "Connecting…" : "Central offline"} title={settings.centralUrl} /></div>
      <span className={cn("ml-auto size-2.5 shrink-0 rounded-full lg:hidden", online ? "bg-success" : "animate-pulse bg-danger")} title={online ? "Central online" : "Central offline"} />
      {h && (
        <>
          <span className="hidden text-muted-foreground md:inline">
            Nodes <span className={cn("font-medium", nodesHealthy < nodesTotal ? "text-warning" : "text-foreground")}>{nodesHealthy}/{nodesTotal}</span> healthy
          </span>
          <span className="hidden text-muted-foreground sm:inline">
            Cameras <span className="font-medium text-foreground">{recording}</span> recording of {h.cameras_enabled}
          </span>
        </>
      )}
      <div className="hidden items-center gap-2 tabular-nums text-muted-foreground lg:ml-auto lg:flex">
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
