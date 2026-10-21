import { Camera as CameraIcon, Copy, ExternalLink, ImageDown, Maximize, MoreVertical, Plus, Search, Trash2, X } from "lucide-react"
import { useCallback, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router"
import { toast } from "sonner"
import { useCameras, useLive } from "@/api/queries"
import type { Camera } from "@/api/types"
import { EmptyState, ErrorState, Loading } from "@/components/common"
import { StatusDot } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { type LiveProtocol, readStored, useSettings, writeStored } from "@/lib/settings"
import { cn } from "@/lib/utils"
import { LivePlayer, pickStream, saveSnapshot } from "./LivePlayer"
import { PtzPanel } from "./PtzPanel"

const LAYOUTS = [1, 4, 9, 16] as const
type Layout = (typeof LAYOUTS)[number]
const STORAGE_KEY = "shah-nvr.live"

interface LiveState {
  layout: Layout
  tiles: (number | null)[]
}

const recordStatus = (c: Camera) => (c.enabled ? (c.streams.find((s) => s.record) ?? c.streams[0])?.status ?? "UNKNOWN" : "DISABLED")

export function LivePage() {
  const cameras = useCameras()
  const { settings } = useSettings()
  const [state, setState] = useState<LiveState>(() => readStored(STORAGE_KEY, { layout: 4, tiles: Array(16).fill(null) }))
  const [selected, setSelected] = useState(0)
  const [protocol, setProtocol] = useState<LiveProtocol>(settings.liveProtocol)
  const [search, setSearch] = useState("")
  const [fullscreenCam, setFullscreenCam] = useState<number | null>(null)
  const gridRef = useRef<HTMLDivElement>(null)

  const save = useCallback((next: LiveState) => {
    setState(next)
    writeStored(STORAGE_KEY, next)
  }, [])

  const byId = useMemo(() => new Map((cameras.data ?? []).map((c) => [c.id, c])), [cameras.data])
  const visible = state.tiles.slice(0, state.layout)
  const cols = Math.sqrt(state.layout)

  const place = (cameraId: number, index?: number) => {
    const tiles = [...state.tiles]
    let target = index ?? (visible[selected] == null ? selected : visible.findIndex((t) => t == null))
    if (target < 0) target = selected
    tiles[target] = cameraId
    save({ ...state, tiles })
    setSelected(Math.min(state.layout - 1, target + 1))
  }
  const clearTile = (index: number) => {
    const tiles = [...state.tiles]
    tiles[index] = null
    save({ ...state, tiles })
  }

  const filtered = (cameras.data ?? []).filter((c) => c.name.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="-m-5 flex h-[calc(100dvh-3.5rem)]">
      {/* camera list */}
      <aside className="flex w-64 shrink-0 flex-col border-r bg-card/30">
        <div className="p-3">
          <div className="relative">
            <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input className="pl-8" placeholder="Search cameras" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>
        <div className="flex-1 overflow-auto px-2 pb-3">
          {cameras.isLoading && <Loading />}
          {cameras.error && <ErrorState error={cameras.error} />}
          {filtered.map((c) => (
            <button
              key={c.id}
              draggable
              onDragStart={(e) => e.dataTransfer.setData("text/camera-id", String(c.id))}
              onClick={() => place(c.id)}
              disabled={!c.enabled}
              className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm hover:bg-accent disabled:opacity-50"
              title="Click or drag onto a tile"
            >
              <StatusDot status={recordStatus(c)} />
              <span className="min-w-0 flex-1 truncate">{c.name}</span>
              {visible.includes(c.id) && <span className="text-[10px] text-primary">on view</span>}
            </button>
          ))}
          {cameras.data && filtered.length === 0 && <div className="p-3 text-sm text-muted-foreground">No cameras.</div>}
        </div>
      </aside>

      {/* grid */}
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-3 border-b px-4 py-2.5">
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={String(state.layout)}
            onValueChange={(v) => v && save({ ...state, layout: Number(v) as Layout })}
          >
            {LAYOUTS.map((l) => (
              <ToggleGroupItem key={l} value={String(l)} className="px-3">
                {l === 1 ? "1" : `${Math.sqrt(l)}×${Math.sqrt(l)}`}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <Select value={protocol} onValueChange={(v) => setProtocol(v as LiveProtocol)}>
            <SelectTrigger size="sm" className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">Auto (WebRTC → HLS)</SelectItem>
              <SelectItem value="webrtc">WebRTC only</SelectItem>
              <SelectItem value="hls">LL-HLS only</SelectItem>
            </SelectContent>
          </Select>
          <div className="ml-auto flex gap-2">
            <Button variant="outline" size="sm" onClick={() => save({ ...state, tiles: Array(16).fill(null) })}>
              <Trash2 className="size-4" /> Clear
            </Button>
            <Button variant="outline" size="sm" onClick={() => gridRef.current?.requestFullscreen?.()}>
              <Maximize className="size-4" /> Fullscreen
            </Button>
          </div>
        </div>

        {cameras.data && cameras.data.length === 0 ? (
          <div className="p-6">
            <EmptyState icon={CameraIcon} title="No cameras yet">
              Add a camera on the Cameras page, then come back here to watch it live.
            </EmptyState>
          </div>
        ) : (
          <div
            ref={gridRef}
            className="grid min-h-0 flex-1 gap-1 bg-background p-1"
            style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gridTemplateRows: `repeat(${cols}, minmax(0, 1fr))` }}
          >
            {visible.map((camId, i) => {
              const cam = camId != null ? byId.get(camId) : undefined
              return (
                <div
                  key={i}
                  onClick={() => setSelected(i)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    const id = Number(e.dataTransfer.getData("text/camera-id"))
                    if (id) place(id, i)
                  }}
                  className={cn(
                    "relative min-h-0 overflow-hidden rounded-md ring-1 ring-border",
                    selected === i && "ring-2 ring-primary",
                  )}
                >
                  {cam ? (
                    <LiveTile
                      camera={cam}
                      profile={state.layout > 1 && settings.gridUsesSubstream && cam.streams.some((s) => s.profile === "sub") ? "sub" : "main"}
                      protocol={protocol}
                      onRemove={() => clearTile(i)}
                      onExpand={() => setFullscreenCam(cam.id)}
                    />
                  ) : (
                    <div className="grid size-full place-items-center bg-video text-xs text-muted-foreground">
                      <span className="flex items-center gap-1.5">
                        <Plus className="size-4" /> Click a camera or drop it here
                      </span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </section>

      <Dialog open={fullscreenCam != null} onOpenChange={(o) => !o && setFullscreenCam(null)}>
        <DialogContent className="max-w-[min(96vw,1600px)] sm:max-w-[min(96vw,1600px)]">
          <DialogHeader>
            <DialogTitle>{fullscreenCam != null ? byId.get(fullscreenCam)?.name : ""} · main stream</DialogTitle>
          </DialogHeader>
          {fullscreenCam != null && (
            <div className="max-h-[80vh] space-y-2 overflow-auto">
              <LivePlayer cameraId={fullscreenCam} profile="main" protocol={protocol} className="aspect-video w-full rounded-md" />
              <FullscreenPtz key={fullscreenCam} cameraId={fullscreenCam} />
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

function LiveTile({
  camera,
  profile,
  protocol: gridProtocol,
  onRemove,
  onExpand,
}: {
  camera: Camera
  profile: string
  protocol: LiveProtocol
  onRemove: () => void
  onExpand: () => void
}) {
  const navigate = useNavigate()
  const live = useLive(camera.id)
  const [override, setOverride] = useState<LiveProtocol | null>(null)
  const [ptzOpen, setPtzOpen] = useState(false)
  const videoEl = useRef<HTMLVideoElement | null>(null)
  const setVideo = useCallback((v: HTMLVideoElement | null) => {
    videoEl.current = v
  }, [])
  const protocol = override ?? gridProtocol
  const recording = camera.streams.some((s) => s.record && s.status === "RECORDING")

  const copyRtsp = () => {
    const url = pickStream(live.data, profile)?.rtsp
    if (!url) return toast.error("Stream URL not available")
    navigator.clipboard.writeText(url).then(() => toast.success("RTSP URL copied (open it in VLC)"), () => toast.message(url))
  }

  return (
    <div className="group relative size-full" onDoubleClick={onExpand}>
      <LivePlayer cameraId={camera.id} profile={profile} protocol={protocol} className="size-full" onVideo={setVideo} />
      {ptzOpen && <div className="absolute inset-x-2 bottom-2 z-10 max-h-[75%] overflow-auto">
        <PtzPanel cameraId={camera.id} profile={profile} />
      </div>}
      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-center gap-2 bg-gradient-to-b from-black/60 to-transparent px-2 py-1.5 text-xs text-white">
        <span className="truncate font-medium">{camera.name}</span>
        {recording && (
          <span className="flex items-center gap-1 rounded bg-danger/80 px-1 text-[10px] font-semibold">
            <span className="size-1.5 animate-pulse rounded-full bg-white" /> REC
          </span>
        )}
        <span className="text-white/60">{profile}</span>
        <div className="pointer-events-auto ml-auto flex opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <Button variant="ghost" size="sm" className="h-6 text-white" onClick={() => setPtzOpen((v) => !v)}>PTZ</Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="size-6 text-white hover:bg-white/15 hover:text-white">
                <MoreVertical className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel className="text-xs">Protocol</DropdownMenuLabel>
              <DropdownMenuRadioGroup value={override ?? "grid"} onValueChange={(v) => setOverride(v === "grid" ? null : (v as LiveProtocol))}>
                <DropdownMenuRadioItem value="grid">Same as grid</DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="webrtc">WebRTC</DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="hls">LL-HLS</DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onExpand}>
                <Maximize className="size-4" /> Open main stream
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => saveSnapshot(videoEl.current, camera.name) || toast.error("No video frame yet")}>
                <ImageDown className="size-4" /> Snapshot
              </DropdownMenuItem>
              <DropdownMenuItem onClick={copyRtsp}>
                <Copy className="size-4" /> Copy RTSP URL
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate(`/cameras/${camera.id}`)}>
                <ExternalLink className="size-4" /> Camera details
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onRemove}>
                <X className="size-4" /> Remove from view
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </div>
  )
}

function FullscreenPtz({ cameraId }: { cameraId: number }) {
  const [open, setOpen] = useState(false)
  return <><Button size="sm" variant="outline" onClick={() => setOpen((v) => !v)}>{open ? "Close PTZ" : "Open PTZ"}</Button>
    {open && <PtzPanel cameraId={cameraId} profile="main" />}</>
}
