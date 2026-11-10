import assert from "node:assert/strict"
import { test } from "node:test"
import { NO_PICTURE_MS, noPictureLimitMs, pushEvent } from "../src/features/live/watchdog.ts"

test("no-picture limits: WebRTC 8 s, LL-HLS waits for its buffer", () => {
  assert.equal(noPictureLimitMs("webrtc", 5), NO_PICTURE_MS)
  assert.equal(noPictureLimitMs("hls", 5), 14_000)
  assert.equal(noPictureLimitMs("hls", 2), NO_PICTURE_MS) // never shorter than WebRTC
})

test("player steps keep the last 16", () => {
  const events: string[] = []
  for (let i = 0; i < 20; i++) pushEvent(events, `s${i}`, i * 500)
  assert.equal(events.length, 16)
  assert.equal(events[0], "s4@2.0s")
  assert.equal(events.at(-1), "s19@9.5s")
})
