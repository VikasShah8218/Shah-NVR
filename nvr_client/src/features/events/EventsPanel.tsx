import { BookmarkPlus, Flag, Loader2, Search, Square, Trash2 } from "lucide-react"
import { useState } from "react"
import { useCreateBookmark, useCreateEvent, useDeleteEvent, useEndEvent, useEvents } from "@/api/queries"
import type { NvrEvent } from "@/api/types"
import { ConfirmDialog, ErrorState } from "@/components/common"
import { Pager } from "@/components/Pager"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useAuth } from "@/lib/auth/useAuth"
import { Perm } from "@/lib/auth/permissions"
import { fmtDateTime } from "@/lib/time"
import { useClampPage, usePaged } from "@/lib/usePaged"
import { cn } from "@/lib/utils"
import { EVENT_TYPE_GROUPS, eventColor, eventText, eventTypeLabel } from "../playback/markers"

const PER_PAGE = 20
type Group = (typeof EVENT_TYPE_GROUPS)[number]["group"]

/** Filter value: "" (all), "group:analytics", or one type. */
const filterParams = (v: string): { type?: string; group?: Group } =>
  v.startsWith("group:") ? { group: v.slice(6) as Group } : v ? { type: v } : {}

/** Analytics details the label does not show (direction). Camera strings: shown as text only. */
export function eventDetails(e: NvrEvent): string | null {
  const d = (e.data ?? {}) as Record<string, unknown>
  return typeof d.direction === "string" ? `Direction: ${d.direction}` : null
}

