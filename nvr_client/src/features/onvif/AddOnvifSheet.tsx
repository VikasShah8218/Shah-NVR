import { AlertTriangle, CheckCircle2, Clock, ImageOff, Loader2, ShieldAlert } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Link } from "react-router"
import { useOnvifAddCall, useOnvifProbeCall, useOnvifSnapshotCall } from "@/api/queries"
import type { OnvifDiscovered, OnvifProbe } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Switch } from "@/components/ui/switch"
import { CLOCK_DRIFT_ALERT_SECONDS, formatOffset, isVideoProfile, onvifErrorText, profileSummary } from "@/lib/onvif"
import { cn } from "@/lib/utils"

type RowStatus = "idle" | "checking" | "ready" | "error" | "adding" | "added"

interface Row {
  device: OnvifDiscovered
  status: RowStatus
  error?: string
  probe?: OnvifProbe
  name: string
  main: string
  sub: string // "" = no sub stream
  recordSub: boolean
  snapshot?: string | null // object URL; null = no preview
  cameraId?: number
}

const NO_SUB = "__none__"
const CONCURRENCY = 4

/** Check (probe) the selected devices with one set of credentials, review main/sub, then add them. */
export function AddOnvifSheet({
  devices,
  open,
  onOpenChange,
}: {
  devices: OnvifDiscovered[]
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const probeCall = useOnvifProbeCall()
  const addCall = useOnvifAddCall()
  const snapshotCall = useOnvifSnapshotCall()
  const [username, setUsername] = useState("admin")
  const [password, setPassword] = useState("")
  const [rows, setRows] = useState<Row[]>(() =>
    devices.map((d) => ({ device: d, status: "idle", name: "", main: "", sub: "", recordSub: false })),
  )
  const urls = useRef<string[]>([])
  useEffect(() => () => urls.current.forEach((u) => URL.revokeObjectURL(u)), [])

  const patch = (endpoint: string, p: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.device.endpoint === endpoint ? { ...r, ...p } : r)))

  const creds = (d: OnvifDiscovered) => ({
    node_id: d.node_id,
    host: d.host,
    port: d.port,
    xaddr: d.xaddr,
    username,
    password,
  })

  async function checkOne(r: Row) {
    const d = r.device
    patch(d.endpoint, { status: "checking", error: undefined })
    try {
      const probe = await probeCall(creds(d))
      const label = [probe.info.manufacturer, probe.info.model].filter(Boolean).join(" ")
      const main = probe.suggested.main ?? ""
      patch(d.endpoint, {
        status: "ready",
        probe,
        name: r.name || `${label || d.name || "Camera"} (${d.host})`,
        main,
        sub: probe.suggested.sub ?? "",
      })
      const snapUri = probe.profiles.find((p) => p.token === main)?.snapshot
      if (snapUri) {
        snapshotCall({ ...creds(d), uri: snapUri })
          .then((u) => {
            urls.current.push(u)
            patch(d.endpoint, { snapshot: u })
          })
          .catch(() => patch(d.endpoint, { snapshot: null }))
      } else patch(d.endpoint, { snapshot: null })
    } catch (err) {
      patch(d.endpoint, { status: "error", error: onvifErrorText(err) })
    }
  }

  async function checkAll() {
    const todo = rows.filter((r) => r.status === "idle" || r.status === "error")
    for (let i = 0; i < todo.length; i += CONCURRENCY) await Promise.all(todo.slice(i, i + CONCURRENCY).map(checkOne))
  }

  async function addAll() {
    for (const r of rows.filter((x) => x.status === "ready")) {
      patch(r.device.endpoint, { status: "adding" })
      try {
        const streams = [{ profile: "main", token: r.main, record: true }]
        if (r.sub) streams.push({ profile: "sub", token: r.sub, record: r.recordSub })
        const cam = await addCall({ ...creds(r.device), name: r.name.trim() || null, streams, enabled: true, allow_duplicate: false })
        patch(r.device.endpoint, { status: "added", cameraId: cam.id })
      } catch (err) {
        patch(r.device.endpoint, { status: "error", error: onvifErrorText(err) })
      }
    }
  }

  const busy = rows.some((r) => r.status === "checking" || r.status === "adding")
  const ready = rows.filter((r) => r.status === "ready").length
  const unchecked = rows.filter((r) => r.status === "idle" || r.status === "error").length
  const added = rows.filter((r) => r.status === "added").length

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 data-[side=right]:sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>Add {devices.length === 1 ? "camera" : `${devices.length} cameras`}</SheetTitle>
          <SheetDescription>
            One login for all selected cameras. Streams are read from the camera: main = highest resolution (recorded), sub =
            lowest (live view in grids).
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 space-y-4 overflow-y-auto px-4 pb-4">
          <div className="grid gap-3 rounded-lg border p-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <div className="grid gap-1.5">
              <Label htmlFor="onvif-user">Username</Label>
              <Input id="onvif-user" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="onvif-pass">Password</Label>
              <Input
                id="onvif-pass"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                onKeyDown={(e) => e.key === "Enter" && unchecked && !busy && checkAll()}
              />
            </div>
            <Button onClick={checkAll} disabled={busy || unchecked === 0}>
              {rows.some((r) => r.status === "checking") && <Loader2 className="size-4 animate-spin" />}
              Check {unchecked > 1 ? `${unchecked} cameras` : "camera"}
            </Button>
            <p className="flex items-start gap-1.5 text-xs text-muted-foreground sm:col-span-3">
              <ShieldAlert className="mt-px size-3.5 shrink-0" />
              Each check is one login. A wrong password is never retried automatically, because many cameras lock the
              account after a few failures.
            </p>
          </div>

          {rows.map((r) => (
            <DeviceRow key={r.device.endpoint} row={r} onChange={(p) => patch(r.device.endpoint, p)} />
          ))}
        </div>

        <SheetFooter className="border-t">
          {added === rows.length ? (
            <Button onClick={() => onOpenChange(false)}>Done</Button>
          ) : (
            <Button onClick={addAll} disabled={busy || ready === 0}>
              {rows.some((r) => r.status === "adding") && <Loader2 className="size-4 animate-spin" />}
              Add {ready > 1 ? `${ready} cameras` : "camera"}
            </Button>
          )}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {added ? "Close" : "Cancel"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

function DeviceRow({ row: r, onChange }: { row: Row; onChange: (p: Partial<Row>) => void }) {
  const d = r.device
  const video = (r.probe?.profiles ?? []).filter(isVideoProfile)
  const offset = r.probe?.clock.offset_seconds
  const editable = r.status === "ready"

  return (
    <div className={cn("rounded-lg border p-3", r.status === "added" && "border-success/40 bg-success/5")}>
      <div className="flex gap-3">
        {r.probe && (
          <div className="grid aspect-video w-36 shrink-0 place-items-center overflow-hidden rounded-md bg-video text-muted-foreground">
            {r.snapshot ? (
              <img src={r.snapshot} alt="" className="size-full object-cover" />
            ) : r.snapshot === null ? (
              <ImageOff className="size-5" />
            ) : (
              <Loader2 className="size-4 animate-spin" />
            )}
          </div>
        )}
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm">{d.host}{d.port !== 80 ? `:${d.port}` : ""}</span>
            <RowBadge row={r} />
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {r.probe
              ? [r.probe.info.manufacturer, r.probe.info.model, r.probe.info.firmwareversion && `fw ${r.probe.info.firmwareversion}`]
                  .filter(Boolean)
                  .join(" · ")
              : d.name || d.hardware || "ONVIF device"}
          </div>
          {r.error && <div className="text-xs text-danger">{r.error}</div>}
          {r.status === "added" && r.cameraId && (
            <Link to={`/cameras/${r.cameraId}`} className="text-xs text-primary hover:underline">
              Open camera →
            </Link>
          )}
          {offset != null && Math.abs(offset) > CLOCK_DRIFT_ALERT_SECONDS && (
            <div className="flex items-center gap-1 text-xs text-warning">
              <Clock className="size-3.5" /> Clock is {formatOffset(offset)} off. After adding, fix it on the camera's Device tab.
            </div>
          )}
        </div>
      </div>

      {r.probe && r.status !== "added" && (
        <div className="mt-3 grid gap-2.5">
          {video.length === 0 ? (
            <div className="flex items-center gap-1.5 text-xs text-danger">
              <AlertTriangle className="size-3.5" /> No H.264/H.265 profile with an RTSP address: add this camera manually.
            </div>
          ) : (
            <>
              <div className="grid gap-1.5">
                <Label className="text-xs">Name</Label>
                <Input className="h-8" value={r.name} disabled={!editable} onChange={(e) => onChange({ name: e.target.value })} />
              </div>
              <div className="grid gap-2 sm:grid-cols-2 [&_[data-slot=select-trigger]]:min-w-0 [&_[data-slot=select-value]]:truncate">
                <div className="grid gap-1.5">
                  <Label className="text-xs">Main stream (recorded)</Label>
                  <Select value={r.main} disabled={!editable} onValueChange={(v) => onChange({ main: v })}>
                    <SelectTrigger size="sm" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {video.map((p) => (
                        <SelectItem key={p.token} value={p.token}>
                          {p.name ?? p.token} · {profileSummary(p)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">Sub stream</Label>
                  <Select value={r.sub || NO_SUB} disabled={!editable} onValueChange={(v) => onChange({ sub: v === NO_SUB ? "" : v })}>
                    <SelectTrigger size="sm" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NO_SUB}>None</SelectItem>
                      {video
                        .filter((p) => p.token !== r.main)
                        .map((p) => (
                          <SelectItem key={p.token} value={p.token}>
                            {p.name ?? p.token} · {profileSummary(p)}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              {r.sub && (
                <label className="flex items-center gap-2 text-xs">
                  <Switch checked={r.recordSub} disabled={!editable} onCheckedChange={(v) => onChange({ recordSub: v })} />
                  Record the sub stream too (otherwise live only)
                </label>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function RowBadge({ row }: { row: Row }) {
  const base = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
  switch (row.status) {
    case "checking":
    case "adding":
      return (
        <span className={cn(base, "bg-info/12 text-info")}>
          <Loader2 className="size-3 animate-spin" /> {row.status === "checking" ? "Checking" : "Adding"}
        </span>
      )
    case "ready":
      return <span className={cn(base, "bg-info/12 text-info")}>Ready</span>
    case "error":
      return <span className={cn(base, "bg-danger/12 text-danger")}>Failed</span>
    case "added":
      return (
        <span className={cn(base, "bg-success/12 text-success")}>
          <CheckCircle2 className="size-3" /> Added
        </span>
      )
    default:
      return <span className={cn(base, "bg-muted text-muted-foreground")}>Not checked</span>
  }
}
