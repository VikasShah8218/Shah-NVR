import { ChevronRight, Folder, FolderOpen, Inbox, Loader2 } from "lucide-react"
import { type ReactNode, useState } from "react"
import { type CameraScope, useCameraOptions, useGroupChildren } from "@/api/queries"
import type { CameraGroup, CameraOption } from "@/api/types"
import { ErrorState } from "@/components/common"
import { StatusDot } from "@/components/StatusBadge"
import { countLabel, UNGROUPED } from "@/lib/groupTree"
import { cn } from "@/lib/utils"
import type { TreeExpanded } from "./useTreeExpanded"

/** Lazy camera-group tree (docs/GROUPING_PLAN.md). Each expanded group asks the server for its own direct
 *  sub-groups and cameras, 50 at a time ("Load more"); collapsed groups cost nothing and do not poll. */

export interface GroupTreeProps {
  expanded: TreeExpanded
  /** live tree: groups and their cameras; management / pickers: groups only */
  showCameras?: boolean
  /** add the virtual "Ungrouped" node (cameras in no group) after the top-level groups */
  showUngrouped?: boolean
  /** "35/38" online of total (live) or just the total */
  countMode?: "online" | "total"
  selectedGroupId?: number | null
  ungroupedSelected?: boolean
  /** clicking a group row selects it (management, pickers); without it a click expands / collapses */
  onSelectGroup?: (g: CameraGroup) => void
  onSelectUngrouped?: () => void
  onPickCamera?: (c: CameraOption) => void
  isGroupDisabled?: (g: CameraGroup) => boolean
  /** trailing buttons of a group row (shown on hover) */
  groupActions?: (g: CameraGroup) => ReactNode
  /** show the group actions all the time (touch), not only on hover */
  actionsVisible?: boolean
  /** trailing badge of a camera row (e.g. "on view") */
  cameraBadge?: (c: CameraOption) => ReactNode
  /** groups can be dragged ("text/group-id"): onto the live grid, or onto another group to move it */
  dragGroups?: boolean
  onDropGroup?: (draggedId: number, target: CameraGroup) => void
  /** cameras can be dragged onto the live grid ("text/camera-id") */
  dragCameras?: boolean
  emptyText?: ReactNode
}

const indent = (depth: number) => ({ paddingLeft: `${depth * 14 + 4}px` })

export function GroupTree(props: GroupTreeProps) {
  return (
    <div role="tree" className="space-y-px">
      <GroupLevel parentId={null} depth={0} props={props} />
      {props.showUngrouped && <UngroupedNode props={props} />}
    </div>
  )
}

function GroupLevel({ parentId, depth, props }: { parentId: number | null; depth: number; props: GroupTreeProps }) {
  const q = useGroupChildren(parentId)
  const rows = q.data?.pages.flatMap((p) => p.items) ?? []
  const total = q.data?.pages[0]?.total ?? 0
  return (
    <>
      {q.isLoading && <LoadingRow depth={depth} />}
      {q.error && <div style={indent(depth)}><ErrorState error={q.error} /></div>}
      {rows.map((g) => <GroupNode key={g.id} group={g} depth={depth} props={props} />)}
      {parentId == null && !q.isLoading && !q.error && total === 0 && props.emptyText && (
        <div className="px-2 py-3 text-sm text-muted-foreground">{props.emptyText}</div>
      )}
      {q.hasNextPage && (
        <MoreRow depth={depth} busy={q.isFetchingNextPage} label={`More groups (${rows.length} of ${total})`}
          onClick={() => void q.fetchNextPage()} />
      )}
    </>
  )
}

function GroupNode({ group: g, depth, props }: { group: CameraGroup; depth: number; props: GroupTreeProps }) {
  const key = String(g.id)
  const open = props.expanded.isOpen(key)
  const hasCameras = !!props.showCameras && g.cameras_direct > 0
  const expandable = g.child_groups > 0 || hasCameras
  const disabled = props.isGroupDisabled?.(g) ?? false
  const selected = props.selectedGroupId === g.id
  const [dropping, setDropping] = useState(false)
  const count = countLabel(g, props.countMode ?? "total")
  const offline = props.countMode === "online" && g.cameras_total > 0 && g.online_total < g.cameras_total

  const onRow = () => {
    if (disabled) return
    if (props.onSelectGroup) props.onSelectGroup(g)
    else if (expandable) props.expanded.toggle(key)
  }

  return (
    <div role="treeitem" aria-expanded={expandable ? open : undefined} aria-selected={selected}>
      <div
        className={cn(
          "group/row flex min-h-8 items-center gap-1 rounded-md pr-1.5 text-sm",
          disabled ? "opacity-45" : "cursor-pointer hover:bg-accent",
          selected && "bg-accent font-medium",
          dropping && "ring-2 ring-primary",
        )}
        style={indent(depth)}
        onClick={onRow}
        title={g.path_label}
        draggable={!!props.dragGroups && !disabled}
        onDragStart={(e) => {
          e.dataTransfer.setData("text/group-id", String(g.id))
          e.dataTransfer.effectAllowed = "move"
        }}
        onDragOver={props.onDropGroup ? (e) => {
          if (!e.dataTransfer.types.includes("text/group-id") || disabled) return
          e.preventDefault()
          setDropping(true)
        } : undefined}
        onDragLeave={() => setDropping(false)}
        onDrop={props.onDropGroup ? (e) => {
          setDropping(false)
          const id = Number(e.dataTransfer.getData("text/group-id"))
          if (id && id !== g.id && !disabled) {
            e.preventDefault()
            props.onDropGroup!(id, g)
          }
        } : undefined}
      >
        <button
          type="button"
          aria-label={open ? "Collapse" : "Expand"}
          className={cn("grid size-6 shrink-0 place-items-center rounded text-muted-foreground hover:text-foreground",
            !expandable && "invisible")}
          onClick={(e) => {
            e.stopPropagation()
            props.expanded.toggle(key)
          }}
        >
          <ChevronRight className={cn("size-4 transition-transform", open && "rotate-90")} />
        </button>
        {open && expandable ? <FolderOpen className="size-4 shrink-0 text-primary/80" /> : <Folder className="size-4 shrink-0 text-primary/80" />}
        <span className="min-w-0 flex-1 truncate">{g.name}</span>
        {props.groupActions && (
          <span className={cn("flex shrink-0 items-center", !props.actionsVisible && "opacity-0 group-hover/row:opacity-100 focus-within:opacity-100")}
            onClick={(e) => e.stopPropagation()}>
            {props.groupActions(g)}
          </span>
        )}
        {count && (
          <span className={cn("shrink-0 text-[11px] tabular-nums text-muted-foreground", offline && "text-amber-500")}
            title={props.countMode === "online" ? "online / cameras (all sub-groups)" : "cameras (all sub-groups)"}>
            {count}
          </span>
        )}
      </div>
      {open && expandable && (
        <div role="group">
          {g.child_groups > 0 && <GroupLevel parentId={g.id} depth={depth + 1} props={props} />}
          {hasCameras && <CameraLevel scope={{ groupId: g.id }} depth={depth + 1} props={props} />}
        </div>
      )}
    </div>
  )
}

