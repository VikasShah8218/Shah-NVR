import test from "node:test"
import assert from "node:assert/strict"
import { bookmarkMarker, MIN_RANGE_WIDTH, placeMarkers, type TimelineMarker } from "../src/features/playback/markers.ts"

const START = Date.UTC(2026, 10, 9, 12, 0)
const MIN = 60_000
const at = (minutes: number) => START + minutes * MIN
const view = [at(0), at(100)] as const

test("a point marker lands at its percentage of the window", () => {
  const [placed] = placeMarkers([{ id: 1, t: at(25), kind: "bookmark" }], ...view)
  assert.equal(placed.x, 25)
  assert.equal(placed.width, null)
})

test("points outside the window are dropped; edges are kept", () => {
  const ms: TimelineMarker[] = [
    { id: "before", t: at(-1), kind: "bookmark" },
    { id: "edge-start", t: at(0), kind: "bookmark" },
    { id: "edge-end", t: at(100), kind: "bookmark" },
    { id: "after", t: at(101), kind: "bookmark" },
  ]
  assert.deepEqual(placeMarkers(ms, ...view).map((m) => m.id), ["edge-start", "edge-end"])
})

test("ranges are clipped to the window and keep a minimum visible width", () => {
  const ms: TimelineMarker[] = [
    { id: "inside", t: at(10), endT: at(30), kind: "bookmark" },
    { id: "overlaps-start", t: at(-20), endT: at(5), kind: "bookmark" },
    { id: "overlaps-end", t: at(90), endT: at(140), kind: "bookmark" },
    { id: "tiny", t: at(50), endT: at(50) + 1000, kind: "bookmark" },
    { id: "outside", t: at(110), endT: at(120), kind: "bookmark" },
  ]
  const byId = Object.fromEntries(placeMarkers(ms, ...view).map((m) => [m.id, m]))
  assert.deepEqual([byId.inside.x, byId.inside.width], [10, 20])
  assert.deepEqual([byId["overlaps-start"].x, byId["overlaps-start"].width], [0, 5])
  assert.deepEqual([byId["overlaps-end"].x, byId["overlaps-end"].width], [90, 10])
  assert.equal(byId.tiny.width, MIN_RANGE_WIDTH)
  assert.equal(byId.outside, undefined)
})

test("an empty or inverted window places nothing", () => {
  assert.deepEqual(placeMarkers([{ id: 1, t: at(5), kind: "bookmark" }], at(10), at(10)), [])
})

test("bookmarks become markers with label and optional range", () => {
  const point = bookmarkMarker({ id: 7, start_time: new Date(at(3)).toISOString(), end_time: null, note: "Truck", label: null, color: null })
  assert.deepEqual(point, { id: "bookmark-7", t: at(3), endT: null, kind: "bookmark", label: "Truck", color: undefined })
  const range = bookmarkMarker({
    id: 8, start_time: new Date(at(3)).toISOString(), end_time: new Date(at(4)).toISOString(), note: "Truck", label: "vehicle", color: "#ff8800",
  })
  assert.equal(range.endT, at(4))
  assert.equal(range.label, "vehicle: Truck")
  assert.equal(range.color, "#ff8800")
})
