/** Pure helpers of the lazy camera-group tree (docs/GROUPING_PLAN.md). No React here, so node --test can run them. */

/** Tree key of the virtual "Ungrouped" node (real groups use their id as the key). */
export const UNGROUPED = "ungrouped"

/** "/3/17/42/" → [3, 17, 42] */
export function pathIds(path: string): number[] {
  return path.split("/").filter(Boolean).map(Number)
}

/** Keys to expand so a group becomes visible: every ancestor (not the group itself). */
export function revealKeys(path: string): string[] {
  return pathIds(path).slice(0, -1).map(String)
}

/** Is `path` the group at `ancestorPath` or somewhere below it? (a group cannot move into its own subtree) */
export function isInSubtree(path: string, ancestorPath: string): boolean {
  return ancestorPath !== "" && path.startsWith(ancestorPath)
}

/** "35/38" (online of total) for the live tree, "38" for management. */
export function countLabel(g: { online_total: number; cameras_total: number }, mode: "online" | "total"): string {
  if (g.cameras_total === 0) return ""
  return mode === "online" ? `${g.online_total}/${g.cameras_total}` : String(g.cameras_total)
}

export function parseExpanded(raw: string | null): string[] {
  try {
    const v = raw ? JSON.parse(raw) : []
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, 500) : []
  } catch {
    return []
  }
}

export function toggleKey(keys: readonly string[], key: string): string[] {
  return keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key]
}

export function addKeys(keys: readonly string[], add: readonly string[]): string[] {
  return [...new Set([...keys, ...add])]
}
