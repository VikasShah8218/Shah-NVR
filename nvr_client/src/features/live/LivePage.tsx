import {
  Camera as CameraIcon,
  ChevronLeft,
  ChevronRight,
  Copy,
  ExternalLink,
  Folder,
  ImageDown,
  Maximize,
  MoreVertical,
  Play,
  Plus,
  Search,
  Settings2,
  Loader2,
  Trash2,
  X,
} from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, useNavigate } from "react-router"
import { toast } from "sonner"
import { ApiError, unwrap } from "@/api/client"
import { useCameraOptions, useCamerasByIds, useCentral, useGroupSearch, useLive } from "@/api/queries"
import type { Camera, CameraGroup, CameraOption, GroupDetail } from "@/api/types"
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
import { GroupTree } from "@/features/groups/GroupTree"
import { useTreeExpanded } from "@/features/groups/useTreeExpanded"
import { revealKeys } from "@/lib/groupTree"
import { type Paged, pageCount } from "@/lib/pager"
import { type LiveProtocol, readStored, useSettings, writeStored } from "@/lib/settings"
import { useMediaQuery } from "@/lib/useMediaQuery"
import { useDebounced } from "@/lib/usePaged"
import { cn } from "@/lib/utils"
import { LivePlayer, pickStream, saveSnapshot } from "./LivePlayer"
import { PtzOverlay } from "./PtzOverlay"

const LAYOUTS = [1, 4, 9, 16] as const
type Layout = (typeof LAYOUTS)[number]
const STORAGE_KEY = "shah-nvr.live"
const MOBILE_STORAGE_KEY = "shah-nvr.live.mobile"

interface LiveState {
  layout: Layout
  tiles: (number | null)[]
  /** grid page last filled with ‹ › (enabled cameras by name, `layout` per page) */
  page?: number
  /** "Play group": ‹ › page through this group's cameras (its whole subtree) instead of all cameras */
  scope?: GridScope
}

interface GridScope {
  groupId: number
  name: string
}

const SIDEBAR_TAB_KEY = "shah-nvr.live.sidebarTab"
type SidebarTab = "groups" | "all"

const scopeParams = (scope?: GridScope) => (scope ? { group_id: scope.groupId, recursive: true } : {})

type OptionsPage = Paged<CameraOption>

/** Enabled cameras by name, one grid page at a time: ‹ › fill the grid with the next 4 / 9 / 16 cameras.
 *  With a group scope only that group's cameras (and its sub-groups') are paged. */
function useGridPages(scope?: GridScope) {
  const { url, api, poll } = useCentral()
  const count = useQuery({
    queryKey: [url, "cameras", "options", "enabled-count", scope?.groupId ?? null],
    queryFn: () => unwrap<OptionsPage>(api.GET("/api/v1/cameras/options", {
      params: { query: { enabled: true, limit: 1, ...scopeParams(scope) } },
    })),
    refetchInterval: poll,
    retry: (n, err) => !(err instanceof ApiError && err.status === 404) && n < 2,
  })
  const fetchPage = (page: number, layout: number, s: GridScope | undefined) =>
    unwrap<OptionsPage>(api.GET("/api/v1/cameras/options", {
      params: { query: { enabled: true, limit: layout, offset: (page - 1) * layout, ...scopeParams(s) } },
    }))
  return { total: count.data?.total, error: count.error, fetchPage }
}

