/** Page maths shared by every paged list (docs/PAGINATION_PLAN.md). Pages are 1-based in the UI,
 *  the API takes `limit` + `offset`. Pure: tested in tests/pager.test.ts, ported to nvr_desktop app/core/paging.py. */

export const PAGE_SIZES = [25, 50, 100] as const
export const DEFAULT_PAGE_SIZE = 50

/** Response shape of every paged list endpoint. */
export interface Paged<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export const pageCount = (total: number, size: number) => Math.max(1, Math.ceil(Math.max(0, total) / size))

export const offsetFor = (page: number, size: number) => (Math.max(1, Math.floor(page)) - 1) * size

/** Keep `page` inside 1..pageCount (the list can shrink while we look at it). */
export const clampPage = (page: number, total: number, size: number) =>
  Math.min(Math.max(1, Math.floor(page) || 1), pageCount(total, size))

/** "101–150 of 987", or "0 of 0" for an empty list. */
export function rangeLabel(page: number, size: number, total: number): string {
  if (total <= 0) return "0 of 0"
  const from = offsetFor(clampPage(page, total, size), size) + 1
  const to = Math.min(total, from + size - 1)
  return `${from}–${to} of ${total}`
}

/** Slice an in-memory list (lists the client already has, e.g. the chunks of a day). */
export const slicePage = <T>(rows: T[], page: number, size: number): T[] => {
  const p = clampPage(page, rows.length, size)
  return rows.slice(offsetFor(p, size), offsetFor(p, size) + size)
}
