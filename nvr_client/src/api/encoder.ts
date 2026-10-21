import { useQuery } from "@tanstack/react-query"
import { unwrap } from "./client"
import { useCentral } from "./queries"
import type { components } from "./central"

export type EncoderState = components["schemas"]["EncoderState"]
export type EncoderValues = components["schemas"]["EncoderValues"]
export type EncoderOption = components["schemas"]["EncoderOption"]
export type EncoderWrite = components["schemas"]["EncoderWrite"]
export type EncoderChange = components["schemas"]["ChangeOut"]
export type EncoderHistory = components["schemas"]["HistoryOut"]
export type EncoderRecovery = components["schemas"]["RecoveryOut"]

export function useEncoderApi() {
  const { url, api } = useCentral()
  const params = (camera_id: number, profile: string) => ({ path: { camera_id, profile } })
  return {
    url,
    read: (id: number, profile: string) => unwrap(api.GET("/api/v1/cameras/{camera_id}/streams/{profile}/encoder", { params: params(id, profile) })),
    map: (id: number, profile: string, token: string) => unwrap(api.PUT("/api/v1/cameras/{camera_id}/streams/{profile}/encoder/mapping",
      { params: params(id, profile), body: { profile_token: token } })),
    check: (id: number, profile: string, body: EncoderWrite) => unwrap(api.POST("/api/v1/cameras/{camera_id}/streams/{profile}/encoder/check",
      { params: params(id, profile), body })),
    apply: (id: number, profile: string, body: EncoderWrite) => unwrap<EncoderChange>(api.PUT("/api/v1/cameras/{camera_id}/streams/{profile}/encoder",
      { params: params(id, profile), body })),
    history: (id: number, profile: string) => unwrap<EncoderHistory>(api.GET("/api/v1/cameras/{camera_id}/streams/{profile}/encoder/history",
      { params: params(id, profile) })),
    recovery: (id: number, profile: string) => unwrap<EncoderRecovery>(api.GET("/api/v1/cameras/{camera_id}/streams/{profile}/encoder/recovery",
      { params: params(id, profile) })),
    resolve: (id: number, profile: string) => unwrap(api.POST("/api/v1/cameras/{camera_id}/streams/{profile}/encoder/resolve",
      { params: params(id, profile) })),
  }
}

export function useEncoder(id: number, profile: string, active: boolean) {
  const api = useEncoderApi()
  return useQuery({
    queryKey: [api.url, "encoder", id, profile],
    queryFn: () => api.read(id, profile), enabled: active, retry: false,
    staleTime: Infinity, refetchOnWindowFocus: false, // never overwrite an unsaved draft with polling
  })
}
