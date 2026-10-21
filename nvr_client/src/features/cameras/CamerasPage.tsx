import { Camera as CameraIcon, History, MonitorPlay, MoreHorizontal, Pencil, Plus, Radar, Search, Trash2 } from "lucide-react"
import { useState } from "react"
import { Link, useNavigate } from "react-router"
import { useCameras, useDeleteCamera, useUpdateCamera } from "@/api/queries"
import type { Camera } from "@/api/types"
import { ConfirmDialog, EmptyState, ErrorState, Loading, PageHeader } from "@/components/common"
import { StatusBadge } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { retentionLabel, timeAgo } from "@/lib/format"
import { CameraFormSheet } from "./CameraFormSheet"

export function CamerasPage() {
  const cameras = useCameras()
  const [search, setSearch] = useState("")
  const [editing, setEditing] = useState<Camera | "new" | null>(null)

  const list = (cameras.data ?? []).filter(
    (c) => c.name.toLowerCase().includes(search.toLowerCase()) || String(c.id) === search.trim(),
  )

  return (
    <div>
      <PageHeader
        title="Cameras"
        description="Register cameras, their streams and how long recordings are kept."
        actions={
          <>
            <div className="relative w-full sm:w-60">
              <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
              <Input className="pl-8" placeholder="Search cameras" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <Button variant="outline" asChild>
              <Link to="/discover">
                <Radar className="size-4" /> Discover
              </Link>
            </Button>
            <Button onClick={() => setEditing("new")}>
              <Plus className="size-4" /> Add camera
            </Button>
          </>
        }
      />
      {cameras.isLoading && <Loading />}
      {cameras.error && <ErrorState error={cameras.error} />}
      {cameras.data && cameras.data.length === 0 && (
        <EmptyState icon={CameraIcon} title="No cameras yet">
          Use <b>Discover</b> to find ONVIF cameras on the network, or click <b>Add camera</b> and enter an RTSP URL.
        </EmptyState>
      )}
      {list.length > 0 && (
        <>
        <div className="space-y-2 md:hidden">
          {list.map((c) => <MobileCameraCard key={c.id} camera={c} onEdit={() => setEditing(c)} />)}
        </div>
        <Card className="hidden overflow-hidden py-0 md:block">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-12 pl-4">#</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Streams</TableHead>
                <TableHead>Media node</TableHead>
                <TableHead>Retention</TableHead>
                <TableHead>Last recording</TableHead>
                <TableHead>Enabled</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((c) => (
                <CameraRow key={c.id} camera={c} onEdit={() => setEditing(c)} />
              ))}
            </TableBody>
          </Table>
        </Card>
        </>
      )}
      {editing && (
        <CameraFormSheet camera={editing === "new" ? undefined : editing} open onOpenChange={(o) => !o && setEditing(null)} />
      )}
    </div>
  )
}

