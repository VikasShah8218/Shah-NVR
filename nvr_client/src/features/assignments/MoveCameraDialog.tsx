import { useState } from "react"
import { useMoveCamera, useNodes } from "@/api/queries"
import { StatusBadge } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

const MOVABLE = ["READY", "ACTIVE", "CORDONED"]

export function MoveCameraDialog({
  cameraId,
  cameraName,
  currentNodeId,
  open,
  onOpenChange,
}: {
  cameraId: number
  cameraName: string
  currentNodeId: number | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const nodes = useNodes()
  const move = useMoveCamera()
  const [target, setTarget] = useState<string>("")
  const options = (nodes.data ?? []).filter((n) => n.id !== currentNodeId)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Move {cameraName}</DialogTitle>
          <DialogDescription>
            The new node starts pulling and recording the camera; the old node stops within a few seconds. Existing
            recordings stay where they are and remain playable.
          </DialogDescription>
        </DialogHeader>
        <Select value={target} onValueChange={setTarget}>
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Choose a media node" />
          </SelectTrigger>
          <SelectContent>
            {options.map((n) => (
              <SelectItem key={n.id} value={String(n.id)} disabled={!MOVABLE.includes(n.state)}>
                <span className="flex items-center gap-2">
                  {n.name} <StatusBadge status={n.state} />
                  <span className="text-xs text-muted-foreground">
                    {n.assigned_cameras}/{n.capacity_cameras} cameras
                  </span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {options.length === 0 && <p className="text-sm text-muted-foreground">There is no other media node to move to.</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!target || move.isPending}
            onClick={() => move.mutate({ cameraId, nodeId: Number(target) }, { onSuccess: () => onOpenChange(false) })}
          >
            Move camera
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
