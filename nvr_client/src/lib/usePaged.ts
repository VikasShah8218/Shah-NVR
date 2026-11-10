import { useEffect, useState } from "react"
import { DEFAULT_PAGE_SIZE, clampPage, offsetFor } from "./pager"

const SEARCH_DEBOUNCE_MS = 300

function readSize(key: string | undefined, fallback: number): number {
  if (!key) return fallback
  try {
    const v = Number(localStorage.getItem(`nvr.pageSize.${key}`))
    return v > 0 ? v : fallback
  } catch {
    return fallback
  }
}

/** Page + page size + debounced search for one paged list. A new search (or page size) goes back to page 1;
 *  `sizeKey` remembers the chosen page size in this browser. */
export function usePaged({ sizeKey, size = DEFAULT_PAGE_SIZE }: { sizeKey?: string; size?: number } = {}) {
  const [page, setPage] = useState(1)
  const [pageSize, setSize] = useState(() => readSize(sizeKey, size))
  const [search, setSearchNow] = useState("")
  const [query, setQuery] = useState("")

  useEffect(() => {
    const t = setTimeout(() => setQuery(search.trim()), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [search])

  const setSearch = (value: string) => {
    setSearchNow(value)
    setPage(1)
  }
  const setPageSize = (value: number) => {
    setSize(value)
    setPage(1)
    try {
      if (sizeKey) localStorage.setItem(`nvr.pageSize.${sizeKey}`, String(value))
    } catch { /* private window */ }
  }

  return {
    page, setPage, pageSize, setPageSize, search, setSearch,
    /** debounced, trimmed search text to send to the server */
    query,
    limit: pageSize,
    offset: offsetFor(page, pageSize),
  }
}

export type PagedState = ReturnType<typeof usePaged>

/** Step back when the list shrank under the current page (e.g. rows deleted while looking at the last page). */
export function useClampPage(p: PagedState, total: number | undefined) {
  const { page, pageSize, setPage } = p
  useEffect(() => {
    if (total == null) return
    const clamped = clampPage(page, total, pageSize)
    if (clamped !== page) setPage(clamped)
  }, [total, page, pageSize, setPage])
}

/** `value`, but only after it stopped changing for `ms` (search boxes). */
export function useDebounced<T>(value: T, ms = SEARCH_DEBOUNCE_MS): T {
  const [out, setOut] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setOut(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return out
}
