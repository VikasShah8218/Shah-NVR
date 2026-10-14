import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { useSettings } from "@/lib/settings"
import { centralClient, nodeClient, nodeGet, unwrap } from "./client"
import type {
  Assignment,
  AssignmentHistory,
  Camera,
  CameraCreate,
  CameraUpdate,
  ClusterHealth,
  LiveInfo,
  LocalSegment,
  MediaNode,
  MtxPath,
  NodeAssignment,
  NodeLogs,
  NodeStatus,
  NodeUpdate,
  StreamIn,
  StorageVolume,
  StreamUpdate,
  Timeline,
  VolumeCreate,
  VolumeUpdate,
} from "./types"

/** Central client + polling interval bound to the current settings. */
export function useCentral() {
  const { settings } = useSettings()
  return { url: settings.centralUrl, api: centralClient(settings.centralUrl), poll: settings.pollSeconds * 1000 }
}

// ================================================================ central: reads

export function useClusterHealth() {
  const { url, api, poll } = useCentral()
  return useQuery({
    queryKey: [url, "cluster-health"],
    queryFn: () => unwrap<ClusterHealth>(api.GET("/api/v1/cluster/health")),
    refetchInterval: poll,
    retry: 1,
  })
}

export function useNodes(refetchMs?: number) {
  const { url, api, poll } = useCentral()
  return useQuery({
    queryKey: [url, "nodes"],
    queryFn: () => unwrap<MediaNode[]>(api.GET("/api/v1/nodes")),
    refetchInterval: refetchMs ?? poll,
  })
}

export function useNode(nodeId: number, refetchMs?: number) {
  const { url, api, poll } = useCentral()
  return useQuery({
    queryKey: [url, "nodes", nodeId],
    queryFn: () => unwrap<MediaNode>(api.GET("/api/v1/nodes/{node_id}", { params: { path: { node_id: nodeId } } })),
    refetchInterval: refetchMs ?? poll,
  })
}

export function useCameras() {
  const { url, api, poll } = useCentral()
  return useQuery({
    queryKey: [url, "cameras"],
    queryFn: () => unwrap<Camera[]>(api.GET("/api/v1/cameras")),
    refetchInterval: poll,
  })
}

export function useCamera(cameraId: number) {
  const { url, api, poll } = useCentral()
  return useQuery({
    queryKey: [url, "cameras", cameraId],
    queryFn: () =>
      unwrap<Camera>(api.GET("/api/v1/cameras/{camera_id}", { params: { path: { camera_id: cameraId } } })),
    refetchInterval: poll,
  })
}

export function useLive(cameraId: number | null) {
  const { url, api } = useCentral()
  return useQuery({
    queryKey: [url, "live", cameraId],
    enabled: cameraId != null,
    queryFn: () =>
      unwrap<LiveInfo>(api.GET("/api/v1/cameras/{camera_id}/live", { params: { path: { camera_id: cameraId! } } })),
    refetchInterval: 15_000, // picks up a new owner after failover
    retry: false,
  })
}

export function useTimeline(cameraId: number | null, profile: string, start: Date, end: Date, refetchMs = 30_000) {
  const { url, api } = useCentral()
  return useQuery({
    queryKey: [url, "timeline", cameraId, profile, start.toISOString(), end.toISOString()],
    enabled: cameraId != null,
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap<Timeline>(
        api.GET("/api/v1/cameras/{camera_id}/recordings", {
          params: {
            path: { camera_id: cameraId! },
            query: { profile, start: start.toISOString(), end: end.toISOString() },
          },
        }),
      ),
    refetchInterval: refetchMs,
  })
}

export function useAssignments() {
  const { url, api, poll } = useCentral()
  return useQuery({
    queryKey: [url, "assignments"],
    queryFn: () => unwrap<Assignment[]>(api.GET("/api/v1/assignments")),
    refetchInterval: poll,
  })
}

export function useAssignmentHistory(cameraId: number | null) {
  const { url, api } = useCentral()
  return useQuery({
    queryKey: [url, "assignment-history", cameraId],
    enabled: cameraId != null,
    queryFn: () =>
      unwrap<AssignmentHistory[]>(
        api.GET("/api/v1/assignments/{camera_id}/history", { params: { path: { camera_id: cameraId! } } }),
      ),
  })
}

