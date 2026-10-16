import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { useEncoder, useEncoderApi } from "@/api/encoder"
import type { EncoderState, EncoderValues, EncoderWrite } from "@/api/encoder"
import type { Camera } from "@/api/types"
import { useCameras } from "@/api/queries"
import { ConfirmDialog, ErrorState, Loading } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { changedValues, presetValues, videoGBPerDay } from "@/lib/encoder"
import type { Preset } from "@/lib/encoder"

const selectClass = "h-9 rounded-md border bg-background px-3 text-sm"
const presets: Preset[] = ["Storage saver", "Best quality", "Low-bandwidth substream"]
const operationId = () => globalThis.crypto?.randomUUID?.() ?? `encoder-${Date.now()}-${Math.random().toString(36).slice(2)}`
const message = (e: unknown) => e instanceof Error ? e.message : String(e)
const estimate = (v: number | null | undefined) => {
  const gb = videoGBPerDay(v)
  return gb == null ? "Unavailable" : `${gb.toFixed(1)} GB/day`
}

export function VideoTab({ camera, active }: { camera: Camera; active: boolean }) {
  const [profile, setProfile] = useState(camera.streams[0]?.profile ?? "main")
  const api = useEncoderApi()
  if (!camera.streams.length) return <p>No streams configured.</p>
  return <div className="space-y-4">
    <div className="flex items-center gap-3"><label htmlFor="encoder-stream">Stream</label>
      <select id="encoder-stream" className={selectClass} value={profile} onChange={e => setProfile(e.target.value)}>
        {camera.streams.map(s => <option key={s.profile}>{s.profile}</option>)}
      </select>
    </div>
    <EncoderEditor key={`${api.url}/${camera.id}/${profile}`} camera={camera} profile={profile} active={active} />
  </div>
}

