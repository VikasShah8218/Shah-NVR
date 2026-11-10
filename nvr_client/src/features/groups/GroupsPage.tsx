import {
  ChevronRight,
  Folder,
  FolderPlus,
  FolderTree,
  Inbox,
  Loader2,
  MoreHorizontal,
  MoveRight,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react"
import { useEffect, useState } from "react"
import { Link, useSearchParams } from "react-router"
import { ApiError } from "@/api/client"
import { type CameraScope, useAssignCameras, useCameraOptionsPage, useGroup, useGroupPage } from "@/api/queries"
import type { CameraGroup } from "@/api/types"
import { EmptyState, ErrorState, Loading, PageHeader } from "@/components/common"
import { GroupPicker } from "@/components/GroupPicker"
import { Pager } from "@/components/Pager"
import { StatusDot } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { revealKeys } from "@/lib/groupTree"
import { useClampPage, usePaged } from "@/lib/usePaged"
import { cn } from "@/lib/utils"
import { AddCamerasDialog, DeleteGroupDialog, GroupFormDialog, MoveGroupDialog } from "./GroupDialogs"
import { GroupTree } from "./GroupTree"
import { useTreeExpanded } from "./useTreeExpanded"

/** Selection: ?group=<id>, ?group=ungrouped, or nothing (the top level). Links from the Live page use it too. */
type Selection = { kind: "root" } | { kind: "ungrouped" } | { kind: "group"; id: number }

function readSelection(raw: string | null): Selection {
  if (raw === "ungrouped") return { kind: "ungrouped" }
  const id = Number(raw)
  return raw && Number.isInteger(id) && id > 0 ? { kind: "group", id } : { kind: "root" }
}

type Dialogs =
  | { kind: "create"; parentId: number | null }
  | { kind: "edit"; group: CameraGroup }
  | { kind: "move"; group: CameraGroup; parentId?: number | null }
  | { kind: "delete"; group: CameraGroup }
  | { kind: "add"; group: CameraGroup }
  | null

export function GroupsPage() {
  const [params, setParams] = useSearchParams()
  const selection = readSelection(params.get("group"))
  const select = (s: Selection) => setParams(s.kind === "root" ? {} : { group: s.kind === "ungrouped" ? "ungrouped" : String(s.id) }, { replace: true })
  const expanded = useTreeExpanded("shah-nvr.groups.manage.expanded")
  const [dialog, setDialog] = useState<Dialogs>(null)
  const close = () => setDialog(null)

  // Opened by link (?group=17): expand the tree down to it once it is known.
  const linked = useGroup(selection.kind === "group" ? selection.id : null)
  const linkedPath = linked.data?.path
  const { open: openKeys } = expanded
  useEffect(() => {
    if (linkedPath) openKeys(revealKeys(linkedPath))
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per linked group
  }, [linkedPath])

  const actions = (g: CameraGroup) => (
    <GroupMenu group={g} onDialog={setDialog} />
  )

  return (
    <div>
      <PageHeader
        title="Groups"
        description="Organise cameras in a tree (region › site › …). A camera sits in one group or none. The Live page shows this tree."
        actions={<Button onClick={() => setDialog({ kind: "create", parentId: null })}><FolderPlus className="size-4" /> New group</Button>}
      />
      <div className="grid gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <Card className="gap-0 py-2 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-9rem)] lg:overflow-y-auto">
          <div className="px-2">
            <button type="button" onClick={() => select({ kind: "root" })}
              className={cn("flex min-h-8 w-full items-center gap-2 rounded-md px-2 text-sm hover:bg-accent",
                selection.kind === "root" && "bg-accent font-medium")}>
              <FolderTree className="size-4 text-muted-foreground" /> All groups
            </button>
            <GroupTree
              expanded={expanded}
              showUngrouped
              selectedGroupId={selection.kind === "group" ? selection.id : null}
              ungroupedSelected={selection.kind === "ungrouped"}
              onSelectGroup={(g) => select({ kind: "group", id: g.id })}
              onSelectUngrouped={() => select({ kind: "ungrouped" })}
              groupActions={actions}
              dragGroups
              onDropGroup={(draggedId, target) => setDialog({ kind: "move", group: { id: draggedId } as CameraGroup, parentId: target.id })}
              emptyText="No groups yet."
            />
          </div>
        </Card>
        <div className="min-w-0">
          {selection.kind === "group" ? (
            <GroupPanel groupId={selection.id} onSelect={select} onDialog={setDialog} />
          ) : selection.kind === "ungrouped" ? (
            <UngroupedPanel />
          ) : (
            <RootPanel onSelect={select} onDialog={setDialog} />
          )}
        </div>
      </div>

      {dialog?.kind === "create" && (
        <GroupFormDialog open onOpenChange={close} parentId={dialog.parentId}
          onDone={(g) => {
            if (dialog.parentId != null) expanded.open([String(dialog.parentId)])
            select({ kind: "group", id: g.id })
          }} />
      )}
      {dialog?.kind === "edit" && <GroupFormDialog open onOpenChange={close} group={dialog.group} />}
      {dialog?.kind === "move" && <MoveDialogLoader groupId={dialog.group.id} parentId={dialog.parentId} onClose={close} />}
      {dialog?.kind === "delete" && (
        <DeleteGroupDialog group={dialog.group} onOpenChange={close}
          onDeleted={() => {
            if (selection.kind === "group" && selection.id === dialog.group.id) {
              select(dialog.group.parent_id != null ? { kind: "group", id: dialog.group.parent_id } : { kind: "root" })
            }
          }} />
      )}
      {dialog?.kind === "add" && <AddCamerasDialog group={dialog.group} onOpenChange={close} />}
    </div>
  )
}

