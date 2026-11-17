import { Link } from "react-router"
import { useSchedules } from "@/api/queries"
import type { RecordingMode } from "@/api/types"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { nowText } from "@/lib/schedule"
import { WeekStrip } from "./WeekGrid"

const MODE_LABEL: Record<RecordingMode, string> = { always: "Always", schedule: "Schedule", never: "Never" }

/** "When to record": Always | Schedule (+ which one) | Never. Used by the camera form and the group dialog. */
export function RecordingFields({
  mode,
  scheduleId,
  onChange,
  current,
}: {
  mode: RecordingMode
  scheduleId: number | null
  onChange: (mode: RecordingMode, scheduleId: number | null) => void
  /** what the camera does right now, shown while the saved setting is unchanged */
  current?: { mode: RecordingMode; scheduleId: number | null; recordingNow: boolean; nextChange: string | null }
}) {
  const schedules = useSchedules()
  const list = schedules.data ?? []
  const chosen = list.find((s) => s.id === scheduleId)
  const unchanged = current && current.mode === mode && (mode !== "schedule" || current.scheduleId === scheduleId)

  const hint = unchanged
    ? nowText(current.recordingNow, current.nextChange)
    : mode === "always" ? "Records all the time."
      : mode === "never" ? "Never records; live view still works."
        : chosen ? `With this schedule: ${nowText(chosen.recording_now, chosen.next_change).replace(/^./, (c) => c.toLowerCase())}` : "Pick a schedule."

  return (
    <div className="grid gap-2">
      <Label>Recording</Label>
      <div className="flex flex-wrap items-center gap-2">
        <ToggleGroup type="single" variant="outline" size="sm" value={mode}
          onValueChange={(v) => v && onChange(v as RecordingMode, v === "schedule" ? scheduleId ?? list[0]?.id ?? null : null)}>
          {(Object.keys(MODE_LABEL) as RecordingMode[]).map((m) => (
            <ToggleGroupItem key={m} value={m} className="px-3">{MODE_LABEL[m]}</ToggleGroupItem>
          ))}
        </ToggleGroup>
        {mode === "schedule" && (
          list.length ? (
            <Select value={scheduleId ? String(scheduleId) : ""} onValueChange={(v) => onChange("schedule", Number(v))}>
              <SelectTrigger size="sm" className="min-w-44 flex-1">
                <SelectValue placeholder="Choose a schedule" />
              </SelectTrigger>
              <SelectContent>
                {list.map((s) => <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>)}
              </SelectContent>
            </Select>
          ) : (
            <span className="text-xs text-muted-foreground">
              {schedules.isLoading ? "Loading…" : <>No schedules yet. <Link to="/schedules" className="text-primary hover:underline">Create one</Link>.</>}
            </span>
          )
        )}
      </div>
      {mode === "schedule" && chosen && <WeekStrip blocks={chosen.blocks} className="w-full max-w-sm" />}
      <span className="text-xs text-muted-foreground">{hint}{/[.:]$/.test(hint) ? "" : "."} Applies to streams set to Record.</span>
    </div>
  )
}
