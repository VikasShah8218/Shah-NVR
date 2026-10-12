import { ArrowLeftRight, History, Play } from "lucide-react"
import { useEffect, useState } from "react"
import { Link } from "react-router"
import { useAssignmentHistory, useAssignments, useRunScheduler } from "@/api/queries"
import type { Assignment } from "@/api/types"
import { EmptyState, ErrorState, Loading, PageHeader } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { timeAgo } from "@/lib/format"
import { fmtDateTime } from "@/lib/time"
import { MoveCameraDialog } from "./MoveCameraDialog"

export function AssignmentsPage() {
  const assignments = useAssignments()
  const run = useRunScheduler()
  const [moving, setMoving] = useState<Assignment | null>(null)
  const [historyFor, setHistoryFor] = useState<Assignment | null>(null)
  const [, tick] = useState(0)
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [])

  return (
    <div>
      <PageHeader
        title="Assignments"
        description="Which media node records each camera. The scheduler places cameras automatically and moves them on failure."
        actions={
          <Button variant="outline" onClick={() => run.mutate(undefined)} disabled={run.isPending}>
            <Play className="size-4" /> Run scheduler now
          </Button>
        }
      />
      {assignments.isLoading && <Loading />}
      {assignments.error && <ErrorState error={assignments.error} />}
      {assignments.data && assignments.data.length === 0 && <EmptyState title="No assignments yet">Add a camera and start a media node.</EmptyState>}
      {assignments.data && assignments.data.length > 0 && (
        <Card className="overflow-hidden py-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">Camera</TableHead>
                <TableHead>Media node</TableHead>
                <TableHead>Generation</TableHead>
                <TableHead>Lease</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead>Updated</TableHead>
                <TableHead className="w-48" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {assignments.data.map((a) => {
                const left = a.lease_expires_at ? Math.round((new Date(a.lease_expires_at).getTime() - Date.now()) / 1000) : null
                return (
                  <TableRow key={a.camera_id}>
                    <TableCell className="pl-4">
                      <Link to={`/cameras/${a.camera_id}`} className="font-medium hover:text-primary">
                        {a.camera_name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      {a.node_id ? (
                        <Link to={`/nodes/${a.node_id}`} className="hover:text-primary">
                          {a.node_name}
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">unassigned</span>
                      )}
                    </TableCell>
                    <TableCell className="tabular-nums">{a.generation}</TableCell>
                    <TableCell className="tabular-nums">
                      {left == null ? "—" : left >= 0 ? `${left}s` : <span className="text-warning">expired</span>}
                    </TableCell>
                    <TableCell>{a.reason ?? "—"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{timeAgo(a.updated_at)}</TableCell>
                    <TableCell className="space-x-1 text-right">
                      <Button variant="ghost" size="sm" onClick={() => setHistoryFor(a)}>
                        <History className="size-4" /> History
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setMoving(a)}>
                        <ArrowLeftRight className="size-4" /> Move
                      </Button>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </Card>
      )}
      {moving && (
        <MoveCameraDialog
          cameraId={moving.camera_id}
          cameraName={moving.camera_name}
          currentNodeId={moving.node_id}
          open
          onOpenChange={(o) => !o && setMoving(null)}
        />
      )}
      <HistorySheet assignment={historyFor} onClose={() => setHistoryFor(null)} />
    </div>
  )
}

function HistorySheet({ assignment, onClose }: { assignment: Assignment | null; onClose: () => void }) {
  const history = useAssignmentHistory(assignment?.camera_id ?? null)
  return (
    <Sheet open={assignment != null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="data-[side=right]:sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Ownership history</SheetTitle>
          <SheetDescription>{assignment?.camera_name}: every move between media nodes.</SheetDescription>
        </SheetHeader>
        <div className="px-4">
          {history.isLoading && <Loading />}
          <ol className="relative space-y-4 border-l pl-5">
            {(history.data ?? []).map((h) => (
              <li key={h.generation}>
                <span className={`absolute -left-1.5 mt-1.5 size-3 rounded-full ${h.ended_at ? "bg-muted-foreground" : "bg-success"}`} />
                <div className="text-sm font-medium">
                  Generation {h.generation} → node {h.node_id ?? "—"} <span className="font-normal text-muted-foreground">({h.reason})</span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {fmtDateTime(new Date(h.started_at))} — {h.ended_at ? fmtDateTime(new Date(h.ended_at)) : "now"}
                </div>
              </li>
            ))}
          </ol>
        </div>
      </SheetContent>
    </Sheet>
  )
}
