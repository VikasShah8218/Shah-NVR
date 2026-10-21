import createClient from "openapi-fetch"
import type { paths as CentralPaths } from "./central"
import type { paths as NodePaths } from "./node"
import type { ExportCreate, ExportJob } from "./types"

export class ApiError extends Error {
  readonly status: number
  /** Machine-readable reason when the server sends {"detail": {"code", "message"}} (ONVIF calls). */
  readonly code?: string
  readonly detail?: Record<string, unknown>

  constructor(status: number, message: string, detail?: Record<string, unknown>) {
    super(message)
    this.status = status
    this.detail = detail
    this.code = typeof detail?.code === "string" ? detail.code : undefined
  }
}

/** FastAPI errors: {"detail": "text"}, {"detail": {"code", "message"}} or {"detail": [{"msg": ...}, ...]}. */
function errorMessage(error: unknown, status: number): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail
  if (typeof detail === "string") return detail
  if (detail && typeof detail === "object" && !Array.isArray(detail) && "message" in detail) return String(detail.message)
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? ""}`)
      .join("; ")
  }
  return status ? `Request failed (HTTP ${status})` : "Server unreachable"
}

/** Resolve an openapi-fetch call to its data, or throw ApiError with the server's message. */
export async function unwrap<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  let result
  try {
    result = await call
  } catch {
    throw new ApiError(0, "Server unreachable")
  }
  const { data, error, response } = result
  if (error !== undefined || !response.ok) {
    const detail = (error as { detail?: unknown } | undefined)?.detail
    const obj = detail && typeof detail === "object" && !Array.isArray(detail) ? (detail as Record<string, unknown>) : undefined
    throw new ApiError(response.status, errorMessage(error, response.status), obj)
  }
  return data as T
}

const centralClients = new Map<string, ReturnType<typeof createClient<CentralPaths>>>()
const nodeClients = new Map<string, ReturnType<typeof createClient<NodePaths>>>()

export function centralClient(baseUrl: string) {
  let c = centralClients.get(baseUrl)
  if (!c) {
    c = createClient<CentralPaths>({ baseUrl })
    centralClients.set(baseUrl, c)
  }
  return c
}

/** Direct, read-only access to a media node's own API (status, paths, chunks, logs). */
export function nodeClient(apiUrl: string) {
  const baseUrl = apiUrl.replace(/\/+$/, "")
  let c = nodeClients.get(baseUrl)
  if (!c) {
    c = createClient<NodePaths>({ baseUrl })
    nodeClients.set(baseUrl, c)
  }
  return c
}

export async function nodeGet<T>(apiUrl: string, path: string, query?: Record<string, string | number>): Promise<T> {
  const url = new URL(apiUrl.replace(/\/+$/, "") + path)
  Object.entries(query ?? {}).forEach(([k, v]) => url.searchParams.set(k, String(v)))
  let res: Response
  try {
    res = await fetch(url)
  } catch {
    throw new ApiError(0, `Node unreachable at ${apiUrl}`)
  }
  if (!res.ok) throw new ApiError(res.status, `Node request failed (HTTP ${res.status})`)
  return (await res.json()) as T
}

export const mediaFileUrl = (apiUrl: string, segmentId: string) =>
  `${apiUrl.replace(/\/+$/, "")}/api/v1/media/${segmentId}/file.mp4`

export function playbackUrl(centralUrl: string, cameraId: number, profile: string, start: Date, end: Date, access: "lan" | "public") {
  const q = new URLSearchParams({ profile, start: start.toISOString(), end: end.toISOString(), access })
  return `${centralUrl}/api/v1/playback/${cameraId}/index.m3u8?${q}`
}

export function playbackAudioUrl(centralUrl: string, cameraId: number, profile: string, start: Date, end: Date, access: "lan" | "public") {
  const q = new URLSearchParams({ profile, start: start.toISOString(), end: end.toISOString(), access })
  return `${centralUrl}/api/v1/playback/${cameraId}/audio.m3u8?${q}`
}

async function exportFetch<T>(centralUrl: string, path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(centralUrl.replace(/\/+$/, "") + path, {
      ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError(0, "Server unreachable")
  }
  if (!response.ok) {
    let error: unknown
    try { error = await response.json() } catch { error = undefined }
    const detail = (error as { detail?: unknown } | undefined)?.detail
    throw new ApiError(response.status, errorMessage(error, response.status),
      detail && typeof detail === "object" && !Array.isArray(detail) ? detail as Record<string, unknown> : undefined)
  }
  return response.json() as Promise<T>
}

export const listExports = (centralUrl: string, cameraId: number) =>
  exportFetch<ExportJob[]>(centralUrl, `/api/v1/exports?camera_id=${cameraId}&limit=50`)
export const createExport = (centralUrl: string, body: ExportCreate) =>
  exportFetch<ExportJob>(centralUrl, "/api/v1/exports", { method: "POST", body: JSON.stringify(body) })
export const cancelExport = (centralUrl: string, id: string) =>
  exportFetch<ExportJob>(centralUrl, `/api/v1/exports/${id}/cancel`, { method: "POST" })
export const exportDownloadUrl = (centralUrl: string, id: string, access: "lan" | "public") =>
  `${centralUrl.replace(/\/+$/, "")}/api/v1/exports/${id}/download?access=${access}`
