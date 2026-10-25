import {
  Camera as CameraIcon,
  Copy,
  ExternalLink,
  ImageDown,
  Maximize,
  MoreVertical,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react"
import { useCallback, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router"
import { toast } from "sonner"
import { useCameras, useLive } from "@/api/queries"
import type { Camera } from "@/api/types"
import { EmptyState, ErrorState, Loading } from "@/components/common"
import { DigitalZoom } from "@/components/DigitalZoom"
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
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { type LiveProtocol, readStored, useSettings, writeStored } from "@/lib/settings"
import { useMediaQuery } from "@/lib/useMediaQuery"
import { cn } from "@/lib/utils"
import { LivePlayer, pickStream, saveSnapshot } from "./LivePlayer"
import { PtzPanel } from "./PtzPanel"

const LAYOUTS = [1, 4, 9, 16] as const
type Layout = (typeof LAYOUTS)[number]
const STORAGE_KEY = "shah-nvr.live"
const MOBILE_STORAGE_KEY = "shah-nvr.live.mobile"

interface LiveState {
  layout: Layout
  tiles: (number | null)[]
}

const recordStatus = (c: Camera) => (c.enabled ? (c.streams.find((s) => s.record) ?? c.streams[0])?.status ?? "UNKNOWN" : "DISABLED")

export function LivePage() {
  const cameras = useCameras()
  const { settings } = useSettings()
  const isMobile = useMediaQuery("(max-width: 767px)")
  const [desktopState, setDesktopState] = useState<LiveState>(() => readStored(STORAGE_KEY, { layout: 4, tiles: Array(16).fill(null) }))
  const [mobileState, setMobileState] = useState<LiveState>(() => readStored(MOBILE_STORAGE_KEY, { layout: 1, tiles: Array(16).fill(null) }))
  const state = isMobile ? mobileState : desktopState
  const [selected, setSelected] = useState(0)
  const [protocol, setProtocol] = useState<LiveProtocol>(settings.liveProtocol)
  const [search, setSearch] = useState("")
  const [fullscreenCam, setFullscreenCam] = useState<number | null>(null)
  const [cameraPicker, setCameraPicker] = useState(false)
  const gridRef = useRef<HTMLDivElement>(null)

  const save = useCallback((next: LiveState) => {
    if (isMobile) {
      setMobileState(next)
      writeStored(MOBILE_STORAGE_KEY, next)
    } else {
      setDesktopState(next)
      writeStored(STORAGE_KEY, next)
    }
  }, [isMobile])

  const byId = useMemo(() => new Map((cameras.data ?? []).map((c) => [c.id, c])), [cameras.data])
  const visible = state.tiles.slice(0, state.layout)
  const cols = Math.sqrt(state.layout)

  const place = (cameraId: number, index?: number) => {
    const tiles = [...state.tiles]
    let target = index ?? (visible[selected] == null ? selected : visible.findIndex((t) => t == null))
    if (target < 0) target = selected
    tiles[target] = cameraId
    save({ ...state, tiles })
    setCameraPicker(false)
    setSelected(Math.min(state.layout - 1, target + 1))
  }
  const clearTile = (index: number) => {
    const tiles = [...state.tiles]
    tiles[index] = null
    save({ ...state, tiles })
  }

  const filtered = (cameras.data ?? []).filter((c) => c.name.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="-m-3 flex min-h-full sm:-m-4 lg:-m-5 lg:h-[calc(100dvh-3.5rem)]">
      {/* camera list */}
      <aside className="hidden w-64 shrink-0 flex-col border-r bg-card/30 md:flex">
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
        <div className="flex flex-wrap items-center gap-2 border-b px-2 py-2 sm:px-4 sm:py-2.5">
          <Button variant="outline" size="sm" className="md:hidden" onClick={() => setCameraPicker(true)}>
            <CameraIcon className="size-4" /> Cameras
          </Button>
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            spacing={2}
            className="gap-2"
            value={String(state.layout)}
            onValueChange={(v) => v && save({ ...state, layout: Number(v) as Layout })}
          >
            {(isMobile ? LAYOUTS.slice(0, 2) : LAYOUTS).map((l) => (
              <ToggleGroupItem key={l} value={String(l)} className="px-3">
                {l === 1 ? "1" : `${Math.sqrt(l)}×${Math.sqrt(l)}`}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <Select value={protocol} onValueChange={(v) => setProtocol(v as LiveProtocol)}>
            <SelectTrigger size="sm" className="min-w-0 flex-1 sm:w-48 sm:flex-none">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">Auto (WebRTC → HLS)</SelectItem>
              <SelectItem value="webrtc">WebRTC only</SelectItem>
              <SelectItem value="hls">LL-HLS only</SelectItem>
            </SelectContent>
          </Select>
          <div className="ml-auto flex gap-1 sm:gap-2">
            <Button variant="outline" size="sm" onClick={() => save({ ...state, tiles: Array(16).fill(null) })}>
              <Trash2 className="size-4" /> <span className="hidden sm:inline">Clear</span>
            </Button>
            <Button variant="outline" size="sm" onClick={() => gridRef.current?.requestFullscreen?.()}>
              <Maximize className="size-4" /> <span className="hidden sm:inline">Fullscreen</span>
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
            className="grid min-h-0 flex-1 auto-rows-[minmax(12rem,calc((100vw-0.75rem)*9/16))] content-start gap-1 overflow-y-auto bg-background p-1 md:auto-rows-auto md:overflow-hidden"
            style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, ...(isMobile ? {} : { gridTemplateRows: `repeat(${cols}, minmax(0, 1fr))` }) }}
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
                      // Fixed policy: one-up uses main; every multi-camera grid uses sub when present.
                      profile={state.layout > 1 && cam.streams.some((s) => s.profile === "sub") ? "sub" : "main"}
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

      <Sheet open={cameraPicker} onOpenChange={setCameraPicker}>
        <SheetContent side="bottom" className="max-h-[82dvh] rounded-t-2xl pb-[env(safe-area-inset-bottom)] md:hidden">
          <SheetHeader className="border-b px-4 pb-3">
            <SheetTitle>Choose a camera</SheetTitle>
            <SheetDescription>Camera will be placed in selected tile {selected + 1}.</SheetDescription>
          </SheetHeader>
          <div className="px-4"><div className="relative"><Search className="absolute top-3 left-3 size-4 text-muted-foreground" /><Input className="h-11 pl-9" placeholder="Search cameras" value={search} onChange={(e) => setSearch(e.target.value)} /></div></div>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
            {cameras.isLoading && <Loading />}
            {cameras.error && <ErrorState error={cameras.error} />}
            {filtered.map((c) => (
              <button key={c.id} type="button" onClick={() => place(c.id)} disabled={!c.enabled} className="flex min-h-12 w-full items-center gap-3 rounded-lg px-3 text-left hover:bg-accent disabled:opacity-50">
                <StatusDot status={recordStatus(c)} /><span className="min-w-0 flex-1 truncate">{c.name}</span>{visible.includes(c.id) && <span className="text-xs text-primary">On view</span>}
              </button>
            ))}
          </div>
        </SheetContent>
      </Sheet>

      <Dialog open={fullscreenCam != null} onOpenChange={(o) => !o && setFullscreenCam(null)}>
        <DialogContent className="flex h-dvh max-h-dvh w-screen max-w-none flex-col gap-3 overflow-hidden rounded-none p-3 sm:h-[96dvh] sm:max-h-[96dvh] sm:max-w-[min(96vw,1600px)] sm:rounded-lg sm:p-6">
          <DialogHeader className="shrink-0 pr-10">
            <DialogTitle>{fullscreenCam != null ? byId.get(fullscreenCam)?.name : ""} · main stream</DialogTitle>
          </DialogHeader>
          {fullscreenCam != null && (
            <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
              <DigitalZoomPlayer key={fullscreenCam} cameraId={fullscreenCam} protocol={protocol} />
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
  const isMobile = useMediaQuery("(max-width: 767px)")
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
      {ptzOpen && <div className="absolute inset-x-2 bottom-2 z-10 hidden max-h-[75%] overflow-auto md:block">
        <PtzPanel cameraId={camera.id} profile={profile} />
      </div>}
      {isMobile && <Sheet open={ptzOpen} onOpenChange={setPtzOpen}>
        <SheetContent side="bottom" className="max-h-[88dvh] overflow-y-auto rounded-t-2xl pb-[calc(1rem+env(safe-area-inset-bottom))] md:hidden">
          <SheetHeader><SheetTitle>{camera.name} PTZ</SheetTitle><SheetDescription>Hold a movement control and release it to stop.</SheetDescription></SheetHeader>
          <div className="px-3 pb-3"><PtzPanel cameraId={camera.id} profile={profile} /></div>
        </SheetContent>
      </Sheet>}
      <div className="pointer-events-none absolute inset-x-0 top-0 flex min-w-0 items-center gap-2 overflow-hidden bg-gradient-to-b from-black/60 to-transparent px-2 py-1.5 text-xs text-white">
        <span className="min-w-0 flex-1 truncate font-medium">{camera.name}</span>
        {recording && (
          <span className="flex shrink-0 items-center gap-1 rounded bg-danger/80 px-1 text-[10px] font-semibold">
            <span className="size-1.5 animate-pulse rounded-full bg-white" /> REC
          </span>
        )}
        <span className="shrink-0 text-white/60">{profile}</span>
        <div className="pointer-events-auto flex shrink-0 opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
          <Button variant="ghost" size="sm" className="h-8 min-w-11 text-white md:h-6 md:min-w-0" onClick={() => setPtzOpen((v) => !v)}>PTZ</Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="size-9 text-white hover:bg-white/15 hover:text-white md:size-6">
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

function DigitalZoomPlayer({ cameraId, protocol }: { cameraId: number; protocol: LiveProtocol }) {
  return (
    <DigitalZoom className="min-h-0 w-full flex-1 rounded-md bg-video">
      {(videoStyle) => <LivePlayer cameraId={cameraId} profile="main" protocol={protocol} className="size-full" videoStyle={videoStyle} />}
    </DigitalZoom>
  )
}

function FullscreenPtz({ cameraId }: { cameraId: number }) {
  const [open, setOpen] = useState(false)
  return <div className="shrink-0">
    <Button size="sm" variant="outline" onClick={() => setOpen((v) => !v)}>{open ? "Close PTZ" : "Open PTZ"}</Button>
    {open && <div className="mt-2 max-h-[min(42dvh,22rem)] overflow-auto"><PtzPanel cameraId={cameraId} profile="main" /></div>}
  </div>
}
