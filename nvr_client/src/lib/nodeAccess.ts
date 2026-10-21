import { useQuery } from "@tanstack/react-query"
import type { MediaNode } from "@/api/types"
import { useSettings } from "@/lib/settings"
import { hasPublicMapping, type NodeAccess } from "@/lib/nodeAccessCore"

export { hasPublicMapping, nodeApiUrl, playbackAccess, selectedNodeAccess, type NodeAccess } from "@/lib/nodeAccessCore"

/** Auto mode probes each private Node API and caches the result. Unreachable LAN nodes use public mapping. */
export function useNodeAccessMap(nodes: MediaNode[]) {
  const { settings } = useSettings()
  const signature = nodes.map((n) => `${n.id}:${n.api_url}:${n.public_enabled}:${n.public_api_url ?? ""}`).join("|")
  return useQuery({
    queryKey: ["node-access", settings.nodeAccess, signature],
    enabled: settings.nodeAccess === "auto" && nodes.length > 0,
    staleTime: 60_000,
    retry: false,
    queryFn: async () => {
      const entries = await Promise.all(nodes.map(async (node): Promise<[number, NodeAccess]> => {
        if (!hasPublicMapping(node)) return [node.id, "lan"]
        try {
          const response = await fetch(`${node.api_url.replace(/\/+$/, "")}/api/v1/status`, {
            signal: AbortSignal.timeout(1500),
            cache: "no-store",
          })
          return [node.id, response.ok ? "lan" : "public"]
        } catch {
          return [node.id, "public"]
        }
      }))
      return Object.fromEntries(entries) as Record<number, NodeAccess>
    },
  })
}
