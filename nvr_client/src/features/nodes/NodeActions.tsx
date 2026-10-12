import { Ban, MoreHorizontal, Play, SlidersHorizontal, Trash2, Waves } from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router"
import { useDeleteNode, useNodeAction, useUpdateNode } from "@/api/queries"
import type { MediaNode } from "@/api/types"
import { ConfirmDialog } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { formatBytes } from "@/lib/format"
import { nodeResources } from "./nodeUtils"

const GB = 1024 ** 3

/** Row/header menu: edit limits, drain, cordon, activate, delete. */
export function NodeActions({ node, variant = "icon" }: { node: MediaNode; variant?: "icon" | "button" }) {
  const action = useNodeAction()
  const del = useDeleteNode()
  const navigate = useNavigate()
  const [limitsOpen, setLimitsOpen] = useState(false)
  const [confirm, setConfirm] = useState<"drain" | "delete" | null>(null)
  const [force, setForce] = useState(false)

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          {variant === "icon" ? (
            <Button variant="ghost" size="icon" className="size-8" onClick={(e) => e.stopPropagation()}>
              <MoreHorizontal className="size-4" />
            </Button>
          ) : (
            <Button variant="outline" size="sm">
              <MoreHorizontal className="size-4" /> Actions
            </Button>
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
          <DropdownMenuItem onClick={() => setLimitsOpen(true)}>
            <SlidersHorizontal className="size-4" /> Edit limits
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => setConfirm("drain")} disabled={node.state === "DRAINING"}>
            <Waves className="size-4" /> Drain (move cameras away)
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => action.mutate({ id: node.id, action: "cordon" })} disabled={node.state === "CORDONED"}>
            <Ban className="size-4" /> Cordon (no new cameras)
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => action.mutate({ id: node.id, action: "activate" })}
            disabled={node.state === "ACTIVE" || node.state === "READY"}
          >
            <Play className="size-4" /> Activate
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem className="text-danger focus:text-danger" onClick={() => setConfirm("delete")}>
            <Trash2 className="size-4" /> Delete node
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Mounted only while open so the form starts from the node's current values. */}
      {limitsOpen && <NodeLimitsDialog node={node} open onOpenChange={setLimitsOpen} />}

      <ConfirmDialog
        open={confirm === "drain"}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={`Drain ${node.name}?`}
        description="All cameras on this node will be moved to other healthy nodes, and it will not receive new cameras until you activate it again."
        confirmLabel="Drain node"
        onConfirm={() => action.mutate({ id: node.id, action: "drain" })}
      />
      <ConfirmDialog
        open={confirm === "delete"}
        onOpenChange={(o) => {
          if (!o) {
            setConfirm(null)
            setForce(false)
          }
        }}
        title={`Delete ${node.name}?`}
        description="Only possible when no cameras are assigned (drain it first). If the node agent is still running it will register itself again."
        confirmLabel="Delete"
        destructive
        onConfirm={() => del.mutate({ id: node.id, force }, { onSuccess: () => navigate("/nodes") })}
      >
        <label className="flex items-center gap-3 rounded-md border p-3 text-sm">
          <Switch checked={force} onCheckedChange={setForce} />
          <span>
            Also remove this node's recordings index
            <span className="block text-xs text-muted-foreground">Recorded files on the node itself are not touched.</span>
          </span>
        </label>
      </ConfirmDialog>
    </>
  )
}

export function NodeLimitsDialog({
  node,
  open,
  onOpenChange,
}: {
  node: MediaNode
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const update = useUpdateNode()
  const res = nodeResources(node)
  const [capacity, setCapacity] = useState(String(node.capacity_cameras))
  const [unlimited, setUnlimited] = useState(node.storage_quota_bytes == null)
  const [quotaGb, setQuotaGb] = useState(node.storage_quota_bytes ? String(+(node.storage_quota_bytes / GB).toFixed(2)) : "100")

  const quotaNum = Number(quotaGb)
  const capNum = Number(capacity)
  const valid = Number.isInteger(capNum) && capNum >= 1 && (unlimited || quotaNum > 0)

  const save = () =>
    update.mutate(
      { id: node.id, body: { capacity_cameras: capNum, storage_quota_gb: unlimited ? null : quotaNum } },
      { onSuccess: () => onOpenChange(false) },
    )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent onClick={(e) => e.stopPropagation()}>
        <DialogHeader>
          <DialogTitle>Limits for {node.name}</DialogTitle>
          <DialogDescription>
            The scheduler never assigns more cameras than the capacity. Above 95% of the storage quota the node
            deletes its oldest recordings until it is back under 90%.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="cap">Camera capacity</Label>
            <Input id="cap" type="number" min={1} value={capacity} onChange={(e) => setCapacity(e.target.value)} />
            <span className="text-xs text-muted-foreground">Currently assigned: {node.assigned_cameras}</span>
          </div>
          <div className="grid gap-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="quota">Storage quota (GB)</Label>
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <Switch checked={unlimited} onCheckedChange={setUnlimited} /> Use whole disk
              </label>
            </div>
            <Input id="quota" type="number" min={0.01} step="any" disabled={unlimited} value={quotaGb} onChange={(e) => setQuotaGb(e.target.value)} />
            <span className="text-xs text-muted-foreground">
              Recordings now {formatBytes(res.recordings)} · disk free {formatBytes(res.diskFree)} of {formatBytes(res.diskTotal)}
            </span>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={save} disabled={!valid || update.isPending}>
            Save limits
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
