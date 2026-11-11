import assert from "node:assert/strict"
import { test } from "node:test"
import { allows, CAMERA_READ, Perm } from "../src/lib/auth/permissions.ts"

const viewer = { is_admin: false, permissions: [Perm.LIVE, Perm.PLAYBACK, Perm.DASHBOARD] }
const admin = { is_admin: true, permissions: [] }

test("permission checks mirror the server rules", () => {
  assert.equal(allows(viewer, [Perm.LIVE]), true)
  assert.equal(allows(viewer, [Perm.CAMERAS_MANAGE]), false)
  assert.equal(allows(viewer, CAMERA_READ), true) // any one of them
  assert.equal(allows(viewer, []), true) // any signed-in user
  assert.equal(allows(admin, [Perm.AUDIT_VIEW]), true)
  assert.equal(allows(null, []), false)
})
