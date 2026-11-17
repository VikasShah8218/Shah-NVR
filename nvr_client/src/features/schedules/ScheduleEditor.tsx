import { Eraser, Loader2, Plus, Trash2 } from "lucide-react"
import { useMemo, useState } from "react"
import { useCreateSchedule, useUpdateSchedule } from "@/api/queries"
import type { RecordingSchedule, ScheduleBlock } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { blockLabel, blocksToBitmap, DAYS, parseHHMM, recordedHours, TEMPLATES } from "@/lib/schedule"
import { cn } from "@/lib/utils"
import { type Brush, WeekGrid } from "./WeekGrid"

const MAX_BLOCKS = 50
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$|^24:00$/

function blockError(b: ScheduleBlock): string | null {
  if (!b.days.length) return "pick at least one day"
  if (!TIME_RE.test(b.start) || !TIME_RE.test(b.end)) return "use HH:MM (00:00–24:00)"
  if (b.start === "24:00") return "start cannot be 24:00"
  return null
}

/** Create or edit a schedule: paint the week grid, or type exact times in the block list under it. */
export function ScheduleEditor({
  schedule,
  readOnly,
  now,
  onOpenChange,
}: {
  schedule?: RecordingSchedule
  readOnly?: boolean
  now?: { day: number; minute: number }
  onOpenChange: (open: boolean) => void
}) {
  const create = useCreateSchedule()
  const update = useUpdateSchedule()
  const [name, setName] = useState(schedule?.name ?? "")
  const [description, setDescription] = useState(schedule?.description ?? "")
  const [blocks, setBlocks] = useState<ScheduleBlock[]>(schedule?.blocks ?? TEMPLATES[1].blocks)
  const [brush, setBrush] = useState<Brush>("on")

  const errors = blocks.map(blockError)
  const valid = useMemo(() => blocks.filter((b) => !blockError(b)), [blocks])
  const hours = useMemo(() => recordedHours(blocksToBitmap(valid)), [valid])
  const busy = create.isPending || update.isPending
  const canSave = !readOnly && name.trim() !== "" && errors.every((e) => !e) && blocks.length <= MAX_BLOCKS

  const setBlock = (i: number, patch: Partial<ScheduleBlock>) => setBlocks((l) => l.map((b, j) => (j === i ? { ...b, ...patch } : b)))

  const save = async () => {
    const body = { name: name.trim(), description: description.trim() || null, blocks }
    if (schedule) await update.mutateAsync({ id: schedule.id, body })
    else await create.mutateAsync(body)
    onOpenChange(false)
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{readOnly ? schedule?.name : schedule ? `Edit ${schedule.name}` : "New recording schedule"}</DialogTitle>
          <DialogDescription>
            Times are site time. Cameras record in the green times only; a change applies within a few seconds
            {schedule?.camera_count ? ` to the ${schedule.camera_count} camera${schedule.camera_count === 1 ? "" : "s"} using it` : ""}.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {!readOnly && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="sch-name">Name</Label>
                <Input id="sch-name" autoFocus maxLength={64} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Office hours" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sch-desc">Description <span className="text-muted-foreground">(optional)</span></Label>
                <Input id="sch-desc" maxLength={1000} value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>
            </div>
          )}

          {!readOnly && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">Start from</span>
              {TEMPLATES.map((t) => (
                <Button key={t.key} type="button" variant="outline" size="sm" title={t.hint} onClick={() => setBlocks(t.blocks)}>
                  {t.label}
                </Button>
              ))}
              <Button type="button" variant="ghost" size="sm" onClick={() => setBlocks([])}><Eraser className="size-4" /> Clear</Button>
              <ToggleGroup type="single" variant="outline" size="sm" className="ml-auto" value={brush} onValueChange={(v) => v && setBrush(v as Brush)}>
                <ToggleGroupItem value="on" className="px-3"><span className="size-2.5 rounded-sm bg-success/70" /> Paint record</ToggleGroupItem>
                <ToggleGroupItem value="off" className="px-3"><span className="size-2.5 rounded-sm border bg-muted" /> Paint off</ToggleGroupItem>
              </ToggleGroup>
            </div>
          )}

          <WeekGrid blocks={valid} brush={brush} now={now} onChange={readOnly ? undefined : setBlocks} />
          <p className="text-xs text-muted-foreground">
            {readOnly ? "" : "Drag across days and hours to paint (15-minute steps). "}
            Records {Math.round(hours * 10) / 10} h of 168 h a week{hours > 0 && hours < 168 ? ` (${Math.round((hours / 168) * 100)}%)` : ""}.
          </p>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Blocks <span className="font-normal text-muted-foreground">(exact times; end before start runs past midnight)</span></Label>
              {!readOnly && (
                <Button type="button" variant="outline" size="sm" disabled={blocks.length >= MAX_BLOCKS}
                  onClick={() => setBlocks((l) => [...l, { days: [0, 1, 2, 3, 4], start: "08:00", end: "18:00", mode: "continuous" }])}>
                  <Plus className="size-4" /> Add block
                </Button>
              )}
            </div>
            {blocks.length === 0 && <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">No blocks: cameras on this schedule never record.</p>}
            {blocks.map((b, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 rounded-md border p-2">
                {readOnly ? (
                  <span className="text-sm">{blockLabel(b)}</span>
                ) : (
                  <>
                    <ToggleGroup type="multiple" variant="outline" size="sm" value={b.days.map(String)}
                      onValueChange={(v) => setBlock(i, { days: v.map(Number).sort((x, y) => x - y) })}>
                      {DAYS.map((d, n) => <ToggleGroupItem key={d} value={String(n)} className="px-2 text-xs">{d}</ToggleGroupItem>)}
                    </ToggleGroup>
                    <Input aria-label="Start" className={cn("h-8 w-20 font-mono text-sm", errors[i] && !TIME_RE.test(b.start) && "border-danger")}
                      value={b.start} onChange={(e) => setBlock(i, { start: e.target.value })} placeholder="08:00" />
                    <span className="text-muted-foreground">–</span>
                    <Input aria-label="End" className={cn("h-8 w-20 font-mono text-sm", errors[i] && !TIME_RE.test(b.end) && "border-danger")}
                      value={b.end} onChange={(e) => setBlock(i, { end: e.target.value })} placeholder="18:00" />
                    {!errors[i] && parseHHMM(b.end) <= parseHHMM(b.start) && b.end !== "00:00" && (
                      <span className="text-xs text-muted-foreground">{b.start === b.end ? "24 h" : "next day"}</span>
                    )}
                    {errors[i] && <span className="text-xs text-danger">{errors[i]}</span>}
                    <Button type="button" variant="ghost" size="icon-sm" className="ml-auto" title="Remove block" onClick={() => setBlocks((l) => l.filter((_, j) => j !== i))}>
                      <Trash2 />
                    </Button>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{readOnly ? "Close" : "Cancel"}</Button>
          {!readOnly && (
            <Button type="button" disabled={!canSave || busy} onClick={() => void save().catch(() => undefined)}>
              {busy && <Loader2 className="size-4 animate-spin" />} {schedule ? "Save" : "Create"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