// ================================================================ media node (direct, read-only)

export function useNodeStatus(apiUrl: string | undefined, refetchMs = 3000) {
  return useQuery({
    queryKey: ["node", apiUrl, "status"],
    enabled: !!apiUrl,
    queryFn: () => unwrap<NodeStatus>(nodeClient(apiUrl!).GET("/api/v1/status")),
    refetchInterval: refetchMs,
    retry: false,
  })
}

export function useNodeAssignments(apiUrl: string | undefined) {
  return useQuery({
    queryKey: ["node", apiUrl, "assignments"],
    enabled: !!apiUrl,
    queryFn: () => nodeGet<NodeAssignment[]>(apiUrl!, "/api/v1/assignments"),
    refetchInterval: 5000,
    retry: false,
  })
}

export function useNodePaths(apiUrl: string | undefined) {
  return useQuery({
    queryKey: ["node", apiUrl, "paths"],
    enabled: !!apiUrl,
    queryFn: () => nodeGet<MtxPath[]>(apiUrl!, "/api/v1/mediamtx/paths"),
    refetchInterval: 3000,
    retry: false,
  })
}

export function useNodeSegments(apiUrl: string | undefined, limit = 100) {
  return useQuery({
    queryKey: ["node", apiUrl, "segments", limit],
    enabled: !!apiUrl,
    queryFn: () => nodeGet<LocalSegment[]>(apiUrl!, "/api/v1/segments", { limit }),
    refetchInterval: 10_000,
    retry: false,
  })
}

export function useNodeLogs(apiUrl: string | undefined, source: "agent" | "mediamtx", paused: boolean) {
  return useQuery({
    queryKey: ["node", apiUrl, "logs", source],
    enabled: !!apiUrl,
    queryFn: () => nodeGet<NodeLogs>(apiUrl!, "/api/v1/logs", { source, lines: 500 }),
    refetchInterval: paused ? false : 3000,
    retry: false,
  })
}

// ================================================================ central: mutations

function useCentralMutation<TVars, TResult>(
  fn: (api: ReturnType<typeof useCentral>["api"], vars: TVars) => Promise<TResult>,
  opts: { success?: string | ((r: TResult, v: TVars) => string); invalidate?: string[] } = {},
) {
  const { url, api } = useCentral()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vars: TVars) => fn(api, vars),
    onSuccess: (result, vars) => {
      const keys = opts.invalidate ?? ["cameras", "nodes", "assignments", "cluster-health"]
      keys.forEach((k) => qc.invalidateQueries({ queryKey: [url, k] }))
      if (opts.success) toast.success(typeof opts.success === "function" ? opts.success(result, vars) : opts.success)
    },
    onError: (err: Error) => toast.error(err.message),
  })
}

export const useCreateCamera = () =>
  useCentralMutation((api, body: CameraCreate) => unwrap<Camera>(api.POST("/api/v1/cameras", { body })), {
    success: (c) => `Camera "${c.name}" added`,
  })

export const useUpdateCamera = () =>
  useCentralMutation(
    (api, { id, body }: { id: number; body: CameraUpdate }) =>
      unwrap<Camera>(api.PATCH("/api/v1/cameras/{camera_id}", { params: { path: { camera_id: id } }, body })),
    { success: "Camera updated" },
  )

export const useDeleteCamera = () =>
  useCentralMutation(
    (api, id: number) => unwrap(api.DELETE("/api/v1/cameras/{camera_id}", { params: { path: { camera_id: id } } })),
    { success: "Camera deleted" },
  )

/** Apply stream changes for an existing camera (add / update / remove profiles). */
export const useSyncStreams = () =>
  useCentralMutation(
    async (
      api,
      { id, add, update, remove }: { id: number; add: StreamIn[]; update: { profile: string; body: StreamUpdate }[]; remove: string[] },
    ) => {
      for (const body of add)
        await unwrap(api.POST("/api/v1/cameras/{camera_id}/streams", { params: { path: { camera_id: id } }, body }))
      for (const u of update)
        await unwrap(
          api.PATCH("/api/v1/cameras/{camera_id}/streams/{profile}", {
            params: { path: { camera_id: id, profile: u.profile } },
            body: u.body,
          }),
        )
      for (const profile of remove)
        await unwrap(
          api.DELETE("/api/v1/cameras/{camera_id}/streams/{profile}", { params: { path: { camera_id: id, profile } } }),
        )
    },
  )