/** A dragged group arrives as an id only: load it before showing the move dialog. */
function MoveDialogLoader({ groupId, parentId, onClose }: { groupId: number; parentId?: number | null; onClose: () => void }) {
  const g = useGroup(groupId)
  if (!g.data) return null
  return <MoveGroupDialog group={g.data} initialParentId={parentId} onOpenChange={(o) => !o && onClose()} />
}

function GroupMenu({ group, onDialog }: { group: CameraGroup; onDialog: (d: Dialogs) => void }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={`${group.name} actions`}><MoreHorizontal /></Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => onDialog({ kind: "add", group })}><Plus /> Add cameras</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onDialog({ kind: "create", parentId: group.id })}><FolderPlus /> New sub-group</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onDialog({ kind: "edit", group })}><Pencil /> Rename</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onDialog({ kind: "move", group })}><MoveRight /> Move…</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={() => onDialog({ kind: "delete", group })}><Trash2 /> Delete</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

// ---------------------------------------------------------------- right panels

function RootPanel({ onSelect, onDialog }: { onSelect: (s: Selection) => void; onDialog: (d: Dialogs) => void }) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">All groups</h2>
        <p className="text-sm text-muted-foreground">Top-level groups. Select a group to see its sub-groups and cameras.</p>
      </div>
      <SubGroupsTable parentId={null} onSelect={onSelect} onDialog={onDialog}
        empty={<EmptyState icon={FolderTree} title="No groups yet">
          Create top-level groups (e.g. Anantnag, Jammu, Ramban), then sub-groups inside them, then add cameras.
          <div className="mt-3"><Button onClick={() => onDialog({ kind: "create", parentId: null })}><FolderPlus className="size-4" /> New group</Button></div>
        </EmptyState>} />
    </div>
  )
}

function UngroupedPanel() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold"><Inbox className="size-5 text-muted-foreground" /> Ungrouped cameras</h2>
        <p className="text-sm text-muted-foreground">Cameras in no group. Select some and move them into a group.</p>
      </div>
      <CamerasTable scope={{ ungrouped: true }} groupId={null} />
    </div>
  )
}

