import { ArrowLeftRight, History, Play, Search } from "lucide-react"
import { useEffect, useState } from "react"
import { Link } from "react-router"
import { useAssignmentHistory, useAssignments, useRunScheduler } from "@/api/queries"
import type { Assignment } from "@/api/types"
import { EmptyState, ErrorState, Loading, PageHeader } from "@/components/common"
import { Pager } from "@/components/Pager"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { timeAgo } from "@/lib/format"
import { fmtDateTime } from "@/lib/time"
import { useClampPage, usePaged } from "@/lib/usePaged"
import { MoveCameraDialog } from "./MoveCameraDialog"

export function AssignmentsPage() {
  const paged = usePaged({ sizeKey: "assignments" })
  const assignments = useAssignments({ q: paged.query, limit: paged.limit, offset: paged.offset })
  useClampPage(paged, assignments.data?.total)
  const rows = assignments.data?.items ?? []
  const run = useRunScheduler()
  const [moving, setMoving] = useState<Assignment | null>(null)
  const [historyFor, setHistoryFor] = useState<Assignment | null>(null)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  return (
    <div>
      <PageHeader
        title="Assignments"
        description="Which media node records each camera. The scheduler places cameras automatically and moves them on failure."
        actions={
          <>
            <div className="relative w-full sm:w-60">
              <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
              <Input className="pl-8" placeholder="Search cameras" value={paged.search} onChange={(e) => paged.setSearch(e.target.value)} />
            </div>
            <Button variant="outline" onClick={() => run.mutate(undefined)} disabled={run.isPending}>
              <Play className="size-4" /> Run scheduler now
            </Button>
          </>
        }
      />
      {assignments.isLoading && <Loading />}
      {assignments.error && <ErrorState error={assignments.error} />}
      {assignments.data && assignments.data.total === 0 && (paged.query
        ? <EmptyState icon={Search} title="No cameras match">Change the search.</EmptyState>
        : <EmptyState title="No assignments yet">Add a camera and start a media node.</EmptyState>)}
      {rows.length > 0 && (
        <>
        <div className="space-y-2 md:hidden">
          {rows.map((a) => {
            const left = a.lease_expires_at ? Math.round((new Date(a.lease_expires_at).getTime() - now) / 1000) : null
            return <Card key={a.camera_id} className="gap-3 p-4">
              <div><Link to={`/cameras/${a.camera_id}`} className="font-medium hover:text-primary">{a.camera_name}</Link><div className="mt-1 text-xs text-muted-foreground">Generation {a.generation} · updated {timeAgo(a.updated_at)}</div></div>
              <div className="grid grid-cols-2 gap-3 border-y py-3 text-sm">
                <div><div className="text-xs text-muted-foreground">Media node</div>{a.node_id ? <Link to={`/nodes/${a.node_id}`} className="hover:text-primary">{a.node_name}</Link> : "Unassigned"}</div>
                <div><div className="text-xs text-muted-foreground">Lease</div>{left == null ? "—" : left >= 0 ? `${left}s` : <span className="text-warning">Expired</span>}</div>
                <div className="col-span-2"><div className="text-xs text-muted-foreground">Reason</div>{a.reason ?? "—"}</div>
              </div>
              <div className="grid grid-cols-2 gap-2"><Button variant="outline" className="min-h-11" onClick={() => setHistoryFor(a)}><History className="size-4" /> History</Button><Button className="min-h-11" onClick={() => setMoving(a)}><ArrowLeftRight className="size-4" /> Move</Button></div>
            </Card>
          })}
        </div>
        <Card className="hidden overflow-hidden py-0 md:block">
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
              {rows.map((a) => {
                const left = a.lease_expires_at ? Math.round((new Date(a.lease_expires_at).getTime() - now) / 1000) : null
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
        </>
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
      {assignments.data && (
        <Pager className="mt-3" page={paged.page} pageSize={paged.pageSize} total={assignments.data.total}
          onPage={paged.setPage} onPageSize={paged.setPageSize} />
      )}
      <HistorySheet assignment={historyFor} onClose={() => setHistoryFor(null)} />
    </div>
  )
}

const HISTORY_PER_PAGE = 20

function HistorySheet({ assignment, onClose }: { assignment: Assignment | null; onClose: () => void }) {
  const [page, setPage] = useState(1)
  useEffect(() => setPage(1), [assignment?.camera_id])
  const history = useAssignmentHistory(assignment?.camera_id ?? null, { limit: HISTORY_PER_PAGE, offset: (page - 1) * HISTORY_PER_PAGE })
  return (
    <Sheet open={assignment != null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full data-[side=right]:max-w-full data-[side=right]:sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Ownership history</SheetTitle>
          <SheetDescription>{assignment?.camera_name}: every move between media nodes.</SheetDescription>
        </SheetHeader>
        <div className="px-4">
          {history.isLoading && <Loading />}
          <ol className="relative space-y-4 border-l pl-5">
            {(history.data?.items ?? []).map((h) => (
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
          {history.data && <Pager className="mt-4" page={page} pageSize={HISTORY_PER_PAGE} total={history.data.total} onPage={setPage} />}
        </div>
      </SheetContent>
    </Sheet>
  )
}
