import { CalendarClock, Eye, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import { useDeleteSchedule, useSchedules } from "@/api/queries"
import type { RecordingSchedule } from "@/api/types"
import { ConfirmDialog, EmptyState, ErrorState, Loading, PageHeader } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Perm } from "@/lib/auth/permissions"
import { useAuth } from "@/lib/auth/useAuth"
import { blockLabel, DAYS, fmtHHMM, nowText } from "@/lib/schedule"
import { cn } from "@/lib/utils"
import { ScheduleEditor } from "./ScheduleEditor"
import { useSiteNow } from "./useSiteNow"
import { WeekStrip } from "./WeekGrid"

type Open = { kind: "new" } | { kind: "edit" | "view"; schedule: RecordingSchedule } | null

export function SchedulesPage() {
  const manage = useAuth().can(Perm.CAMERAS_MANAGE)
  const schedules = useSchedules()
  const site = useSiteNow()
  const del = useDeleteSchedule()
  const [open, setOpen] = useState<Open>(null)
  const [deleting, setDeleting] = useState<RecordingSchedule | null>(null)
  const list = schedules.data ?? []

  return (
    <div>
      <PageHeader
        title="Recording schedules"
        description={`Weekly plans for when cameras record. Set a camera to a schedule in its Edit form, or a whole group from the Groups page.${
          site.zone ? ` Site time: ${site.zone}${site.now ? `, now ${DAYS[site.now.day]} ${fmtHHMM(site.now.minute)}` : ""}.` : ""}`}
        actions={manage && <Button onClick={() => setOpen({ kind: "new" })}><Plus className="size-4" /> New schedule</Button>}
      />

      {schedules.isLoading ? <Loading /> : schedules.error ? <ErrorState error={schedules.error} /> : list.length === 0 ? (
        <EmptyState icon={CalendarClock} title="No schedules yet">
          Cameras record all the time until you give them a schedule. Create one, e.g. office hours or nights only.
          {manage && <div className="mt-3"><Button onClick={() => setOpen({ kind: "new" })}><Plus className="size-4" /> New schedule</Button></div>}
        </EmptyState>
      ) : (
        <Card className="py-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">Name</TableHead>
                <TableHead className="hidden md:table-cell">Week (Mon–Sun)</TableHead>
                <TableHead>Now</TableHead>
                <TableHead className="text-right">Cameras</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((s) => (
                <TableRow key={s.id} className="cursor-pointer" onClick={() => setOpen({ kind: manage ? "edit" : "view", schedule: s })}>
                  <TableCell className="pl-4">
                    <div className="font-medium">{s.name}</div>
                    <div className="max-w-80 truncate text-xs text-muted-foreground">
                      {s.description || (s.blocks.length ? s.blocks.slice(0, 2).map(blockLabel).join("; ") + (s.blocks.length > 2 ? ` +${s.blocks.length - 2}` : "") : "No blocks (never records)")}
                    </div>
                  </TableCell>
                  <TableCell className="hidden md:table-cell"><WeekStrip blocks={s.blocks} /></TableCell>
                  <TableCell>
                    <span className={cn("inline-flex items-center gap-1.5 text-sm", s.recording_now ? "text-success" : "text-muted-foreground")}>
                      <span className={cn("size-1.5 rounded-full", s.recording_now ? "bg-success" : "bg-muted-foreground")} />
                      {nowText(s.recording_now, s.next_change)}
                    </span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{s.camera_count}</TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label={`${s.name} actions`}><MoreHorizontal /></Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {manage ? (
                          <>
                            <DropdownMenuItem onSelect={() => setOpen({ kind: "edit", schedule: s })}><Pencil /> Edit</DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(s)}><Trash2 /> Delete</DropdownMenuItem>
                          </>
                        ) : (
                          <DropdownMenuItem onSelect={() => setOpen({ kind: "view", schedule: s })}><Eye /> View</DropdownMenuItem>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      {open && (
        <ScheduleEditor
          key={open.kind === "new" ? "new" : open.schedule.id}
          schedule={open.kind === "new" ? undefined : open.schedule}
          readOnly={open.kind === "view"}
          now={site.now}
          onOpenChange={(o) => !o && setOpen(null)}
        />
      )}
      {deleting && (
        <ConfirmDialog
          open
          onOpenChange={(o) => !o && setDeleting(null)}
          title={`Delete "${deleting.name}"?`}
          description={deleting.camera_count
            ? `${deleting.camera_count} camera${deleting.camera_count === 1 ? " uses" : "s use"} this schedule. Move them to another schedule (or Always) first.`
            : "No camera uses this schedule."}
          confirmLabel="Delete"
          destructive
          onConfirm={() => del.mutate(deleting.id)}
        />
      )}
    </div>
  )
}
