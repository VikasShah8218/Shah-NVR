import test from "node:test"
import assert from "node:assert/strict"
import { thumbnailUrl, thumbTarget, type ThumbSegment } from "../src/features/playback/thumbs.ts"

const T0 = Date.UTC(2026, 10, 9, 12, 0)
const S = 1000
const iso = (ms: number) => new Date(ms).toISOString()
const segs: ThumbSegment[] = [
  { id: "a", node_id: 1, start_time: iso(T0), end_time: iso(T0 + 60 * S) },
  { id: "b", node_id: 2, start_time: iso(T0 + 60 * S), end_time: iso(T0 + 120 * S) },
  // gap 120..180 s
  { id: "c", node_id: 1, start_time: iso(T0 + 180 * S), end_time: iso(T0 + 240 * S) },
]

test("hover inside a 30 s slot maps to the slot start of that segment", () => {
  assert.deepEqual(thumbTarget(segs, T0 + 10 * S), { segmentId: "a", nodeId: 1, atMs: 0, slotStart: T0 })
  assert.deepEqual(thumbTarget(segs, T0 + 29_999), { segmentId: "a", nodeId: 1, atMs: 0, slotStart: T0 })
  assert.deepEqual(thumbTarget(segs, T0 + 45 * S), { segmentId: "a", nodeId: 1, atMs: 30_000, slotStart: T0 + 30 * S })
})

test("2 thumbnails per 60 s segment; the boundary belongs to the next segment", () => {
  const slots = new Set<string>()
  for (let t = T0; t < T0 + 120 * S; t += 5 * S) {
    const x = thumbTarget(segs, t)!
    slots.add(`${x.segmentId}:${x.atMs}`)
  }
  assert.deepEqual([...slots], ["a:0", "a:30000", "b:0", "b:30000"])
  assert.equal(thumbTarget(segs, T0 + 60 * S)!.segmentId, "b")
})

test("gaps and times outside every segment give no thumbnail", () => {
  assert.equal(thumbTarget(segs, T0 + 150 * S), null)
  assert.equal(thumbTarget(segs, T0 - 1), null)
  assert.equal(thumbTarget(segs, T0 + 240 * S), null)
})

test("custom grid (10 s)", () => {
  assert.equal(thumbTarget(segs, T0 + 25 * S, 10_000)!.atMs, 20_000)
})

test("url goes straight to the node and tolerates a trailing slash", () => {
  assert.equal(thumbnailUrl("http://10.0.0.5:7100/", "abc", 30000), "http://10.0.0.5:7100/api/v1/media/abc/thumb.jpg?at_ms=30000&w=240")
})
