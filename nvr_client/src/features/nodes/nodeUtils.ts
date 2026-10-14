import { type MediaNode, nodeMetrics, type StorageVolume } from "@/api/types"
import { ratio } from "@/lib/format"

/** Room a volume still has for recordings: limited by its cap and by the free space of its disk. */
export function volumeRoom(v: StorageVolume): number | null {
  const byCap = v.quota_bytes != null ? Math.max(0, v.quota_bytes - (v.recordings_bytes ?? 0)) : null
  const byDisk = v.free_bytes
  if (byCap != null && byDisk != null) return Math.min(byCap, byDisk)
  return byCap ?? byDisk ?? null
}

/** A volume that can receive new recordings right now. */
export const volumeUsable = (v: StorageVolume) => v.accepting && (v.state === "OK" || v.state === "FULL")

/** Everything the UI shows about a node's resources, derived from its last heartbeat (+ its storage volumes). */
export function nodeResources(node: MediaNode) {
  const m = nodeMetrics(node)
  const disk = m.disk ?? null
  const volumes = node.volumes ?? []
  const quota = node.storage_quota_bytes ?? null
  const diskFree = disk?.free_bytes ?? null

  let recordings: number | null
  let remaining: number | null
  if (volumes.length) {
    // Several drives / shares: add up what each one holds and how much room each still has.
    recordings = volumes.reduce((a, v) => a + (v.recordings_bytes ?? 0), 0)
    const rooms = volumes.filter(volumeUsable).map(volumeRoom)
    remaining = rooms.length ? rooms.reduce<number>((a, r) => a + (r ?? 0), 0) : 0
  } else {
    // Node older than storage volumes: one folder, one disk.
    recordings = m.recordings_bytes ?? null
    const byQuota = quota != null && recordings != null ? Math.max(0, quota - recordings) : null
    remaining = byQuota != null && diskFree != null ? Math.min(byQuota, diskFree) : (byQuota ?? diskFree)
  }
  const usable = recordings != null && remaining != null ? recordings + remaining : null
  const accepting = volumes.filter((v) => v.accepting)

  return {
    cpuPercent: m.cpu_percent ?? null,
    cpuCount: m.cpu_count ?? null,
    gpus: m.gpus ?? [],
    memUsed: m.memory_used_bytes ?? null,
    memTotal: m.memory_total_bytes ?? null,
    memPercent: m.memory_percent ?? ratio(m.memory_used_bytes, m.memory_total_bytes),
    diskTotal: disk?.total_bytes ?? null,
    diskFree,
    diskPercent: disk?.used_percent ?? null,
    recordings,
    quota,
    /** Recordings vs quota when a quota is set, otherwise disk usage. */
    storagePercent: quota != null ? ratio(recordings, quota) : (disk?.used_percent ?? null),
    remaining,
    usable,
    netRx: m.net_rx_mbps ?? null,
    netTx: m.net_tx_mbps ?? null,
    mediamtxRunning: m.mediamtx_running ?? null,
    pendingUploads: m.pending_uploads ?? null,
    camerasPercent: ratio(node.assigned_cameras, node.capacity_cameras),
    volumes,
    writingVolume: volumes.find((v) => v.writing) ?? null,
    volumesOffline: volumes.filter((v) => v.state === "UNAVAILABLE" || v.state === "ERROR"),
    /** Every accepting volume is full: the node is overwriting its oldest recordings. */
    allFull: accepting.length > 0 && accepting.every((v) => v.state === "FULL"),
  }
}

export type NodeResources = ReturnType<typeof nodeResources>

export const isNodeHealthy = (node: MediaNode) => node.state === "ACTIVE" || node.state === "READY"
