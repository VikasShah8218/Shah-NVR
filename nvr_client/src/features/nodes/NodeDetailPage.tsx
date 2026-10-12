import { ArrowLeft, Download } from "lucide-react"
import { Link, useParams } from "react-router"
import { mediaFileUrl } from "@/api/client"
import { useNode, useNodeAssignments, useNodePaths, useNodeSegments, useNodeStatus } from "@/api/queries"
import type { MediaNode } from "@/api/types"
import { EmptyState, ErrorState, Field, Loading, PageHeader } from "@/components/common"
import { StatusBadge } from "@/components/StatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { UsageMeter } from "@/components/UsageBar"
import { formatBytes, formatDuration, formatMbps, formatPercent, timeAgo } from "@/lib/format"
import { fmtDateTime } from "@/lib/time"
import { LogViewer } from "./LogViewer"
import { NodeActions } from "./NodeActions"
import { nodeResources } from "./nodeUtils"
import { ResourceCharts, useNodeHistory } from "./ResourceCharts"

export function NodeDetailPage() {
  const nodeId = Number(useParams().id)
  const node = useNode(nodeId, 3000)
  const points = useNodeHistory(node.data, node.dataUpdatedAt)

  if (node.isLoading) return <Loading />
  if (node.error || !node.data) return <ErrorState error={node.error ?? "Node not found"} />
  const n = node.data

  return (
    <div className="space-y-4">
      <Link to="/nodes" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Media Nodes
      </Link>
      <PageHeader
        title={n.name}
        description={`${n.api_url} · media host ${n.media_host} · heartbeat ${timeAgo(n.last_heartbeat_at)}`}
        actions={
          <>
            <StatusBadge status={n.state} />
            <NodeActions node={n} variant="button" />
          </>
        }
      />
      <ResourceSummary node={n} />
      <ResourceCharts points={points} />
      <Tabs defaultValue="cameras">
        <TabsList>
          <TabsTrigger value="cameras">Cameras</TabsTrigger>
          <TabsTrigger value="paths">MediaMTX paths</TabsTrigger>
          <TabsTrigger value="chunks">Recorded chunks</TabsTrigger>
          <TabsTrigger value="logs">Logs</TabsTrigger>
        </TabsList>
        <TabsContent value="cameras">
          <NodeCameras apiUrl={n.api_url} />
        </TabsContent>
        <TabsContent value="paths">
          <NodePaths apiUrl={n.api_url} />
        </TabsContent>
        <TabsContent value="chunks">
          <NodeChunks apiUrl={n.api_url} />
        </TabsContent>
        <TabsContent value="logs">
          <Card>
            <CardContent>
              <LogViewer apiUrl={n.api_url} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

function ResourceSummary({ node }: { node: MediaNode }) {
  const r = nodeResources(node)
  const status = useNodeStatus(node.api_url)
  const s = status.data
  const gpu = r.gpus[0]
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="gap-3">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm font-medium">Compute</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <UsageMeter label="CPU" value={`${formatPercent(r.cpuPercent)}${r.cpuCount ? ` · ${r.cpuCount} cores` : ""}`} percent={r.cpuPercent} />
          <UsageMeter label="RAM" value={`${formatBytes(r.memUsed)} / ${formatBytes(r.memTotal)}`} percent={r.memPercent} />
          {r.gpus.length ? (
            r.gpus.map((g, i) => (
              <UsageMeter
                key={i}
                label={`GPU · ${g.name}`}
                value={`${formatPercent(g.utilization_percent)} · ${formatBytes(g.memory_used_bytes)} / ${formatBytes(g.memory_total_bytes)}`}
                percent={g.utilization_percent}
              />
            ))
          ) : (
            <Field label="GPU">
              <span className="text-muted-foreground">{gpu ? gpu.name : "No GPU data"}</span>
            </Field>
          )}
          <Field label="Network">
            ↓ {formatMbps(r.netRx)} · ↑ {formatMbps(r.netTx)}
          </Field>
        </CardContent>
      </Card>
      <Card className="gap-3">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm font-medium">Storage</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <UsageMeter
            label="Recordings vs quota"
            value={r.quota != null ? `${formatBytes(r.recordings)} / ${formatBytes(r.quota)}` : `${formatBytes(r.recordings)} · no quota`}
            percent={r.storagePercent}
            warnAt={80}
            dangerAt={95}
          />
          <UsageMeter
            label="Disk"
            value={`${formatBytes(r.diskFree)} free of ${formatBytes(r.diskTotal)}`}
            percent={r.diskPercent}
            warnAt={85}
            dangerAt={95}
          />
          <Field label="Usable for recordings">{formatBytes(r.usable)}</Field>
          <Field label="Room left">{formatBytes(r.remaining)}</Field>
          <Field label="Recordings folder">
            <span className="break-all text-xs">{s?.recordings_dir ?? "—"}</span>
          </Field>
        </CardContent>
      </Card>
      <Card className="gap-3">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm font-medium">Node agent</CardTitle>
        </CardHeader>
        <CardContent>
          {status.error ? (
            <ErrorState error={status.error} />
          ) : (
            <>
              <Field label="Central connection">
                <OnOff ok={s?.central_online} />
              </Field>
              <Field label="MediaMTX">
                <OnOff ok={s?.mediamtx_running} /> {s?.mediamtx_version}
              </Field>
              <Field label="Cameras assigned">
                {node.assigned_cameras} / {node.capacity_cameras}
              </Field>
              <Field label="Streams ready">{s ? s.ready_paths.length : "—"}</Field>
              <Field label="Chunks stored">{s?.local_segments ?? "—"}</Field>
              <Field label="Pending uploads">
                <span className={s && s.pending_uploads > 20 ? "text-warning" : ""}>{s?.pending_uploads ?? "—"}</span>
              </Field>
              <Field label="Agent version">{node.version ?? "—"}</Field>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function OnOff({ ok }: { ok: boolean | undefined }) {
  if (ok == null) return <span className="text-muted-foreground">—</span>
  return <span className={ok ? "text-success" : "text-danger"}>{ok ? "Online" : "Offline"}</span>
}

function NodeCameras({ apiUrl }: { apiUrl: string }) {
  const q = useNodeAssignments(apiUrl)
  if (q.error) return <ErrorState error={q.error} />
  if (!q.data) return <Loading />
  if (!q.data.length) return <EmptyState title="No cameras on this node" />
  return (
    <Card className="py-0">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Camera</TableHead>
            <TableHead>Generation</TableHead>
            <TableHead>Streams</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {q.data.map((c) => (
            <TableRow key={c.camera_id}>
              <TableCell>
                <Link className="font-medium hover:text-primary" to={`/cameras/${c.camera_id}`}>
                  {c.camera_name}
                </Link>
              </TableCell>
              <TableCell className="tabular-nums">{c.generation}</TableCell>
              <TableCell className="space-x-1">
                {c.streams.map((s) => (
                  <Badge key={s.profile} variant="secondary">
                    {s.profile} {s.record ? "· rec" : "· live"}
                  </Badge>
                ))}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  )
}

function NodePaths({ apiUrl }: { apiUrl: string }) {
  const q = useNodePaths(apiUrl)
  if (q.error) return <ErrorState error={q.error} />
  if (!q.data) return <Loading />
  if (!q.data.length) return <EmptyState title="No active MediaMTX paths" />
  return (
    <Card className="py-0">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Path</TableHead>
            <TableHead>State</TableHead>
            <TableHead>Tracks</TableHead>
            <TableHead>Viewers</TableHead>
            <TableHead>Received</TableHead>
            <TableHead>Sent</TableHead>
            <TableHead>Online since</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {q.data.map((p) => (
            <TableRow key={p.name}>
              <TableCell className="font-mono text-xs">{p.name}</TableCell>
              <TableCell>
                <StatusBadge status={p.ready ? "STREAMING" : "CONNECTING"} />
              </TableCell>
              <TableCell>{(p.tracks ?? []).map((t) => (typeof t === "string" ? t : t.codec)).join(", ") || "—"}</TableCell>
              <TableCell className="tabular-nums">{p.readers?.length ?? 0}</TableCell>
              <TableCell className="tabular-nums">{formatBytes(p.bytesReceived)}</TableCell>
              <TableCell className="tabular-nums">{formatBytes(p.bytesSent)}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{p.readyTime ? timeAgo(p.readyTime) : "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  )
}

function NodeChunks({ apiUrl }: { apiUrl: string }) {
  const q = useNodeSegments(apiUrl, 100)
  if (q.error) return <ErrorState error={q.error} />
  if (!q.data) return <Loading />
  if (!q.data.length) return <EmptyState title="No recorded chunks yet" />
  return (
    <Card className="py-0">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Start</TableHead>
            <TableHead>Camera</TableHead>
            <TableHead>Length</TableHead>
            <TableHead>Size</TableHead>
            <TableHead>Codec</TableHead>
            <TableHead>Parts</TableHead>
            <TableHead>Uploaded</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {q.data.map((s) => (
            <TableRow key={s.id}>
              <TableCell className="tabular-nums">{fmtDateTime(new Date(s.start_time))}</TableCell>
              <TableCell>
                <Link to={`/cameras/${s.camera_id}`} className="hover:text-primary">
                  cam-{s.camera_id}/{s.profile}
                </Link>
              </TableCell>
              <TableCell className="tabular-nums">{formatDuration(s.duration_ms)}</TableCell>
              <TableCell className="tabular-nums">{formatBytes(s.size_bytes)}</TableCell>
              <TableCell>{s.codec ?? "—"}</TableCell>
              <TableCell className="tabular-nums">{s.part_count}</TableCell>
              <TableCell>
                {s.uploaded ? (
                  <span className="text-xs text-success">In catalog</span>
                ) : (
                  <span className="text-xs text-warning">Pending</span>
                )}
              </TableCell>
              <TableCell>
                <Button variant="ghost" size="icon" className="size-8" asChild>
                  <a href={mediaFileUrl(apiUrl, s.id)} download title="Download MP4">
                    <Download className="size-4" />
                  </a>
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  )
}
