import type { MediaNode } from "@/api/types"
import type { NodeAccessPreference } from "@/lib/settings"

export type NodeAccess = "lan" | "public"

export const hasPublicMapping = (node: MediaNode) =>
  node.public_enabled && !!node.public_api_url && !!node.public_media_host

export const nodeApiUrl = (node: MediaNode, access: NodeAccess) =>
  access === "public" && hasPublicMapping(node) ? node.public_api_url! : node.api_url

export function selectedNodeAccess(
  node: MediaNode,
  preference: NodeAccessPreference,
  detected?: Record<number, NodeAccess>,
): NodeAccess {
  if (preference === "lan") return "lan"
  if (preference === "public") return hasPublicMapping(node) ? "public" : "lan"
  return detected?.[node.id] ?? (hasPublicMapping(node) ? "public" : "lan")
}

export function playbackAccess(
  nodes: MediaNode[],
  requiredNodeIds: number[],
  preference: NodeAccessPreference,
  detected?: Record<number, NodeAccess>,
): NodeAccess {
  if (preference === "lan") return "lan"
  if (preference === "public") return "public"
  const required = new Set(requiredNodeIds)
  const relevant = nodes.filter((node) => required.has(node.id))
  return relevant.length > 0 && relevant.every((node) => selectedNodeAccess(node, preference, detected) === "lan")
    ? "lan"
    : "public"
}
