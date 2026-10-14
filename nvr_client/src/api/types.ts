import type { components as C } from "./central"
import type { components as N } from "./node"

// ---------------------------------------------------------------- central manager
export type Camera = C["schemas"]["CameraOut"]
export type CameraCreate = C["schemas"]["CameraCreate"]
export type CameraUpdate = C["schemas"]["CameraUpdate"]
export type Stream = C["schemas"]["StreamOut"]
export type StreamIn = C["schemas"]["StreamIn"]
export type StreamUpdate = C["schemas"]["StreamUpdate"]
export type StreamStatus = Stream["status"]
export type LiveInfo = C["schemas"]["LiveOut"]
export type LiveUrls = C["schemas"]["LiveStreamUrls"]
export type MediaNode = C["schemas"]["NodeOut"]
export type NodeState = MediaNode["state"]
export type NodeUpdate = C["schemas"]["NodeUpdate"]
export type Assignment = C["schemas"]["AssignmentOut"]
export type AssignmentHistory = C["schemas"]["AssignmentHistoryOut"]
export type Timeline = C["schemas"]["TimelineOut"]
export type Segment = C["schemas"]["SegmentOut"]
export type Gap = C["schemas"]["GapOut"]
export type ClusterHealth = C["schemas"]["ClusterHealthOut"]
export type GpuInfo = C["schemas"]["GpuInfo"]
export type StorageVolume = C["schemas"]["VolumeOut"]
export type VolumeState = StorageVolume["state"]
export type VolumeCreate = C["schemas"]["VolumeCreate"]
export type VolumeUpdate = C["schemas"]["VolumeUpdate"]
export type DriveInfo = C["schemas"]["DriveInfo"]

/** Shape of MediaNode.metrics (the node's last heartbeat; stored as free JSON by central). */
export interface NodeMetrics {
  cpu_percent?: number | null
  cpu_count?: number | null
  memory_percent?: number | null
  memory_total_bytes?: number | null
  memory_used_bytes?: number | null
  gpus?: GpuInfo[]
  disk?: { path: string; total_bytes: number; free_bytes: number; used_percent: number } | null
  recordings_bytes?: number | null
  net_rx_mbps?: number | null
  net_tx_mbps?: number | null
  mediamtx_running?: boolean
  paths_configured?: number
  paths_ready?: number
  pending_uploads?: number
  /** Local fixed drives of the node (offered in "Add storage"). */
  drives?: DriveInfo[]
  /** The node's own recordings folder (its default storage volume). */
  default_recordings_dir?: string | null
}

export const nodeMetrics = (node: MediaNode): NodeMetrics => (node.metrics ?? {}) as NodeMetrics

// ---------------------------------------------------------------- media node (direct)
export type NodeStatus = N["schemas"]["NodeStatusOut"]
export type LocalSegment = N["schemas"]["LocalSegmentOut"]

export interface NodeAssignment {
  camera_id: number
  camera_name: string
  generation: number
  streams: { profile: string; path_name: string; record: boolean; rtsp_transport: string }[]
}

/** MediaMTX /v3/paths/list item (fields we use). */
export interface MtxPath {
  name: string
  ready: boolean
  readyTime?: string | null
  tracks?: (string | { codec?: string })[]
  bytesReceived?: number
  bytesSent?: number
  readers?: { type: string; id: string }[]
  source?: { type: string; id: string } | null
}

export interface NodeLogs {
  source: "agent" | "mediamtx"
  lines: string[]
}