export const useUpdateNode = () =>
  useCentralMutation(
    (api, { id, body }: { id: number; body: NodeUpdate }) =>
      unwrap<MediaNode>(api.PATCH("/api/v1/nodes/{node_id}", { params: { path: { node_id: id } }, body })),
    { success: (n) => `Limits saved for ${n.name}` },
  )

export type NodeAction = "drain" | "cordon" | "activate"

export const useNodeAction = () =>
  useCentralMutation(
    (api, { id, action }: { id: number; action: NodeAction }) => {
      const params = { params: { path: { node_id: id } } }
      const call =
        action === "drain"
          ? api.POST("/api/v1/nodes/{node_id}/drain", params)
          : action === "cordon"
            ? api.POST("/api/v1/nodes/{node_id}/cordon", params)
            : api.POST("/api/v1/nodes/{node_id}/activate", params)
      return unwrap<MediaNode>(call)
    },
    { success: (n) => `${n.name} is now ${n.state}` },
  )

export const useDeleteNode = () =>
  useCentralMutation(
    (api, { id, force }: { id: number; force: boolean }) =>
      unwrap(api.DELETE("/api/v1/nodes/{node_id}", { params: { path: { node_id: id }, query: { force } } })),
    { success: "Node removed" },
  )

// ---------------------------------------------------------------- storage volumes (where a node records)

const VOLUME_KEYS = ["nodes", "cluster-health"]

export const useAddVolume = () =>
  useCentralMutation(
    (api, { nodeId, body }: { nodeId: number; body: VolumeCreate }) =>
      unwrap<StorageVolume>(api.POST("/api/v1/nodes/{node_id}/volumes", { params: { path: { node_id: nodeId } }, body })),
    { success: (v) => `Storage added: ${v.path}`, invalidate: VOLUME_KEYS },
  )

export const useUpdateVolume = () =>
  useCentralMutation(
    (api, { nodeId, volumeId, body }: { nodeId: number; volumeId: number; body: VolumeUpdate }) =>
      unwrap<StorageVolume>(
        api.PATCH("/api/v1/nodes/{node_id}/volumes/{volume_id}", {
          params: { path: { node_id: nodeId, volume_id: volumeId } },
          body,
        }),
      ),
    { success: "Storage updated", invalidate: VOLUME_KEYS },
  )

export const useReorderVolumes = () =>
  useCentralMutation(
    (api, { nodeId, volumeIds }: { nodeId: number; volumeIds: number[] }) =>
      unwrap<StorageVolume[]>(
        api.POST("/api/v1/nodes/{node_id}/volumes/reorder", {
          params: { path: { node_id: nodeId } },
          body: { volume_ids: volumeIds },
        }),
      ),
    { success: "Fill order saved", invalidate: VOLUME_KEYS },
  )

export const useDeleteVolume = () =>
  useCentralMutation(
    (api, { nodeId, volumeId, force }: { nodeId: number; volumeId: number; force: boolean }) =>
      unwrap(
        api.DELETE("/api/v1/nodes/{node_id}/volumes/{volume_id}", {
          params: { path: { node_id: nodeId, volume_id: volumeId }, query: { force } },
        }),
      ),
    { success: "Storage removed", invalidate: VOLUME_KEYS },
  )

export const useMoveCamera = () =>
  useCentralMutation(
    (api, { cameraId, nodeId }: { cameraId: number; nodeId: number }) =>
      unwrap<Assignment>(
        api.PUT("/api/v1/assignments/{camera_id}", { params: { path: { camera_id: cameraId } }, body: { node_id: nodeId } }),
      ),
    { success: (a) => `${a.camera_name} moved to ${a.node_name}` },
  )

export const useRunScheduler = () =>
  useCentralMutation((api) => unwrap(api.POST("/api/v1/assignments/run-scheduler")), {
    success: "Scheduler cycle finished",
  })
