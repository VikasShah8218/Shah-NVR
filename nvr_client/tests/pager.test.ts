import test from "node:test"
import assert from "node:assert/strict"
import { clampPage, offsetFor, pageCount, rangeLabel, slicePage } from "../src/lib/pager.ts"

test("page count is at least one and rounds up", () => {
  assert.equal(pageCount(0, 50), 1)
  assert.equal(pageCount(50, 50), 1)
  assert.equal(pageCount(51, 50), 2)
  assert.equal(pageCount(987, 50), 20)
})

test("offset from a 1-based page", () => {
  assert.equal(offsetFor(1, 50), 0)
  assert.equal(offsetFor(3, 50), 100)
  assert.equal(offsetFor(0, 50), 0)
})

test("page is clamped when the list shrinks", () => {
  assert.equal(clampPage(5, 120, 50), 3)
  assert.equal(clampPage(0, 120, 50), 1)
  assert.equal(clampPage(2, 0, 50), 1)
})

test("range label", () => {
  assert.equal(rangeLabel(3, 50, 987), "101–150 of 987")
  assert.equal(rangeLabel(20, 50, 987), "951–987 of 987")
  assert.equal(rangeLabel(1, 50, 0), "0 of 0")
})

test("in-memory slice", () => {
  const rows = Array.from({ length: 7 }, (_, i) => i)
  assert.deepEqual(slicePage(rows, 2, 3), [3, 4, 5])
  assert.deepEqual(slicePage(rows, 9, 3), [6])
})
