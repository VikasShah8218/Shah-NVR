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

test("event markers: moment, range, ongoing; click plays from the pre-event seconds", async () => {
  const { eventMarker, eventTypeLabel } = await import("../src/features/playback/markers.ts")
  const base = { id: 7, type: "manual", label: "Door", pre_seconds: 10 }
  const point = eventMarker({ ...base, start_time: "2026-11-17T10:00:00Z", end_time: "2026-11-17T10:00:00Z" })
  assert.equal(point.endT, null)
  assert.equal(point.seekT, Date.parse("2026-11-17T09:59:50Z"))
  assert.equal(point.label, "Marked: Door")
  const range = eventMarker({ ...base, type: "video_loss", label: null, start_time: "2026-11-17T10:00:00Z", end_time: "2026-11-17T10:05:00Z" })
  assert.equal(range.endT, Date.parse("2026-11-17T10:05:00Z"))
  assert.equal(range.color, "#ef4444")
  const open = eventMarker({ ...base, start_time: "2026-11-17T10:00:00Z", end_time: null }, Date.parse("2026-11-17T10:01:00Z"))
  assert.equal(open.endT, Date.parse("2026-11-17T10:01:00Z"))
  assert.ok(open.label?.endsWith("(ongoing)"))
  assert.equal(eventTypeLabel("onvif_line.crossing"), "Onvif line crossing")
})

test("analytics events: colours, titles, no doubled title, groups", async () => {
  const { eventMarker, eventText, eventColor, EVENT_TYPE_GROUPS } = await import("../src/features/playback/markers.ts")
  assert.equal(eventColor("line_crossing"), "#d946ef")
  assert.equal(eventText({ type: "line_crossing", label: "Line crossing · Gate line ×3" }), "Line crossing · Gate line ×3")
  assert.equal(eventText({ type: "digital_input", label: "Input DI1" }), "Input DI1")  // was "Input: Input DI1"
  assert.equal(eventText({ type: "manual", label: "Gate open" }), "Marked: Gate open")
  assert.equal(eventText({ type: "intrusion", label: null }), "Intrusion")
  const m = eventMarker({ id: 1, type: "intrusion", start_time: "2026-11-26T10:00:00Z", end_time: "2026-11-26T10:00:05Z",
    label: "Intrusion · Parking", pre_seconds: 10 })
  assert.equal(m.label, "Intrusion · Parking")
  assert.equal(m.color, "#e11d48")
  const analytics = EVENT_TYPE_GROUPS.find((g) => g.group === "analytics")!
  assert.equal(analytics.types.length, 8)
})
