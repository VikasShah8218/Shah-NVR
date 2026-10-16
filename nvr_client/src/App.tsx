import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { lazy } from "react"
import { BrowserRouter, Route, Routes } from "react-router"
import { AppLayout } from "@/components/layout/AppLayout"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { SettingsProvider } from "@/lib/settings"

// Each page is its own chunk, loaded on first visit.
const AssignmentsPage = lazy(() => import("@/features/assignments/AssignmentsPage").then((m) => ({ default: m.AssignmentsPage })))
const CameraDetailPage = lazy(() => import("@/features/cameras/CameraDetailPage").then((m) => ({ default: m.CameraDetailPage })))
const CamerasPage = lazy(() => import("@/features/cameras/CamerasPage").then((m) => ({ default: m.CamerasPage })))
const DiscoverPage = lazy(() => import("@/features/onvif/DiscoverPage").then((m) => ({ default: m.DiscoverPage })))
const DashboardPage = lazy(() => import("@/features/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })))
const LivePage = lazy(() => import("@/features/live/LivePage").then((m) => ({ default: m.LivePage })))
const NodeDetailPage = lazy(() => import("@/features/nodes/NodeDetailPage").then((m) => ({ default: m.NodeDetailPage })))
const NodesPage = lazy(() => import("@/features/nodes/NodesPage").then((m) => ({ default: m.NodesPage })))
const PlaybackPage = lazy(() => import("@/features/playback/PlaybackPage").then((m) => ({ default: m.PlaybackPage })))
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
            <Routes>
              <Route element={<AppLayout />}>
                <Route index element={<DashboardPage />} />
                <Route path="live" element={<LivePage />} />
                <Route path="playback" element={<PlaybackPage />} />
                <Route path="cameras" element={<CamerasPage />} />
                <Route path="cameras/:id" element={<CameraDetailPage />} />
                <Route path="discover" element={<DiscoverPage />} />
                <Route path="nodes" element={<NodesPage />} />
                <Route path="nodes/:id" element={<NodeDetailPage />} />
                <Route path="assignments" element={<AssignmentsPage />} />
                <Route path="settings" element={<SettingsPage />} />
              </Route>
            </Routes>
          </BrowserRouter>
          <Toaster position="bottom-right" richColors />
        </TooltipProvider>
      </QueryClientProvider>
    </SettingsProvider>
  )
}
