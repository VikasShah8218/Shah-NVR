import assert from "node:assert/strict"
import test from "node:test"
import { changedValues, presetValues, videoGBPerDay } from "../src/lib/encoder.ts"

test("video storage uses decimal GB and excludes invalid/unlimited bitrates", () => {
  assert.equal(videoGBPerDay(1000), 10.8)
  for (const value of [null, 0, -1, Infinity, NaN, 2147483647]) assert.equal(videoGBPerDay(value), null)
})

test("draft patch includes only actual changed values", () => {
  assert.deepEqual(changedValues({ encoding: "H264", fps: 25 }, { encoding: "H264", fps: 12.5 }), { fps: 12.5 })
})

test("presets stay within advertised ranges and keep the codec", () => {
  const option = { encoding: "H264", resolutions: [[1920, 1080], [640, 360]],
    bitrate_range: [256, 8192], frame_rates: [25, 12.5, 5], quality_range: [1, 10], codec_profiles: [], rate_controls: [] }
  const out = presetValues({ encoding: "H264", fps: 25, bitrate_kbps: 512, width: 1920, height: 1080 }, option, "Low-bandwidth substream")
  assert.equal(out.encoding, "H264")
  assert.equal(out.bitrate_kbps, 256)
  assert.equal(out.fps, 5)
  assert.deepEqual([out.width, out.height], [640, 360])
})

test("missing capabilities never invent editable limits", () => {
  const current = { encoding: "H265" as const, bitrate_kbps: 4096, fps: 25 }
  assert.deepEqual(presetValues(current, { encoding: "H265", resolutions: [], frame_rates: [], codec_profiles: [], rate_controls: [] }, "Storage saver"), current)
})
