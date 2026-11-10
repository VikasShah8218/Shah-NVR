import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { onvifErrorText } from "@/lib/onvif"
import { type NodeAccess, selectedNodeAccess, useNodeAccessMap } from "@/lib/nodeAccess"
import type { Paged } from "@/lib/pager"
import { useSettings } from "@/lib/settings"
import { ApiError, cancelExport, centralClient, createExport, listExports, nodeClient, nodeGet, unwrap } from "./client"
import type {
  Assignment,
  AssignmentHistory,
  BackfillConfig,
  BackfillConfigUpdate,
  BackfillJob,
  BackfillJobCreate,
  BackfillProbe,
  Bookmark,
  BookmarkCreate,
  BookmarkUpdate,
  AlertPage,
  Camera,
  CameraCreate,
  CameraOption,
  CameraUpdate,
  CameraGroup,
  ClusterHealth,
  GroupCreate,
  GroupDetail,
  GroupUpdate,
  LiveInfo,
  LocalSegment,
  MediaNode,
  MtxPath,
  NodeAssignment,
  NodeLogs,
  NodeStatus,
  NodeUpdate,
  OnvifCameraCreate,
  OnvifClock,
  OnvifDeviceIn,
  OnvifDeviceState,
  OnvifDiscovered,
  OnvifNtpIn,
  OnvifProbe,
  OnvifServer,
  OnvifServerUpdate,
  StreamIn,
  StorageVolume,
  StreamUpdate,
  Timeline,
  ExportCreate,
  ExportJob,
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

export function useOnvifServer(nodeId: number, refetchMs = 5000) {
  const { url, api } = useCentral()
  return useQuery({
    queryKey: [url, "onvif-server", nodeId],
    queryFn: () => unwrap<OnvifServer>(api.GET("/api/v1/nodes/{node_id}/onvif-server", { params: { path: { node_id: nodeId } } })),
    refetchInterval: refetchMs,
  })
}

/** Camera group filter of the camera lists: directly in a group, in its whole subtree, or in no group. */
export interface CameraScope {
  groupId?: number
  ungrouped?: boolean
  recursive?: boolean
}

const scopeQuery = (s: CameraScope) => ({
  group_id: s.groupId, ungrouped: s.ungrouped || undefined, recursive: s.recursive || undefined,
})

export interface CameraQuery extends CameraScope {
  q?: string
  enabled?: boolean
  nodeId?: number
  status?: Camera["streams"][number]["status"]
  limit: number
  offset: number
}

/** One page of full camera rows (Cameras page, node ONVIF tab). Keys start with [url, "cameras"], so every
 *  camera mutation still refreshes them. */
export function usePagedCameras(params: CameraQuery, enabled = true) {
  const { url, api, poll } = useCentral()
  const query = {
    q: params.q || undefined, enabled: params.enabled, node_id: params.nodeId, status: params.status,
    limit: params.limit, offset: params.offset, ...scopeQuery(params),
  }
  return useQuery({
    queryKey: [url, "cameras", "page", query],
    enabled,
    placeholderData: keepPreviousData,
    queryFn: () => unwrap<Paged<Camera>>(api.GET("/api/v1/cameras", { params: { query } })),
    refetchInterval: poll,
  })
}

/** Full rows for just these cameras (live tiles, the bulk-encoder list). Max 200 ids. */
export function useCamerasByIds(ids: number[]) {
  const { url, api, poll } = useCentral()
  const key = [...new Set(ids)].sort((a, b) => a - b).join(",")
  return useQuery({
    queryKey: [url, "cameras", "ids", key],
    enabled: key !== "",
    placeholderData: keepPreviousData,
    queryFn: async () =>
      (await unwrap<Paged<Camera>>(api.GET("/api/v1/cameras", { params: { query: { ids: key, limit: 200 } } }))).items,
    refetchInterval: poll,
  })
}

export const CAMERA_OPTIONS_PAGE = 50

const nextOffset = (last: Paged<unknown>) =>
  last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined

/** Small searchable camera rows for pickers and the live sidebar, loaded 50 at a time ("Load more").
 *  `scope` limits it to a camera group (the group tree); `poll` keeps status dots fresh; `active: false` waits. */
export function useCameraOptions(
  q: string,
  opts: { enabled?: boolean; nodeId?: number; scope?: CameraScope; poll?: boolean; active?: boolean } = {},
) {
  const { url, api, poll } = useCentral()
  const query = {
    q: q.trim() || undefined, enabled: opts.enabled, node_id: opts.nodeId, limit: CAMERA_OPTIONS_PAGE,
    ...scopeQuery(opts.scope ?? {}),
  }
  return useInfiniteQuery({
    queryKey: [url, "cameras", "options", query],
    enabled: opts.active ?? true,
    initialPageParam: 0,
    placeholderData: opts.scope ? undefined : keepPreviousData,
    queryFn: ({ pageParam }) =>
      unwrap<Paged<CameraOption>>(api.GET("/api/v1/cameras/options", { params: { query: { ...query, offset: pageParam } } })),
    getNextPageParam: nextOffset,
    refetchInterval: opts.poll ? poll : undefined,
  })
}

/** One page of camera picker rows for a table (Groups page: cameras of a group, "Add cameras" dialog). */
export function useCameraOptionsPage(params: { q?: string; scope: CameraScope; limit: number; offset: number }) {
  const { url, api, poll } = useCentral()
  const query = { q: params.q?.trim() || undefined, limit: params.limit, offset: params.offset, ...scopeQuery(params.scope) }
  return useQuery({
    queryKey: [url, "cameras", "options", "page", query],
    placeholderData: keepPreviousData,
    queryFn: () => unwrap<Paged<CameraOption>>(api.GET("/api/v1/cameras/options", { params: { query } })),
    refetchInterval: poll,
  })
}

// ---------------------------------------------------------------- camera groups (lazy tree)

export const GROUP_PAGE = 50

/** Direct sub-groups of one group (or the top level), 50 at a time. Only mounted (= expanded) tree nodes poll. */
export function useGroupChildren(parentId: number | null, active = true) {
  const { url, api, poll } = useCentral()
  return useInfiniteQuery({
    queryKey: [url, "groups", "children", parentId],
    enabled: active,
    initialPageParam: 0,
    queryFn: ({ pageParam }) => unwrap<Paged<CameraGroup>>(api.GET("/api/v1/groups", {
      params: { query: { parent_id: parentId ?? undefined, limit: GROUP_PAGE, offset: pageParam } },
    })),
    getNextPageParam: nextOffset,
    refetchInterval: poll,
  })
}

/** One page of sub-groups for a table (Groups page). */
export function useGroupPage(parentId: number | null, limit: number, offset: number) {
  const { url, api, poll } = useCentral()
  return useQuery({
    queryKey: [url, "groups", "page", parentId, limit, offset],
    placeholderData: keepPreviousData,
    queryFn: () => unwrap<Paged<CameraGroup>>(api.GET("/api/v1/groups", {
      params: { query: { parent_id: parentId ?? undefined, limit, offset } },
    })),
    refetchInterval: poll,
  })
}

export function useGroup(groupId: number | null) {
  const { url, api, poll } = useCentral()
  return useQuery({
    queryKey: [url, "groups", "one", groupId],
    enabled: groupId != null,
    queryFn: () => unwrap<GroupDetail>(api.GET("/api/v1/groups/{group_id}", { params: { path: { group_id: groupId! } } })),
    refetchInterval: poll,
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  })
}

/** Groups whose name matches, anywhere in the tree (with their full path label). */
export function useGroupSearch(q: string, limit = 20) {
  const { url, api } = useCentral()
  const term = q.trim()
  return useQuery({
    queryKey: [url, "groups", "search", term, limit],
    enabled: term !== "",
    placeholderData: keepPreviousData,
    queryFn: () => unwrap<Paged<CameraGroup>>(api.GET("/api/v1/groups/search", { params: { query: { q: term, limit } } })),
  })
}

/** Camera alerts built by central (danger first). Node alerts are still built in the dashboard. */
export function useAlerts(params: { level?: "danger" | "warning"; limit: number; offset: number }) {
  const { url, api, poll } = useCentral()
  return useQuery({
    queryKey: [url, "cluster-alerts", params],
    placeholderData: keepPreviousData,
    queryFn: () => unwrap<AlertPage>(api.GET("/api/v1/cluster/alerts", { params: { query: params } })),
    refetchInterval: poll,
  })
}

export function useCamera(cameraId: number, enabled = true) {
  const { url, api, poll } = useCentral()
  return useQuery({
    queryKey: [url, "cameras", cameraId],
    enabled,
    queryFn: () =>
      unwrap<Camera>(api.GET("/api/v1/cameras/{camera_id}", { params: { path: { camera_id: cameraId } } })),
    refetchInterval: poll,
  })
}

export function useLive(cameraId: number | null) {
  const { url, api } = useCentral()
  const { settings } = useSettings()
  const nodes = useNodes(30_000)
  const detected = useNodeAccessMap(nodes.data ?? [])
  const primaryAccess = settings.nodeAccess === "lan" ? "lan" : "public"
  const primary = useQuery({
    queryKey: [url, "live", cameraId, primaryAccess],
    enabled: cameraId != null,
    queryFn: () =>
      unwrap<LiveInfo>(api.GET("/api/v1/cameras/{camera_id}/live", {
        params: { path: { camera_id: cameraId! }, query: { access: primaryAccess } },
      })),
    refetchInterval: 15_000, // picks up a new owner after failover
    retry: false,
  })
  const node = nodes.data?.find((candidate) => candidate.id === primary.data?.node_id)
  const resolvedAccess = node ? selectedNodeAccess(node, settings.nodeAccess, detected.data) : primaryAccess
  const alternate = useQuery({
    queryKey: [url, "live", cameraId, resolvedAccess],
    enabled: cameraId != null && !!primary.data && resolvedAccess !== primaryAccess,
    queryFn: () =>
      unwrap<LiveInfo>(api.GET("/api/v1/cameras/{camera_id}/live", {
        params: { path: { camera_id: cameraId! }, query: { access: resolvedAccess } },
      })),
    refetchInterval: 15_000,
    retry: false,
  })
  return resolvedAccess !== primaryAccess && (alternate.data || alternate.error) ? alternate : primary
}

/** The lan/public choice for a camera's assigned node, matching how useLive resolves it. */
export function useResolvedAccess(cameraId: number | null): NodeAccess {
  const { settings } = useSettings()
  const nodes = useNodes(30_000)
  const detected = useNodeAccessMap(nodes.data ?? [])
  const live = useLive(cameraId)
  const node = nodes.data?.find((candidate) => candidate.id === live.data?.node_id)
  const fallback: NodeAccess = settings.nodeAccess === "lan" ? "lan" : "public"
  return node ? selectedNodeAccess(node, settings.nodeAccess, detected.data) : fallback
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

export function useBackfill(cameraId: number, enabled = true) {
  const { url, api } = useCentral()
  return useQuery({
    queryKey: [url, "backfill", cameraId],
    enabled,
    queryFn: () => unwrap<BackfillConfig>(api.GET("/api/v1/cameras/{camera_id}/backfill", {
      params: { path: { camera_id: cameraId } },
    })),
  })
}

export function useBackfillJobs(cameraId: number, enabled = true, page = { limit: 10, offset: 0 }) {
  const { url, api } = useCentral()
  return useQuery({
    queryKey: [url, "backfill-jobs", cameraId, page],
    enabled,
    placeholderData: keepPreviousData,
    queryFn: () => unwrap<Paged<BackfillJob>>(api.GET("/api/v1/cameras/{camera_id}/backfill/jobs", {
      params: { path: { camera_id: cameraId }, query: page },
    })),
    refetchInterval: 3000,
  })
}

export function useExports(cameraId: number | null, page = { limit: 10, offset: 0 }) {
  const { url } = useCentral()
  return useQuery({
    queryKey: [url, "exports", cameraId, page], enabled: cameraId != null,
    placeholderData: keepPreviousData,
    queryFn: () => listExports(url, cameraId!, page.limit, page.offset), refetchInterval: 3000,
  })
}

export function useCreateExport() {
  const { url } = useCentral()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ExportCreate) => createExport(url, body),
    onSuccess: (job: ExportJob) => { qc.invalidateQueries({ queryKey: [url, "exports", job.camera_id] }); toast.success("Export queued") },
    onError: (error: Error) => toast.error(error.message),
  })
}