const duration = (e: NvrEvent) => {
  if (!e.end_time) return "ongoing"
  const s = Math.round((Date.parse(e.end_time) - Date.parse(e.start_time)) / 1000)
  if (s <= 0) return null
  return s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${(s / 3600).toFixed(1)} h`
}

/** "Mark event" (docs/EVENT_RECORDING_PLAN.md §6.5): an operator marks a moment on a camera. In event recording mode
 * the node keeps the video around it. `at` = a playback moment (default: now). */
export function MarkEventButton({ cameraId, at, className, size = "default" }: {
  cameraId: number | null
  at?: Date | null
  className?: string
  size?: "default" | "sm" | "icon-sm"
}) {
  const { can } = useAuth()
  const mark = useCreateEvent()
  if (!can(Perm.BOOKMARKS_EDIT)) return null
  return (
    <Button variant="outline" size={size} className={className} disabled={cameraId == null || mark.isPending}
      title={at ? "Mark an event at the playhead" : "Mark an event now (keeps the video around it in event recording mode)"}
      onClick={() => cameraId != null && mark.mutate({ cameraId, body: { type: "manual", duration_seconds: 0, ongoing: false, ...(at ? { start_time: at.toISOString() } : {}) } })}>
      {mark.isPending ? <Loader2 className="size-4 animate-spin" /> : <Flag className="size-4" />}
      {size !== "icon-sm" && " Mark event"}
    </Button>
  )
}

/** Event list: this camera (playback) or every camera (Events page), newest first, filter by type. */
export function EventsPanel({ cameraId, onOpen, allCameras, className }: {
  cameraId?: number | null
  onOpen: (e: NvrEvent) => void
  /** Events page: no camera scope toggle, always every visible camera */
  allCameras?: boolean
  className?: string
}) {
  const { can } = useAuth()
  const [scope, setScope] = useState<"camera" | "all">(allCameras ? "all" : "camera")
  const [type, setType] = useState("")
  const paged = usePaged({ size: PER_PAGE, sizeKey: allCameras ? "events" : undefined })
  const [deleting, setDeleting] = useState<NvrEvent | null>(null)
  const del = useDeleteEvent()
  const end = useEndEvent()
  const bookmark = useCreateBookmark()
  const list = useEvents(
    { cameraId: scope === "camera" ? cameraId : undefined, ...filterParams(type), q: paged.query, order: "desc",
      limit: paged.limit, offset: paged.offset, refetch: 15_000 },
    scope === "all" || cameraId != null,
  )
  useClampPage(paged, list.data?.total)
  const rows = list.data?.items ?? []

  const saveAsBookmark = (e: NvrEvent) =>
    bookmark.mutate({
      camera_id: e.camera_id,
      start_time: e.start_time,
      end_time: e.end_time && e.end_time !== e.start_time ? e.end_time : null,
      note: eventText(e).slice(0, 500),
      label: "event",
      color: eventColor(e.type),
    })

  return (
    <Card className={cn("gap-2", className)}>
      <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <Flag className="size-4" /> Events
          {list.isFetching && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
        </CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={paged.search} onChange={(ev) => paged.setSearch(ev.target.value)} maxLength={64}
              placeholder="Search rule, object…" aria-label="Search events" className="h-8 w-44 pl-7 text-sm" />
          </div>
          <Select value={type || "all"} onValueChange={(v) => { setType(v === "all" ? "" : v); paged.setPage(1) }}>
            <SelectTrigger size="sm" className="w-44" aria-label="Event type"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              {EVENT_TYPE_GROUPS.map((g) => (
                <SelectGroup key={g.group}>
                  <SelectSeparator />
                  <SelectLabel>{g.title}</SelectLabel>
                  <SelectItem value={`group:${g.group}`}>All {g.title.toLowerCase()}</SelectItem>
                  {g.types.map((t) => <SelectItem key={t} value={t}>{eventTypeLabel(t)}</SelectItem>)}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
          {!allCameras && (
            <ToggleGroup type="single" variant="outline" size="sm" value={scope} onValueChange={(v) => { if (v) { setScope(v as typeof scope); paged.setPage(1) } }}>
              <ToggleGroupItem value="camera" className="px-3">This camera</ToggleGroupItem>
              <ToggleGroupItem value="all" className="px-3">All cameras</ToggleGroupItem>
            </ToggleGroup>
          )}
        </div>
      </CardHeader>
      <CardContent className={cn("space-y-1.5 overflow-auto", !allCameras && "max-h-80")}>
        {list.error && <ErrorState error={list.error} />}
        {!list.error && rows.length === 0 && (
          <p className="py-2 text-sm text-muted-foreground">
            {type || paged.query ? "No matching events." : "No events yet. Use “Mark event”, or wait for a camera event (e.g. video loss)."}
          </p>
        )}
        {rows.map((e) => (
          <div key={e.id} className="group flex items-start gap-3 rounded-lg border bg-background/30 p-2.5 hover:bg-accent/40">
            <button type="button" className="flex min-w-0 flex-1 items-start gap-3 text-left" onClick={() => onOpen(e)}
              title={`Play from ${e.pre_seconds} s before`}>
              <span className="mt-1.5 size-2.5 shrink-0 rounded-full" style={{ background: eventColor(e.type) }} />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground tabular-nums">
                  <span>{fmtDateTime(new Date(e.start_time))}</span>
                  {duration(e) && <span className={cn(!e.end_time && "text-warning")}>{duration(e)}</span>}
                  {(scope === "all" || allCameras) && <span className="font-medium text-foreground/80">{e.camera_name}</span>}
                  <span className="truncate">{e.source}</span>
                </span>
                <span className="mt-0.5 block break-words text-sm">{eventText(e)}</span>
                {eventDetails(e) && <span className="block text-xs text-muted-foreground">{eventDetails(e)}</span>}
              </span>
            </button>
            <div className="flex shrink-0 gap-0.5 opacity-100 md:opacity-0 md:group-hover:opacity-100">
              {can(Perm.BOOKMARKS_EDIT) && !e.end_time && (
                <Button variant="ghost" size="icon" className="size-8" aria-label="End event" title="End this event now"
                  onClick={() => end.mutate(e.id)}>
                  <Square className="size-3.5" />
                </Button>
              )}
              {can(Perm.BOOKMARKS_EDIT) && (
                <Button variant="ghost" size="icon" className="size-8" aria-label="Save as bookmark" title="Save as bookmark"
                  onClick={() => saveAsBookmark(e)}>
                  <BookmarkPlus className="size-3.5" />
                </Button>
              )}
              {can(Perm.CAMERAS_MANAGE) && (
                <Button variant="ghost" size="icon" className="size-8 text-danger hover:text-danger" aria-label="Delete event"
                  onClick={() => setDeleting(e)}>
                  <Trash2 className="size-3.5" />
                </Button>
              )}
            </div>
          </div>
        ))}
      </CardContent>
      {list.data && (
        <Pager className="px-6" page={paged.page} pageSize={paged.pageSize} total={list.data.total} onPage={paged.setPage} />
      )}
      <ConfirmDialog
        open={deleting != null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete this event mark?"
        description="Video already kept for it stays until its retention ends."
        confirmLabel="Delete"
        destructive
        onConfirm={() => deleting && del.mutate(deleting.id)}
      />
    </Card>
  )
}