function UngroupedNode({ props }: { props: GroupTreeProps }) {
  const open = props.expanded.isOpen(UNGROUPED)
  return (
    <div role="treeitem" aria-expanded={props.showCameras ? open : undefined} aria-selected={!!props.ungroupedSelected}>
      <div
        className={cn("flex min-h-8 cursor-pointer items-center gap-1 rounded-md pr-1.5 text-sm text-muted-foreground hover:bg-accent",
          props.ungroupedSelected && "bg-accent font-medium text-foreground")}
        style={indent(0)}
        onClick={() => (props.onSelectUngrouped ? props.onSelectUngrouped() : props.expanded.toggle(UNGROUPED))}
      >
        <button type="button" aria-label={open ? "Collapse" : "Expand"}
          className={cn("grid size-6 shrink-0 place-items-center rounded hover:text-foreground", !props.showCameras && "invisible")}
          onClick={(e) => {
            e.stopPropagation()
            props.expanded.toggle(UNGROUPED)
          }}>
          <ChevronRight className={cn("size-4 transition-transform", open && "rotate-90")} />
        </button>
        <Inbox className="size-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate italic">Ungrouped</span>
      </div>
      {open && props.showCameras && <CameraLevel scope={{ ungrouped: true }} depth={1} props={props} />}
    </div>
  )
}

function CameraLevel({ scope, depth, props }: { scope: CameraScope; depth: number; props: GroupTreeProps }) {
  const q = useCameraOptions("", { scope, poll: true })
  const rows = q.data?.pages.flatMap((p) => p.items) ?? []
  const total = q.data?.pages[0]?.total ?? 0
  return (
    <>
      {q.isLoading && <LoadingRow depth={depth} />}
      {q.error && <div style={indent(depth)}><ErrorState error={q.error} /></div>}
      {rows.map((c) => (
        <button
          key={c.id}
          type="button"
          role="treeitem"
          className="flex min-h-8 w-full items-center gap-2 rounded-md pr-2 text-left text-sm hover:bg-accent disabled:opacity-50"
          style={{ paddingLeft: `${depth * 14 + 12}px` }}
          disabled={!c.enabled}
          draggable={!!props.dragCameras && c.enabled}
          onDragStart={(e) => e.dataTransfer.setData("text/camera-id", String(c.id))}
          onClick={() => props.onPickCamera?.(c)}
          title={props.dragCameras ? "Click or drag onto a tile" : undefined}
        >
          <StatusDot status={c.status} />
          <span className="min-w-0 flex-1 truncate">{c.name}</span>
          {props.cameraBadge?.(c)}
        </button>
      ))}
      {!q.isLoading && !q.error && total === 0 && (
        <div className="py-1.5 text-xs text-muted-foreground" style={{ paddingLeft: `${depth * 14 + 12}px` }}>No cameras</div>
      )}
      {q.hasNextPage && (
        <MoreRow depth={depth} busy={q.isFetchingNextPage} label={`More cameras (${rows.length} of ${total})`}
          onClick={() => void q.fetchNextPage()} />
      )}
    </>
  )
}

function LoadingRow({ depth }: { depth: number }) {
  return (
    <div className="flex h-8 items-center gap-2 text-xs text-muted-foreground" style={{ paddingLeft: `${depth * 14 + 12}px` }}>
      <Loader2 className="size-3.5 animate-spin" /> Loading…
    </div>
  )
}

function MoreRow({ depth, busy, label, onClick }: { depth: number; busy: boolean; label: string; onClick: () => void }) {
  return (
    <button type="button" disabled={busy} onClick={onClick}
      className="flex h-7 w-full items-center gap-2 rounded-md text-left text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
      style={{ paddingLeft: `${depth * 14 + 12}px` }}>
      {busy ? <Loader2 className="size-3.5 animate-spin" /> : label}
    </button>
  )
}
