import { useNavigate } from "react-router"
import type { NvrEvent } from "@/api/types"
import { PageHeader } from "@/components/common"
import { EventsPanel } from "./EventsPanel"

/** Every event the user may see (docs/EVENT_RECORDING_PLAN.md §6.6). A click opens playback from the pre-event seconds. */
export function EventsPage() {
  const navigate = useNavigate()
  const open = (e: NvrEvent) =>
    navigate(`/playback?camera=${e.camera_id}&t=${new Date(Date.parse(e.start_time) - e.pre_seconds * 1000).toISOString()}`)
  return (
    <div className="space-y-4">
      <PageHeader title="Events" description="Camera events (motion, analytics…), marked events and video loss, newest first. Click one to play it." />
      <EventsPanel allCameras onOpen={open} />
    </div>
  )
}
