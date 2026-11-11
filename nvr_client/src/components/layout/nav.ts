import {
  ArrowLeftRight,
  Camera,
  FolderTree,
  Gauge,
  History,
  KeyRound,
  MonitorPlay,
  Radar,
  ScrollText,
  Server,
  Settings,
  type LucideIcon,
} from "lucide-react"
import { CAMERA_READ, Perm } from "@/lib/auth/permissions"

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
  /** any one of these permissions opens the page (empty = everyone) */
  perms: readonly number[]
}

/** Pages and the permission each needs (the server enforces the same rules on its API). */
export const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: Gauge, end: true, perms: [Perm.DASHBOARD] },
  { to: "/live", label: "Live View", icon: MonitorPlay, perms: [Perm.LIVE] },
  { to: "/playback", label: "Playback", icon: History, perms: [Perm.PLAYBACK] },
  { to: "/cameras", label: "Cameras", icon: Camera, perms: CAMERA_READ },
  { to: "/groups", label: "Groups", icon: FolderTree, perms: [Perm.GROUPS_MANAGE] },
  { to: "/discover", label: "Discover", icon: Radar, perms: [Perm.CAMERAS_MANAGE] },
  { to: "/nodes", label: "Media Nodes", icon: Server, perms: [Perm.NODES_MANAGE] },
  { to: "/assignments", label: "Assignments", icon: ArrowLeftRight, perms: [Perm.ASSIGNMENTS] },
  { to: "/access", label: "Access", icon: KeyRound, perms: [Perm.ACCESS_MANAGE] },
  { to: "/audit", label: "Audit log", icon: ScrollText, perms: [Perm.AUDIT_VIEW] },
  { to: "/settings", label: "Settings", icon: Settings, perms: [] },
]
