import { Bookmark as BookmarkIcon, Loader2, Pencil, Search, Trash2 } from "lucide-react"
import { useState } from "react"
import { useBookmarks, useCreateBookmark, useDeleteBookmark, useUpdateBookmark } from "@/api/queries"
import type { Bookmark } from "@/api/types"
import { ConfirmDialog, ErrorState } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { fmtDateTime } from "@/lib/time"
import { cn } from "@/lib/utils"
import { Pager } from "@/components/Pager"
import { useClampPage, usePaged } from "@/lib/usePaged"

const COLORS = ["#f59e0b", "#ef4444", "#22c55e", "#3b82f6", "#8b5cf6"]
const DURATIONS = [
  { label: "Point", seconds: 0 },
  { label: "10 s", seconds: 10 },
  { label: "30 s", seconds: 30 },
  { label: "1 min", seconds: 60 },
  { label: "5 min", seconds: 300 },
]

const pad = (n: number) => String(n).padStart(2, "0")
/** Date -> value of an <input type="datetime-local" step="1"> (local time). */
const toLocalInput = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`

/**
 * Add a bookmark (cameraId + at) or edit one (existing). Editing changes note / label / colour only;
 * the time stays where it was recorded.
 */
export function BookmarkDialog({
  open,
  onOpenChange,
  cameraId,
  profile,
  at,
  existing,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  cameraId?: number
  profile?: string
  at?: Date
  existing?: Bookmark
}) {
  const create = useCreateBookmark()
  const update = useUpdateBookmark()
  const [time, setTime] = useState(() => toLocalInput(at ?? new Date()))
  const [duration, setDuration] = useState(0)
  const [note, setNote] = useState(existing?.note ?? "")
  const [label, setLabel] = useState(existing?.label ?? "")
  const [color, setColor] = useState(existing?.color ?? COLORS[0])
  const start = new Date(time)
  const pending = create.isPending || update.isPending
  const valid = note.trim().length > 0 && (!!existing || !Number.isNaN(start.getTime()))

  const save = () => {
    const done = { onSuccess: () => onOpenChange(false) }
    if (existing) {
      update.mutate({ id: existing.id, body: { note: note.trim(), label: label.trim() || null, color } }, done)
    } else if (cameraId != null) {
      create.mutate({
        camera_id: cameraId,
        profile: profile ?? null,
        start_time: start.toISOString(),
        end_time: duration ? new Date(start.getTime() + duration * 1000).toISOString() : null,
        note: note.trim(),
        label: label.trim() || null,
        color,
      }, done)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{existing ? "Edit bookmark" : "Add bookmark"}</DialogTitle>
          <DialogDescription>
            {existing ? fmtDateTime(new Date(existing.start_time)) : "Mark this moment with a note you can search later."}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          {!existing && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label htmlFor="bm-time">Time</Label>
                <Input id="bm-time" type="datetime-local" step={1} value={time} onChange={(e) => setTime(e.target.value)} />
              </div>
              <div className="grid gap-1.5">
                <Label>Length</Label>
                <select className="h-9 rounded-md border bg-background px-3 text-sm" value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}>
                  {DURATIONS.map((d) => <option key={d.seconds} value={d.seconds}>{d.label}</option>)}
                </select>
              </div>
            </div>
          )}
          <div className="grid gap-1.5">
            <Label htmlFor="bm-note">Note</Label>
            <Textarea id="bm-note" autoFocus maxLength={4000} rows={3} value={note} placeholder="What happened?"
              onChange={(e) => setNote(e.target.value)} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="bm-label">Label (optional)</Label>
              <Input id="bm-label" maxLength={64} value={label} placeholder="e.g. vehicle" onChange={(e) => setLabel(e.target.value)} />
            </div>
            <div className="grid gap-1.5">
              <Label>Colour</Label>
              <div className="flex h-9 items-center gap-2">
                {COLORS.map((c) => (
                  <button key={c} type="button" aria-label={`Colour ${c}`} onClick={() => setColor(c)}
                    className={cn("size-6 rounded-full ring-offset-2 ring-offset-background", color === c && "ring-2 ring-foreground")}
                    style={{ background: c }} />
                ))}
              </div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!valid || pending} onClick={save}>
            {pending && <Loader2 className="size-4 animate-spin" />} {existing ? "Save" : "Add bookmark"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

const BOOKMARKS_PER_PAGE = 25

/** Searchable bookmark list: this camera or all cameras, newest first. Clicking one opens it in the player. */
export function BookmarksPanel({ cameraId, onOpen }: { cameraId: number | null; onOpen: (b: Bookmark) => void }) {
  const [scope, setScope] = useState<"camera" | "all">("camera")
  const paged = usePaged({ size: BOOKMARKS_PER_PAGE })
  const [editing, setEditing] = useState<Bookmark | null>(null)
  const [deleting, setDeleting] = useState<Bookmark | null>(null)
  const del = useDeleteBookmark()
  const list = useBookmarks(
    { cameraId: scope === "camera" ? cameraId : undefined, q: paged.query, order: "desc", limit: paged.limit, offset: paged.offset },
    scope === "all" || cameraId != null,
  )
  useClampPage(paged, list.data?.total)
  const rows = list.data?.items ?? []

  return (
    <Card className="gap-2">
      <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <BookmarkIcon className="size-4" /> Bookmarks
          {list.isFetching && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
        </CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-0 flex-1 sm:w-56 sm:flex-none">
            <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input className="pl-8" placeholder="Search notes" value={paged.search} onChange={(e) => paged.setSearch(e.target.value)} />
          </div>
          <ToggleGroup type="single" variant="outline" size="sm" value={scope} onValueChange={(v) => { if (v) { setScope(v as typeof scope); paged.setPage(1) } }}>
            <ToggleGroupItem value="camera" className="px-3">This camera</ToggleGroupItem>
            <ToggleGroupItem value="all" className="px-3">All cameras</ToggleGroupItem>
          </ToggleGroup>
        </div>
      </CardHeader>
      <CardContent className="max-h-80 space-y-1.5 overflow-auto">
        {list.error && <ErrorState error={list.error} />}
        {!list.error && rows.length === 0 && (
          <p className="py-2 text-sm text-muted-foreground">
            {paged.query ? "No bookmarks match." : "No bookmarks yet. Use “Bookmark” above the player to mark a moment."}
          </p>
        )}
        {rows.map((b) => (
          <div key={b.id} className="group flex items-start gap-3 rounded-lg border bg-background/30 p-2.5 hover:bg-accent/40">
            <button type="button" className="flex min-w-0 flex-1 items-start gap-3 text-left" onClick={() => onOpen(b)}
              title="Open in the player">
              <span className="mt-1.5 size-2.5 shrink-0 rounded-full" style={{ background: b.color ?? "var(--primary)" }} />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground tabular-nums">
                  <span>{fmtDateTime(new Date(b.start_time))}</span>
                  {b.end_time && <span>→ {fmtDateTime(new Date(b.end_time)).split(", ").pop()}</span>}
                  {scope === "all" && <span className="font-medium text-foreground/80">{b.camera_name}</span>}
                  {b.label && <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">{b.label}</span>}
                </span>
                <span className="mt-0.5 block break-words text-sm">{b.note}</span>
              </span>
            </button>
            <div className="flex shrink-0 gap-0.5 opacity-100 md:opacity-0 md:group-hover:opacity-100">
              <Button variant="ghost" size="icon" className="size-8" aria-label="Edit bookmark" onClick={() => setEditing(b)}>
                <Pencil className="size-3.5" />
              </Button>
              <Button variant="ghost" size="icon" className="size-8 text-danger hover:text-danger" aria-label="Delete bookmark"
                onClick={() => setDeleting(b)}>
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          </div>
        ))}
      </CardContent>
      {list.data && (
        <Pager className="px-6" page={paged.page} pageSize={paged.pageSize} total={list.data.total} onPage={paged.setPage} />
      )}
      {editing && <BookmarkDialog open existing={editing} onOpenChange={(o) => !o && setEditing(null)} />}
      <ConfirmDialog
        open={deleting != null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete this bookmark?"
        description={deleting?.note}
        confirmLabel="Delete"
        destructive
        onConfirm={() => deleting && del.mutate(deleting.id)}
      />
    </Card>
  )
}
