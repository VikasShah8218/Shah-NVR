import { AlertTriangle, ArrowDown, ArrowUp, HardDrive, Info, MoreHorizontal, Network, Pause, Pencil, Play, Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import { useAddVolume, useDeleteVolume, useReorderVolumes, useUpdateVolume } from "@/api/queries"
import { type MediaNode, nodeMetrics, type StorageVolume } from "@/api/types"
import { ConfirmDialog, EmptyState } from "@/components/common"
import { StatusBadge } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { UsageBar } from "@/components/UsageBar"
import { formatBytes, ratio, timeAgo } from "@/lib/format"
import { cn } from "@/lib/utils"
import { nodeResources } from "./nodeUtils"

const GB = 1024 ** 3
const isNetwork = (path: string) => path.startsWith("\\\\") || path.startsWith("//")
const shareHost = (path: string) => path.replace(/^[\\/]+/, "").split(/[\\/]/)[0] || "<host>"

/**
 * Where a media node may record: its own folder plus extra drives and network shares, each with an
 * optional cap. The node fills them in order and overwrites the oldest recordings only when all are full.
 */
export function StorageTab({ node }: { node: MediaNode }) {
  const r = nodeResources(node)
  const volumes = r.volumes
  const reorder = useReorderVolumes()
  const update = useUpdateVolume()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<StorageVolume | null>(null)
  const [removing, setRemoving] = useState<StorageVolume | null>(null)

  const move = (index: number, delta: number) => {
    const ids = volumes.map((v) => v.id)
    const [id] = ids.splice(index, 1)
    ids.splice(index + delta, 0, id)
    reorder.mutate({ nodeId: node.id, volumeIds: ids })
  }

  return (
    <Card className="gap-3">
      <CardHeader className="flex flex-row items-start justify-between gap-4 pb-0">
        <div className="space-y-1">
          <CardTitle className="text-sm font-medium">Storage</CardTitle>
          <p className="text-xs text-muted-foreground">
            The node records to the first storage in this order that has room, moves to the next when it is full, and
            overwrites the oldest recordings only when every storage is full. Recordings stay playable wherever they are.
          </p>
        </div>
        <Button size="sm" onClick={() => setAdding(true)}>
          <Plus className="size-4" /> Add storage
        </Button>
      </CardHeader>
      <CardContent className="space-y-3 px-0">
        {r.allFull && (
          <Banner tone="warning">All storage is full: the node is overwriting its oldest recordings. Add storage or raise a cap.</Banner>
        )}
        {r.volumesOffline.length > 0 && (
          <Banner tone="danger">
            {r.volumesOffline.length === 1 ? "1 storage is" : `${r.volumesOffline.length} storages are`} offline: recordings on it
            cannot be played until it is back; new recordings go to the next storage.
          </Banner>
        )}
        {volumes.length === 0 ? (
          <div className="px-6">
            <EmptyState icon={HardDrive} title="Waiting for the node">
              The node registers its own recordings folder on its next heartbeat (nodes updated to storage volumes only).
            </EmptyState>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-20 pl-6">Order</TableHead>
                <TableHead>Folder</TableHead>
                <TableHead>State</TableHead>
                <TableHead className="w-56">Recordings / cap</TableHead>
                <TableHead>Disk free</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {volumes.map((v, i) => (
                <TableRow key={v.id} className={cn(!v.accepting && "opacity-60")}>
                  <TableCell className="pl-6">
                    <div className="flex items-center gap-0.5">
                      <span className="w-5 text-muted-foreground tabular-nums">{i + 1}</span>
                      <Button variant="ghost" size="icon" className="size-7" disabled={i === 0 || reorder.isPending} onClick={() => move(i, -1)} title="Earlier">
                        <ArrowUp className="size-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7"
                        disabled={i === volumes.length - 1 || reorder.isPending}
                        onClick={() => move(i, 1)}
                        title="Later"
                      >
                        <ArrowDown className="size-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                  <TableCell className="max-w-[26rem] whitespace-normal">
                    <div className="flex items-start gap-2">
                      {v.kind === "network" ? <Network className="size-4 shrink-0 text-info" /> : <HardDrive className="size-4 shrink-0 text-muted-foreground" />}
                      <span className="font-mono text-xs break-all">{v.path}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-2 pl-6 text-[11px] text-muted-foreground">
                      {v.is_default && <span>node's own folder</span>}
                      {v.writing && <span className="font-medium text-success">● recording here now</span>}
                      {!v.accepting && <span className="text-warning">new recordings stopped</span>}
                    </div>
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    <StatusBadge status={v.state} />
                    {v.state_detail && <div className="mt-1 max-w-72 text-[11px] text-muted-foreground">{v.state_detail}</div>}
                    {v.state === "PENDING" && <div className="mt-1 text-[11px] text-muted-foreground">waiting for the node to check it</div>}
                    {v.last_report_at && v.state !== "PENDING" && (
                      <div className="mt-0.5 text-[10px] text-muted-foreground">checked {timeAgo(v.last_report_at)}</div>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="space-y-1">
                      <div className="text-xs tabular-nums">
                        {formatBytes(v.recordings_bytes)} / {v.quota_bytes != null ? formatBytes(v.quota_bytes) : "whole disk"}
                      </div>
                      <UsageBar
                        percent={v.quota_bytes != null ? ratio(v.recordings_bytes, v.quota_bytes) : ratio(v.total_bytes != null && v.free_bytes != null ? v.total_bytes - v.free_bytes : null, v.total_bytes)}
                        warnAt={90}
                        dangerAt={95}
                      />
                    </div>
                  </TableCell>
                  <TableCell className="text-xs tabular-nums text-muted-foreground">
                    {v.free_bytes != null ? `${formatBytes(v.free_bytes)} of ${formatBytes(v.total_bytes)}` : "—"}
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="size-8">
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => setEditing(v)}>
                          <Pencil className="size-4" /> Edit cap
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => update.mutate({ nodeId: node.id, volumeId: v.id, body: { accepting: !v.accepting } })}
                        >
                          {v.accepting ? <Pause className="size-4" /> : <Play className="size-4" />}
                          {v.accepting ? "Stop new recordings" : "Resume new recordings"}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem className="text-danger focus:text-danger" disabled={v.is_default} onClick={() => setRemoving(v)}>
                          <Trash2 className="size-4" /> Remove
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
      {adding && <AddStorageDialog node={node} open onOpenChange={setAdding} />}
      {editing && <EditCapDialog node={node} volume={editing} open onOpenChange={(o) => !o && setEditing(null)} />}
      {removing && <RemoveStorageDialog node={node} volume={removing} open onOpenChange={(o) => !o && setRemoving(null)} />}
    </Card>
  )
}

function Banner({ tone, children }: { tone: "warning" | "danger"; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "mx-6 flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
        tone === "danger" ? "border-danger/40 bg-danger/10 text-danger" : "border-warning/40 bg-warning/10 text-warning",
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span>{children}</span>
    </div>
  )
}

/** "Use whole disk" switch + cap in GB, shared by the add and edit dialogs. */
function CapField({
  unlimited,
  setUnlimited,
  gb,
  setGb,
}: {
  unlimited: boolean
  setUnlimited: (v: boolean) => void
  gb: string
  setGb: (v: string) => void
}) {
  return (
    <div className="grid gap-1.5">
      <div className="flex items-center justify-between">
        <Label htmlFor="cap-gb">Cap for recordings (GB)</Label>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <Switch checked={unlimited} onCheckedChange={setUnlimited} /> Use whole disk
        </label>
      </div>
      <Input id="cap-gb" type="number" min={0.01} step="any" disabled={unlimited} value={gb} onChange={(e) => setGb(e.target.value)} />
      <span className="text-xs text-muted-foreground">Recording moves to the next storage at 95% of the cap.</span>
    </div>
  )
}

function AddStorageDialog({ node, open, onOpenChange }: { node: MediaNode; open: boolean; onOpenChange: (o: boolean) => void }) {
  const add = useAddVolume()
  const drives = nodeMetrics(node).drives ?? []
  const used = new Set((node.volumes ?? []).map((v) => v.path.toLowerCase()))
  const [kind, setKind] = useState<"local" | "network">("local")
  const [drive, setDrive] = useState(drives[0]?.root ?? "")
  const [localPath, setLocalPath] = useState(drives[0] ? `${drives[0].root}ShahNVR\\recordings` : "")
  const [uncPath, setUncPath] = useState("\\\\")
  const [unlimited, setUnlimited] = useState(true)
  const [gb, setGb] = useState("500")

  const path = (kind === "local" ? localPath : uncPath).trim()
  const capNum = Number(gb)
  const duplicate = used.has(path.toLowerCase())
  const valid =
    path.length > 3 &&
    !duplicate &&
    (unlimited || capNum > 0) &&
    (kind === "local" ? /^[A-Za-z]:[\\/]/.test(path) : /^\\\\[^\\/]+\\[^\\/]+/.test(path))

  const pickDrive = (root: string) => {
    setDrive(root)
    setLocalPath(`${root}ShahNVR\\recordings`)
  }

  const save = () =>
    add.mutate(
      { nodeId: node.id, body: { path, quota_gb: unlimited ? null : capNum, accepting: true } },
      { onSuccess: () => onOpenChange(false) },
    )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add storage to {node.name}</DialogTitle>
          <DialogDescription>
            It is added at the end of the fill order. The node checks the folder within a few seconds and shows OK or
            the exact problem.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <ToggleGroup type="single" variant="outline" value={kind} onValueChange={(v) => v && setKind(v as "local" | "network")} className="justify-start">
            <ToggleGroupItem value="local" className="px-4">
              <HardDrive className="size-4" /> Drive on the node
            </ToggleGroupItem>
            <ToggleGroupItem value="network" className="px-4">
              <Network className="size-4" /> Network share
            </ToggleGroupItem>
          </ToggleGroup>

          {kind === "local" ? (
            <>
              <div className="grid gap-1.5">
                <Label>Drive</Label>
                {drives.length ? (
                  <Select value={drive} onValueChange={pickDrive}>
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Choose a drive" />
                    </SelectTrigger>
                    <SelectContent>
                      {drives.map((d) => (
                        <SelectItem key={d.root} value={d.root}>
                          {d.root} · {formatBytes(d.free_bytes)} free of {formatBytes(d.total_bytes)} {d.fstype ? `· ${d.fstype}` : ""}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <span className="text-xs text-muted-foreground">The node has not reported its drives yet; type the folder below.</span>
                )}
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="local-path">Folder</Label>
                <Input id="local-path" className="font-mono text-xs" value={localPath} onChange={(e) => setLocalPath(e.target.value)} placeholder="D:\ShahNVR\recordings" />
                <span className="text-xs text-muted-foreground">Created automatically if it does not exist.</span>
              </div>
            </>
          ) : (
            <>
              <div className="grid gap-1.5">
                <Label htmlFor="unc-path">Share folder (UNC path)</Label>
                <Input id="unc-path" className="font-mono text-xs" value={uncPath} onChange={(e) => setUncPath(e.target.value)} placeholder="\\192.168.1.9\nvr\recordings" />
              </div>
              <div className="flex gap-2 rounded-md border border-info/30 bg-info/10 p-3 text-xs">
                <Info className="mt-0.5 size-4 shrink-0 text-info" />
                <div className="space-y-1.5">
                  <p>
                    The share's username and password are never stored in the central manager. Save them once on the
                    node PC, signed in as the Windows user that runs the media node:
                  </p>
                  <code className="block rounded bg-muted px-2 py-1 font-mono break-all">
                    cmdkey /add:{shareHost(uncPath)} /user:&lt;user&gt; /pass:&lt;password&gt;
                  </code>
                  <p>Use the \\host\share\folder path, not a mapped drive letter (Z:): drive letters are not visible to the media node.</p>
                </div>
              </div>
            </>
          )}

          <CapField unlimited={unlimited} setUnlimited={setUnlimited} gb={gb} setGb={setGb} />
          {duplicate && <span className="text-xs text-danger">This node already has that folder.</span>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={save} disabled={!valid || add.isPending}>
            Add storage
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EditCapDialog({
  node,
  volume,
  open,
  onOpenChange,
}: {
  node: MediaNode
  volume: StorageVolume
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const update = useUpdateVolume()
  const [unlimited, setUnlimited] = useState(volume.quota_bytes == null)
  const [gb, setGb] = useState(volume.quota_bytes ? String(+(volume.quota_bytes / GB).toFixed(2)) : "500")
  const capNum = Number(gb)
  const save = () =>
    update.mutate(
      { nodeId: node.id, volumeId: volume.id, body: { quota_gb: unlimited ? null : capNum } },
      { onSuccess: () => onOpenChange(false) },
    )
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Cap for {isNetwork(volume.path) ? "network share" : "folder"}</DialogTitle>
          <DialogDescription className="font-mono text-xs break-all">{volume.path}</DialogDescription>
        </DialogHeader>
        <CapField unlimited={unlimited} setUnlimited={setUnlimited} gb={gb} setGb={setGb} />
        <span className="text-xs text-muted-foreground">
          Recordings here now: {formatBytes(volume.recordings_bytes)} · disk free {formatBytes(volume.free_bytes)} of{" "}
          {formatBytes(volume.total_bytes)}. A cap below the current size removes the oldest recordings here.
        </span>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={save} disabled={(!unlimited && !(capNum > 0)) || update.isPending}>
            Save cap
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function RemoveStorageDialog({
  node,
  volume,
  open,
  onOpenChange,
}: {
  node: MediaNode
  volume: StorageVolume
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const remove = useDeleteVolume()
  const [force, setForce] = useState(false)
  const hasRecordings = (volume.recordings_bytes ?? 0) > 0
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Remove this storage?"
      description={
        <>
          <span className="block font-mono text-xs break-all">{volume.path}</span>
          The node stops using it. Recorded files there are not deleted.
        </>
      }
      confirmLabel="Remove storage"
      destructive
      onConfirm={() => remove.mutate({ nodeId: node.id, volumeId: volume.id, force })}
    >
      {hasRecordings && (
        <label className="flex items-start gap-3 rounded-md border p-3 text-sm">
          <Switch checked={force} onCheckedChange={setForce} />
          <span>
            Also forget its {formatBytes(volume.recordings_bytes)} of recordings
            <span className="block text-xs text-muted-foreground">
              Needed while recordings are stored there; they disappear from playback. Safer: stop new recordings and let
              retention empty it first.
            </span>
          </span>
        </label>
      )}
    </ConfirmDialog>
  )
}
