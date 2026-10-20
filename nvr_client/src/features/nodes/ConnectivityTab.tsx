import { useState } from "react"
import { useUpdateNode } from "@/api/queries"
import type { MediaNode } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"

const port = (value: string): number | null => {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed >= 1 && parsed <= 65535 ? parsed : null
}

/** Per-node browser-facing endpoints. Internal central-to-node traffic always keeps using the LAN URL. */
export function ConnectivityTab({ node }: { node: MediaNode }) {
  const update = useUpdateNode()
  const [enabled, setEnabled] = useState(node.public_enabled)
  const [apiUrl, setApiUrl] = useState(node.public_api_url ?? "")
  const [host, setHost] = useState(node.public_media_host ?? "")
  const [rtspPort, setRtspPort] = useState(String(node.public_rtsp_port ?? node.rtsp_port))
  const [hlsPort, setHlsPort] = useState(String(node.public_hls_port ?? node.hls_port))
  const [webrtcPort, setWebrtcPort] = useState(String(node.public_webrtc_port ?? node.webrtc_port))
  const [tls, setTls] = useState(node.public_media_tls)

  const ports = [port(rtspPort), port(hlsPort), port(webrtcPort)]
  const valid = (!enabled || (apiUrl.trim().match(/^https?:\/\//) && host.trim())) && ports.every((p) => p != null)

  const save = () => {
    if (!valid) return
    update.mutate({
      id: node.id,
      body: {
        public_enabled: enabled,
        public_api_url: apiUrl.trim() || null,
        public_media_host: host.trim() || null,
        public_rtsp_port: ports[0],
        public_hls_port: ports[1],
        public_webrtc_port: ports[2],
        public_media_tls: tls,
      },
    })
  }

  return (
    <Card className="gap-4">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm font-medium">Internet / public access</CardTitle>
        <p className="text-xs text-muted-foreground">
          These addresses are available to browsers that select Auto or Public mode. Heartbeats, camera assignments, and
          recording uploads continue over the private Node API address.
        </p>
      </CardHeader>
      <CardContent className="space-y-5">
        <label className="flex items-center justify-between gap-4 rounded-lg border p-4">
          <span>
            <span className="block text-sm font-medium">Public mapping available</span>
            <span className="block text-xs text-muted-foreground">Allow browsers configured for Auto or Public mode to use this mapping.</span>
          </span>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </label>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="grid gap-1.5 md:col-span-2">
            <Label htmlFor="public-api">Public Node API URL</Label>
            <Input id="public-api" placeholder="http://203.0.113.10:17100" value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} />
            <span className="text-xs text-muted-foreground">Used for recorded chunks, downloads, node status, paths, and logs.</span>
          </div>
          <div className="grid gap-1.5 md:col-span-2">
            <Label htmlFor="public-host">Public media hostname or IP</Label>
            <Input id="public-host" placeholder="nvr.example.com or 203.0.113.10" value={host} onChange={(e) => setHost(e.target.value)} />
          </div>
          <PortField id="public-rtsp" label="Public RTSP port" value={rtspPort} onChange={setRtspPort} />
          <PortField id="public-hls" label="Public HLS port" value={hlsPort} onChange={setHlsPort} />
          <PortField id="public-webrtc" label="Public WebRTC HTTP port" value={webrtcPort} onChange={setWebrtcPort} />
          <label className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
            <span>
              <span className="block text-sm font-medium">HTTPS for HLS and WebRTC</span>
              <span className="block text-xs text-muted-foreground">Enable only when TLS is terminated on these public ports.</span>
            </span>
            <Switch checked={tls} onCheckedChange={setTls} />
          </label>
        </div>

        <div className="space-y-1 rounded-lg border bg-muted/30 p-3 font-mono text-xs">
          <div>Public API preview: {enabled && apiUrl ? apiUrl : "disabled"}</div>
          <div>RTSP: rtsp://{enabled && host ? host : node.media_host}:{enabled ? rtspPort : node.rtsp_port}</div>
          <div>{tls && enabled ? "https" : "http"}://{enabled && host ? host : node.media_host}:{enabled ? hlsPort : node.hls_port} (HLS)</div>
          <div>{tls && enabled ? "https" : "http"}://{enabled && host ? host : node.media_host}:{enabled ? webrtcPort : node.webrtc_port} (WebRTC)</div>
        </div>

        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">
          Forward the MediaMTX WebRTC UDP port (normally 8189) to the same UDP port on this node. A changed external UDP
          port cannot be represented by this mapping. HTTPS pages also require HTTPS media endpoints to avoid browser mixed-content blocking.
        </div>

        <Button onClick={save} disabled={!valid || update.isPending}>Save connectivity</Button>
      </CardContent>
    </Card>
  )
}

function PortField({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (value: string) => void }) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type="number" min={1} max={65535} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}
