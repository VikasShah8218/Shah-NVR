import assert from "node:assert/strict"
import { test } from "node:test"
import { PtzHoldController, type MotionCommand } from "../src/features/live/ptzController.ts"

function deferred() {
  let resolve!: () => void
  let reject!: (error: unknown) => void
  const promise = new Promise<void>((ok, bad) => { resolve = ok; reject = bad })
  return { promise, resolve, reject }
}

test("release sends a higher-sequence Stop before an outstanding move responds", async () => {
  const move = deferred()
  const sent: MotionCommand[] = []
  const c = new PtzHoldController(async (command) => { sent.push(command); if (command.action === "move") await move.promise }, assert.fail)
  const running = c.start({ pan: .1 })
  await c.stop()
  assert.deepEqual(sent.map((x) => [x.action, x.sequence]), [["move", 1], ["stop", 2]])
  move.resolve()
  await running
  assert.equal(sent.filter((x) => x.action === "move").length, 1)
})

test("dispose prevents delayed responses from resuming movement", async () => {
  const move = deferred()
  const sent: MotionCommand[] = []
  const c = new PtzHoldController(async (command) => { sent.push(command); if (command.action === "move") await move.promise }, assert.fail)
  const running = c.start({ zoom: .1 })
  await c.dispose()
  move.resolve(); await running
  await c.start({ pan: .1 })
  assert.equal(sent.filter((x) => x.action === "move").length, 1)
})

test("failed move attempts Stop and is never retried", async () => {
  const sent: MotionCommand[] = [], errors: unknown[] = []
  const c = new PtzHoldController(async (command) => {
    sent.push(command)
    if (command.action === "move") throw new Error("503")
  }, (e) => errors.push(e))
  await c.start({ tilt: .1 }); await c.start({ tilt: .1 })
  assert.deepEqual(sent.map((x) => x.action), ["move", "stop"])
  assert.equal(errors.length, 1)
  assert.equal(c.available, false)
})

test("parallel pointer presses cannot queue moves", async () => {
  const move = deferred()
  const sent: MotionCommand[] = []
  const c = new PtzHoldController(async (command) => { sent.push(command); if (command.action === "move") await move.promise }, assert.fail)
  const running = c.start({ pan: .1 })
  await c.start({ pan: -.1 })
  await c.stop(); move.resolve(); await running
  assert.equal(sent.filter((x) => x.action === "move").length, 1)
})

test("Stop overtaking a released move is expected, not a fatal failure", async () => {
  const move = deferred()
  const c = new PtzHoldController(async (command) => { if (command.action === "move") await move.promise }, assert.fail)
  const running = c.start({ pan: .1 })
  await c.stop()
  move.reject({ code: "ptz_stale_command" })
  await running
  assert.equal(c.available, true)
})

test("Stop failure is surfaced and blocks more movement", async () => {
  const errors: unknown[] = []
  const c = new PtzHoldController(async () => { throw new Error("Stop failed") }, (e) => errors.push(e))
  await c.stop()
  assert.equal(errors.length, 1)
  assert.equal(c.available, false)
})
