import { type MediaNode, nodeMetrics } from "@/api/types"
import { ratio } from "@/lib/format"

/** Everything the UI shows about a node's resources, derived from its last heartbeat. */
export function nodeResources(node: MediaNode) {
  const m = nodeMetrics(node)
  const disk = m.disk ?? null
  const recordings = m.recordings_bytes ?? null
  const quota = node.storage_quota_bytes ?? null
  const diskFree = disk?.free_bytes ?? null

  // Space recordings may still grow into: limited by the quota and by what is free on the disk.
  const remainingByDisk = diskFree
  const remainingByQuota = quota != null && recordings != null ? Math.max(0, quota - recordings) : null
  const remaining =
    remainingByQuota != null && remainingByDisk != null
      ? Math.min(remainingByQuota, remainingByDisk)
      : (remainingByQuota ?? remainingByDisk)
  const usable = recordings != null && remaining != null ? recordings + remaining : null

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
  }
}

export type NodeResources = ReturnType<typeof nodeResources>

export const isNodeHealthy = (node: MediaNode) => node.state === "ACTIVE" || node.state === "READY"
