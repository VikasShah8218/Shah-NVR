import assert from "node:assert/strict"
import test from "node:test"
import { changedValues, encoderAlternatives, encoderOptionErrors, preferredEncoderOption, presetValues, videoGBPerDay } from "../src/lib/encoder.ts"

const current = { encoding: "H265" as const, width: 1920, height: 1080, fps: 18, bitrate_kbps: 1024,
  gop: 20, quality: 5, rate_control: "VBR" as const }
const full = { encoding: "H265", resolutions: [[1920, 1080]], frame_rates: [18],
  bitrate_range: [1024, 8000], gop_range: [2, 255], quality_range: [0, 5], codec_profiles: [], rate_controls: ["VBR", "CBR"] }
const low = { ...full, resolutions: [[640, 360]], frame_rates: [5], bitrate_range: [128, 2048] }

test("duplicate H265 options collapse without changing the advertised limits", () => {
  const options = encoderAlternatives([full, structuredClone(full), low], "H265")
  assert.deepEqual(options, [full, low])
  assert.deepEqual(encoderOptionErrors(options[0], current, { ...current, bitrate_kbps: 4096 }), [])
})

test("prefer the complete matching alternative rather than the first codec entry", () => {
  assert.equal(preferredEncoderOption([low, full], current, { ...current, bitrate_kbps: 4096 }), 1)
  assert.equal(preferredEncoderOption([full, low], current,
    { ...current, width: 640, height: 360, fps: 5, bitrate_kbps: 512 }), 1)
})

test("mixed limits cannot make an unsupported combination valid", () => {
  const mixed = { ...current, fps: 5 } // low-option frame rate, full-option resolution
  assert.ok(encoderOptionErrors(full, current, mixed).some(e => e.includes("fps")))
  assert.ok(encoderOptionErrors(low, current, mixed).some(e => e.includes("Resolution")))
  assert.equal(preferredEncoderOption([low, full], current, mixed), 1)
})

test("unadvertised unchanged fields can be preserved, but edits need known limits", () => {
  const option = { ...full, bitrate_range: null }
  assert.deepEqual(encoderOptionErrors(option, current, { ...current, quality: 4 }), [])
  assert.ok(encoderOptionErrors(option, current, { ...current, bitrate_kbps: 4096 }).some(e => e.includes("bitrate_kbps")))
})

test("codec filtering never leaks a different codec's alternatives", () => {
  assert.deepEqual(encoderAlternatives([full, low], "H264"), [])
})

test("unchanged profile and rate mode still constrain the chosen alternative", () => {
  const restricted = { ...full, codec_profiles: ["Main"], rate_controls: ["CBR"] }
  const original = { ...current, codec_profile: "High" }
  const errors = encoderOptionErrors(restricted, original, { ...original, bitrate_kbps: 4096 })
  assert.ok(errors.some(e => e.includes("codec_profile")))
  assert.ok(errors.some(e => e.includes("rate_control")))
})

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

test("PTZ unknown bitrate remains unknown while other settings can change", () => {
  const reported = { ...current, bitrate_kbps: null }
  const option = { ...full, bitrate_range: null, frame_rates: [18, 15] }
  assert.deepEqual(encoderOptionErrors(option, reported, { ...reported, fps: 15 }), [])
  const draft = presetValues(reported, option, "Storage saver")
  assert.equal(draft.bitrate_kbps, null)
  assert.equal(videoGBPerDay(draft.bitrate_kbps), null)
  assert.deepEqual(changedValues(reported, draft), { fps: 15 })
})
