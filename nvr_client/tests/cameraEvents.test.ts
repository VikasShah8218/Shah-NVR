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

// ---------------------------------------------------------------- analytics (docs/ONVIF_ANALYTICS_EVENTS_PLAN.md)
import { kindsBody, kindTitle, savedKinds, withKind, isAnalyticsKind } from "../src/lib/cameraEvents.ts"

test("null = the basic three; analytics only when chosen", () => {
  assert.deepEqual(savedKinds(null), ["motion", "tamper", "digital_input"])
  assert.deepEqual(savedKinds(["motion", "line_crossing", "bogus"]), ["motion", "line_crossing"])
  assert.equal(kindsBody(["motion", "tamper", "digital_input"]), null)
  assert.deepEqual(kindsBody(["motion", "tamper", "digital_input", "intrusion"]), ["motion", "tamper", "digital_input", "intrusion"])
  assert.deepEqual(kindsBody(["line_crossing"]), ["line_crossing"])
})

test("withKind keeps the canonical order", () => {
  assert.deepEqual(withKind(["audio_alarm", "motion"], "line_crossing", true), ["motion", "line_crossing", "audio_alarm"])
  assert.deepEqual(withKind(["motion", "line_crossing"], "motion", false), ["line_crossing"])
  assert.ok(isAnalyticsKind("face") && !isAnalyticsKind("motion"))
  assert.equal(kindTitle("counting"), "People counting")
})

test("busy: analytics over the cap is a warning", () => {
  const l = cameraEventsStatusLine(true, ["line_crossing"], { state: "ok", offered: ["line_crossing"],
    detail: "busy: 12 analytics event(s) not stored (over 30 a minute)" }, ago)
  assert.equal(l.tone, "warning")
  assert.match(l.text, /busy: 12/)
  const missing = cameraEventsStatusLine(true, ["motion", "intrusion"], { state: "ok", offered: ["motion"] }, ago)
  assert.match(missing.text, /Intrusion not offered/)
})
