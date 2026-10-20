import test from "node:test"
import assert from "node:assert/strict"
import type { MediaNode } from "../src/api/types.ts"
import { nodeApiUrl, playbackAccess, selectedNodeAccess } from "../src/lib/nodeAccessCore.ts"

const node = (id: number, publicEnabled = true) => ({
  id,
  api_url: `http://192.168.1.${100 + id}:7100`,
  public_enabled: publicEnabled,
  public_api_url: publicEnabled ? `http://public.example:${7100 + id}` : null,
  public_media_host: publicEnabled ? "public.example" : null,
}) as MediaNode

test("explicit LAN and public preferences are browser-local choices", () => {
  const n = node(1)
  assert.equal(selectedNodeAccess(n, "lan"), "lan")
  assert.equal(selectedNodeAccess(n, "public"), "public")
  assert.equal(nodeApiUrl(n, "lan"), "http://192.168.1.101:7100")
  assert.equal(nodeApiUrl(n, "public"), "http://public.example:7101")
})

test("public preference safely falls back when a node has no public mapping", () => {
  const n = node(2, false)
  assert.equal(selectedNodeAccess(n, "public"), "lan")
  assert.equal(nodeApiUrl(n, "public"), "http://192.168.1.102:7100")
})

test("auto uses cached reachability independently for each node", () => {
  const a = node(1)
  const b = node(2)
  const detected = { 1: "lan", 2: "public" } as const
  assert.equal(selectedNodeAccess(a, "auto", detected), "lan")
  assert.equal(selectedNodeAccess(b, "auto", detected), "public")
  assert.equal(playbackAccess([a, b], [1], "auto", detected), "lan")
  assert.equal(playbackAccess([a, b], [1, 2], "auto", detected), "public")
})
