import test from "node:test"
import assert from "node:assert/strict"
import { frameStepTarget, RATES, reverseDone, reverseTarget } from "../src/features/playback/transport.ts"

const close = (a: number, b: number) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`)

test("a frame step moves 1/30 s by default, forward and back", () => {
  close(frameStepTarget(10, 1, 60), 10 + 1 / 30)
  close(frameStepTarget(10, -1, 60), 10 - 1 / 30)
  close(frameStepTarget(10, 1, 60, 25), 10.04)
})

test("frame steps clamp to the start and the end", () => {
  assert.equal(frameStepTarget(0.01, -1, 60), 0)
  assert.equal(frameStepTarget(59.99, 1, 60), 60)
})

test("unknown duration (NaN / Infinity) only clamps at zero", () => {
  close(frameStepTarget(100, 1, NaN), 100 + 1 / 30)
  close(frameStepTarget(100, 1, Infinity), 100 + 1 / 30)
})

test("reverse target moves back at the chosen rate by wall time", () => {
  const anchor = { media: 100, clock: 5_000, rate: 1 }
  assert.equal(reverseTarget(anchor, 5_000), 100)
  assert.equal(reverseTarget(anchor, 6_000), 99)
  assert.equal(reverseTarget({ ...anchor, rate: 4 }, 6_500), 94)
  assert.equal(reverseTarget({ ...anchor, rate: 0.5 }, 7_000), 99)
})

test("reverse stops at zero and reports done", () => {
  const t = reverseTarget({ media: 1, clock: 0, rate: 8 }, 1_000)
  assert.equal(t, 0)
  assert.equal(reverseDone(t), true)
  assert.equal(reverseDone(0.5), false)
})

test("rates include the old ones plus 16x", () => {
  for (const r of [0.5, 1, 2, 4, 8, 16]) assert.ok(RATES.includes(r))
})
