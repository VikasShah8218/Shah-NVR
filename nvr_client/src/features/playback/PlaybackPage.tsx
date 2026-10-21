import { CalendarDays, ChevronLeft, ChevronRight, Copy, Crosshair, Download, Film } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useSearchParams } from "react-router"
import { toast } from "sonner"
import { mediaFileUrl, playbackAudioUrl, playbackUrl } from "@/api/client"
import { useCameras, useNodes, useTimeline } from "@/api/queries"
import type { Segment } from "@/api/types"
import { EmptyState, ErrorState, PageHeader } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Calendar } from "@/components/ui/calendar"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { formatBytes, formatDuration } from "@/lib/format"
import { useSettings } from "@/lib/settings"
import { nodeApiUrl, playbackAccess, selectedNodeAccess, useNodeAccessMap } from "@/lib/nodeAccess"
import { DAY, HOUR, fmtDay, fmtTime, startOfLocalDay } from "@/lib/time"
import { Timeline } from "./Timeline"
import { VodPlayer } from "./VodPlayer"

const ZOOMS = [
  { label: "24h", ms: DAY },
  { label: "6h", ms: 6 * HOUR },
  { label: "1h", ms: HOUR },
  { label: "10m", ms: 10 * 60_000 },
]

export function PlaybackPage() {
  const [params, setParams] = useSearchParams()
  const { settings } = useSettings()
  const cameras = useCameras()
  const nodes = useNodes(30_000)
  const detected = useNodeAccessMap(nodes.data ?? [])

  const initialT = params.get("t") ? new Date(params.get("t")!) : null
  const [cameraId, setCameraId] = useState<number | null>(params.get("camera") ? Number(params.get("camera")) : null)
  const [profile, setProfile] = useState(params.get("profile") ?? "main")
  const [day, setDay] = useState(() => startOfLocalDay(initialT ?? new Date()))
  const [zoom, setZoom] = useState(DAY)
  const [viewStart, setViewStart] = useState(day.getTime())
  const [playFrom, setPlayFrom] = useState<Date | null>(initialT)
  // End of the loaded playlist, fixed when playback starts (end of day, or "now" for today).
  const [playTo, setPlayTo] = useState<Date>(() => new Date(Math.min(startOfLocalDay(initialT ?? new Date()).getTime() + DAY, Date.now())))
  const [playhead, setPlayhead] = useState<Date | null>(null)
  const [goto, setGoto] = useState("")

  // Default to the first camera once the list loads.
  useEffect(() => {
    if (cameraId == null && cameras.data?.length) setCameraId(cameras.data[0].id)
  }, [cameras.data, cameraId])

  const camera = cameras.data?.find((c) => c.id === cameraId)
  const profiles = useMemo(() => camera?.streams.map((s) => s.profile) ?? [], [camera])
  useEffect(() => {
    if (camera && !profiles.includes(profile)) setProfile(camera.streams.find((s) => s.record)?.profile ?? profiles[0])
  }, [camera, profile, profiles])

  const dayStart = day.getTime()
  const dayEnd = dayStart + DAY
  const isToday = startOfLocalDay(new Date()).getTime() === dayStart
  const timeline = useTimeline(cameraId, profile, new Date(dayStart), new Date(dayEnd), isToday ? 20_000 : 0)
  const segments: Segment[] = timeline.data?.segments ?? []
  const access = playbackAccess(
    nodes.data ?? [], [...new Set(segments.map((segment) => segment.node_id))], settings.nodeAccess, detected.data,
  )
  const nodeUrl = useMemo(
    () => new Map((nodes.data ?? []).map((n) => [n.id, nodeApiUrl(n, selectedNodeAccess(n, settings.nodeAccess, detected.data))])),
    [nodes.data, settings.nodeAccess, detected.data],
  )

  const viewEnd = viewStart + zoom
  const src = useMemo(
    () => (cameraId != null && playFrom ? playbackUrl(settings.centralUrl, cameraId, profile, playFrom, playTo, access) : null),
    [settings.centralUrl, cameraId, profile, playFrom, playTo, access],
  )
  const hasRecordedAudio = segments.some((segment) =>
    !!segment.audio_codec || /(^|\+)(aac|opus|g711|g711a|g711u|g722|lpcm|g726)(\+|$)/i.test(segment.codec ?? ""),
  )
  const audioSrc = useMemo(
    () => (cameraId != null && playFrom && hasRecordedAudio ? playbackAudioUrl(settings.centralUrl, cameraId, profile, playFrom, playTo, access) : null),
    [settings.centralUrl, cameraId, profile, playFrom, playTo, hasRecordedAudio, access],
  )

  // Keep the URL shareable / reload-safe.
  useEffect(() => {
    const p: Record<string, string> = {}
    if (cameraId != null) p.camera = String(cameraId)
    if (profile) p.profile = profile
    if (playFrom) p.t = playFrom.toISOString()
    setParams(p, { replace: true })
  }, [cameraId, profile, playFrom, setParams])

  const changeDay = (d: Date) => {
    const s = startOfLocalDay(d)
    setDay(s)
    setViewStart(s.getTime())
    setZoom(DAY)
    setPlayFrom(null)
    setPlayhead(null)
  }

  const setZoomAround = (ms: number) => {
    const center = playhead?.getTime() ?? viewStart + zoom / 2
    setZoom(ms)
    setViewStart(Math.max(dayStart, Math.min(dayEnd - ms, center - ms / 2)))
  }

  const seek = (t: number) => {
    setPlayFrom(new Date(t))
    setPlayTo(new Date(Math.min(dayEnd, Date.now())))
    setPlayhead(new Date(t))
  }

  // Keep the playhead visible while zoomed in.
  useEffect(() => {
    if (!playhead || zoom === DAY) return
    const t = playhead.getTime()
    if (t > viewStart + zoom * 0.9) setViewStart(Math.min(dayEnd - zoom, t - zoom * 0.1))
  }, [playhead, zoom, viewStart, dayEnd])

  const goToTime = () => {
    const m = goto.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/)
    if (!m) return toast.error("Use HH:MM or HH:MM:SS")
    seek(dayStart + (+m[1] * 3600 + +m[2] * 60 + +(m[3] ?? 0)) * 1000)
  }

  const copyVlc = () => {
    if (!src) return
    navigator.clipboard.writeText(src).then(() => toast.success("Playlist URL copied (open it in VLC)"), () => toast.message(src))
  }

  const windowSegments = segments.filter((s) => new Date(s.end_time).getTime() > viewStart && new Date(s.start_time).getTime() < viewEnd)

  if (cameras.data && cameras.data.length === 0) {
    return (
      <div>
        <PageHeader title="Playback" />
        <EmptyState icon={Film} title="No cameras yet">Add a camera first; its recordings will appear here.</EmptyState>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Playback" description="Browse and play recordings. Click the timeline to play from that moment." />

      <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center">
        <Select value={cameraId != null ? String(cameraId) : undefined} onValueChange={(v) => { setCameraId(Number(v)); setPlayFrom(null); setPlayhead(null) }}>
          <SelectTrigger className="col-span-2 w-full sm:w-56">
            <SelectValue placeholder="Select camera" />
          </SelectTrigger>
          <SelectContent>
            {(cameras.data ?? []).map((c) => (
              <SelectItem key={c.id} value={String(c.id)}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={profile} onValueChange={(v) => { setProfile(v); setPlayFrom(null) }}>
          <SelectTrigger className="w-full sm:w-28">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {profiles.map((p) => (
              <SelectItem key={p} value={p}>
                {p}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex min-w-0 items-center">
          <Button variant="outline" size="icon" className="rounded-r-none" onClick={() => changeDay(new Date(dayStart - DAY))}>
            <ChevronLeft className="size-4" />
          </Button>
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" className="min-w-0 flex-1 rounded-none border-x-0 px-2 sm:flex-none sm:px-4">
                <CalendarDays className="size-4" /> {fmtDay(day)}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar mode="single" selected={day} onSelect={(d) => d && changeDay(d)} disabled={{ after: new Date() }} />
            </PopoverContent>
          </Popover>
          <Button variant="outline" size="icon" className="rounded-l-none" disabled={isToday} onClick={() => changeDay(new Date(dayStart + DAY))}>
            <ChevronRight className="size-4" />
          </Button>
        </div>
        <div className="col-span-2 flex items-center gap-1 sm:col-span-1">
          <Input className="min-w-0 flex-1 sm:w-28 sm:flex-none" placeholder="HH:MM:SS" inputMode="numeric" value={goto} onChange={(e) => setGoto(e.target.value)} onKeyDown={(e) => e.key === "Enter" && goToTime()} />
          <Button variant="outline" onClick={goToTime}>
            Go
          </Button>
        </div>
        <div className="col-span-2 flex items-center gap-2 sm:col-span-1 sm:ml-auto">
          <Button variant="outline" className="w-full sm:w-auto" onClick={copyVlc} disabled={!src}>
            <Copy className="size-4" /> VLC URL
          </Button>
        </div>
      </div>

      <VodPlayer src={src} audioSrc={audioSrc} onTime={setPlayhead} />

      <Card className="gap-3 py-4">
        <CardContent className="space-y-3 px-4">
          <div className="flex flex-col gap-3 text-sm sm:flex-row sm:flex-wrap sm:items-center">
            <ToggleGroup type="single" variant="outline" size="sm" value={String(zoom)} onValueChange={(v) => v && setZoomAround(Number(v))}>
              {ZOOMS.map((z) => (
                <ToggleGroupItem key={z.label} value={String(z.ms)} className="px-3">
                  {z.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            {isToday && (
              <Button variant="ghost" size="sm" onClick={() => setViewStart(Math.max(dayStart, Math.min(dayEnd - zoom, Date.now() - zoom * 0.8)))}>
                <Crosshair className="size-4" /> Now
              </Button>
            )}
            <span className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground sm:ml-auto sm:gap-4">
              <span className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-sm bg-success/75" /> recorded
              </span>
              <span className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-sm bg-muted ring-1 ring-border" /> no recording
              </span>
              {timeline.data && (
                <span>
                  Coverage {timeline.data.coverage_percent.toFixed(1)}% · {formatBytes(timeline.data.total_size_bytes)}
                </span>
              )}
            </span>
          </div>
          {timeline.error ? (
            <ErrorState error={timeline.error} />
          ) : (
            <Timeline
              segments={segments}
              viewStart={viewStart}
              viewEnd={viewEnd}
              bounds={[dayStart, dayEnd]}
              playhead={playhead?.getTime() ?? null}
              onSeek={seek}
              onPan={zoom < DAY ? setViewStart : undefined}
              height={64}
            />
          )}
        </CardContent>
      </Card>

      <Card className="gap-2">
        <CardHeader>
          <CardTitle className="text-sm font-medium">
            Chunks in view <span className="font-normal text-muted-foreground">({windowSegments.length})</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="max-h-80 overflow-auto px-0">
          {windowSegments.length === 0 ? (
            <div className="px-6 pb-2 text-sm text-muted-foreground">No recordings in this window.</div>
          ) : (
            <>
            <div className="space-y-2 px-3 pb-3 md:hidden">
              {[...windowSegments].reverse().map((s) => {
                const start = new Date(s.start_time)
                const apiUrl = nodeUrl.get(s.node_id)
                return <button key={s.id} type="button" onClick={() => seek(start.getTime())} className="flex w-full items-center gap-3 rounded-lg border bg-background/30 p-3 text-left">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium tabular-nums">{fmtTime(start)} – {fmtTime(new Date(s.end_time))}</div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      <span>{formatDuration(s.duration_ms)}</span><span>{formatBytes(s.size_bytes)}</span><span>{s.audio_codec ? s.audio_codec.toUpperCase() : "No audio"}</span><span>node {s.node_id}</span>
                    </div>
                  </div>
                  {apiUrl && <a href={mediaFileUrl(apiUrl, s.id)} download title="Download MP4" aria-label="Download recording" onClick={(e) => e.stopPropagation()} className="grid size-11 shrink-0 place-items-center rounded-md hover:bg-accent"><Download className="size-4" /></a>}
                </button>
              })}
            </div>
            <div className="hidden md:block"><Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-6">Start</TableHead>
                  <TableHead>End</TableHead>
                  <TableHead>Length</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Audio</TableHead>
                  <TableHead>Node</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...windowSegments].reverse().map((s) => {
                  const start = new Date(s.start_time)
                  const apiUrl = nodeUrl.get(s.node_id)
                  return (
                    <TableRow key={s.id} className="cursor-pointer" onClick={() => seek(start.getTime())}>
                      <TableCell className="pl-6 tabular-nums">{fmtTime(start)}</TableCell>
                      <TableCell className="tabular-nums">{fmtTime(new Date(s.end_time))}</TableCell>
                      <TableCell className="tabular-nums">{formatDuration(s.duration_ms)}</TableCell>
                      <TableCell className="tabular-nums">{formatBytes(s.size_bytes)}</TableCell>
                      <TableCell className="text-xs">{s.audio_codec ? s.audio_codec.toUpperCase() : "—"}</TableCell>
                      <TableCell className="text-muted-foreground">node {s.node_id}</TableCell>
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        {apiUrl && (
                          <Button variant="ghost" size="icon" className="size-8" asChild>
                            <a href={mediaFileUrl(apiUrl, s.id)} download title="Download MP4">
                              <Download className="size-4" />
                            </a>
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table></div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
