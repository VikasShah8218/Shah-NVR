import { Folder, Loader2, Search } from "lucide-react"
import { useState } from "react"
import { useAssignCameras, useCameraOptionsPage, useCreateGroup, useDeleteGroup, useGroup, useUpdateGroup } from "@/api/queries"
import type { CameraGroup, GroupDetail } from "@/api/types"
import { ConfirmDialog, ErrorState } from "@/components/common"
import { GroupPicker } from "@/components/GroupPicker"
import { Pager } from "@/components/Pager"
import { StatusDot } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { isInSubtree } from "@/lib/groupTree"
import { usePaged } from "@/lib/usePaged"

type GroupLike = Pick<CameraGroup, "id" | "name" | "path" | "path_label" | "parent_id"> & Partial<CameraGroup>

/** Create a group (under `parentId`, or at the top level) or edit an existing one's name / description. */
export function GroupFormDialog({
  open,
  onOpenChange,
  parentId = null,
  group,
  onDone,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  parentId?: number | null
  group?: GroupLike | null
  onDone?: (g: GroupDetail) => void
}) {
  const create = useCreateGroup()
  const update = useUpdateGroup()
  const parent = useGroup(group ? null : parentId)
  const [name, setName] = useState(group?.name ?? "")
  const [description, setDescription] = useState(group?.description ?? "")
  const busy = create.isPending || update.isPending
  const submit = async () => {
    const body = { name: name.trim(), description: description.trim() || null }
    const g = group
      ? await update.mutateAsync({ id: group.id, body })
      : await create.mutateAsync({ ...body, parent_id: parentId })
    onDone?.(g)
    onOpenChange(false)
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{group ? "Edit group" : parentId != null ? "New sub-group" : "New group"}</DialogTitle>
          <DialogDescription>
            {group ? group.path_label : parentId != null ? `Inside ${parent.data?.path_label ?? "…"}` : "A top-level group, e.g. a district or region."}
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void submit().catch(() => undefined) }}>
          <div className="space-y-1.5">
            <Label htmlFor="group-name">Name</Label>
            <Input id="group-name" autoFocus maxLength={128} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Anantnag" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="group-desc">Description <span className="text-muted-foreground">(optional)</span></Label>
            <Textarea id="group-desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !name.trim()}>
              {busy && <Loader2 className="size-4 animate-spin" />} {group ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Move a group (with its whole subtree) under another group or to the top level. */
export function MoveGroupDialog({
  group,
  initialParentId,
  onOpenChange,
}: {
  group: GroupLike | null
  /** preset target (drag and drop in the tree); undefined = current parent */
  initialParentId?: number | null
  onOpenChange: (open: boolean) => void
}) {
  const update = useUpdateGroup()
  const [target, setTarget] = useState<number | null>(initialParentId !== undefined ? initialParentId : group?.parent_id ?? null)
  const targetGroup = useGroup(target)
  if (!group) return null
  const unchanged = target === group.parent_id
  const result = `${target == null ? "" : `${targetGroup.data?.path_label ?? "…"} › `}${group.name}`
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Move "{group.name}"</DialogTitle>
          <DialogDescription>Its sub-groups and cameras move with it.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>New parent</Label>
            <GroupPicker className="w-full" value={target} onChange={(id) => setTarget(id)} noneLabel="Top level"
              isDisabled={(g) => isInSubtree(g.path, group.path)} />
          </div>
          <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
            <Folder className="size-4 shrink-0 text-primary/80" />
            <span className="min-w-0 truncate">{result}</span>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={unchanged || update.isPending}
            onClick={() => update.mutate({ id: group.id, body: { parent_id: target } }, { onSuccess: () => onOpenChange(false) })}>
            {update.isPending && <Loader2 className="size-4 animate-spin" />} Move
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Delete: an empty group goes at once; a non-empty one only with "move its contents up one level" (D3). */
export function DeleteGroupDialog({
  group,
  onOpenChange,
  onDeleted,
}: {
  group: CameraGroup | null
  onOpenChange: (open: boolean) => void
  onDeleted?: () => void
}) {
  const del = useDeleteGroup()
  if (!group) return null
  const empty = group.child_groups === 0 && group.cameras_direct === 0
  const where = group.parent_id == null ? "the top level / Ungrouped" : "the parent group"
  return (
    <ConfirmDialog
      open
      onOpenChange={onOpenChange}
      title={`Delete "${group.name}"?`}
      destructive
      confirmLabel={empty ? "Delete" : "Move contents up & delete"}
      description={empty
        ? "The group is empty."
        : `It holds ${group.child_groups} sub-group${group.child_groups === 1 ? "" : "s"} and ${group.cameras_direct} camera${group.cameras_direct === 1 ? "" : "s"}. They move to ${where}; no camera or recording is deleted.`}
      onConfirm={() => del.mutate({ id: group.id, moveChildren: !empty }, { onSuccess: () => onDeleted?.() })}
    />
  )
}

const MAX_PICK = 500

/** Pick cameras (paged, searchable; "Ungrouped only" by default) and move them into `group`. */
export function AddCamerasDialog({ group, onOpenChange }: { group: GroupLike | null; onOpenChange: (open: boolean) => void }) {
  const paged = usePaged({ size: 25 })
  const [onlyUngrouped, setOnlyUngrouped] = useState(true)
  const [picked, setPicked] = useState<Map<number, string>>(new Map())
  const assign = useAssignCameras()
  const list = useCameraOptionsPage({
    q: paged.query, scope: onlyUngrouped ? { ungrouped: true } : {}, limit: paged.limit, offset: paged.offset,
  })
  if (!group) return null
  const rows = list.data?.items ?? []
  const toggle = (id: number, name: string) => setPicked((m) => {
    const next = new Map(m)
    if (next.has(id)) next.delete(id)
    else if (next.size < MAX_PICK) next.set(id, name)
    return next
  })
  const selectable = rows.filter((c) => c.group_id !== group.id)
  const allOnPage = selectable.length > 0 && selectable.every((c) => picked.has(c.id))
  const togglePage = () => setPicked((m) => {
    const next = new Map(m)
    for (const c of selectable) {
      if (allOnPage) next.delete(c.id)
      else if (next.size < MAX_PICK) next.set(c.id, c.name)
    }
    return next
  })
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90dvh] flex-col sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add cameras to "{group.name}"</DialogTitle>
          <DialogDescription>{group.path_label}. A camera is in one group at a time: cameras from another group are moved.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-0 flex-1">
            <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input className="pl-8" placeholder="Search name or #id" value={paged.search} onChange={(e) => paged.setSearch(e.target.value)} />
          </div>
          <ToggleGroup type="single" variant="outline" size="sm" value={onlyUngrouped ? "ungrouped" : "all"}
            onValueChange={(v) => { if (v) { setOnlyUngrouped(v === "ungrouped"); paged.setPage(1) } }}>
            <ToggleGroupItem value="ungrouped" className="px-3">Ungrouped</ToggleGroupItem>
            <ToggleGroupItem value="all" className="px-3">All</ToggleGroupItem>
          </ToggleGroup>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto rounded-md border">
          {list.error && <ErrorState error={list.error} className="m-2" />}
          {rows.length > 0 && (
            <label className="flex items-center gap-2.5 border-b px-3 py-2 text-xs text-muted-foreground">
              <input type="checkbox" className="size-4 accent-primary" checked={allOnPage} onChange={togglePage} disabled={selectable.length === 0} />
              Select this page
            </label>
          )}
          {rows.map((c) => {
            const here = c.group_id === group.id
            return (
              <label key={c.id} className="flex cursor-pointer items-center gap-2.5 px-3 py-1.5 text-sm hover:bg-accent has-[:disabled]:cursor-default has-[:disabled]:opacity-50">
                <input type="checkbox" className="size-4 accent-primary" disabled={here} checked={here || picked.has(c.id)} onChange={() => toggle(c.id, c.name)} />
                <StatusDot status={c.status} />
                <span className="min-w-0 flex-1 truncate">{c.name}</span>
                <span className="max-w-[45%] truncate text-xs text-muted-foreground">{here ? "already here" : c.group_path ?? ""}</span>
              </label>
            )
          })}
          {list.isLoading && <div className="flex justify-center p-4"><Loader2 className="size-4 animate-spin" /></div>}
          {list.data?.total === 0 && (
            <div className="p-4 text-sm text-muted-foreground">
              {paged.query ? "No cameras match." : onlyUngrouped ? "Every camera is already in a group. Choose “All” to move cameras from other groups." : "No cameras."}
            </div>
          )}
        </div>
        {list.data && <Pager page={paged.page} pageSize={paged.pageSize} total={list.data.total} onPage={paged.setPage} />}
        <DialogFooter className="items-center gap-2 sm:justify-between">
          <span className="text-xs text-muted-foreground">
            {picked.size} selected{picked.size >= MAX_PICK ? ` (max ${MAX_PICK} at a time)` : ""}
            {picked.size > 0 && <button type="button" className="ml-2 underline" onClick={() => setPicked(new Map())}>clear</button>}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button disabled={picked.size === 0 || assign.isPending}
              onClick={() => assign.mutate({ cameraIds: [...picked.keys()], groupId: group.id }, { onSuccess: () => onOpenChange(false) })}>
              {assign.isPending && <Loader2 className="size-4 animate-spin" />} Add {picked.size || ""} camera{picked.size === 1 ? "" : "s"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