function EncoderEditor({ camera, profile, active }: { camera: Camera; profile: string; active: boolean }) {
  const api = useEncoderApi()
  const cache = useQueryClient()
  const query = useEncoder(camera.id, profile, active)
  const [loaded, setLoaded] = useState<EncoderState | null>(null)
  const [draft, setDraft] = useState<EncoderValues | null>(null)
  const [token, setToken] = useState("")
  const [shared, setShared] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<EncoderWrite | null>(null)
  const state = loaded ?? query.data
  const current = state?.current
  const values = draft ?? current
  const option = state?.options?.find(o => o.encoding === values?.encoding)
  const history = useQuery({ queryKey: [api.url, "encoder-history", camera.id, profile],
    queryFn: () => api.history(camera.id, profile), enabled: active, retry: false, refetchInterval: busy ? false : 5000 })
  const recovery = useQuery({ queryKey: [api.url, "encoder-recovery", camera.id, profile],
    queryFn: () => api.recovery(camera.id, profile), enabled: active && !!history.data?.changes.length, retry: false,
    refetchInterval: 5000 })
  const pending = !!history.data?.pending
  const patch = (v: Partial<EncoderValues>) => setDraft({ ...values, ...v })
  const refresh = async () => {
    const next = await api.read(camera.id, profile)
    setLoaded(next); setDraft(null); setShared(false)
    cache.setQueryData([api.url, "encoder", camera.id, profile], next)
  }
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null)
    try { await fn() } catch (e) { setError(message(e)) } finally {
      setBusy(false); void history.refetch(); void recovery.refetch()
    }
  }
  const prepare = async (restore_from?: string) => {
    if (!state?.revision || !values || !current) return
    const body: EncoderWrite = { operation_id: operationId(), revision: state.revision,
      values: restore_from ? {} : changedValues(current, values), acknowledge_shared: shared, restore_from }
    await api.check(camera.id, profile, body)
    setConfirm(body)
  }
  const apply = async (body: EncoderWrite) => {
    setConfirm(null)
    const change = await api.apply(camera.id, profile, body)
    if (change.result?.after) { setLoaded(change.result.after); setDraft(null) }
    if (change.status === "verified") toast.success("Encoder readback verified. Check stream recovery below.")
    else setError(change.result?.message ?? `Operation status: ${change.status}. Check history before another write.`)
    void cache.invalidateQueries({ queryKey: [api.url, "cameras"] })
  }
  if (query.isLoading) return <Loading label="Reading camera encoder and supported settings…" />
  if (!state) return <div className="space-y-2"><ErrorState error={query.error ?? "Encoder unavailable"} />
    <Button onClick={() => void query.refetch()}>Retry read</Button></div>
  const sharedProfiles = state.shared_profiles ?? []
  const sharedEncoder = sharedProfiles.length > 1 || (state.use_count ?? 0) > 1
  return <div className="space-y-4">
    <Card><CardHeader><CardTitle>Video encoder · {profile}</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">Changes are written to the camera, not transcoded by the NVR. Applying may briefly interrupt all streams on this device and create a recording gap.</p>
        {error && <ErrorState error={error} />}
        {history.error && <ErrorState error={history.error} />}
        {pending && <div className="rounded border border-warning p-3 text-sm">A device operation is pending or uncertain. Wait two minutes, then obtain fresh readback before another write.
          <Button variant="outline" className="ml-3" disabled={busy} onClick={() => void run(async () => {
            await api.resolve(camera.id, profile); await refresh()
          })}>Check uncertain operation</Button></div>}
        <fieldset disabled={busy || pending} className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="onvif-profile">ONVIF profile mapping</label>
            <select id="onvif-profile" className={selectClass} value={token || state.profile_token || ""} onChange={e => setToken(e.target.value)}>
              <option value="">Select explicitly…</option>
              {state.profiles?.filter(p => p.encoder_token).map(p => <option key={p.token} value={p.token}>{p.name || p.token} ({p.token})</option>)}
            </select>
            <Button variant="outline" disabled={!token} onClick={() => void run(async () => {
              const next = await api.map(camera.id, profile, token); setLoaded(next); setDraft(null); setToken(""); setShared(false)
              void cache.invalidateQueries({ queryKey: [api.url, "cameras"] })
            })}>Save mapping</Button>
            <Button variant="outline" onClick={() => void run(refresh)}>Reload / discard draft</Button>
          </div>
          <p className="text-xs text-muted-foreground">Map this NVR stream to its actual camera profile. Saving a mapping does not change its RTSP URL. Encoder token: {state.encoder_token ?? "not mapped"} · {state.api === "tr2" ? "Media2" : "Media1"}</p>
          {state.warnings?.map(w => <p key={w} className="text-sm text-warning">{w}</p>)}
          {sharedEncoder && <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={shared} onChange={e => setShared(e.target.checked)} />
            I understand this changes shared profiles: {sharedProfiles.join(", ")} (camera use count: {state.use_count ?? "unknown"})
          </label>}
          {values && current && <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <label className="grid gap-1 text-sm">Codec
                <select className={selectClass} value={values.encoding ?? ""} onChange={e => patch({ encoding: e.target.value as "H264" | "H265" })}>
                  {[...new Set([values.encoding, ...(state.options ?? []).map(o => o.encoding)])].filter(Boolean).map(v => <option key={v!}>{v}</option>)}
                </select>
              </label>
              <label className="grid gap-1 text-sm">Resolution
                <select className={selectClass} value={`${values.width}x${values.height}`} disabled={!option?.resolutions?.length}
                  onChange={e => { const [width, height] = e.target.value.split("x").map(Number); patch({ width, height }) }}>
                  {[...new Set([`${values.width}x${values.height}`, ...(option?.resolutions ?? []).map(r => r.join("x"))])].map(r => <option key={r}>{r}</option>)}
                </select>
              </label>
              {(["fps", "bitrate_kbps", "gop", "quality"] as const).map(key => {
                const range = option?.[({ fps: "fps_range", bitrate_kbps: "bitrate_range", gop: "gop_range", quality: "quality_range" } as const)[key]]
                const rates = key === "fps" ? option?.frame_rates : null
                const enabled = values[key] != null && (!!range || !!rates?.length)
                return <label key={key} className="grid gap-1 text-sm">
                  {{ fps: "Frame rate (fps)", bitrate_kbps: "Bitrate limit (kbps)", gop: "GOP (frames)", quality: "Quality" }[key]}
                  {rates?.length ? <select className={selectClass} value={values.fps ?? ""} onChange={e => patch({ fps: Number(e.target.value) })}>
                    {[...new Set([values.fps, ...rates])].filter(v => v != null).map(v => <option key={v!}>{v}</option>)}
                  </select> : <Input type="number" value={values[key] ?? ""} disabled={!enabled} min={range?.[0]} max={range?.[1]}
                    step={key === "quality" || (key === "fps" && state.api === "tr2") ? "any" : 1}
                    onChange={e => { if (e.target.value !== "") patch({ [key]: Number(e.target.value) }) }} />}
                  <span className="text-xs text-muted-foreground">{range ? `${range[0]}–${range[1]}` : rates?.length ? "Advertised values only" : "Camera did not advertise editable limits"}</span>
                </label>
              })}
              <label className="grid gap-1 text-sm">Rate control
                <select className={selectClass} disabled={!option?.rate_controls?.length} value={values.rate_control ?? ""}
                  onChange={e => patch({ rate_control: e.target.value as "CBR" | "VBR" })}>
                  <option value="">Not exposed</option>
                  {[...new Set([values.rate_control, ...(option?.rate_controls ?? [])])].filter(Boolean).map(v => <option key={v!}>{v}</option>)}
                </select>
              </label>
              <label className="grid gap-1 text-sm">Codec profile
                <select className={selectClass} disabled={values.codec_profile == null || !option?.codec_profiles?.length} value={values.codec_profile ?? ""}
                  onChange={e => patch({ codec_profile: e.target.value })}>
                  <option value="">Not exposed</option>
                  {[...new Set([values.codec_profile, ...(option?.codec_profiles ?? [])])].filter(Boolean).map(v => <option key={v!}>{v}</option>)}
                </select>
              </label>
            </div>
            <div className="flex flex-wrap gap-2">{presets.map(p => <Button key={p} variant="outline" disabled={!option}
              onClick={() => option && setDraft(presetValues(values, option, p))}>{p}</Button>)}</div>
            <p className="text-sm">Video storage if recorded continuously: current <b>{estimate(current.bitrate_kbps)}</b> → proposed <b>{estimate(values.bitrate_kbps)}</b>.
              {camera.retention_days != null && videoGBPerDay(values.bitrate_kbps) != null && ` About ${(videoGBPerDay(values.bitrate_kbps)! * camera.retention_days).toFixed(1)} GB for ${camera.retention_days} days.`}
            </p>
            {!camera.streams.find(s => s.profile === profile)?.record && <p className="text-xs text-muted-foreground">This stream is currently live-only; no recording storage is expected.</p>}
            <p className="text-xs text-muted-foreground">Video only, decimal GB at configured bitrate. Audio/overhead are extra; VBR varies. Changing codec at the same bitrate does not by itself reduce this estimate. Presets are editable proposals, not guaranteed quality levels.</p>
            {(values.encoding === "H265" || current.encoding === "H265") && <p className="text-sm text-warning">
              H.265 browser support varies. An H.264 substream can help live viewing; it does not make H.265 main-stream recordings browser-compatible. No transcoding is performed.
            </p>}
            <Button disabled={!option || !Object.keys(changedValues(current, values)).length || (sharedEncoder && !shared) || !!history.error}
              onClick={() => void run(() => prepare())}>Review and apply</Button>
          </>}
        </fieldset>
      </CardContent>
    </Card>
    {current && values && !pending && <BulkEncoder sourceId={camera.id} profile={profile} values={changedValues(current, values)} />}
    <Card><CardHeader><CardTitle>Verification and history</CardTitle></CardHeader><CardContent className="space-y-3">
      {recovery.data && <p className="text-sm">Stream: {recovery.data.status} · Fresh heartbeat: {recovery.data.fresh_status ? "yes" : "pending"} · New recording: {
        !recovery.data.recording_expected ? "not expected" : recovery.data.new_recording ? "observed" : "pending"
      }. Also check live view and playback after applying.</p>}
      {recovery.error && <ErrorState error={recovery.error} />}
      {!history.data?.changes.length && <p className="text-sm text-muted-foreground">No encoder changes recorded.</p>}
      {history.data?.changes.map(change => <div key={change.id} className="rounded border p-3 text-sm">
        <div>{new Date(change.created_at).toLocaleString()} · <b>{change.status}</b></div>
        <p>{change.result?.message}</p>
        {change.before?.current && <p className="text-xs text-muted-foreground">Previous: {change.before.current.encoding} · {change.before.current.width}×{change.before.current.height} · {change.before.current.fps} fps · {change.before.current.bitrate_kbps} kbps</p>}
        {change.result?.recovery && <p className="text-xs">Path restart: {Object.entries(change.result.recovery).map(([k, v]) => `${k}: ${v}`).join(", ")}</p>}
        <Button className="mt-2" size="sm" variant="outline" disabled={busy || pending || !change.before || !state.revision || (sharedEncoder && !shared)}
          onClick={() => void run(() => prepare(change.id))}>Review restore of previous settings</Button>
      </div>)}
    </CardContent></Card>
    <ConfirmDialog open={!!confirm} onOpenChange={open => { if (!open) setConfirm(null) }} title={confirm?.restore_from ? "Restore previous encoder settings?" : "Apply encoder settings?"}
      description="This changes the physical camera. All streams on this device may briefly restart, including recording. Settings will be read back; an uncertain write will not be automatically retried."
      confirmLabel="Apply to camera" onConfirm={() => { if (confirm) void run(() => apply(confirm)) }}>
      <pre className="max-h-56 overflow-auto text-xs">{JSON.stringify(confirm?.restore_from
        ? history.data?.changes.find(c => c.id === confirm.restore_from)?.before?.current : confirm?.values, null, 2)}</pre>
    </ConfirmDialog>
  </div>
}

