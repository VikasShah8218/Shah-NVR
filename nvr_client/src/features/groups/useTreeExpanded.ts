import { useCallback, useMemo, useState } from "react"
import { addKeys, parseExpanded, toggleKey } from "@/lib/groupTree"

export interface TreeExpanded {
  isOpen: (key: string) => boolean
  toggle: (key: string) => void
  open: (keys: string[]) => void
}

/** Expanded keys of a group tree, remembered in this browser under `storageKey` (null = not remembered,
 *  e.g. a picker). */
export function useTreeExpanded(storageKey: string | null): TreeExpanded {
  const [keys, setKeys] = useState<string[]>(() => {
    if (!storageKey) return []
    try {
      return parseExpanded(localStorage.getItem(storageKey))
    } catch {
      return []
    }
  })
  const save = useCallback((next: string[]) => {
    setKeys(next)
    if (!storageKey) return
    try {
      localStorage.setItem(storageKey, JSON.stringify(next))
    } catch { /* private window */ }
  }, [storageKey])
  return useMemo(() => ({
    isOpen: (key: string) => keys.includes(key),
    toggle: (key: string) => save(toggleKey(keys, key)),
    open: (add: string[]) => save(addKeys(keys, add)),
  }), [keys, save])
}
