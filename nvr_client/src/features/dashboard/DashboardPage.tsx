import { AlertTriangle, CheckCircle2, CircleAlert, Database, HardDrive, Server, Video } from "lucide-react"
import { Link } from "react-router"
import { useCameras, useClusterHealth, useNodes } from "@/api/queries"
import type { Camera, MediaNode } from "@/api/types"
import { ErrorState, KpiCard, Loading, PageHeader } from "@/components/common"
import { StatusBadge, toneOf } from "@/components/StatusBadge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { UsageBar, UsageMeter } from "@/components/UsageBar"
import { formatBytes, formatMbps, formatPercent, timeAgo } from "@/lib/format"
import { cn } from "@/lib/utils"
import { isNodeHealthy, nodeResources } from "../nodes/nodeUtils"

interface Alert {
  level: "danger" | "warning"
  title: string
  detail: string
  to: string
}

function buildAlerts(cameras: Camera[], nodes: MediaNode[]): Alert[] {
  const alerts: Alert[] = []
  for (const n of nodes) {
    const r = nodeResources(n)
    if (n.state === "UNREACHABLE")
      alerts.push({ level: "danger", title: `${n.name} is unreachable`, detail: `last heartbeat ${timeAgo(n.last_heartbeat_at)}`, to: `/nodes/${n.id}` })
    if (r.diskPercent != null && r.diskPercent >= 85)
      alerts.push({ level: r.diskPercent >= 95 ? "danger" : "warning", title: `${n.name}: disk ${formatPercent(r.diskPercent)} full`, detail: `${formatBytes(r.diskFree)} free`, to: `/nodes/${n.id}` })
    for (const v of r.volumesOffline)
      alerts.push({ level: "danger", title: `${n.name}: storage ${v.state === "ERROR" ? "error" : "offline"}`, detail: `${v.path}${v.state_detail ? ` · ${v.state_detail}` : ""}`, to: `/nodes/${n.id}` })
    if (r.allFull)
      alerts.push({ level: "warning", title: `${n.name}: all storage full`, detail: "The oldest recordings are being overwritten. Add storage or raise a cap.", to: `/nodes/${n.id}` })
    else if (r.quota != null && r.storagePercent != null && r.storagePercent >= 85)
      alerts.push({ level: "warning", title: `${n.name}: ${formatPercent(r.storagePercent)} of storage caps used`, detail: `${formatBytes(r.recordings)} of ${formatBytes(r.quota)}`, to: `/nodes/${n.id}` })
  }
  for (const c of cameras) {
    if (!c.enabled) continue
    if (!c.assignment?.node_id) {
      alerts.push({ level: "danger", title: `${c.name} is not assigned to any node`, detail: "No node with free capacity", to: `/cameras/${c.id}` })
      continue
    }
    for (const s of c.streams) {
      if (s.record && s.status !== "RECORDING" && s.status !== "ASSIGNED")
        alerts.push({
          level: toneOf(s.status) === "danger" ? "danger" : "warning",
          title: `${c.name} (${s.profile}) is ${s.status.replace(/_/g, " ").toLowerCase()}`,
          detail: s.status_detail ?? "Recording is not running",
          to: `/cameras/${c.id}`,
        })
    }
  }
  return alerts.sort((a, b) => (a.level === b.level ? 0 : a.level === "danger" ? -1 : 1))
}