function GroupPanel({ groupId, onSelect, onDialog }: { groupId: number; onSelect: (s: Selection) => void; onDialog: (d: Dialogs) => void }) {
  const q = useGroup(groupId)
  if (q.isLoading) return <Loading />
  if (q.error) {
    return q.error instanceof ApiError && q.error.status === 404
      ? <EmptyState icon={Folder} title="Group not found">It was deleted. <Button variant="link" onClick={() => onSelect({ kind: "root" })}>Back to all groups</Button></EmptyState>
      : <ErrorState error={q.error} />
  }
  const g = q.data!
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <nav className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
          <button type="button" className="hover:text-foreground" onClick={() => onSelect({ kind: "root" })}>All groups</button>
          {g.breadcrumb.map((b) => (
            <span key={b.id} className="flex items-center gap-1">
              <ChevronRight className="size-3" />
              <button type="button" className="hover:text-foreground" onClick={() => onSelect({ kind: "group", id: b.id })}>{b.name}</button>
            </span>
          ))}
        </nav>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-lg font-semibold"><Folder className="size-5 text-primary/80" /> <span className="truncate">{g.name}</span></h2>
            {g.description && <p className="mt-0.5 text-sm text-muted-foreground">{g.description}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => onDialog({ kind: "add", group: g })}><Plus className="size-4" /> Add cameras</Button>
            <Button size="sm" variant="outline" onClick={() => onDialog({ kind: "create", parentId: g.id })}><FolderPlus className="size-4" /> Sub-group</Button>
            <Button size="sm" variant="outline" onClick={() => onDialog({ kind: "edit", group: g })}><Pencil className="size-4" /> Edit</Button>
            <Button size="sm" variant="outline" onClick={() => onDialog({ kind: "move", group: g })}><MoveRight className="size-4" /> Move</Button>
            <Button size="sm" variant="outline" className="text-danger" onClick={() => onDialog({ kind: "delete", group: g })}><Trash2 className="size-4" /> Delete</Button>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <Stat label="Sub-groups" value={g.child_groups} />
          <Stat label="Cameras here" value={g.cameras_direct} />
          <Stat label="Cameras in total" value={g.cameras_total} />
          <Stat label="Online" value={`${g.online_total} / ${g.cameras_total}`} warn={g.online_total < g.cameras_total} />
        </div>
      </div>

      {g.child_groups > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-medium">Sub-groups</h3>
          <SubGroupsTable parentId={g.id} onSelect={onSelect} onDialog={onDialog} />
        </section>
      )}
      <section className="space-y-2">
        <h3 className="text-sm font-medium">Cameras in this group</h3>
        <CamerasTable key={g.id} scope={{ groupId: g.id }} groupId={g.id}
          empty={<EmptyState title="No cameras directly in this group">
            {g.cameras_total > 0 ? `Its sub-groups hold ${g.cameras_total}. ` : ""}
            <Button variant="link" className="px-0" onClick={() => onDialog({ kind: "add", group: g })}>Add cameras</Button>
          </EmptyState>} />
      </section>
    </div>
  )
}

function Stat({ label, value, warn }: { label: string; value: number | string; warn?: boolean }) {
  return (
    <span className="rounded-md border bg-card px-2.5 py-1">
      <span className="text-muted-foreground">{label}</span>{" "}
      <span className={cn("font-medium tabular-nums", warn && "text-amber-500")}>{value}</span>
    </span>
  )
}

