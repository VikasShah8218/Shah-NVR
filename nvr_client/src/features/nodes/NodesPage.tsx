import { Cpu, HardDrive, MemoryStick, Server, Video } from "lucide-react"
import { useNavigate } from "react-router"
import { useNodes } from "@/api/queries"
import type { MediaNode } from "@/api/types"
import { EmptyState, ErrorState, KpiCard, Loading, PageHeader } from "@/components/common"
import { StatusBadge } from "@/components/StatusBadge"
import { Card } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { UsageMeter } from "@/components/UsageBar"
import { formatBytes, formatMbps, formatPercent, ratio, timeAgo } from "@/lib/format"
import { NodeActions } from "./NodeActions"
import { isNodeHealthy, nodeResources } from "./nodeUtils"

export function NodesPage() {
  const nodes = useNodes()
  const navigate = useNavigate()

  return (
    <div>
      <PageHeader
        title="Media Nodes"
        description="Recording & streaming servers: resource usage, storage limits and state."
      />
      {nodes.isLoading && <Loading />}
      {nodes.error && <ErrorState error={nodes.error} />}
      {nodes.data && nodes.data.length === 0 && (
        <EmptyState icon={Server} title="No media nodes registered">
          Start a media node (<code>py main.py</code> in <code>media_node/</code>); it registers itself with the central manager.
        </EmptyState>
      )}
      {nodes.data && nodes.data.length > 0 && (
        <>
          <ClusterTotals nodes={nodes.data} />
          <Card className="mt-4 overflow-hidden py-0">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-56">Node</TableHead>
                  <TableHead className="w-36">CPU</TableHead>
                  <TableHead className="w-40">GPU</TableHead>
                  <TableHead className="w-40">RAM</TableHead>
                  <TableHead className="w-64">Storage (recordings / quota)</TableHead>
                  <TableHead className="w-32">Cameras</TableHead>
                  <TableHead className="w-32">Network in / out</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {nodes.data.map((n) => (
                  <NodeRow key={n.id} node={n} onOpen={() => navigate(`/nodes/${n.id}`)} />
                ))}
              </TableBody>
            </Table>
          </Card>
        </>
      )}
    </div>
  )
}

function NodeRow({ node, onOpen }: { node: MediaNode; onOpen: () => void }) {
  const r = nodeResources(node)
  const gpu = r.gpus[0]
  const stale = node.state === "UNREACHABLE" || node.state === "OFFLINE"
  return (
    <TableRow className="cursor-pointer align-top" onClick={onOpen}>
      <TableCell className="py-3">
        <div className="font-medium">{node.name}</div>
        <div className="mt-1 flex items-center gap-2">
          <StatusBadge status={node.state} />
        </div>
        <div className="mt-1 text-[11px] text-muted-foreground">
          heartbeat {timeAgo(node.last_heartbeat_at)} · v{node.version ?? "?"} · MediaMTX {node.mediamtx_version ?? "?"}
        </div>
      </TableCell>
      <TableCell className={stale ? "opacity-50" : ""}>
        <UsageMeter value={`${formatPercent(r.cpuPercent)}${r.cpuCount ? ` · ${r.cpuCount} cores` : ""}`} percent={r.cpuPercent} />
      </TableCell>
      <TableCell className={stale ? "opacity-50" : ""}>
        {gpu ? (
          <UsageMeter
            value={formatPercent(gpu.utilization_percent)}
            percent={gpu.utilization_percent}
            hint={`${gpu.name}${gpu.memory_total_bytes ? ` · ${formatBytes(gpu.memory_used_bytes)} / ${formatBytes(gpu.memory_total_bytes)}` : ""}`}
          />
        ) : (
          <span className="text-xs text-muted-foreground">No GPU data</span>
        )}
      </TableCell>
      <TableCell className={stale ? "opacity-50" : ""}>
        <UsageMeter value={`${formatBytes(r.memUsed)} / ${formatBytes(r.memTotal)}`} percent={r.memPercent} />
      </TableCell>
      <TableCell className={stale ? "opacity-50" : ""}>
        <UsageMeter
          value={
            r.quota != null
              ? `${formatBytes(r.recordings)} / ${formatBytes(r.quota)} (${formatPercent(r.storagePercent)})`
              : `${formatBytes(r.recordings)} · no quota`
          }
          percent={r.storagePercent}
          warnAt={80}
          dangerAt={95}
          hint={`disk free ${formatBytes(r.diskFree)} of ${formatBytes(r.diskTotal)} · usable ${formatBytes(r.usable)}`}
        />
      </TableCell>
      <TableCell>
        <UsageMeter value={`${node.assigned_cameras} / ${node.capacity_cameras}`} percent={r.camerasPercent} />
      </TableCell>
      <TableCell className="text-xs tabular-nums">
        <div>↓ {formatMbps(r.netRx)}</div>
        <div className="text-muted-foreground">↑ {formatMbps(r.netTx)}</div>
      </TableCell>
      <TableCell onClick={(e) => e.stopPropagation()}>
        <NodeActions node={node} />
      </TableCell>
    </TableRow>
  )
}

function ClusterTotals({ nodes }: { nodes: MediaNode[] }) {
  const rs = nodes.map(nodeResources)
  const sum = (f: (r: (typeof rs)[number]) => number | null) => rs.reduce((acc, r) => acc + (f(r) ?? 0), 0)
  const cpuValues = rs.map((r) => r.cpuPercent).filter((v): v is number => v != null)
  const cpuAvg = cpuValues.length ? cpuValues.reduce((a, b) => a + b, 0) / cpuValues.length : null
  const healthy = nodes.filter(isNodeHealthy).length
  const quotaTotal = sum((r) => r.quota)
  const recordings = sum((r) => r.recordings)
  const cams = nodes.reduce((a, n) => a + n.assigned_cameras, 0)
  const capacity = nodes.reduce((a, n) => a + n.capacity_cameras, 0)

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <KpiCard icon={Server} label="Nodes healthy" value={`${healthy} / ${nodes.length}`} tone={healthy < nodes.length ? "warning" : "success"} />
      <KpiCard icon={Cpu} label="CPU (average)" value={formatPercent(cpuAvg)} hint={`${sum((r) => r.cpuCount)} cores total`} />
      <KpiCard
        icon={MemoryStick}
        label="RAM in use"
        value={formatBytes(sum((r) => r.memUsed))}
        hint={`of ${formatBytes(sum((r) => r.memTotal))} (${formatPercent(ratio(sum((r) => r.memUsed), sum((r) => r.memTotal)))})`}
      />
      <KpiCard
        icon={HardDrive}
        label="Recordings stored"
        value={formatBytes(recordings)}
        hint={quotaTotal ? `quota ${formatBytes(quotaTotal)} · free disk ${formatBytes(sum((r) => r.diskFree))}` : `free disk ${formatBytes(sum((r) => r.diskFree))}`}
      />
      <KpiCard icon={Video} label="Cameras placed" value={`${cams} / ${capacity}`} hint="assigned / total capacity" />
    </div>
  )
}
