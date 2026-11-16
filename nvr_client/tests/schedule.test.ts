import assert from "node:assert/strict"
import { test } from "node:test"
import { bitmapToBlocks, blockLabel, blocksToBitmap, cellCoverage, dayRuns, recordedHours, siteWall, TEMPLATES } from "../src/lib/schedule.ts"

const b = (days: number[], start: string, end: string) => ({ days, start, end, mode: "continuous" as const })

test("templates round-trip through the bitmap unchanged", () => {
  for (const t of TEMPLATES) assert.deepEqual(bitmapToBlocks(blocksToBitmap(t.blocks)), t.blocks, t.key)
})

test("overnight blocks wrap, Sunday night runs into Monday", () => {
  const bits = blocksToBitmap([b([6], "22:00", "06:00")])
  assert.equal(recordedHours(bits), 8)
  assert.deepEqual(dayRuns(bits, 6), [[1320, 1440]])
  assert.deepEqual(dayRuns(bits, 0), [[0, 360]])
  assert.deepEqual(bitmapToBlocks(bits), [b([6], "22:00", "06:00")])
})

test("start == end is 24 h; long runs split at midnight", () => {
  assert.equal(recordedHours(blocksToBitmap([b([2], "08:00", "08:00")])), 24)
  // Fri 18:00 -> Mon 08:00
  const bits = blocksToBitmap([b([4], "18:00", "24:00"), b([5, 6], "00:00", "24:00"), b([0], "00:00", "08:00")])
  assert.deepEqual(bitmapToBlocks(bits), [b([0], "00:00", "08:00"), b([4], "18:00", "24:00"), b([5, 6], "00:00", "24:00")])
})

test("off blocks add nothing; exact minutes survive", () => {
  const bits = blocksToBitmap([b([0], "18:03", "18:05"), { days: [1], start: "00:00", end: "24:00", mode: "off" }])
  assert.equal(recordedHours(bits) * 60, 2)
  assert.deepEqual(bitmapToBlocks(bits), [b([0], "18:03", "18:05")])
  const cov = cellCoverage(bits)
  assert.ok(cov[0][72] > 0 && cov[0][72] < 1)
})

test("labels and site wall clock", () => {
  assert.equal(blockLabel(b([0, 1, 2, 3, 4], "08:00", "18:00")), "Mon–Fri 08:00–18:00")
  assert.equal(blockLabel(b([5, 6], "00:00", "24:00")), "Sat, Sun all day")
  assert.equal(blockLabel(b([0, 2], "18:00", "08:00")), "Mon, Wed 18:00–08:00 (next day)")
  assert.deepEqual(siteWall("2026-11-16T18:30:00+05:30"), { day: 0, minute: 1110, date: "2026-11-16" })
})
