import { useEffect, useRef, useState } from "react"
import { ptzApi, type PtzCommand, type PtzState } from "@/api/ptz"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useSettings } from "@/lib/settings"
import { PtzHoldController, type Velocity } from "./ptzController"

export function PtzPanel({ cameraId, profile }: { cameraId: number; profile: string }) {
  const { settings } = useSettings()
  const [generation, setGeneration] = useState(0)
  // Recreate the entire session/controller when server/camera/profile changes.
  return <Controls key={`${settings.centralUrl}/${cameraId}/${profile}/${generation}`} url={settings.centralUrl} cameraId={cameraId} profile={profile}
    onReload={() => setGeneration((n) => n + 1)} />
}

function Controls({ url, cameraId, profile, onReload }: { url: string; cameraId: number; profile: string; onReload: () => void }) {
  const [state, setState] = useState<PtzState | null>(null)
  const [error, setError] = useState("")
  const [message, setMessage] = useState("")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [preset, setPreset] = useState("")
  const [name, setName] = useState("")
  const [speed, setSpeed] = useState(.1)
  const controller = useRef<PtzHoldController | null>(null)
  const actionBusy = useRef(false)
  const pressed = useRef(false)
  const api = ptzApi(url, cameraId, profile)

  useEffect(() => {
    let live = true
    let control: PtzHoldController | null = null
    const service = ptzApi(url, cameraId, profile)
    const report = (e: unknown) => { if (live) setError(e instanceof Error ? e.message : "PTZ request failed. Reload controls.") }
    void service.open().then((next) => {
      if (!live) return
      control = new PtzHoldController((command) => service.command({ ...command, session_id: next.session_id }), report)
      controller.current = control
      setState(next)
    }).catch(report).finally(() => { if (live) setLoading(false) })
    const stop = () => { pressed.current = false; void control?.stop() }
    const hidden = () => { if (document.hidden) stop() }
    window.addEventListener("blur", stop)
    window.addEventListener("pagehide", stop)
    document.addEventListener("visibilitychange", hidden)
    return () => {
      live = false
      window.removeEventListener("blur", stop)
      window.removeEventListener("pagehide", stop)
      document.removeEventListener("visibilitychange", hidden)
      void control?.dispose()
      controller.current = null
    }
  }, [url, cameraId, profile])

  const stop = () => { pressed.current = false; void controller.current?.stop() }
  const start = (velocity: Velocity) => {
    if (error || loading || actionBusy.current || pressed.current) return
    pressed.current = true
    void controller.current?.start(velocity)
  }
  const operate = async (command: Omit<PtzCommand, "session_id" | "sequence">) => {
    const control = controller.current
    if (!state || !control || actionBusy.current || pressed.current) return
    actionBusy.current = true; setBusy(true); setMessage("")
    try {
      await control.stop()
      if (!control.available) return
      const result = await api.command({ ...command, session_id: state.session_id, sequence: control.nextSequence() })
      setMessage(result.message)
      setState((old) => old && { ...old, status: result.status ?? old.status, presets: result.presets ?? old.presets })
      if (command.action === "preset_remove") setPreset("")
      if (command.action === "preset_save") setName("")
    } catch (e) {
      setError(e instanceof Error ? e.message : "PTZ operation failed. Reload controls.")
    } finally { actionBusy.current = false; setBusy(false) }
  }
  const disabled = loading || busy || !!error || !state
  const moveButton = (label: string, velocity: Velocity, supported: boolean) => (
    <Button type="button" variant="outline" size="sm" disabled={disabled || !supported}
      aria-label={label} title={`Hold: ${label}`} className="touch-none select-none"
      onContextMenu={(e) => e.preventDefault()}
      onPointerDown={(e) => {
        if (e.button !== 0) return
        e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); start(velocity)
      }}
      onPointerUp={stop} onPointerCancel={stop} onLostPointerCapture={stop} onBlur={stop}
      onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); if (!e.repeat) start(velocity) } }}
      onKeyUp={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); stop() } }}
    >{label}</Button>
  )
  const caps = state?.capabilities
  return <section aria-label="PTZ controls" className="space-y-2 rounded-md border bg-card p-3 text-xs"
    onDoubleClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
    <div className="flex items-center justify-between gap-2"><strong>PTZ · {profile}</strong>
      <Button size="sm" variant="outline" disabled={loading || busy} onClick={() => { stop(); onReload() }}>Reload</Button>
    </div>
    <p className="text-muted-foreground">Hold a direction or zoom button; release to stop. Keyboard: focus a button, then hold Space or Enter.</p>
    {loading && <p>Reading camera capabilities…</p>}
    {error && <p role="alert" className="text-danger">{error}</p>}
    {state?.warnings.map((w) => <p key={w} className="text-warning">{w}</p>)}
    <div className="flex flex-wrap items-center gap-2">
      {moveButton("Left", { pan: -speed }, !!caps?.pan_tilt)}
      {moveButton("Right", { pan: speed }, !!caps?.pan_tilt)}
      {moveButton("Up", { tilt: speed }, !!caps?.pan_tilt)}
      {moveButton("Down", { tilt: -speed }, !!caps?.pan_tilt)}
      {moveButton("Zoom +", { zoom: speed }, !!caps?.zoom)}
      {moveButton("Zoom −", { zoom: -speed }, !!caps?.zoom)}
      <Button size="sm" variant="destructive" disabled={!state} onClick={stop}>Stop</Button>
    </div>
    <label className="flex items-center gap-2">Speed
      <input aria-label="PTZ speed" type="range" min="0.05" max="0.5" step="0.05" value={speed}
        onChange={(e) => { stop(); setSpeed(Number(e.target.value)) }} />{speed.toFixed(2)}
    </label>
    {state && <p className="text-muted-foreground">Last read status: pan/tilt {state.status.pan_tilt_state ?? "unknown"}, zoom {state.status.zoom_state ?? "unknown"}.
      <button className="ml-2 underline" disabled={disabled} onClick={() => void operate({ action: "refresh" })}>Refresh status/presets</button>
    </p>}
    {caps?.presets && <div className="space-y-2 border-t pt-2">
      <div className="flex flex-wrap gap-2">
        <select aria-label="PTZ preset" className="min-w-0 flex-1 rounded border bg-background p-1" value={preset} onChange={(e) => setPreset(e.target.value)}>
          <option value="">Select preset</option>{state?.presets.map((p) => <option key={p.token} value={p.token}>{p.name}</option>)}
        </select>
        <Button size="sm" disabled={disabled || !preset} onClick={() => void operate({ action: "preset_goto", preset_token: preset })}>Go</Button>
        <Button size="sm" variant="outline" disabled={disabled || !preset} onClick={() => {
          if (window.confirm("Delete this preset from the camera?")) void operate({ action: "preset_remove", preset_token: preset, confirm: true })
        }}>Delete</Button>
      </div>
      <div className="flex gap-2"><Input aria-label="New preset name" placeholder="New preset name" maxLength={64} value={name} onChange={(e) => setName(e.target.value)} />
        <Button size="sm" disabled={disabled || !name.trim()} onClick={() => void operate({ action: "preset_save", preset_name: name.trim() })}>Save position</Button>
      </div>
    </div>}
    {caps?.home && <div className="flex gap-2">
      <Button size="sm" disabled={disabled} onClick={() => void operate({ action: "home_goto" })}>Go home</Button>
      {caps.home_set && <Button size="sm" variant="outline" disabled={disabled} onClick={() => {
        if (window.confirm("Replace the camera's home position with its current position?")) void operate({ action: "home_set", confirm: true })
      }}>Set home</Button>}
    </div>}
    {state && !caps?.home && <p className="text-muted-foreground">ONVIF home position is not advertised by this camera.</p>}
    {message && <p role="status">{message}</p>}
  </section>
}
