import { Search } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router"
import { useAudit } from "@/api/queries"
import { EmptyState, ErrorState, Loading, PageHeader } from "@/components/common"
import { Pager } from "@/components/Pager"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { fmtDateTime } from "@/lib/time"
import { useClampPage, usePaged } from "@/lib/usePaged"

/** Who did what, when (docs/AUTH_INTEGRATION_PLAN.md §7.7): sign-ins, live / playback opens, exports, changes. */

const ACTIONS: { value: string; label: string }[] = [
  { value: "all", label: "All actions" },
  { value: "auth", label: "Sign-in / out" },
  { value: "live", label: "Live view" },
  { value: "playback", label: "Playback" },
  { value: "export", label: "Exports" },
  { value: "cameras", label: "Cameras" },
  { value: "groups", label: "Groups" },
  { value: "nodes", label: "Media nodes" },
  { value: "assignments", label: "Assignments" },
  { value: "access", label: "Access" },
]

const STATUS_TONE: Record<string, "default" | "secondary" | "destructive" | "outline"> = { ok: "secondary", denied: "destructive", failed: "outline" }

export function AuditPage() {
  const paged = usePaged({ sizeKey: "audit", size: 50 })
  const [action, setAction] = useState("all")
  const [status, setStatus] = useState("any")
  const q = useAudit({
    username: paged.query, action: action === "all" ? undefined : action,
    status: status === "any" ? undefined : (status as "ok" | "denied" | "failed"),
    limit: paged.limit, offset: paged.offset,
  })
  useClampPage(paged, q.data?.total)
  const rows = q.data?.items ?? []

  return (
    <div>
      <PageHeader
        title="Audit log"
        description="Sign-ins, live and playback views, exports and every change, newest first."
        actions={
          <>
            <div className="relative w-full sm:w-52">
              <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
              <Input className="pl-8" placeholder="User" value={paged.search} onChange={(e) => paged.setSearch(e.target.value)} />
            </div>
            <Select value={action} onValueChange={(v) => { setAction(v); paged.setPage(1) }}>
              <SelectTrigger className="w-full sm:w-44" aria-label="Action"><SelectValue /></SelectTrigger>
              <SelectContent>{ACTIONS.map((a) => <SelectItem key={a.value} value={a.value}>{a.label}</SelectItem>)}</SelectContent>
            </Select>
            <Select value={status} onValueChange={(v) => { setStatus(v); paged.setPage(1) }}>
              <SelectTrigger className="w-full sm:w-32" aria-label="Result"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="any">Any result</SelectItem>
                <SelectItem value="ok">OK</SelectItem>
                <SelectItem value="denied">Denied</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
              </SelectContent>
            </Select>
          </>
        }
      />
      {q.isLoading && <Loading />}
      {q.error && <ErrorState error={q.error} />}
      {q.data && q.data.total === 0 && <EmptyState title="No events">Nothing matches these filters.</EmptyState>}
      {rows.length > 0 && (
        <Card className="overflow-hidden py-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">Time</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Camera</TableHead>
                <TableHead>Result</TableHead>
                <TableHead>Request</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="pl-4 text-xs whitespace-nowrap tabular-nums">{fmtDateTime(new Date(e.at))}</TableCell>
                  <TableCell className="font-medium">{e.username}</TableCell>
                  <TableCell><code className="text-xs">{e.action}</code></TableCell>
                  <TableCell>
                    {e.camera_id != null ? <Link to={`/cameras/${e.camera_id}`} className="text-xs hover:text-primary">#{e.camera_id}</Link> : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell>
                    <Badge variant={STATUS_TONE[e.status] ?? "outline"}>{e.status}</Badge>
                    {e.detail && typeof e.detail === "object" && "http_status" in e.detail && (
                      <span className="ml-1 text-xs text-muted-foreground">HTTP {String(e.detail.http_status)}</span>
                    )}
                  </TableCell>
                  <TableCell className="max-w-80 truncate text-xs text-muted-foreground" title={`${e.method ?? ""} ${e.path}`}>
                    {e.method} {e.path}{e.ip ? ` · ${e.ip}` : ""}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
      {q.data && <Pager className="mt-3" page={paged.page} pageSize={paged.pageSize} total={q.data.total} onPage={paged.setPage} onPageSize={paged.setPageSize} />}
    </div>
  )
}