function MobileCameraCard({ camera: c, onEdit }: { camera: Camera; onEdit: () => void }) {
  const navigate = useNavigate()
  const update = useUpdateCamera()
  const del = useDeleteCamera()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const lastSegment = c.streams.map((s) => s.last_segment_at).filter(Boolean).sort().pop()
  return <Card className="gap-3 p-4" onClick={() => navigate(`/cameras/${c.id}`)}>
    <div className="flex items-start gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2"><span className="truncate font-medium">{c.name}</span><span className="text-xs text-muted-foreground">#{c.id}</span></div>
        {c.description && <div className="mt-0.5 truncate text-xs text-muted-foreground">{c.description}</div>}
      </div>
      <div onClick={(e) => e.stopPropagation()}><Switch checked={c.enabled} disabled={update.isPending} onCheckedChange={(v) => update.mutate({ id: c.id, body: { enabled: v } })} /></div>
      <div onClick={(e) => e.stopPropagation()}><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className="size-10"><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">
        <DropdownMenuItem onClick={onEdit}><Pencil className="size-4" /> Edit</DropdownMenuItem>
        <DropdownMenuItem onClick={() => navigate(`/cameras/${c.id}`)}><MonitorPlay className="size-4" /> Details & live</DropdownMenuItem>
        <DropdownMenuItem onClick={() => navigate(`/playback?camera=${c.id}`)}><History className="size-4" /> Recordings</DropdownMenuItem>
        <DropdownMenuSeparator /><DropdownMenuItem className="text-danger focus:text-danger" onClick={() => setConfirmDelete(true)}><Trash2 className="size-4" /> Delete</DropdownMenuItem>
      </DropdownMenuContent></DropdownMenu></div>
    </div>
    <div className="flex flex-wrap gap-1.5">{c.streams.map((s) => <span key={s.profile} className="flex items-center gap-1 text-xs"><span className="text-muted-foreground">{s.profile}</span><StatusBadge status={s.status} /></span>)}</div>
    <div className="grid grid-cols-2 gap-2 border-t pt-3 text-xs">
      <div><div className="text-muted-foreground">Media node</div><div className="truncate">{c.assignment?.node_name ?? "Unassigned"}</div></div>
      <div><div className="text-muted-foreground">Retention</div><div>{retentionLabel(c.retention_days)}</div></div>
      <div className="col-span-2"><span className="text-muted-foreground">Last recording: </span>{lastSegment ? timeAgo(lastSegment) : "—"}</div>
    </div>
    <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} title={`Delete ${c.name}?`} description="Only cameras without recordings can be deleted. Disable cameras with recordings to preserve their history." confirmLabel="Delete camera" destructive onConfirm={() => del.mutate(c.id)} />
  </Card>
}

function CameraRow({ camera: c, onEdit }: { camera: Camera; onEdit: () => void }) {
  const navigate = useNavigate()
  const update = useUpdateCamera()
  const del = useDeleteCamera()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const lastSegment = c.streams
    .map((s) => s.last_segment_at)
    .filter(Boolean)
    .sort()
    .pop()

  return (
    <TableRow className="cursor-pointer" onClick={() => navigate(`/cameras/${c.id}`)}>
      <TableCell className="pl-4 text-muted-foreground tabular-nums">{c.id}</TableCell>
      <TableCell>
        <div className="font-medium">{c.name}</div>
        {c.description && <div className="max-w-xs truncate text-xs text-muted-foreground">{c.description}</div>}
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1.5">
          {c.streams.map((s) => (
            <span key={s.profile} className="flex items-center gap-1 text-xs">
              <span className="text-muted-foreground">{s.profile}</span>
              <StatusBadge status={s.status} title={s.status_detail ?? undefined} />
            </span>
          ))}
        </div>
      </TableCell>
      <TableCell onClick={(e) => e.stopPropagation()}>
        {c.assignment?.node_id ? (
          <Link to={`/nodes/${c.assignment.node_id}`} className="hover:text-primary">
            {c.assignment.node_name}
          </Link>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="tabular-nums">{retentionLabel(c.retention_days)}</TableCell>
      <TableCell className="text-xs text-muted-foreground">{lastSegment ? timeAgo(lastSegment) : "—"}</TableCell>
      <TableCell onClick={(e) => e.stopPropagation()}>
        <Switch checked={c.enabled} disabled={update.isPending} onCheckedChange={(v) => update.mutate({ id: c.id, body: { enabled: v } })} />
      </TableCell>
      <TableCell onClick={(e) => e.stopPropagation()}>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="size-8">
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={onEdit}>
              <Pencil className="size-4" /> Edit
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => navigate(`/cameras/${c.id}`)}>
              <MonitorPlay className="size-4" /> Live preview
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => navigate(`/playback?camera=${c.id}`)}>
              <History className="size-4" /> Recordings
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-danger focus:text-danger" onClick={() => setConfirmDelete(true)}>
              <Trash2 className="size-4" /> Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <ConfirmDialog
          open={confirmDelete}
          onOpenChange={setConfirmDelete}
          title={`Delete ${c.name}?`}
          description="Only cameras without recordings can be deleted. If it has recordings, disable it instead; they stay until their retention or storage space removes them."
          confirmLabel="Delete camera"
          destructive
          onConfirm={() => del.mutate(c.id)}
        />
      </TableCell>
    </TableRow>
  )
}
