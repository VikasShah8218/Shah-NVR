import assert from "node:assert/strict"
import { test } from "node:test"
import { cameraEventsStatusLine } from "../src/lib/cameraEvents.ts"

const ago = () => "2 min ago"
const ALL = ["motion", "tamper", "digital_input"]

test("off: tells what the camera offers once detected", () => {
  assert.equal(cameraEventsStatusLine(false, ALL, null, ago).text, "Off. Press Detect to see what the camera offers.")
  const l = cameraEventsStatusLine(false, ALL, { state: "detected", offered: ["tamper", "digital_input"] }, ago)
  assert.equal(l.text, "Off. The camera offers: Tamper, Digital inputs.")
})

test("ok: last event, and a warning for kinds the camera lacks (AXIS without its motion app)", () => {
  const l = cameraEventsStatusLine(true, ALL, { state: "ok", offered: ["tamper", "digital_input"], last_event_at: "x" }, ago)
  assert.equal(l.tone, "warning")
  assert.equal(l.text, "Receiving events (last 2 min ago). Motion not offered by the camera.")
  assert.equal(cameraEventsStatusLine(true, ["motion"], { state: "ok", offered: ["motion"] }, ago).tone, "success")
})

test("problems", () => {
  assert.equal(cameraEventsStatusLine(true, ALL, { state: "auth_failed" }, ago).tone, "danger")
  assert.equal(cameraEventsStatusLine(true, ALL, { state: "no_topics" }, ago).tone, "warning")
  assert.match(cameraEventsStatusLine(true, ALL, undefined, ago).text, /^Starting/)
})