export function useCancelExport() {
  const { url } = useCentral()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id }: { id: string; cameraId: number }) => cancelExport(url, id),
    onSuccess: (_job, values) => { qc.invalidateQueries({ queryKey: [url, "exports", values.cameraId] }); toast.success("Export cancelled") },
    onError: (error: Error) => toast.error(error.message),
  })
}

export interface BookmarkQuery {
  cameraId?: number | null
  /** also returns camera-wide bookmarks (no profile) */
  profile?: string
  q?: string
  start?: Date
  end?: Date
  /** by start time; "desc" = newest first (search lists) */
  order?: "asc" | "desc"
  limit?: number
  offset?: number
}

export function useBookmarks(params: BookmarkQuery, enabled = true) {
  const { url, api } = useCentral()
  const query = {
    camera_id: params.cameraId ?? undefined,
    profile: params.profile || undefined,
    q: params.q?.trim() || undefined,
    start: params.start?.toISOString(),
    end: params.end?.toISOString(),
    order: params.order,
    limit: params.limit,
    offset: params.offset,
  }
  return useQuery({
    queryKey: [url, "bookmarks", query],
    enabled,
    placeholderData: keepPreviousData,
    queryFn: () => unwrap<Paged<Bookmark>>(api.GET("/api/v1/bookmarks", { params: { query } })),
  })
}

