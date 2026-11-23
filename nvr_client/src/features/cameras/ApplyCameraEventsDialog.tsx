import { Loader2 } from "lucide-react"
import { useState } from "react"
import { useApplyCameraEvents } from "@/api/queries"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Switch } from "@/components/ui/switch"
import { CAMERA_EVENT_KINDS, CAMERA_EVENT_LABELS, type CameraEventKind } from "@/lib/cameraEvents"

/** Switch camera events (ONVIF motion / tamper / inputs) on or off for a group or selected cameras. */
export function ApplyCameraEventsDialog({
  target,
  onOpenChange,
  onDone,
}: {
  target: { kind: "group"; id: number; name: string } | { kind: "cameras"; ids: number[] }
  onOpenChange: (open: boolean) => void
  onDone?: () => void
}) {
  const apply = useApplyCameraEvents()
  const [enabled, setEnabled] = useState(true)
  const [kinds, setKinds] = useState<CameraEventKind[]>([...CAMERA_EVENT_KINDS])
  const [subgroups, setSubgroups] = useState(true)

  const submit = () =>
    apply.mutate(
      {
        enabled,
        kinds: kinds.length === CAMERA_EVENT_KINDS.length ? null : kinds,
        ...(target.kind === "group" ? { group_id: target.id, include_subgroups: subgroups } : { camera_ids: target.ids, include_subgroups: false }),
      },
      { onSuccess: () => { onDone?.(); onOpenChange(false) } },
    )

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Camera events</DialogTitle>
          <DialogDescription>
            {target.kind === "group"
              ? `Motion, tamper and inputs from every camera in "${target.name}" (cameras with ONVIF).`
              : `Motion, tamper and inputs from the ${target.ids.length} selected camera${target.ids.length === 1 ? "" : "s"} (cameras with ONVIF).`}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <label className="flex items-center justify-between rounded-md border px-3 py-2.5 text-sm">
            <span>Use camera events</span>
            <Switch checked={enabled} onCheckedChange={setEnabled} />
          </label>
          {enabled && CAMERA_EVENT_KINDS.map((k) => (
            <label key={k} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
              <span>
                {CAMERA_EVENT_LABELS[k].title}
                <span className="block text-xs text-muted-foreground">{CAMERA_EVENT_LABELS[k].hint}</span>
              </span>
              <Switch checked={kinds.includes(k)}
                onCheckedChange={(on) => setKinds((cur) => CAMERA_EVENT_KINDS.filter((x) => (x === k ? on : cur.includes(x))))} />
            </label>
          ))}
          {target.kind === "group" && (
            <label className="flex items-center justify-between rounded-md border px-3 py-2.5 text-sm">
              <span>
                Include sub-groups
                <span className="block text-xs text-muted-foreground">Off: only cameras directly in this group.</span>
              </span>
              <Switch checked={subgroups} onCheckedChange={setSubgroups} />
            </label>
          )}
          <p className="text-xs text-muted-foreground">
            Each camera's Camera events tab shows what it offers and whether events arrive.
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={apply.isPending || (enabled && !kinds.length)} onClick={submit}>
            {apply.isPending && <Loader2 className="size-4 animate-spin" />} Apply
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
