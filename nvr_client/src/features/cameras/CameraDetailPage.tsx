import { ArrowLeft, ArrowLeftRight, Copy, History, Pencil } from "lucide-react"
import { useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { toast } from "sonner"
import { useAssignmentHistory, useCamera, useLive, useTimeline } from "@/api/queries"
import type { Camera } from "@/api/types"
import { ErrorState, Field, Loading, PageHeader } from "@/components/common"
import { StatusBadge } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { formatBytes, retentionLabel, timeAgo } from "@/lib/format"
import { deviceLabel } from "@/lib/onvif"
import { useSettings } from "@/lib/settings"
import { DAY, fmtDateTime } from "@/lib/time"
import { MoveCameraDialog } from "../assignments/MoveCameraDialog"
import { LivePlayer } from "../live/LivePlayer"
import { Timeline } from "../playback/Timeline"
import { CameraFormSheet } from "./CameraFormSheet"
import { DeviceTab } from "./DeviceTab"
import { VideoTab } from "./VideoTab"

export function CameraDetailPage() {
  const id = Number(useParams().id)
  const camera = useCamera(id)
  const [editing, setEditing] = useState(false)
  const [tab, setTab] = useState("overview")

  if (camera.isLoading) return <Loading />
  if (camera.error || !camera.data) return <ErrorState error={camera.error ?? "Camera not found"} />
  const c = camera.data

  return (
    <div className="space-y-4">
      <Link to="/cameras" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Cameras
      </Link>
      <PageHeader
        title={c.name}
        description={c.description ?? `Camera #${c.id}`}
        actions={
          <>
            {!c.enabled && <StatusBadge status="DISABLED" />}
            <Button variant="outline" asChild>
              <Link to={`/playback?camera=${c.id}`}>
                <History className="size-4" /> Recordings
              </Link>
            </Button>
            <Button onClick={() => setEditing(true)}>
              <Pencil className="size-4" /> Edit
            </Button>
          </>
        }
      />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="recordings">Recordings</TabsTrigger>
          <TabsTrigger value="assignment">Assignment</TabsTrigger>
          <TabsTrigger value="device">Device</TabsTrigger>
          <TabsTrigger value="video">Video</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <Overview camera={c} />
        </TabsContent>
        <TabsContent value="recordings">
          <RecentRecordings camera={c} />
        </TabsContent>
        <TabsContent value="assignment">
          <AssignmentTab camera={c} />
        </TabsContent>
        <TabsContent value="device">
          <DeviceTab camera={c} active={tab === "device"} />
        </TabsContent>
        <TabsContent value="video">
          <VideoTab key={c.id} camera={c} active={tab === "video"} />
        </TabsContent>
      </Tabs>
      {editing && <CameraFormSheet camera={c} open onOpenChange={setEditing} />}
    </div>
  )
}

function Overview({ camera: c }: { camera: Camera }) {
  const { settings } = useSettings()
  const [profile, setProfile] = useState(c.streams[0]?.profile ?? "main")
  const live = useLive(c.enabled ? c.id : null)

  const copy = (text: string) =>
    navigator.clipboard.writeText(text).then(() => toast.success("Copied"), () => toast.message(text))

  return (
    <div className="grid gap-4 xl:grid-cols-5">
      <Card className="gap-3 xl:col-span-3">
        <CardHeader className="flex flex-row items-center justify-between pb-0">
          <CardTitle className="text-sm font-medium">Live preview</CardTitle>
          <ToggleGroup type="single" variant="outline" size="sm" value={profile} onValueChange={(v) => v && setProfile(v)}>
            {c.streams.map((s) => (
              <ToggleGroupItem key={s.profile} value={s.profile} className="px-3">
                {s.profile}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </CardHeader>
        <CardContent>
          {c.enabled ? (
            <LivePlayer cameraId={c.id} profile={profile} protocol={settings.liveProtocol} className="aspect-video w-full rounded-md" />
          ) : (
            <div className="grid aspect-video place-items-center rounded-md bg-video text-sm text-muted-foreground">Camera is disabled</div>
          )}
        </CardContent>
      </Card>

      <div className="space-y-4 xl:col-span-2">
        <Card className="gap-2">
          <CardHeader className="pb-0">
            <CardTitle className="text-sm font-medium">Details</CardTitle>
          </CardHeader>
          <CardContent>
            <Field label="Media node">
              {c.assignment?.node_id ? (
                <Link to={`/nodes/${c.assignment.node_id}`} className="hover:text-primary">
                  {c.assignment.node_name}
                </Link>
              ) : (
                "Not assigned"
              )}
            </Field>
            <Field label="Username">{c.username ?? "—"}</Field>
            <Field label="Password">{c.has_password ? "Set" : "Not set"}</Field>
            <Field label="Keep recordings">{retentionLabel(c.retention_days)}</Field>
            {c.model && <Field label="Device">{deviceLabel(c.manufacturer, c.model)}</Field>}
            <Field label="Added">{fmtDateTime(new Date(c.created_at))}</Field>
          </CardContent>
        </Card>
        <Card className="gap-2">
          <CardHeader className="pb-0">
            <CardTitle className="text-sm font-medium">Live URLs (for VLC)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {live.error && <div className="text-sm text-muted-foreground">{(live.error as Error).message}</div>}
            {live.data?.streams.map((s) => (
              <div key={s.profile} className="space-y-1">
                <div className="text-xs text-muted-foreground">{s.profile}</div>
                {[s.rtsp, s.hls].map((u) => (
                  <div key={u} className="flex items-center gap-1">
                    <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1 text-xs">{u}</code>
                    <Button variant="ghost" size="icon" className="size-7" onClick={() => copy(u)}>
                      <Copy className="size-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card className="py-0 xl:col-span-5">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-4">Stream</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Source URL</TableHead>
              <TableHead>Record</TableHead>
              <TableHead>Transport</TableHead>
              <TableHead>Audio</TableHead>
              <TableHead>Received</TableHead>
              <TableHead>Last chunk</TableHead>
              <TableHead>Last report</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {c.streams.map((s) => (
              <TableRow key={s.profile}>
                <TableCell className="pl-4 font-medium">{s.profile}</TableCell>
                <TableCell>
                  <StatusBadge status={s.status} />
                  {s.status_detail && <div className="mt-0.5 max-w-56 truncate text-[11px] text-muted-foreground">{s.status_detail}</div>}
                </TableCell>
                <TableCell className="max-w-72 truncate font-mono text-xs" title={s.source_url}>
                  {s.source_url}
                </TableCell>
                <TableCell>{s.record ? "Yes" : "Live only"}</TableCell>
                <TableCell className="uppercase">{s.rtsp_transport}</TableCell>
                <TableCell className="text-xs">
                  {s.audio_state === "available" ? (
                    <span title={s.audio_codec_raw ?? undefined}>
                      {(s.audio_codec ?? "audio").toUpperCase()}
                      {s.audio_sample_rate ? ` · ${s.audio_sample_rate / 1000} kHz` : ""}
                      {s.audio_channels ? ` · ${s.audio_channels === 1 ? "mono" : `${s.audio_channels} ch`}` : ""}
                      {s.audio_bitrate_kbps ? ` · ${s.audio_bitrate_kbps} kbps` : ""}
                    </span>
                  ) : s.audio_state === "advertised_not_observed" ? (
                    <span className="text-warning">Advertised, not received</span>
                  ) : s.audio_state === "unsupported" ? (
                    <span className="text-warning" title={s.audio_codec_raw ?? undefined}>Unsupported {s.audio_codec_raw ?? "audio"}</span>
                  ) : s.audio_state === "none" ? "None" : <span className="text-muted-foreground">Unknown</span>}
                </TableCell>
                <TableCell className="tabular-nums">{formatBytes(s.bytes_received)}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{s.last_segment_at ? timeAgo(s.last_segment_at) : "—"}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{s.last_status_at ? timeAgo(s.last_status_at) : "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  )
}

function RecentRecordings({ camera: c }: { camera: Camera }) {
  const navigate = useNavigate()
  const recorded = c.streams.filter((s) => s.record)
  const [profile, setProfile] = useState(recorded[0]?.profile ?? c.streams[0]?.profile ?? "main")
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000)
    return () => clearInterval(t)
  }, [])
  const start = Math.floor((now - DAY) / 60_000) * 60_000
  const end = start + DAY
  const timeline = useTimeline(c.id, profile, new Date(start), new Date(end), 60_000)

  return (
    <Card className="gap-3">
      <CardHeader className="flex flex-row items-center justify-between pb-0">
        <CardTitle className="text-sm font-medium">Last 24 hours</CardTitle>
        <ToggleGroup type="single" variant="outline" size="sm" value={profile} onValueChange={(v) => v && setProfile(v)}>
          {c.streams.map((s) => (
            <ToggleGroupItem key={s.profile} value={s.profile} className="px-3">
              {s.profile}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </CardHeader>
      <CardContent className="space-y-3">
        {timeline.error && <ErrorState error={timeline.error} />}
        <Timeline
          segments={timeline.data?.segments ?? []}
          viewStart={start}
          viewEnd={end}
          bounds={[start, end]}
          playhead={null}
          onSeek={(t) => navigate(`/playback?camera=${c.id}&profile=${profile}&t=${new Date(t).toISOString()}`)}
        />
        {timeline.data && (
          <div className="flex flex-wrap gap-6 text-sm">
            <span>
              Coverage <b>{timeline.data.coverage_percent.toFixed(1)}%</b>
            </span>
            <span>
              Chunks <b>{timeline.data.segments.length}</b>
            </span>
            <span>
              Size <b>{formatBytes(timeline.data.total_size_bytes)}</b>
            </span>
            <span>
              Gaps <b>{timeline.data.gaps.length}</b>
            </span>
            <span className="text-muted-foreground">Click the bar to open playback at that time.</span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function AssignmentTab({ camera: c }: { camera: Camera }) {
  const history = useAssignmentHistory(c.id)
  const [moving, setMoving] = useState(false)
  const [, tick] = useState(0)
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [])
  const a = c.assignment
  const leaseLeft = a?.lease_expires_at ? Math.round((new Date(a.lease_expires_at).getTime() - Date.now()) / 1000) : null

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="gap-2">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm font-medium">Current owner</CardTitle>
        </CardHeader>
        <CardContent>
          <Field label="Media node">{a?.node_name ?? "Not assigned"}</Field>
          <Field label="Generation">{a?.generation ?? 0}</Field>
          <Field label="Lease">
            {leaseLeft == null ? "—" : leaseLeft >= 0 ? `${leaseLeft}s left` : <span className="text-warning">expired {-leaseLeft}s ago</span>}
          </Field>
          <Button className="mt-3 w-full" variant="outline" onClick={() => setMoving(true)} disabled={!c.enabled}>
            <ArrowLeftRight className="size-4" /> Move to another node
          </Button>
        </CardContent>
      </Card>
      <Card className="py-0 lg:col-span-2">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-4">Generation</TableHead>
              <TableHead>Node</TableHead>
              <TableHead>Reason</TableHead>
              <TableHead>From</TableHead>
              <TableHead>Until</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(history.data ?? []).map((h) => (
              <TableRow key={h.generation}>
                <TableCell className="pl-4 tabular-nums">{h.generation}</TableCell>
                <TableCell>{h.node_id ? `node ${h.node_id}` : "—"}</TableCell>
                <TableCell>{h.reason}</TableCell>
                <TableCell className="text-xs tabular-nums">{fmtDateTime(new Date(h.started_at))}</TableCell>
                <TableCell className="text-xs tabular-nums">{h.ended_at ? fmtDateTime(new Date(h.ended_at)) : <span className="text-success">current</span>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
      {moving && (
        <MoveCameraDialog cameraId={c.id} cameraName={c.name} currentNodeId={a?.node_id ?? null} open onOpenChange={setMoving} />
      )}
    </div>
  )
}