export const useCreateBookmark = () =>
  useCentralMutation((api, body: BookmarkCreate) => unwrap<Bookmark>(api.POST("/api/v1/bookmarks", { body })), {
    success: "Bookmark added",
    invalidate: ["bookmarks"],
  })

export const useUpdateBookmark = () =>
  useCentralMutation(
    (api, { id, body }: { id: number; body: BookmarkUpdate }) =>
      unwrap<Bookmark>(api.PATCH("/api/v1/bookmarks/{bookmark_id}", { params: { path: { bookmark_id: id } }, body })),
    { success: "Bookmark updated", invalidate: ["bookmarks"] },
  )

export const useDeleteBookmark = () =>
  useCentralMutation(
    (api, id: number) => unwrap(api.DELETE("/api/v1/bookmarks/{bookmark_id}", { params: { path: { bookmark_id: id } } })),
    { success: "Bookmark deleted", invalidate: ["bookmarks"] },
  )

export function useAssignments(params: { q?: string; nodeId?: number; limit: number; offset: number }) {
  const { url, api, poll } = useCentral()
  const query = { q: params.q || undefined, node_id: params.nodeId, limit: params.limit, offset: params.offset }
  return useQuery({
    queryKey: [url, "assignments", query],
    placeholderData: keepPreviousData,
    queryFn: () => unwrap<Paged<Assignment>>(api.GET("/api/v1/assignments", { params: { query } })),
    refetchInterval: poll,
  })
}

