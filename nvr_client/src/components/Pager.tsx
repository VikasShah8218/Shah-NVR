import { ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { PAGE_SIZES, clampPage, pageCount, rangeLabel } from "@/lib/pager"
import { cn } from "@/lib/utils"

/** "101–150 of 987 · ‹ Page 3 / 20 › · 50 / page". Hidden when everything fits on one page and the size
 *  can't be changed, so short lists stay clean. */
export function Pager({
  page,
  pageSize,
  total,
  onPage,
  onPageSize,
  sizes = PAGE_SIZES,
  className,
}: {
  page: number
  pageSize: number
  total: number
  onPage: (page: number) => void
  onPageSize?: (size: number) => void
  sizes?: readonly number[]
  className?: string
}) {
  const pages = pageCount(total, pageSize)
  const current = clampPage(page, total, pageSize)
  if (pages <= 1 && (!onPageSize || total <= Math.min(...sizes))) return null
  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground", className)}>
      <span className="tabular-nums">{rangeLabel(current, pageSize, total)}</span>
      <div className="flex items-center gap-1">
        {onPageSize && (
          <Select value={String(pageSize)} onValueChange={(v) => onPageSize(Number(v))}>
            <SelectTrigger size="sm" className="h-7 w-[6.5rem] text-xs" aria-label="Rows per page"><SelectValue /></SelectTrigger>
            <SelectContent>
              {sizes.map((s) => <SelectItem key={s} value={String(s)}>{s} / page</SelectItem>)}
            </SelectContent>
          </Select>
        )}
        <Button variant="ghost" size="icon-sm" aria-label="Previous page" disabled={current <= 1} onClick={() => onPage(current - 1)}>
          <ChevronLeft />
        </Button>
        <span className="min-w-[5.5rem] text-center tabular-nums">Page {current} / {pages}</span>
        <Button variant="ghost" size="icon-sm" aria-label="Next page" disabled={current >= pages} onClick={() => onPage(current + 1)}>
          <ChevronRight />
        </Button>
      </div>
    </div>
  )
}
