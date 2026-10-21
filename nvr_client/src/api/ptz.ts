import { centralClient, unwrap } from "./client"
import type { components } from "./central"

export type PtzState = components["schemas"]["PtzState"]
type CommandSchema = components["schemas"]["PtzCommand"]
export type PtzCommand = Pick<CommandSchema, "session_id" | "sequence" | "action"> & Partial<Omit<CommandSchema, "session_id" | "sequence" | "action">>

export function ptzApi(url: string, camera_id: number, profile: string) {
  const api = centralClient(url)
  const params = { path: { camera_id, profile } }
  return {
    open: () => unwrap(api.POST("/api/v1/cameras/{camera_id}/streams/{profile}/ptz", { params })),
    command: (body: PtzCommand) => unwrap(api.POST("/api/v1/cameras/{camera_id}/streams/{profile}/ptz/command", {
      params, body: { pan: 0, tilt: 0, zoom: 0, confirm: false, ...body }, keepalive: body.action === "stop",
    })),
  }
}
