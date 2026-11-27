import { Loader2, Radar, Zap } from "lucide-react"
import { useState } from "react"
import { useProbeCameraEvents, useUpdateCamera } from "@/api/queries"
import type { Camera } from "@/api/types"
import { Field } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import {
  ANALYTICS_KINDS, CAMERA_EVENT_KINDS, CAMERA_EVENT_LABELS, type CameraEventKind, type CameraEventsStatus,
  cameraEventsStatusLine, kindsBody, kindTitle, savedKinds, withKind,
} from "@/lib/cameraEvents"
import { timeAgo } from "@/lib/format"

const TONE = { success: "text-success", warning: "text-warning", danger: "text-danger", muted: "text-muted-foreground" }

/** Camera events from ONVIF (docs/ONVIF_EVENTS_PLAN.md §7): switch, kinds, Detect, live status.
 * Mount with `key={cameraEventsKey(camera)}` so saved changes reset the draft. */
export function CameraEventsTab({ camera: c }: { camera: Camera }) {
  const update = useUpdateCamera()
  const probe = useProbeCameraEvents()
  const [enabled, setEnabled] = useState(c.onvif_events_enabled ?? false)
  const [kinds, setKinds] = useState<CameraEventKind[]>(savedKinds(c.onvif_event_kinds))
  const [storeOther, setStoreOther] = useState(c.onvif_events_store_other ?? false)

  const status = c.onvif_events_status as CameraEventsStatus | null | undefined
  const offered = status?.offered ?? null
  const dirty = enabled !== (c.onvif_events_enabled ?? false) || storeOther !== (c.onvif_events_store_other ?? false)
    || kinds.join() !== savedKinds(c.onvif_event_kinds).join()
  // analytics: the kinds the camera offers first; rules from the last Detect
  const analytics = probe.data?.analytics ?? status?.analytics ?? []
  const offeredAnalytics = ANALYTICS_KINDS.filter((k) => offered?.includes(k) || kinds.includes(k))
  const otherAnalytics = ANALYTICS_KINDS.filter((k) => !offeredAnalytics.includes(k))
  const rulesOf = (k: string) => analytics.find((a) => a.kind === k)?.rules ?? []
  const line = cameraEventsStatusLine(c.onvif_events_enabled ?? false, kinds, status, (iso) => timeAgo(iso))

  const toggle = (k: CameraEventKind, on: boolean) => setKinds((cur) => withKind(cur, k, on))
  const save = () => update.mutate({
    id: c.id,
    body: { onvif_events_enabled: enabled, onvif_event_kinds: kindsBody(kinds), onvif_events_store_other: storeOther },
  })
  const kindRow = (k: CameraEventKind, notOffered: boolean) => {
    const rules = rulesOf(k)
    return (
      <label key={k} className={`flex items-center justify-between rounded-md border px-3 py-2 text-sm ${enabled ? "" : "opacity-60"}`}>
        <span className="min-w-0">
          {CAMERA_EVENT_LABELS[k].title}
          <span className="block text-xs text-muted-foreground">
            {notOffered ? "Not offered by this camera" : CAMERA_EVENT_LABELS[k].hint}
          </span>
          {rules.length > 0 && (
            <span className="block truncate text-xs text-muted-foreground" title={rules.map((r) => r.name).join(", ")}>
              Rules: {rules.map((r) => r.name).join(", ")}
            </span>
          )}
        </span>
        <Switch checked={kinds.includes(k)} disabled={!enabled} onCheckedChange={(on) => toggle(k, on)} />
      </label>
    )
  }

  if (!c.onvif_host) {
    return (
      <Card><CardContent className="py-6 text-sm text-muted-foreground">
        This camera has no ONVIF address yet. Open the Device tab once (or add the camera through ONVIF) to use camera events.
      </CardContent></Card>
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-col items-stretch justify-between gap-3 sm:flex-row sm:items-center">
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <Zap className="size-4" /> Camera events
          </CardTitle>
          <Button variant="outline" size="sm" onClick={() => probe.mutate(c.id)} disabled={probe.isPending}>
            {probe.isPending ? <Loader2 className="size-4 animate-spin" /> : <Radar className="size-4" />} Detect
          </Button>
        </CardHeader>
        <CardContent className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-3">
            <label className="flex items-center justify-between rounded-md border px-3 py-2.5 text-sm">
              <span>
                Use camera events
                <span className="block text-xs text-muted-foreground">
                  The camera tells Shah-NVR about motion, tamper and inputs. Each event keeps video in Event mode and
                  shows as a mark on the playback timeline.
                </span>
              </span>
              <Switch checked={enabled} onCheckedChange={setEnabled} />
            </label>
            {CAMERA_EVENT_KINDS.map((k) => kindRow(k, offered !== null && !offered.includes(k)))}
            <p className="pt-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Analytics</p>
            {offeredAnalytics.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {offered ? "This camera offers no analytics." : "Press Detect to see which analytics the camera offers."}
              </p>
            )}
            {offeredAnalytics.map((k) => kindRow(k, offered !== null && !offered.includes(k)))}
            {otherAnalytics.length > 0 && (
              <details className="text-sm">
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  {offered ? `Not offered by this camera (${otherAnalytics.length})` : `All analytics kinds (${otherAnalytics.length})`}
                </summary>
                <div className="mt-2 space-y-2">{otherAnalytics.map((k) => kindRow(k, offered !== null))}</div>
              </details>
            )}
            <p className="text-xs text-muted-foreground">
              Analytics are off until you switch them on. Set up lines and zones in the camera's own web page.
            </p>
            <label className={`flex items-center justify-between rounded-md border px-3 py-2 text-sm ${enabled ? "" : "opacity-60"}`}>
              <span>
                Also store other camera events
                <span className="block text-xs text-muted-foreground">
                  Any other event the camera sends, as a grey "Camera event" mark. PTZ and health messages are never stored.
                </span>
              </span>
              <Switch checked={storeOther} disabled={!enabled} onCheckedChange={setStoreOther} />
            </label>
            <Button onClick={save} disabled={!dirty || update.isPending || (enabled && !kinds.length && !storeOther)}>
              {update.isPending && <Loader2 className="size-4 animate-spin" />} Save
            </Button>
          </div>
          <div className="space-y-1">
            <p className={`text-sm ${TONE[line.tone]}`}>{line.text}</p>
            {status?.since && c.onvif_events_enabled && (
              <Field label="Since">{timeAgo(status.since)}</Field>
            )}
            <Field label="Camera offers">
              {offered ? (offered.length ? offered.map(kindTitle).join(", ") : "None of these events") : "Not detected yet"}
            </Field>
            {Object.entries(status?.topics ?? {}).map(([k, topic]) => (
              <Field key={k} label={kindTitle(k)}><span className="break-all font-mono text-xs">{topic}</span></Field>
            ))}
            {probe.data && (
              <details className="pt-2 text-xs text-muted-foreground">
                <summary className="cursor-pointer">All {probe.data.all_topics.length} topics the camera lists</summary>
                <ul className="mt-1 space-y-0.5 font-mono">{probe.data.all_topics.map((t) => <li key={t} className="break-all">{t}</li>)}</ul>
              </details>
            )}
            <p className="pt-2 text-xs text-muted-foreground">
              Shah-NVR does not change camera settings. If a kind is missing, enable it in the camera's own web page
              (for example the motion detection app on AXIS), then press Detect.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
