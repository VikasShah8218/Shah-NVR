import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { lazy } from "react"
import { BrowserRouter, Route, Routes } from "react-router"
import { AppLayout } from "@/components/layout/AppLayout"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { AuthProvider } from "@/lib/auth/AuthProvider"
import { Perm, CAMERA_READ } from "@/lib/auth/permissions"
import { HomeRoute, RequirePerm } from "@/lib/auth/RequirePerm"
import { SettingsProvider } from "@/lib/settings"

// Each page is its own chunk, loaded on first visit.
const GroupsPage = lazy(() => import("@/features/groups/GroupsPage").then((m) => ({ default: m.GroupsPage })))
const AssignmentsPage = lazy(() => import("@/features/assignments/AssignmentsPage").then((m) => ({ default: m.AssignmentsPage })))
const CameraDetailPage = lazy(() => import("@/features/cameras/CameraDetailPage").then((m) => ({ default: m.CameraDetailPage })))
const CamerasPage = lazy(() => import("@/features/cameras/CamerasPage").then((m) => ({ default: m.CamerasPage })))
const DiscoverPage = lazy(() => import("@/features/onvif/DiscoverPage").then((m) => ({ default: m.DiscoverPage })))
const DashboardPage = lazy(() => import("@/features/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })))
const LivePage = lazy(() => import("@/features/live/LivePage").then((m) => ({ default: m.LivePage })))
const NodeDetailPage = lazy(() => import("@/features/nodes/NodeDetailPage").then((m) => ({ default: m.NodeDetailPage })))
const NodesPage = lazy(() => import("@/features/nodes/NodesPage").then((m) => ({ default: m.NodesPage })))
const PlaybackPage = lazy(() => import("@/features/playback/PlaybackPage").then((m) => ({ default: m.PlaybackPage })))
const AccessPage = lazy(() => import("@/features/access/AccessPage").then((m) => ({ default: m.AccessPage })))
const AuditPage = lazy(() => import("@/features/audit/AuditPage").then((m) => ({ default: m.AuditPage })))
const SettingsPage = lazy(() => import("@/features/settings/SettingsPage").then((m) => ({ default: m.SettingsPage })))

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 2000, refetchOnWindowFocus: false } },
})

export default function App() {
  return (
    <SettingsProvider>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={300}>
          <BrowserRouter>
            {/* sign-in gate: when central requires it, nothing below renders before sign-in */}
            <AuthProvider>
              <Routes>
                <Route element={<AppLayout />}>
                  <Route index element={<HomeRoute perms={[Perm.DASHBOARD]}><DashboardPage /></HomeRoute>} />
                  <Route path="live" element={<RequirePerm any={[Perm.LIVE]}><LivePage /></RequirePerm>} />
                  <Route path="playback" element={<RequirePerm any={[Perm.PLAYBACK]}><PlaybackPage /></RequirePerm>} />
                  <Route path="cameras" element={<RequirePerm any={CAMERA_READ}><CamerasPage /></RequirePerm>} />
                  <Route path="cameras/:id" element={<RequirePerm any={CAMERA_READ}><CameraDetailPage /></RequirePerm>} />
                  <Route path="discover" element={<RequirePerm any={[Perm.CAMERAS_MANAGE]}><DiscoverPage /></RequirePerm>} />
                  <Route path="nodes" element={<RequirePerm any={[Perm.NODES_MANAGE]}><NodesPage /></RequirePerm>} />
                  <Route path="nodes/:id" element={<RequirePerm any={[Perm.NODES_MANAGE]}><NodeDetailPage /></RequirePerm>} />
                  <Route path="groups" element={<RequirePerm any={[Perm.GROUPS_MANAGE]}><GroupsPage /></RequirePerm>} />
                  <Route path="assignments" element={<RequirePerm any={[Perm.ASSIGNMENTS]}><AssignmentsPage /></RequirePerm>} />
                  <Route path="access" element={<RequirePerm any={[Perm.ACCESS_MANAGE]}><AccessPage /></RequirePerm>} />
                  <Route path="audit" element={<RequirePerm any={[Perm.AUDIT_VIEW]}><AuditPage /></RequirePerm>} />
                  <Route path="settings" element={<SettingsPage />} />
                </Route>
              </Routes>
            </AuthProvider>
          </BrowserRouter>
          <Toaster position="bottom-right" richColors />
        </TooltipProvider>
      </QueryClientProvider>
    </SettingsProvider>
  )
}