export function DashboardPage() {
  const health = useClusterHealth()
  const nodes = useNodes()
  const cameras = useCameras()

  if (health.isLoading || nodes.isLoading || cameras.isLoading) return <Loading />
  const error = health.error ?? nodes.error ?? cameras.error
  if (error) return <ErrorState error={error} />

  const h = health.data!
  const nodeList = nodes.data ?? []
  const cameraList = cameras.data ?? []
  const alerts = buildAlerts(cameraList, nodeList)
  const recording = h.streams_by_status.RECORDING ?? 0
  const recordStreams = cameraList.filter((c) => c.enabled).flatMap((c) => c.streams.filter((s) => s.record)).length
  const healthy = nodeList.filter(isNodeHealthy).length
  const rs = nodeList.map(nodeResources)
  const storage = rs.reduce((a, r) => a + (r.recordings ?? 0), 0)
  const ingress = rs.reduce((a, r) => a + (r.netRx ?? 0), 0)

  return (
    <div className="space-y-5">
      <PageHeader title="Dashboard" description="Cluster overview: cameras, recording health and media nodes." />

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
        <KpiCard icon={Video} label="Cameras" value={h.cameras_total} hint={`${h.cameras_enabled} enabled`} />
        <KpiCard
          icon={CheckCircle2}
          label="Recording"
          value={`${recording} / ${recordStreams}`}
          hint="recorded streams healthy"
          tone={recording < recordStreams ? "warning" : "success"}
        />
        <KpiCard icon={Server} label="Nodes healthy" value={`${healthy} / ${nodeList.length}`} tone={healthy < nodeList.length ? "danger" : "success"} />
        <KpiCard icon={Database} label="Chunks last hour" value={h.segments_last_hour} hint={`${h.segments_total} in catalog`} />
        <KpiCard icon={HardDrive} label="Recordings stored" value={formatBytes(storage)} hint={`ingest ${formatMbps(ingress)}`} />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="size-4 text-warning" /> Alerts
              <span className="text-sm font-normal text-muted-foreground">({alerts.length})</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {alerts.length === 0 ? (
              <div className="flex items-center gap-2 rounded-lg bg-success/10 p-4 text-sm text-success">
                <CheckCircle2 className="size-4" /> All cameras are recording and all nodes are healthy.
              </div>
            ) : (
              <ul className="divide-y">
                {alerts.map((a, i) => (
                  <li key={i}>
                    <Link to={a.to} className="flex items-start gap-3 py-2.5 hover:text-primary">
                      <CircleAlert className={cn("mt-0.5 size-4 shrink-0", a.level === "danger" ? "text-danger" : "text-warning")} />
                      <div className="min-w-0">
                        <div className="text-sm font-medium">{a.title}</div>
                        <div className="truncate text-xs text-muted-foreground">{a.detail}</div>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Camera streams by status</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {Object.entries(h.streams_by_status)
              .sort((a, b) => b[1] - a[1])
              .map(([status, count]) => {
                const total = Object.values(h.streams_by_status).reduce((a, b) => a + b, 0)
                return (
                  <div key={status} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <StatusBadge status={status} />
                      <span className="tabular-nums">{count}</span>
                    </div>
                    <UsageBar percent={(count / total) * 100} warnAt={101} />
                  </div>
                )
              })}
            {Object.keys(h.streams_by_status).length === 0 && <div className="text-sm text-muted-foreground">No cameras yet.</div>}
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">Media nodes</h2>
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {nodeList.map((n) => {
            const r = nodeResources(n)
            return (
              <Link key={n.id} to={`/nodes/${n.id}`}>
                <Card className="gap-3 transition-colors hover:border-primary/50">
                  <CardHeader className="pb-0">
                    <CardTitle className="flex items-center justify-between text-sm">
                      <span className="truncate">{n.name}</span>
                      <StatusBadge status={n.state} />
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <UsageMeter label="CPU" value={formatPercent(r.cpuPercent)} percent={r.cpuPercent} />
                    <UsageMeter label="RAM" value={`${formatBytes(r.memUsed)} / ${formatBytes(r.memTotal)}`} percent={r.memPercent} />
                    <UsageMeter
                      label="Storage"
                      value={r.quota != null ? `${formatBytes(r.recordings)} / ${formatBytes(r.quota)}` : `${formatBytes(r.recordings)} (disk ${formatPercent(r.diskPercent)})`}
                      percent={r.storagePercent}
                      warnAt={80}
                      dangerAt={95}
                    />
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>
                        {n.assigned_cameras} / {n.capacity_cameras} cameras
                      </span>
                      <span>heartbeat {timeAgo(n.last_heartbeat_at)}</span>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            )
          })}
        </div>
      </div>
    </div>
  )
}