export function useAssignmentHistory(cameraId: number | null, page = { limit: 10, offset: 0 }) {
  const { url, api } = useCentral()
  return useQuery({
    queryKey: [url, "assignment-history", cameraId, page],
    enabled: cameraId != null,
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap<Paged<AssignmentHistory>>(
        api.GET("/api/v1/assignments/{camera_id}/history", { params: { path: { camera_id: cameraId! }, query: page } }),
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

export function useNodeSegments(apiUrl: string | undefined, limit = 50, offset = 0) {
  return useQuery({
    queryKey: ["node", apiUrl, "segments", limit, offset],
    enabled: !!apiUrl,
    placeholderData: keepPreviousData,
    queryFn: () => nodeGet<Paged<LocalSegment>>(apiUrl!, "/api/v1/segments", { limit, offset }),
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
  opts: { success?: string | ((r: TResult, v: TVars) => string); invalidate?: string[]; errorText?: (err: Error) => string } = {},
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
    onError: (err: Error) => toast.error(opts.errorText ? opts.errorText(err) : err.message),
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

const GROUP_KEYS = ["groups", "cameras"]

export const useCreateGroup = () =>
  useCentralMutation((api, body: GroupCreate) => unwrap<GroupDetail>(api.POST("/api/v1/groups", { body })), {
    invalidate: GROUP_KEYS, success: (g) => `Group "${g.name}" created`,
  })

export const useUpdateGroup = () =>
  useCentralMutation(
    (api, { id, body }: { id: number; body: GroupUpdate }) =>
      unwrap<GroupDetail>(api.PATCH("/api/v1/groups/{group_id}", { params: { path: { group_id: id } }, body })),
    { invalidate: GROUP_KEYS, success: "Group updated" },
  )

export const useDeleteGroup = () =>
  useCentralMutation(
    (api, { id, moveChildren }: { id: number; moveChildren: boolean }) =>
      unwrap(api.DELETE("/api/v1/groups/{group_id}", {
        params: { path: { group_id: id }, query: { move_children: moveChildren ? "parent" : undefined } },
      })),
    { invalidate: GROUP_KEYS, success: "Group deleted" },
  )

/** Move cameras into a group (`groupId: null` = out of every group). */
export const useAssignCameras = () =>
  useCentralMutation(
    (api, { cameraIds, groupId }: { cameraIds: number[]; groupId: number | null }) =>
      unwrap<{ updated: number }>(api.POST("/api/v1/groups/assign", { body: { camera_ids: cameraIds, group_id: groupId } })),
    {
      invalidate: GROUP_KEYS,
      success: (r, v) => `${r.updated} camera${r.updated === 1 ? "" : "s"} ${v.groupId == null ? "removed from group" : "moved"}`,
    },
  )

const BACKFILL_KEYS = ["backfill", "backfill-jobs", "timeline"]

export const useProbeBackfill = () =>
  useCentralMutation(
    (api, cameraId: number) => unwrap<BackfillProbe>(api.POST("/api/v1/cameras/{camera_id}/backfill/probe", {
      params: { path: { camera_id: cameraId } },
    })),
    { success: "Camera edge storage tested", invalidate: BACKFILL_KEYS, errorText: onvifErrorText },
  )

export const useUpdateBackfill = () =>
  useCentralMutation(
    (api, { cameraId, body }: { cameraId: number; body: BackfillConfigUpdate }) =>
      unwrap<BackfillConfig>(api.PATCH("/api/v1/cameras/{camera_id}/backfill", {
        params: { path: { camera_id: cameraId } }, body,
      })),
    { success: "Edge-storage settings saved", invalidate: BACKFILL_KEYS },
  )

export const useCreateBackfillJob = () =>
  useCentralMutation(
    (api, { cameraId, body }: { cameraId: number; body: BackfillJobCreate }) =>
      unwrap<BackfillJob>(api.POST("/api/v1/cameras/{camera_id}/backfill/jobs", {
        params: { path: { camera_id: cameraId } }, body,
      })),
    { success: "Backfill job queued", invalidate: BACKFILL_KEYS },
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
    { success: (n) => `Node settings saved for ${n.name}` },
  )

export const useUpdateOnvifServer = () =>
  useCentralMutation(
    (api, { id, body }: { id: number; body: OnvifServerUpdate }) =>
      unwrap<OnvifServer>(api.PATCH("/api/v1/nodes/{node_id}/onvif-server", { params: { path: { node_id: id } }, body })),
    { success: "ONVIF server configuration saved", invalidate: ["nodes", "onvif-server"] },
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

// ================================================================ ONVIF (H1): discovery, add, device management

/** Scan the LAN of one node (or all online nodes). Errors are shown by the page, not as toasts. */
export function useOnvifDiscover() {
  const { api } = useCentral()
  return useMutation({
    mutationFn: (body: { node_id?: number | null; seconds?: number }) =>
      unwrap<OnvifDiscovered[]>(api.POST("/api/v1/onvif/discover", { body: { seconds: 3, ...body } })),
  })
}

/** Probe one device (identity, clock, profiles). One login attempt; the caller shows the error. */
export function useOnvifProbeCall() {
  const { api } = useCentral()
  return (body: OnvifDeviceIn) => unwrap<OnvifProbe>(api.POST("/api/v1/onvif/probe", { body }))
}

/** Add one camera from ONVIF; the caller shows per-camera results (no toast here). */
export function useOnvifAddCall() {
  const { url, api } = useCentral()
  const qc = useQueryClient()
  return async (body: OnvifCameraCreate) => {
    const cam = await unwrap<Camera>(api.POST("/api/v1/onvif/cameras", { body }))
    ;["cameras", "assignments", "cluster-health"].forEach((k) => qc.invalidateQueries({ queryKey: [url, k] }))
    return cam
  }
}

/** JPEG preview through central -> node -> camera, as an object URL (revoke it when done). */
export function useOnvifSnapshotCall() {
  const { url } = useCentral()
  return async (body: OnvifDeviceIn & { uri: string }): Promise<string> => {
    let res: Response
    try {
      res = await fetch(`${url}/api/v1/onvif/snapshot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
    } catch {
      throw new ApiError(0, "Server unreachable")
    }
    if (!res.ok) throw new ApiError(res.status, `Snapshot failed (HTTP ${res.status})`)
    return URL.createObjectURL(await res.blob())
  }
}

/** Live device state of a camera (calls the camera, so no polling: refresh on demand). */
export function useCameraDevice(cameraId: number, enabled: boolean) {
  const { url, api } = useCentral()
  return useQuery({
    queryKey: [url, "onvif-device", cameraId],
    enabled,
    retry: false,
    staleTime: 30_000,
    queryFn: () =>
      unwrap<OnvifDeviceState>(api.GET("/api/v1/onvif/cameras/{camera_id}/device", { params: { path: { camera_id: cameraId } } })),
  })
}

const DEVICE_KEYS = ["cameras", "onvif-device"]

export const useCameraTimeSync = () =>
  useCentralMutation(
    (api, cameraId: number) =>
      unwrap<OnvifClock>(api.POST("/api/v1/onvif/cameras/{camera_id}/time-sync", { params: { path: { camera_id: cameraId } } })),
    { success: "Camera clock set to the node's time", invalidate: DEVICE_KEYS, errorText: onvifErrorText },
  )

export const useCameraNtp = () =>
  useCentralMutation(
    (api, { cameraId, body }: { cameraId: number; body: OnvifNtpIn }) =>
      unwrap(api.POST("/api/v1/onvif/cameras/{camera_id}/ntp", { params: { path: { camera_id: cameraId } }, body })),
    { success: "NTP settings saved on the camera", invalidate: DEVICE_KEYS, errorText: onvifErrorText },
  )

export const useCameraReboot = () =>
  useCentralMutation(
    (api, cameraId: number) =>
      unwrap<{ message: string }>(api.POST("/api/v1/onvif/cameras/{camera_id}/reboot", { params: { path: { camera_id: cameraId } } })),
    { success: (r) => `Camera: ${r.message}`, invalidate: DEVICE_KEYS, errorText: onvifErrorText },
  )
