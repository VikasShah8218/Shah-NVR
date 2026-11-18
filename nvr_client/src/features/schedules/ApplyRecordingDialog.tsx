import { Loader2 } from "lucide-react"
import { useState } from "react"
import { useApplySchedule } from "@/api/queries"
import type { RecordingMode } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Switch } from "@/components/ui/switch"
import { EVENT_DEFAULTS, type EventSettings, eventSettingsValid } from "@/lib/eventSettings"
import { RecordingFields } from "./RecordingFields"

/** Set the recording mode of a whole group (optionally with its sub-groups) or of selected cameras. */
export function ApplyRecordingDialog({
  target,
  onOpenChange,
  onDone,
}: {
  target: { kind: "group"; id: number; name: string } | { kind: "cameras"; ids: number[] }
  onOpenChange: (open: boolean) => void
  onDone?: () => void
}) {
  const apply = useApplySchedule()
  const [mode, setMode] = useState<RecordingMode>("schedule")
  const [scheduleId, setScheduleId] = useState<number | null>(null)
  const [subgroups, setSubgroups] = useState(true)
  const [events, setEvents] = useState<EventSettings>(EVENT_DEFAULTS)

  const submit = () =>
    apply.mutate(
      {
        mode,
        schedule_id: mode === "schedule" ? scheduleId : null,
        event_pre_seconds: events.pre,
        event_post_seconds: events.post,
        event_marking: events.marking,
        ...(target.kind === "group" ? { group_id: target.id, include_subgroups: subgroups } : { camera_ids: target.ids, include_subgroups: false }),
      },
      { onSuccess: () => { onDone?.(); onOpenChange(false) } },
    )

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Recording schedule</DialogTitle>
          <DialogDescription>
            {target.kind === "group"
              ? `Set when every camera in "${target.name}" records. Cameras added to the group later keep their own setting.`
              : `Set when the ${target.ids.length} selected camera${target.ids.length === 1 ? "" : "s"} record.`}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <RecordingFields mode={mode} scheduleId={scheduleId} onChange={(m, id) => { setMode(m); setScheduleId(id) }}
            events={events} onEventsChange={setEvents} />
          {target.kind === "group" && (
            <label className="flex items-center justify-between rounded-md border px-3 py-2.5 text-sm">
              <span>
                Include sub-groups
                <span className="block text-xs text-muted-foreground">Off: only cameras directly in this group.</span>
              </span>
              <Switch checked={subgroups} onCheckedChange={setSubgroups} />
            </label>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={apply.isPending || (mode === "schedule" && scheduleId == null) || !eventSettingsValid(events)} onClick={submit}>
            {apply.isPending && <Loader2 className="size-4 animate-spin" />} Apply
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
