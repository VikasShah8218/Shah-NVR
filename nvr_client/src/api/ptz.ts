import type { NodeAccess } from "@/lib/nodeAccessCore"
import { centralClient, unwrap } from "./client"
import type { components } from "./central"

export type PtzState = components["schemas"]["PtzState"]
export type PtzTicket = components["schemas"]["PtzTicket"]
export type PtzCapabilities = components["schemas"]["PtzCapabilities"]
type CommandSchema = components["schemas"]["PtzCommand"]
export type PtzCommand = Pick<CommandSchema, "session_id" | "sequence" | "action"> & Partial<Omit<CommandSchema, "session_id" | "sequence" | "action">>

export function ptzApi(url: string, camera_id: number, profile: string) {
  const api = centralClient(url)
  const params = { path: { camera_id, profile } }
  return {
    // Legacy REST relay (kept as the fallback control path).
    open: () => unwrap(api.POST("/api/v1/cameras/{camera_id}/streams/{profile}/ptz", { params })),
    command: (body: PtzCommand) => unwrap(api.POST("/api/v1/cameras/{camera_id}/streams/{profile}/ptz/command", {
      params, body: { pan: 0, tilt: 0, zoom: 0, confirm: false, ...body }, keepalive: body.action === "stop",
    })),
    // Mint a direct-to-node WebSocket session; central brokers only the open.
    session: (access: NodeAccess) => unwrap(api.POST("/api/v1/cameras/{camera_id}/streams/{profile}/ptz/session", {
      params: { ...params, query: { access } },
    })),
  }
}