type BulkRow = { id: number; name: string; body?: EncoderWrite; status: string }
function BulkEncoder({ sourceId, profile, values }: { sourceId: number; profile: string; values: EncoderValues }) {
  const cameras = useCameras()
  const api = useEncoderApi()
  const [selected, setSelected] = useState<number[]>([])
  const [rows, setRows] = useState<BulkRow[]>([])
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [reviewed, setReviewed] = useState("")
  const signature = JSON.stringify({ values, selected })
  const preflight = async () => {
    setBusy(true); setRows([]); setReviewed("")
    const out: BulkRow[] = []
    for (const id of selected) {
      const row: BulkRow = { id, name: cameras.data?.find(c => c.id === id)?.name ?? String(id), status: "Checking" }
      try {
        const state = await api.read(id, profile)
        if (!state.revision) throw new Error("ONVIF profile mapping required")
        const body: EncoderWrite = { operation_id: operationId(), revision: state.revision, values, acknowledge_shared: false }
        await api.check(id, profile, body) // shared encoders must be handled individually, never silently acknowledged
        row.body = body; row.status = "Ready (exact requested values)"
      } catch (e) { row.status = message(e) }
      out.push(row); setRows([...out])
    }
    setReviewed(signature); setBusy(false)
  }
  const apply = async () => {
    setConfirm(false); setBusy(true)
    const results = rows.map(row => ({ ...row }))
    for (const row of results) {
      if (!row.body) continue
      try { const result = await api.apply(row.id, profile, row.body); row.status = `${result.status}: ${result.result?.message ?? ""}` }
      catch (e) { row.status = `${message(e)} — inspect this camera's history; no retry sent.` }
      row.body = undefined; setRows(results.map(r => ({ ...r })))
    }
    setBusy(false); setReviewed("")
  }
  return <details className="rounded-lg border p-4"><summary className="cursor-pointer font-medium">Apply this draft to other cameras</summary>
    <p className="my-3 text-sm text-muted-foreground">Copies only changed fields to the same stream name ({profile}). Each target gets its own read, capability check and revision. Unsupported/shared targets are skipped; nothing is substituted. Maximum 20 cameras.</p>
    <fieldset disabled={busy} className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">{cameras.data?.filter(c => c.id !== sourceId && c.streams.some(s => s.profile === profile)).map(c => <label className="flex gap-2 text-sm" key={c.id}>
        <input type="checkbox" checked={selected.includes(c.id)} disabled={!selected.includes(c.id) && selected.length >= 20}
          onChange={e => { setSelected(e.target.checked ? [...selected, c.id] : selected.filter(id => id !== c.id)); setRows([]) }} />{c.name}
      </label>)}</div>
      <Button variant="outline" disabled={!selected.length || !Object.keys(values).length} onClick={() => void preflight()}>Preflight selected cameras</Button>
      {rows.map(row => <p key={row.id} className="text-sm">{row.name}: {row.status}</p>)}
      <Button disabled={reviewed !== signature || !rows.some(r => r.body)} onClick={() => setConfirm(true)}>Review bulk apply</Button>
    </fieldset>
    <ConfirmDialog open={confirm} onOpenChange={setConfirm} title="Apply to preflighted cameras?"
      description={`Apply these exact changes to ${rows.filter(r => r.body).length} cameras sequentially. Recording may briefly pause. Other targets are skipped.`}
      onConfirm={() => void apply()}><pre className="text-xs">{JSON.stringify(values, null, 2)}</pre></ConfirmDialog>
  </details>
}
