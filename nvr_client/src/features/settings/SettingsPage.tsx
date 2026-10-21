import { CheckCircle2, Loader2, RotateCcw, XCircle } from "lucide-react"
import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { PageHeader } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { type LiveProtocol, type NodeAccessPreference, useSettings } from "@/lib/settings"

type TestState = { kind: "idle" } | { kind: "testing" } | { kind: "ok"; text: string } | { kind: "fail"; text: string }

export function SettingsPage() {
  const { settings, update, reset } = useSettings()
  const qc = useQueryClient()
  const [url, setUrl] = useState(settings.centralUrl)
  const [test, setTest] = useState<TestState>({ kind: "idle" })

  const testConnection = async () => {
    setTest({ kind: "testing" })
    try {
      const res = await fetch(`${url.replace(/\/+$/, "")}/`, { signal: AbortSignal.timeout(5000) })
      const body = await res.json()
      setTest({ kind: "ok", text: `${body.service ?? "Connected"} (HTTP ${res.status})` })
    } catch (err) {
      setTest({ kind: "fail", text: `Cannot reach ${url}: ${(err as Error).message}` })
    }
  }

  const saveUrl = () => {
    update({ centralUrl: url })
    qc.clear()
    toast.success("Central manager URL saved")
  }

  return (
    <div className="max-w-3xl space-y-4">
      <PageHeader title="Settings" description="Stored in this browser only." />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Central manager</CardTitle>
          <CardDescription>All data and actions go through this API. Media nodes are reached via the addresses they register.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-1.5">
            <Label htmlFor="url">API URL</Label>
            <div className="grid gap-2 sm:grid-cols-[1fr_auto_auto]">
              <Input id="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://192.168.1.3:8000" />
              <Button variant="outline" onClick={testConnection} disabled={test.kind === "testing"}>
                {test.kind === "testing" && <Loader2 className="size-4 animate-spin" />} Test
              </Button>
              <Button onClick={saveUrl} disabled={url.replace(/\/+$/, "") === settings.centralUrl}>
                Save
              </Button>
            </div>
          </div>
          {test.kind === "ok" && (
            <p className="flex items-center gap-2 text-sm text-success">
              <CheckCircle2 className="size-4" /> {test.text}
            </p>
          )}
          {test.kind === "fail" && (
            <p className="flex items-center gap-2 text-sm text-danger">
              <XCircle className="size-4" /> {test.text}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Display</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex flex-col items-stretch justify-between gap-3 sm:flex-row sm:items-center">
            <div>
              <Label>Refresh interval</Label>
              <p className="text-xs text-muted-foreground">How often lists and statuses are refreshed.</p>
            </div>
            <Select value={String(settings.pollSeconds)} onValueChange={(v) => update({ pollSeconds: Number(v) })}>
              <SelectTrigger className="w-full sm:w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[2, 5, 10, 30].map((s) => (
                  <SelectItem key={s} value={String(s)}>
                    {s} seconds
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col items-stretch justify-between gap-3 sm:flex-row sm:items-center">
            <div>
              <Label>Media node connection</Label>
              <p className="text-xs text-muted-foreground">Auto uses LAN when reachable and otherwise uses each node&apos;s public mapping.</p>
            </div>
            <Select value={settings.nodeAccess} onValueChange={(v) => { update({ nodeAccess: v as NodeAccessPreference }); qc.removeQueries({ queryKey: ["node-access"] }) }}>
              <SelectTrigger className="w-full sm:w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">Auto (LAN → public)</SelectItem>
                <SelectItem value="lan">LAN only</SelectItem>
                <SelectItem value="public">Public only</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col items-stretch justify-between gap-3 sm:flex-row sm:items-center">
            <div>
              <Label>Live video protocol</Label>
              <p className="text-xs text-muted-foreground">WebRTC has the lowest delay; LL-HLS works through more networks.</p>
            </div>
            <Select value={settings.liveProtocol} onValueChange={(v) => update({ liveProtocol: v as LiveProtocol })}>
              <SelectTrigger className="w-full sm:w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">Auto (WebRTC → HLS)</SelectItem>
                <SelectItem value="webrtc">WebRTC only</SelectItem>
                <SelectItem value="hls">LL-HLS only</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center justify-between gap-4">
            <div>
              <Label>Use substream in grids</Label>
              <p className="text-xs text-muted-foreground">Multi-camera grids play the low-resolution "sub" profile when a camera has one.</p>
            </div>
            <Switch checked={settings.gridUsesSubstream} onCheckedChange={(v) => update({ gridUsesSubstream: v })} />
          </div>
        </CardContent>
      </Card>

      <Button variant="outline" onClick={() => { reset(); setUrl(import.meta.env.VITE_CENTRAL_URL ?? "http://localhost:8000"); qc.clear() }}>
        <RotateCcw className="size-4" /> Reset to defaults
      </Button>
    </div>
  )
}
