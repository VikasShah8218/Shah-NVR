import { useEffect, useState } from "react"
import { useCameras, useOnvifServer, useUpdateCamera, useUpdateOnvifServer } from "@/api/queries"
import type { MediaNode } from "@/api/types"
import { EmptyState, ErrorState, Field, Loading } from "@/components/common"
import { StatusBadge } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"

export function OnvifServerTab({ node }: { node: MediaNode }) {
  const server = useOnvifServer(node.id)
  const cameras = useCameras()
  const update = useUpdateOnvifServer()
  const updateCamera = useUpdateCamera()
  const [name, setName] = useState("")
  const [location, setLocation] = useState("")

  useEffect(() => {
    if (server.data) {
      setName(server.data.discovery_name)
      setLocation(server.data.location ?? "")
    }
  }, [server.data])

  if (server.isLoading) return <Loading />
  if (server.error || !server.data) return <ErrorState error={server.error ?? "ONVIF server state unavailable"} />
  const state = server.data
  const assigned = (cameras.data ?? []).filter((camera) => camera.assignment?.node_id === node.id)

  return <div className="space-y-4">
    <Card>
      <CardHeader>
        <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
          <div><CardTitle className="text-base">Virtual ONVIF NVR</CardTitle>
            <CardDescription>Expose this node and its assigned cameras to third-party VMS software.</CardDescription></div>
          <div className="flex items-center gap-3"><StatusBadge status={state.status.toUpperCase()} />
            <Switch checked={state.enabled} disabled={update.isPending}
              onCheckedChange={(enabled) => update.mutate({ id: node.id, body: { enabled } })} /></div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {!state.credentials_configured && <p className="rounded-md border border-warning/50 bg-warning/10 p-3 text-sm text-warning">
          Configure ONVIF_SERVER_USERNAME and ONVIF_SERVER_PASSWORD in the media node .env before enabling this service.
        </p>}
        {state.last_error && <p className="rounded-md border border-danger/50 bg-danger/10 p-3 text-sm text-danger">{state.last_error}</p>}
        <div className="grid gap-3 md:grid-cols-2">
          <div className="grid gap-1.5"><Label htmlFor="onvif-name">Discovery name</Label>
            <Input id="onvif-name" value={name} maxLength={128} onChange={(e) => setName(e.target.value)} /></div>
          <div className="grid gap-1.5"><Label htmlFor="onvif-location">Location</Label>
            <Input id="onvif-location" value={location} maxLength={256} placeholder="Optional" onChange={(e) => setLocation(e.target.value)} /></div>
        </div>
        <Button disabled={update.isPending || !name.trim()} onClick={() => update.mutate({ id: node.id,
          body: { discovery_name: name.trim(), location: location.trim() || null } })}>Save identity</Button>
        <div className="grid gap-2 md:grid-cols-2">
          <Field label="SOAP address"><span className="break-all font-mono text-xs">{state.xaddr ?? "—"}</span></Field>
          <Field label="Authenticated RTSP"><span className="break-all font-mono text-xs">{state.rtsp_address ?? "—"}</span></Field>
          <Field label="Authentication">{state.credentials_configured ? "Local credentials configured" : "Not configured"}</Field>
          <Field label="Exposed">{state.exposed_cameras} cameras · {state.exposed_profiles} profiles</Field>
        </div>
        <p className="text-xs text-muted-foreground">The password stays on this node and is never sent to Central Manager or this browser.</p>
      </CardContent>
    </Card>

    <Card>
      <CardHeader><CardTitle className="text-base">Exposed cameras</CardTitle>
        <CardDescription>Only enabled cameras currently assigned to this node can be advertised.</CardDescription></CardHeader>
      <CardContent className="space-y-2">
        {cameras.isLoading && <Loading />}
        {cameras.error && <ErrorState error={cameras.error} />}
        {!cameras.isLoading && !assigned.length && <EmptyState title="No cameras assigned to this node" />}
        {assigned.map((camera) => <div key={camera.id} className="flex items-center justify-between rounded-md border px-3 py-2">
          <div><div className="text-sm font-medium">{camera.name}</div>
            <div className="text-xs text-muted-foreground">{camera.streams.map((s) => s.profile).join(", ")}</div></div>
          <Switch checked={camera.expose_via_onvif} disabled={updateCamera.isPending || !camera.enabled}
            onCheckedChange={(value) => updateCamera.mutate({ id: camera.id, body: { expose_via_onvif: value } })} />
        </div>)}
      </CardContent>
    </Card>
  </div>
}
