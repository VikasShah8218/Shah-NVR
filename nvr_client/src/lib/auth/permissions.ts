/** Mirror of central_manager/app/auth/permissions.py (the server enforces; the UI only hides). */
export const Perm = {
  LIVE: 1,
  PLAYBACK: 2,
  EXPORT: 3,
  BOOKMARKS_EDIT: 4,
  PTZ: 5,
  PTZ_ADMIN: 6,
  AUDIO: 7,
  CAMERAS_MANAGE: 20,
  ENCODER: 21,
  GROUPS_MANAGE: 22,
  NODES_MANAGE: 23,
  ASSIGNMENTS: 24,
  BACKFILL: 25,
  ACCESS_MANAGE: 30,
  AUDIT_VIEW: 31,
  DASHBOARD: 40,
} as const

export type PermNumber = (typeof Perm)[keyof typeof Perm]

/** Anyone who works with cameras may open the camera list (same rule as the server's CAMERA_READ). */
export const CAMERA_READ: PermNumber[] = [Perm.LIVE, Perm.PLAYBACK, Perm.EXPORT, Perm.CAMERAS_MANAGE, Perm.GROUPS_MANAGE, Perm.ASSIGNMENTS]

export const PERM_LABELS: Record<number, string> = {
  1: "Live view", 2: "Playback", 3: "Export", 4: "Bookmarks edit", 5: "PTZ control", 6: "PTZ admin", 7: "Audio",
  20: "Cameras manage", 21: "Encoder", 22: "Groups manage", 23: "Nodes manage", 24: "Assignments", 25: "Backfill",
  30: "Access manage", 31: "Audit view", 40: "Dashboard",
}

/** Does a user with these permissions pass a check that needs any one of `anyOf`? Empty = any signed-in user. */
export function allows(user: { is_admin: boolean; permissions: number[] } | null, anyOf: readonly number[] = []): boolean {
  if (!user) return false
  if (user.is_admin || anyOf.length === 0) return true
  return anyOf.some((p) => user.permissions.includes(p))
}
