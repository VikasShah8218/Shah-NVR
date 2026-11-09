import { Check, ChevronsUpDown, Loader2, Search } from "lucide-react"
import { useMemo, useState } from "react"
import { useCameraOptions } from "@/api/queries"
import type { CameraOption } from "@/api/types"
import { ErrorState } from "@/components/common"
import { StatusDot } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { useDebounced } from "@/lib/usePaged"
import { cn } from "@/lib/utils"

/** Search + "Load more" list of small camera rows from the server (never the whole camera list). */
export function CameraOptionsList({
  search,
  isSelected,
  onPick,
  filter,
  className,
}: {
  search: string
  isSelected: (c: CameraOption) => boolean
  onPick: (c: CameraOption) => void
  /** extra client-side filter on loaded rows (e.g. "has this profile") */
  filter?: (c: CameraOption) => boolean
  className?: string
}) {
  const options = useCameraOptions(useDebounced(search))
  const rows = useMemo(() => {
    const all = options.data?.pages.flatMap((p) => p.items) ?? []
    return filter ? all.filter(filter) : all
  }, [options.data, filter])
  const total = options.data?.pages[0]?.total
  const loaded = options.data?.pages.reduce((n, p) => n + p.items.length, 0) ?? 0
  return (
    <div className={cn("space-y-0.5", className)}>
      {options.isLoading && <div className="flex justify-center p-3"><Loader2 className="size-4 animate-spin text-muted-foreground" /></div>}
      {options.error && <ErrorState error={options.error} />}
      {rows.map((c) => (
        <button key={c.id} type="button" onClick={() => onPick(c)}
          className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-accent">
          <StatusDot status={c.status} />
          <span className="min-w-0 flex-1 truncate">{c.name}</span>
          {isSelected(c) && <Check className="size-4 text-primary" />}
        </button>
      ))}
      {!options.isLoading && rows.length === 0 && (
        <div className="p-3 text-sm text-muted-foreground">{search.trim() ? "No cameras match." : "No cameras."}</div>
      )}
      {options.hasNextPage && (
        <Button variant="ghost" size="sm" className="w-full text-muted-foreground" disabled={options.isFetchingNextPage}
          onClick={() => void options.fetchNextPage()}>
          {options.isFetchingNextPage ? <Loader2 className="size-3.5 animate-spin" /> : `Load more (${loaded} of ${total})`}
        </Button>
      )}
    </div>
  )
}

/** Searchable camera select (replaces a plain <Select> with every camera in it). */
export function CameraPicker({
  value,
  label,
  onChange,
  className,
}: {
  value: number | null
  /** name of the selected camera (the caller usually has it already) */
  label?: string
  onChange: (c: CameraOption) => void
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" role="combobox" aria-expanded={open} className={cn("justify-between font-normal", className)}>
          <span className={cn("truncate", !label && "text-muted-foreground")}>{label ?? (value != null ? `Camera #${value}` : "Select camera")}</span>
          <ChevronsUpDown className="size-4 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-2">
        <div className="relative mb-2">
          <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
          <Input autoFocus className="pl-8" placeholder="Search name or #id" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <CameraOptionsList className="max-h-72 overflow-y-auto" search={search} isSelected={(c) => c.id === value}
          onPick={(c) => { onChange(c); setOpen(false) }} />
      </PopoverContent>
    </Popover>
  )
}
