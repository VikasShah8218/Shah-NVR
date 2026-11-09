/**
 * Timeline hover thumbnails: map a wall-clock time to (segment, offset in it, 30 s slot).
 * Pure so it can be unit-tested; the node snaps to the same grid, and snapping here too makes every
 * hover inside one slot the same URL, so the browser cache answers before the node is even asked.
 */

/** Must match the node's THUMBNAIL_GRID_SECONDS (the node snaps anyway; this only keeps URLs identical). */
export const THUMB_GRID_MS = 30_000
/** Debounce before asking for a preview, so a fast drag fires a few requests, not a hundred. */
export const THUMB_DEBOUNCE_MS = 150

export interface ThumbSegment {
  id: string
  node_id: number
  start_time: string
  end_time: string
}

export interface ThumbTarget {
  segmentId: string
  nodeId: number
  /** Offset of the slot start inside the segment (what the node is asked for). */
  atMs: number
  /** Wall-clock time of the slot start (what the picture actually shows). */
  slotStart: number
}

export function thumbTarget(segments: ThumbSegment[], t: number, gridMs = THUMB_GRID_MS): ThumbTarget | null {
  for (const s of segments) {
    const start = new Date(s.start_time).getTime()
    const end = new Date(s.end_time).getTime()
    if (t < start || t >= end) continue
    const atMs = Math.floor((t - start) / gridMs) * gridMs
    return { segmentId: s.id, nodeId: s.node_id, atMs, slotStart: start + atMs }
  }
  return null
}

/** Direct-to-node preview URL (like mediaFileUrl). */
export const thumbnailUrl = (apiUrl: string, segmentId: string, atMs: number, width = 240) =>
  `${apiUrl.replace(/\/+$/, "")}/api/v1/media/${segmentId}/thumb.jpg?at_ms=${atMs}&w=${width}`
