import { Clock, Loader2, Power, RefreshCw, Server } from "lucide-react"
import { useState } from "react"
import { useCameraDevice, useCameraNtp, useCameraReboot, useCameraTimeSync } from "@/api/queries"
import type { Camera } from "@/api/types"
import { ConfirmDialog, ErrorState, Field } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { timeAgo } from "@/lib/format"
import { CLOCK_DRIFT_ALERT_SECONDS, driftTone, formatOffset, onvifErrorText, serviceNames } from "@/lib/onvif"
import { cn } from "@/lib/utils"

/** ONVIF device page of a camera: identity, clock (sync / NTP) and reboot. Talks to the camera through its node. */
export function DeviceTab({ camera: c, active }: { camera: Camera; active: boolean }) {
  const device = useCameraDevice(c.id, active)
  const timeSync = useCameraTimeSync()
  const reboot = useCameraReboot()
  const [ntpOpen, setNtpOpen] = useState(false)
  const [rebootOpen, setRebootOpen] = useState(false)

  const d = device.data
  const info = d?.info
  const offset = d?.clock.offset_seconds ?? c.clock_offset_seconds
  const tone = driftTone(offset)

  return (
    <div className="space-y-4">
      {device.error && (
        <ErrorState
          error={`${onvifErrorText(device.error)}${c.onvif_host ? "" : " This camera was added manually; ONVIF is tried on its stream address, port 80."}`}
        />
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="gap-2">
          <CardHeader className="flex flex-row items-center justify-between pb-0">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Server className="size-4" /> Device
            </CardTitle>
            <Button variant="ghost" size="sm" onClick={() => device.refetch()} disabled={device.isFetching}>
              <RefreshCw className={cn("size-3.5", device.isFetching && "animate-spin")} /> Refresh
            </Button>
          </CardHeader>
          <CardContent>
            <Field label="Manufacturer">{info?.manufacturer ?? c.manufacturer ?? "—"}</Field>
            <Field label="Model">{info?.model ?? c.model ?? "—"}</Field>
            <Field label="Firmware">{info?.firmwareversion ?? c.firmware ?? "—"}</Field>
            <Field label="Serial">{info?.serialnumber ?? c.serial ?? "—"}</Field>
            <Field label="MAC">{d?.network?.mac ?? c.mac ?? "—"}</Field>
            <Field label="Hostname">{d?.hostname ?? "—"}</Field>
            <Field label="IP">
              {d?.network?.ip ? `${d.network.ip}${d.network.prefix_length ? `/${d.network.prefix_length}` : ""} · ${d.network.dhcp ? "DHCP" : "static"}` : "—"}
            </Field>
            <Field label="ONVIF address">
              <span className="font-mono text-xs">{d ? `${d.host}:${d.port}` : c.onvif_host ? `${c.onvif_host}:${c.onvif_port ?? 80}` : "—"}</span>
            </Field>
            <div className="flex flex-wrap gap-1 pt-2">
              {serviceNames(d?.services ?? c.onvif_services).map((s) => (
                <span key={s} className="rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium">
                  {s}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="gap-2">
          <CardHeader className="pb-0">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Clock className="size-4" /> Clock
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Field label="Offset from node">
              <span className={cn("font-medium", tone === "warning" && "text-warning", tone === "success" && "text-success")}>
                {formatOffset(offset)}
              </span>
            </Field>
            <Field label="Time source">{d?.clock.source ?? "—"}</Field>
            <Field label="Time zone">{d?.clock.timezone ?? "—"}</Field>
            <Field label="NTP">
              {d?.ntp ? (d.ntp.from_dhcp ? "From DHCP" : d.ntp.servers.join(", ") || "None") : "—"}
            </Field>
            <Field label="Reachable">
              {c.onvif_reachable == null ? "—" : c.onvif_reachable ? "Yes" : <span className="text-danger">No</span>}
              {c.onvif_checked_at && <span className="text-xs text-muted-foreground"> · {timeAgo(c.onvif_checked_at)}</span>}
            </Field>
            {offset != null && Math.abs(offset) > CLOCK_DRIFT_ALERT_SECONDS && (
              <p className="pt-1 text-xs text-warning">
                The camera's clock is off. Its on-screen time and its events will not match the recordings.
              </p>
            )}
            <div className="flex flex-wrap gap-2 pt-3">
              <Button size="sm" onClick={() => timeSync.mutate(c.id)} disabled={timeSync.isPending}>
                {timeSync.isPending && <Loader2 className="size-3.5 animate-spin" />} Sync time to node
              </Button>
              <Button size="sm" variant="outline" onClick={() => setNtpOpen(true)}>
                Use NTP…
              </Button>
            </div>
            <p className="pt-2 text-xs text-muted-foreground">
              Sync sets the camera once (manual time). NTP keeps it right; the camera must reach the NTP server.
            </p>
          </CardContent>
        </Card>

        <Card className="gap-2">
          <CardHeader className="pb-0">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Power className="size-4" /> Maintenance
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Restart the camera. Recording stops for about a minute and resumes on its own.
            </p>
            <Button variant="outline" className="w-full" onClick={() => setRebootOpen(true)} disabled={reboot.isPending}>
              {reboot.isPending ? <Loader2 className="size-4 animate-spin" /> : <Power className="size-4" />} Reboot camera
            </Button>
          </CardContent>
        </Card>
      </div>

      {device.isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Reading the camera…
        </div>
      )}

      <ConfirmDialog
        open={rebootOpen}
        onOpenChange={setRebootOpen}
        title={`Reboot ${c.name}?`}
        description="The camera restarts now. Live view and recording stop until it is back (usually about a minute)."
        confirmLabel="Reboot"
        destructive
        onConfirm={() => reboot.mutate(c.id)}
      />
      {ntpOpen && (
        <NtpDialog
          cameraId={c.id}
          current={d?.ntp ?? null}
          onOpenChange={setNtpOpen}
        />
      )}
    </div>
  )
}

function NtpDialog({
  cameraId,
  current,
  onOpenChange,
}: {
  cameraId: number
  current: { from_dhcp?: boolean; servers?: string[] } | null
  onOpenChange: (open: boolean) => void
}) {
  const ntp = useCameraNtp()
  const [fromDhcp, setFromDhcp] = useState(current?.from_dhcp ?? false)
  const [servers, setServers] = useState((current?.servers ?? []).join(", ") || window.location.hostname)
  const list = servers.split(/[\s,]+/).filter(Boolean)

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Use NTP</DialogTitle>
          <DialogDescription>The camera sets its own clock from an NTP server and keeps it right.</DialogDescription>
        </DialogHeader>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={fromDhcp} onCheckedChange={setFromDhcp} /> Use the NTP server given by DHCP
        </label>
        {!fromDhcp && (
          <div className="grid gap-1.5">
            <Label htmlFor="ntp-servers">NTP servers</Label>
            <Input id="ntp-servers" value={servers} onChange={(e) => setServers(e.target.value)} placeholder="192.168.1.3, pool.ntp.org" />
            <span className="text-xs text-muted-foreground">IP addresses or host names, separated by commas.</span>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={ntp.isPending || (!fromDhcp && list.length === 0)}
            onClick={() =>
              ntp.mutate({ cameraId, body: { from_dhcp: fromDhcp, servers: fromDhcp ? [] : list } }, { onSuccess: () => onOpenChange(false) })
            }
          >
            {ntp.isPending && <Loader2 className="size-4 animate-spin" />} Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
