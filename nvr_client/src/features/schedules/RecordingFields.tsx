import { Link } from "react-router"
import { useSchedules } from "@/api/queries"
import type { RecordingMode } from "@/api/types"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { type EventSettings, eventSettingsValid } from "@/lib/eventSettings"
import { nowText, type RecordingState } from "@/lib/schedule"
import { WeekStrip } from "./WeekGrid"

const MODE_LABEL: Record<RecordingMode, string> = { always: "Always", schedule: "Schedule", event: "Event", never: "Never" }

/** "When to record": Always | Schedule (+ which one) | Event | Never, plus the event seconds and the event marks
 * switch. Used by the camera form and the group dialog. */
export function RecordingFields({
  mode,
  scheduleId,
  onChange,
  current,
  events,
  onEventsChange,
}: {
  mode: RecordingMode
  scheduleId: number | null
  onChange: (mode: RecordingMode, scheduleId: number | null) => void
  /** what the camera does right now, shown while the saved setting is unchanged */
  current?: { mode: RecordingMode; scheduleId: number | null; state: RecordingState; nextChange: string | null }
  events?: EventSettings
  onEventsChange?: (e: EventSettings) => void
}) {
  const schedules = useSchedules()
  const list = schedules.data ?? []
  const chosen = list.find((s) => s.id === scheduleId)
  const unchanged = current && current.mode === mode && (mode !== "schedule" || current.scheduleId === scheduleId)
  const usesEvents = mode === "event" || (mode === "schedule" && !!chosen?.blocks.some((b) => b.mode === "event"))

  const hint = unchanged
    ? nowText(current.state, current.nextChange)
    : mode === "always" ? "Records all the time."
      : mode === "never" ? "Never records; live view still works."
        : mode === "event" ? "Keeps video only around events (the seconds before and after below)."
          : chosen ? `With this schedule: ${nowText(chosen.state_now ?? chosen.recording_now, chosen.next_change).replace(/^./, (c) => c.toLowerCase())}` : "Pick a schedule."

  const setEv = (patch: Partial<EventSettings>) => events && onEventsChange?.({ ...events, ...patch })

  return (
    <div className="grid gap-2">
      <Label>Recording</Label>
      <div className="flex flex-wrap items-center gap-2">
        <ToggleGroup type="single" variant="outline" size="sm" value={mode}
          onValueChange={(v) => v && onChange(v as RecordingMode, v === "schedule" ? scheduleId ?? list[0]?.id ?? null : null)}>
          {(Object.keys(MODE_LABEL) as RecordingMode[]).map((m) => (
            <ToggleGroupItem key={m} value={m} className="px-3"
              title={m === "event" ? "Keep video only around events (marked by an operator, another system or video loss)" : undefined}>
              {MODE_LABEL[m]}
            </ToggleGroupItem>
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
      {events && usesEvents && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border px-3 py-2.5 text-sm">
          <label className="flex items-center gap-2">
            Keep
            <Input aria-label="Seconds before an event" type="number" min={0} max={60} className="h-8 w-20"
              value={events.pre} onChange={(e) => setEv({ pre: Number(e.target.value) })} />
            s before
          </label>
          <label className="flex items-center gap-2">
            <Input aria-label="Seconds after an event" type="number" min={0} max={600} className="h-8 w-20"
              value={events.post} onChange={(e) => setEv({ post: Number(e.target.value) })} />
            s after each event
          </label>
          {!eventSettingsValid(events) && <span className="text-xs text-danger">Before: 0–60 s, after: 0–600 s.</span>}
        </div>
      )}
      {events && (
        <label className="flex items-center justify-between rounded-md border px-3 py-2.5 text-sm">
          <span>
            Show events on the timeline
            <span className="block text-xs text-muted-foreground">
              Logs camera events (video loss; motion and inputs later) as marks in playback. Marks you add by hand are always kept.
            </span>
          </span>
          <Switch checked={events.marking} onCheckedChange={(v) => setEv({ marking: v })} />
        </label>
      )}
    </div>
  )
}
