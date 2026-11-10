import assert from "node:assert/strict"
import { test } from "node:test"
import { addKeys, countLabel, isInSubtree, parseExpanded, pathIds, revealKeys, toggleKey } from "../src/lib/groupTree.ts"

test("path ids and reveal keys", () => {
  assert.deepEqual(pathIds("/3/17/42/"), [3, 17, 42])
  assert.deepEqual(pathIds(""), [])
  assert.deepEqual(revealKeys("/3/17/42/"), ["3", "17"])
  assert.deepEqual(revealKeys("/3/"), [])
})

test("subtree check used to block moving a group into itself", () => {
  assert.equal(isInSubtree("/3/17/", "/3/"), true)
  assert.equal(isInSubtree("/3/", "/3/"), true)
  assert.equal(isInSubtree("/31/", "/3/"), false) // ids are delimited: 31 is not under 3
  assert.equal(isInSubtree("/3/", ""), false)
})

test("count labels", () => {
  assert.equal(countLabel({ online_total: 35, cameras_total: 38 }, "online"), "35/38")
  assert.equal(countLabel({ online_total: 35, cameras_total: 38 }, "total"), "38")
  assert.equal(countLabel({ online_total: 0, cameras_total: 0 }, "online"), "")
})

test("expanded keys are parsed defensively and toggled", () => {
  assert.deepEqual(parseExpanded('["1","ungrouped",3]'), ["1", "ungrouped"])
  assert.deepEqual(parseExpanded("{bad"), [])
  assert.deepEqual(parseExpanded(null), [])
  assert.deepEqual(toggleKey(["1"], "2"), ["1", "2"])
  assert.deepEqual(toggleKey(["1", "2"], "1"), ["2"])
  assert.deepEqual(addKeys(["1"], ["1", "3"]), ["1", "3"])
})