function SubGroupsTable({ parentId, onSelect, onDialog, empty }: {
  parentId: number | null
  onSelect: (s: Selection) => void
  onDialog: (d: Dialogs) => void
  empty?: React.ReactNode
}) {
  const paged = usePaged({ sizeKey: "groups.sub", size: 25 })
  const q = useGroupPage(parentId, paged.limit, paged.offset)
  useClampPage(paged, q.data?.total)
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorState error={q.error} />
  if (q.data!.total === 0) return <>{empty ?? null}</>
  return (
    <>
      <Card className="overflow-hidden py-0">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-4">Name</TableHead>
              <TableHead className="text-right">Sub-groups</TableHead>
              <TableHead className="text-right">Cameras</TableHead>
              <TableHead className="text-right">Online</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {q.data!.items.map((g) => (
              <TableRow key={g.id} className="cursor-pointer" onClick={() => onSelect({ kind: "group", id: g.id })}>
                <TableCell className="pl-4">
                  <span className="flex items-center gap-2 font-medium"><Folder className="size-4 text-primary/80" /> {g.name}</span>
                </TableCell>
                <TableCell className="text-right tabular-nums">{g.child_groups}</TableCell>
                <TableCell className="text-right tabular-nums">{g.cameras_total}</TableCell>
                <TableCell className={cn("text-right tabular-nums", g.online_total < g.cameras_total && "text-amber-500")}>
                  {g.cameras_total ? `${g.online_total} / ${g.cameras_total}` : "—"}
                </TableCell>
                <TableCell onClick={(e) => e.stopPropagation()}><GroupMenu group={g} onDialog={onDialog} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
      <Pager page={paged.page} pageSize={paged.pageSize} total={q.data!.total} onPage={paged.setPage} onPageSize={paged.setPageSize} />
    </>
  )
}

/** Cameras of a group (or ungrouped): paged, searchable, with selection and bulk move / remove. */
function CamerasTable({ scope, groupId, empty }: { scope: CameraScope; groupId: number | null; empty?: React.ReactNode }) {
  const paged = usePaged({ sizeKey: "groups.cameras", size: 25 })
  const q = useCameraOptionsPage({ q: paged.query, scope, limit: paged.limit, offset: paged.offset })
  useClampPage(paged, q.data?.total)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [moveOpen, setMoveOpen] = useState(false)
  const assign = useAssignCameras()
  const rows = q.data?.items ?? []
  const allOnPage = rows.length > 0 && rows.every((c) => selected.has(c.id))
  const toggle = (id: number) => setSelected((s) => {
    const next = new Set(s)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
  const togglePage = () => setSelected((s) => {
    const next = new Set(s)
    rows.forEach((c) => (allOnPage ? next.delete(c.id) : next.add(c.id)))
    return next
  })
  const move = (target: number | null) => {
    assign.mutate({ cameraIds: [...selected].slice(0, 500), groupId: target }, { onSuccess: () => setSelected(new Set()) })
    setMoveOpen(false)
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
          <Input className="pl-8" placeholder="Search cameras" value={paged.search} onChange={(e) => paged.setSearch(e.target.value)} />
        </div>
        {selected.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border bg-accent/40 px-2 py-1 text-sm">
            <span className="tabular-nums">{selected.size} selected</span>
            <Popover open={moveOpen} onOpenChange={setMoveOpen}>
              <PopoverTrigger asChild>
                <Button size="sm" variant="outline" disabled={assign.isPending}><MoveRight className="size-4" /> Move to…</Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-80 p-3">
                <div className="mb-2 text-sm font-medium">Move {selected.size} camera{selected.size === 1 ? "" : "s"} to</div>
                <GroupPicker className="w-full" value={null} placeholder="Choose a group"
                  isDisabled={(g) => g.id === groupId} onChange={(id) => id != null && move(id)} />
              </PopoverContent>
            </Popover>
            {groupId != null && (
              <Button size="sm" variant="outline" disabled={assign.isPending} onClick={() => move(null)}>
                <X className="size-4" /> Remove from group
              </Button>
            )}
            {assign.isPending && <Loader2 className="size-4 animate-spin" />}
            <button type="button" className="text-xs text-muted-foreground underline" onClick={() => setSelected(new Set())}>clear</button>
          </div>
        )}
      </div>
      {q.isLoading && <Loading />}
      {q.error && <ErrorState error={q.error} />}
      {q.data && q.data.total === 0 && (paged.query
        ? <EmptyState icon={Search} title="No cameras match">Change the search.</EmptyState>
        : empty ?? <EmptyState title="No ungrouped cameras">Every camera is in a group.</EmptyState>)}
      {rows.length > 0 && (
        <Card className="overflow-hidden py-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-10 pl-4">
                  <input type="checkbox" aria-label="Select page" className="size-4 accent-primary" checked={allOnPage} onChange={togglePage} />
                </TableHead>
                <TableHead>Camera</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">#</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((c) => (
                <TableRow key={c.id} data-state={selected.has(c.id) ? "selected" : undefined}>
                  <TableCell className="pl-4">
                    <input type="checkbox" aria-label={`Select ${c.name}`} className="size-4 accent-primary"
                      checked={selected.has(c.id)} onChange={() => toggle(c.id)} />
                  </TableCell>
                  <TableCell>
                    <Link to={`/cameras/${c.id}`} className="font-medium hover:text-primary">{c.name}</Link>
                  </TableCell>
                  <TableCell>
                    <span className="flex items-center gap-2 text-xs text-muted-foreground"><StatusDot status={c.status} /> {c.status.toLowerCase().replace("_", " ")}</span>
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums text-muted-foreground">{c.id}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
      {q.data && <Pager page={paged.page} pageSize={paged.pageSize} total={q.data.total} onPage={paged.setPage} onPageSize={paged.setPageSize} />}
    </div>
  )
}
