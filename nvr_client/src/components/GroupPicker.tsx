import { ChevronsUpDown, Folder, Inbox, Loader2, Search } from "lucide-react"
import { useState } from "react"
import { useGroup, useGroupSearch } from "@/api/queries"
import type { CameraGroup } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { GroupTree } from "@/features/groups/GroupTree"
import { useTreeExpanded } from "@/features/groups/useTreeExpanded"
import { useDebounced } from "@/lib/usePaged"
import { cn } from "@/lib/utils"

/** Group select: a lazy tree (expand to drill down) plus server-side name search. Never loads every group.
 *  `noneLabel` adds a "no group" / "top level" choice (value null). */
export function GroupPicker({
  value,
  onChange,
  noneLabel,
  isDisabled,
  placeholder = "Select group",
  className,
}: {
  value: number | null
  onChange: (groupId: number | null, group?: CameraGroup) => void
  noneLabel?: string
  isDisabled?: (g: CameraGroup) => boolean
  placeholder?: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const query = useDebounced(search)
  const expanded = useTreeExpanded(null)
  const current = useGroup(value)
  const found = useGroupSearch(query)
  const label = value == null ? noneLabel : current.data?.path_label ?? `Group #${value}`

  const pick = (id: number | null, g?: CameraGroup) => {
    onChange(id, g)
    setOpen(false)
    setSearch("")
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" role="combobox" aria-expanded={open} className={cn("justify-between font-normal", className)}>
          <span className={cn("flex min-w-0 items-center gap-2", !label && "text-muted-foreground")}>
            {value != null ? <Folder className="size-4 shrink-0 text-primary/80" /> : null}
            <span className="truncate">{label ?? placeholder}</span>
          </span>
          <ChevronsUpDown className="size-4 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-2">
        <div className="relative mb-2">
          <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
          <Input autoFocus className="pl-8" placeholder="Search groups" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className="max-h-80 overflow-y-auto">
          {noneLabel && !query && (
            <button type="button" onClick={() => pick(null)}
              className={cn("flex min-h-8 w-full items-center gap-2 rounded-md px-2 text-left text-sm hover:bg-accent",
                value == null && "bg-accent font-medium")}>
              <Inbox className="size-4 text-muted-foreground" /> <span className="italic">{noneLabel}</span>
            </button>
          )}
          {query ? (
            <>
              {found.isFetching && !found.data && <div className="flex justify-center p-3"><Loader2 className="size-4 animate-spin" /></div>}
              {found.data?.items.map((g) => {
                const off = isDisabled?.(g) ?? false
                return (
                  <button key={g.id} type="button" disabled={off} onClick={() => pick(g.id, g)}
                    className={cn("flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent disabled:opacity-45",
                      value === g.id && "bg-accent")}>
                    <Folder className="mt-0.5 size-4 shrink-0 text-primary/80" />
                    <span className="min-w-0">
                      <span className="block truncate">{g.name}</span>
                      <span className="block truncate text-xs text-muted-foreground">{g.path_label}</span>
                    </span>
                  </button>
                )
              })}
              {found.data?.total === 0 && <div className="p-3 text-sm text-muted-foreground">No groups match.</div>}
              {found.data && found.data.total > found.data.items.length && (
                <div className="px-2 py-1 text-xs text-muted-foreground">
                  {found.data.items.length} of {found.data.total} shown: type more to narrow down.
                </div>
              )}
            </>
          ) : (
            <GroupTree expanded={expanded} selectedGroupId={value} isGroupDisabled={isDisabled}
              onSelectGroup={(g) => pick(g.id, g)} emptyText="No groups yet." />
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}