export function LivePage() {
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
  const { api } = useCentral()
  const navigate = useNavigate()
  const [tab, setTabNow] = useState<SidebarTab>(() => (readStored<string>(SIDEBAR_TAB_KEY, "groups") === "all" ? "all" : "groups"))
  const setTab = (t: SidebarTab) => {
    setTabNow(t)
    writeStored(SIDEBAR_TAB_KEY, t)
  }
  const treeExpanded = useTreeExpanded("shah-nvr.live.groups.expanded")

  const save = useCallback((next: LiveState) => {
    if (isMobile) {
      setMobileState(next)
      writeStored(MOBILE_STORAGE_KEY, next)
    } else {
      setDesktopState(next)
      writeStored(STORAGE_KEY, next)
    }
  }, [isMobile])

  const visible = state.tiles.slice(0, state.layout)
  const cols = Math.sqrt(state.layout)
  // Only the cameras on screen are loaded in full (never the whole camera list).
  const tileCameras = useCamerasByIds(visible.filter((id): id is number => id != null))
  const byId = useMemo(() => new Map((tileCameras.data ?? []).map((c) => [c.id, c])), [tileCameras.data])
  const query = useDebounced(search).trim()
  const searching = query !== ""
  // the flat list only loads when it is shown (All tab, or a search)
  const options = useCameraOptions(query, { active: tab === "all" || searching })
  const optionRows = useMemo(() => options.data?.pages.flatMap((p) => p.items) ?? [], [options.data])
  const optionTotal = options.data?.pages[0]?.total
  const grid = useGridPages(state.scope)
  const gridPages = grid.total != null ? pageCount(grid.total, state.layout) : null
  const [paging, setPaging] = useState(false)
  const showGridPage = async (page: number, scope: GridScope | undefined = state.scope) => {
    let target = page
    if (scope?.groupId === state.scope?.groupId) {
      if (gridPages == null) return
      target = ((page - 1 + gridPages) % gridPages) + 1 // wraps around: last page › first page
    }
    setPaging(true)
    try {
      const rows = await grid.fetchPage(target, state.layout, scope)
      if (rows.total === 0) {
        toast.info(scope ? `No enabled cameras in ${scope.name}` : "No enabled cameras")
        return
      }
      const tiles = Array(16).fill(null)
      rows.items.forEach((c, i) => { tiles[i] = c.id })
      save({ ...state, tiles, page: target, scope })
      setSelected(0)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setPaging(false)
    }
  }
  const playGroup = (g: { id: number; name: string }) => {
    setCameraPicker(false)
    void showGridPage(1, { groupId: g.id, name: g.name })
  }
  const playGroupById = async (groupId: number) => {
    try {
      playGroup(await unwrap<GroupDetail>(api.GET("/api/v1/groups/{group_id}", { params: { path: { group_id: groupId } } })))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }
  const revealGroup = (g: CameraGroup) => {
    treeExpanded.open([...revealKeys(g.path), String(g.id)])
    setTab("groups")
    setSearch("")
  }
  // the played group was deleted: back to all cameras
  const scopeGone = !!state.scope && grid.error instanceof ApiError && grid.error.status === 404
  useEffect(() => {
    if (!scopeGone) return
    toast.info(`Group "${state.scope?.name}" no longer exists: showing all cameras`)
    save({ ...state, scope: undefined, page: undefined })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the scope disappears
  }, [scopeGone])

  const place = (cameraId: number, index?: number) => {
    const tiles = [...state.tiles]
    let target = index ?? (visible[selected] == null ? selected : visible.findIndex((t) => t == null))
    if (target < 0) target = selected
    tiles[target] = cameraId
    save({ ...state, tiles, page: undefined })
    setCameraPicker(false)
    setSelected(Math.min(state.layout - 1, target + 1))
  }
  const clearTile = (index: number) => {
    const tiles = [...state.tiles]
    tiles[index] = null
    save({ ...state, tiles })
  }

  const cameraList = (big: boolean) => (
    <CameraOptionList rows={optionRows} total={optionTotal} visible={visible} big={big} onPick={(id) => place(id)}
      loading={options.isLoading} error={options.error} hasMore={!!options.hasNextPage}
      loadingMore={options.isFetchingNextPage} onMore={() => void options.fetchNextPage()} searching={searching} />
  )

  const groupTree = (big: boolean) => (
    <GroupTree
      expanded={treeExpanded}
      showCameras
      showUngrouped
      countMode="online"
      onPickCamera={(c) => place(c.id)}
      dragGroups={!big}
      dragCameras={!big}
      actionsVisible={big}
      cameraBadge={(c) => (visible.includes(c.id) ? <span className="text-[10px] text-primary">on view</span> : null)}
      groupActions={(g) => (
        <>
          <Button variant="ghost" size="icon-sm" title={`Play ${g.name} on the grid`} aria-label={`Play ${g.name}`}
            disabled={g.cameras_total === 0} onClick={() => playGroup(g)}><Play /></Button>
          {!big && (
            <Button variant="ghost" size="icon-sm" title="Manage group" aria-label={`Manage ${g.name}`}
              onClick={() => navigate(`/groups?group=${g.id}`)}><Settings2 /></Button>
          )}
        </>
      )}
      emptyText={<>No groups yet. <Link className="text-primary hover:underline" to="/groups">Create groups</Link> or use the All tab.</>}
    />
  )

  const sidebarBody = (big: boolean) => (
    searching ? (
      <>
        <GroupSearchResults q={query} big={big} onReveal={revealGroup} onPlay={playGroup} />
        {cameraList(big)}
      </>
    ) : tab === "groups" ? groupTree(big) : cameraList(big)
  )

  const sidebarTabs = (
    <ToggleGroup type="single" variant="outline" size="sm" className="w-full" value={tab}
      onValueChange={(v) => v && setTab(v as SidebarTab)}>
      <ToggleGroupItem value="groups" className="flex-1">Groups</ToggleGroupItem>
      <ToggleGroupItem value="all" className="flex-1">All cameras</ToggleGroupItem>
    </ToggleGroup>
  )

  return (
    <div className="-m-3 flex min-h-full sm:-m-4 lg:-m-5 lg:h-[calc(100dvh-3.5rem)]">
      {/* camera list */}
      <aside className="hidden w-64 shrink-0 flex-col border-r bg-card/30 md:flex">
        <div className="p-3">
          <div className="relative">
            <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input className="pl-8" placeholder="Search cameras or groups" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          {!searching && <div className="mt-2">{sidebarTabs}</div>}
        </div>
        <div className="flex-1 overflow-auto px-2 pb-3">{sidebarBody(false)}</div>
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
            onValueChange={(v) => v && save({ ...state, layout: Number(v) as Layout, page: undefined })}
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
          {state.scope && (
            <span className="flex items-center gap-1 rounded-lg border bg-accent/40 py-0.5 pr-0.5 pl-2 text-xs" title="Grid pages run through this group (and its sub-groups)">
              <Folder className="size-3.5 shrink-0 text-primary/80" />
              <span className="max-w-40 truncate">{state.scope.name}</span>
              <Button variant="ghost" size="icon-sm" aria-label="Stop playing this group"
                onClick={() => save({ ...state, scope: undefined, page: undefined })}><X /></Button>
            </span>
          )}
          {gridPages != null && grid.total! > 0 && (
            <div className="flex items-center gap-0.5 rounded-lg border px-0.5"
              title={state.scope ? `Fill the grid with the next cameras of ${state.scope.name}` : "Fill the grid with the next cameras (by name)"}>
              <Button variant="ghost" size="icon-sm" aria-label="Previous cameras" disabled={paging}
                onClick={() => void showGridPage((state.page ?? 1) - 1)}><ChevronLeft /></Button>
              <span className="min-w-[4.5rem] text-center text-xs tabular-nums text-muted-foreground">
                {paging ? <Loader2 className="mx-auto size-3.5 animate-spin" /> : state.page ? `Page ${state.page} / ${gridPages}` : `${gridPages} pages`}
              </span>
              <Button variant="ghost" size="icon-sm" aria-label="Next cameras" disabled={paging}
                onClick={() => void showGridPage(state.page ? state.page + 1 : 1)}><ChevronRight /></Button>
            </div>
          )}
          <div className="ml-auto flex gap-1 sm:gap-2">
            <Button variant="outline" size="sm" onClick={() => save({ ...state, tiles: Array(16).fill(null), page: undefined })}>
              <Trash2 className="size-4" /> <span className="hidden sm:inline">Clear</span>
            </Button>
            <Button variant="outline" size="sm" onClick={() => gridRef.current?.requestFullscreen?.()}>
              <Maximize className="size-4" /> <span className="hidden sm:inline">Fullscreen</span>
            </Button>
          </div>
        </div>

        {!state.scope && grid.total === 0 && !searching && (tab === "groups" || optionTotal === 0) ? (
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
                    const groupId = Number(e.dataTransfer.getData("text/group-id"))
                    if (groupId) void playGroupById(groupId)
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
                      suspended={fullscreenCam != null}
                      onRemove={() => clearTile(i)}
                      onExpand={() => setFullscreenCam(cam.id)}
                    />
                  ) : camId != null && tileCameras.isFetching ? (
                    <div className="grid size-full place-items-center bg-video"><Loading /></div>
                  ) : (
                    <div className="grid size-full place-items-center bg-video text-xs text-muted-foreground">
                      <span className="flex items-center gap-1.5">
                        <Plus className="size-4" /> Click a camera or drop it (or a group) here
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
          <div className="space-y-2 px-4"><div className="relative"><Search className="absolute top-3 left-3 size-4 text-muted-foreground" /><Input className="h-11 pl-9" placeholder="Search cameras or groups" value={search} onChange={(e) => setSearch(e.target.value)} /></div>{!searching && sidebarTabs}</div>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">{sidebarBody(true)}</div>
        </SheetContent>
      </Sheet>

      <Dialog open={fullscreenCam != null} onOpenChange={(o) => !o && setFullscreenCam(null)}>
        <DialogContent className="flex h-dvh max-h-dvh w-screen max-w-none flex-col gap-3 overflow-hidden rounded-none p-3 sm:h-[96dvh] sm:max-h-[96dvh] sm:max-w-[min(96vw,1600px)] sm:rounded-lg sm:p-6">
          <DialogHeader className="shrink-0 pr-10">
            <DialogTitle>{fullscreenCam != null ? byId.get(fullscreenCam)?.name : ""} · main stream</DialogTitle>
          </DialogHeader>
          {fullscreenCam != null && (
            <div className="relative flex min-h-0 flex-1 overflow-hidden">
              <DigitalZoomPlayer key={fullscreenCam} cameraId={fullscreenCam} protocol={protocol} />
              {byId.get(fullscreenCam)?.has_ptz && <PtzOverlay key={`ptz-${fullscreenCam}`} cameraId={fullscreenCam} />}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

/** Groups matching the sidebar search (top 8, with their path): click shows it in the tree, ▶ plays it. */
function GroupSearchResults({ q, big, onReveal, onPlay }: {
  q: string
  big: boolean
  onReveal: (g: CameraGroup) => void
  onPlay: (g: CameraGroup) => void
}) {
  const found = useGroupSearch(q, 8)
  const rows = found.data?.items ?? []
  if (rows.length === 0) return null
  return (
    <div className="mb-2 border-b pb-2">
      <div className="px-2.5 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        Groups{found.data!.total > rows.length ? ` (${rows.length} of ${found.data!.total})` : ""}
      </div>
      {rows.map((g) => (
        <div key={g.id} className={cn("flex items-center gap-1 rounded-md hover:bg-accent", big ? "min-h-12 px-2" : "px-1")}>
          <button type="button" onClick={() => onReveal(g)} title="Show in the group tree"
            className="flex min-w-0 flex-1 items-start gap-2 py-1.5 pl-1.5 text-left text-sm">
            <Folder className="mt-0.5 size-4 shrink-0 text-primary/80" />
            <span className="min-w-0">
              <span className="block truncate">{g.name}</span>
              <span className="block truncate text-[11px] text-muted-foreground">
                {g.path_label}{g.cameras_total ? ` · ${g.online_total}/${g.cameras_total}` : ""}
              </span>
            </span>
          </button>
          <Button variant="ghost" size="icon-sm" aria-label={`Play ${g.name}`} title="Play on the grid"
            disabled={g.cameras_total === 0} onClick={() => onPlay(g)}><Play /></Button>
        </div>
      ))}
    </div>
  )
}

/** Searchable camera list (sidebar and mobile sheet): small rows from the server, 50 at a time. */
function CameraOptionList({
  rows, total, visible, big, onPick, loading, error, hasMore, loadingMore, onMore, searching,
}: {
  rows: CameraOption[]
  total: number | undefined
  visible: (number | null)[]
  big: boolean
  onPick: (id: number) => void
  loading: boolean
  error: unknown
  hasMore: boolean
  loadingMore: boolean
  onMore: () => void
  searching: boolean
}) {
  return (
    <>
      {loading && <Loading />}
      {error != null && <ErrorState error={error} />}
      {rows.map((c) => (
        <button
          key={c.id}
          type="button"
          draggable={!big}
          onDragStart={(e) => e.dataTransfer.setData("text/camera-id", String(c.id))}
          onClick={() => onPick(c.id)}
          disabled={!c.enabled}
          className={cn(
            "flex w-full items-center text-left hover:bg-accent disabled:opacity-50",
            big ? "min-h-12 gap-3 rounded-lg px-3" : "gap-2.5 rounded-md px-2.5 py-2 text-sm",
          )}
          title={big ? undefined : "Click or drag onto a tile"}
        >
          <StatusDot status={c.status} />
          <span className="min-w-0 flex-1">
            <span className="block truncate">{c.name}</span>
            {searching && c.group_path && <span className="block truncate text-[11px] text-muted-foreground">{c.group_path}</span>}
          </span>
          {visible.includes(c.id) && <span className={cn("text-primary", big ? "text-xs" : "text-[10px]")}>on view</span>}
        </button>
      ))}
      {!loading && total === 0 && (
        <div className="p-3 text-sm text-muted-foreground">{searching ? "No cameras match." : "No cameras."}</div>
      )}
      {hasMore && (
        <Button variant="ghost" size="sm" className="mt-1 w-full text-muted-foreground" disabled={loadingMore} onClick={onMore}>
          {loadingMore ? <Loader2 className="size-3.5 animate-spin" /> : `Load more (${rows.length} of ${total})`}
        </Button>
      )}
    </>
  )
}

function LiveTile({
  camera,
  profile,
  protocol: gridProtocol,
  suspended,
  onRemove,
  onExpand,
}: {
  camera: Camera
  profile: string
  protocol: LiveProtocol
  /** The main-stream dialog is open: freeze this tile (no network, no decode). */
  suspended: boolean
  onRemove: () => void
  onExpand: () => void
}) {
  const navigate = useNavigate()
  const live = useLive(camera.id)
  const [override, setOverride] = useState<LiveProtocol | null>(null)
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
      <LivePlayer cameraId={camera.id} profile={profile} protocol={protocol} suspended={suspended} className="size-full" onVideo={setVideo} />
      <div className="pointer-events-none absolute inset-x-0 top-0 flex min-w-0 items-center gap-2 overflow-hidden bg-gradient-to-b from-black/60 to-transparent px-2 py-1.5 text-xs text-white">
        <span className="min-w-0 flex-1 truncate font-medium">{camera.name}</span>
        {recording && (
          <span className="flex shrink-0 items-center gap-1 rounded bg-danger/80 px-1 text-[10px] font-semibold">
            <span className="size-1.5 animate-pulse rounded-full bg-white" /> REC
          </span>
        )}
        <span className="shrink-0 text-white/60">{profile}</span>
        <div className="pointer-events-auto flex shrink-0 opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
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
