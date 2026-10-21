import { Loader2 } from "lucide-react"
import { useState } from "react"
import { useCreateExport } from "@/api/queries"
import type { ExportCreate, ExportMode } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"

const localValue = (date: Date) => {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return shifted.toISOString().slice(0, 16)
}

export function ExportDialog({ open, onOpenChange, cameraId, profile, initialStart, initialEnd }: {
  open: boolean; onOpenChange: (value: boolean) => void; cameraId: number; profile: string
  initialStart: Date; initialEnd: Date
}) {
  const create = useCreateExport()
  const [start, setStart] = useState(localValue(initialStart))
  const [end, setEnd] = useState(localValue(initialEnd))
  const [mode, setMode] = useState<ExportMode>("original")
  const [codec, setCodec] = useState<"h264" | "h265">("h264")
  const [quality, setQuality] = useState<"high" | "balanced" | "small">("balanced")
  const [processor, setProcessor] = useState<"auto" | "cpu" | "gpu">("auto")
  const [height, setHeight] = useState<ExportCreate["max_height"]>(0)
  const [fps, setFps] = useState(0)
  const [audio, setAudio] = useState(true)
  const from = new Date(start), to = new Date(end)
  const duration = (to.getTime() - from.getTime()) / 3_600_000
  const valid = Number.isFinite(duration) && duration > 0 && duration <= 4 && to <= new Date()
  const submit = () => create.mutate({ camera_id: cameraId, profile, start_time: from.toISOString(), end_time: to.toISOString(),
    mode, video_codec: codec, quality, processor, max_height: height, max_fps: fps, include_audio: audio,
    audio_bitrate_kbps: 128 }, { onSuccess: () => onOpenChange(false) })
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
      <DialogHeader><DialogTitle>Export recording</DialogTitle><DialogDescription>
        Export up to four hours. Original is fastest and preserves quality; compressed uses FFmpeg and more node resources.
      </DialogDescription></DialogHeader>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-1.5"><Label>Start</Label><Input type="datetime-local" value={start} onChange={e => setStart(e.target.value)} /></div>
        <div className="grid gap-1.5"><Label>End</Label><Input type="datetime-local" value={end} onChange={e => setEnd(e.target.value)} /></div>
        <div className="sm:col-span-2 grid gap-1.5"><Label>Export type</Label><Select value={mode} onValueChange={v => setMode(v as ExportMode)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="original">Original quality (join without transcoding)</SelectItem><SelectItem value="compressed">Compressed file (transcode)</SelectItem></SelectContent></Select></div>
        {mode === "compressed" && <>
          <div className="grid gap-1.5"><Label>Video codec</Label><Select value={codec} onValueChange={v => setCodec(v as typeof codec)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="h264">H.264 (best compatibility)</SelectItem><SelectItem value="h265">H.265 (smaller file)</SelectItem></SelectContent></Select></div>
          <div className="grid gap-1.5"><Label>Quality</Label><Select value={quality} onValueChange={v => setQuality(v as typeof quality)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="high">High quality</SelectItem><SelectItem value="balanced">Balanced</SelectItem><SelectItem value="small">Small file</SelectItem></SelectContent></Select></div>
          <div className="grid gap-1.5"><Label>Processor</Label><Select value={processor} onValueChange={v => setProcessor(v as typeof processor)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="auto">Auto</SelectItem><SelectItem value="cpu">CPU</SelectItem><SelectItem value="gpu">GPU (fail if unavailable)</SelectItem></SelectContent></Select></div>
          <div className="grid gap-1.5"><Label>Maximum resolution</Label><Select value={String(height)} onValueChange={v => setHeight(Number(v) as typeof height)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="0">Keep original</SelectItem>{[2160,1440,1080,720,480,360].map(v => <SelectItem key={v} value={String(v)}>{v}p</SelectItem>)}</SelectContent></Select></div>
          <div className="grid gap-1.5"><Label>Maximum frame rate</Label><Input type="number" min={0} max={120} value={fps} onChange={e => setFps(Number(e.target.value))} /><span className="text-xs text-muted-foreground">0 keeps the original frame rate.</span></div>
          <label className="flex items-center gap-2 self-center"><Switch checked={audio} onCheckedChange={setAudio} /> Include audio when available</label>
        </>}
      </div>
      <p className={valid ? "text-xs text-muted-foreground" : "text-xs text-danger"}>{valid ? `${duration.toFixed(2)} hours selected.` : "Choose a past interval longer than zero and no more than four hours."}</p>
      <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button disabled={!valid || create.isPending} onClick={submit}>{create.isPending && <Loader2 className="size-4 animate-spin" />} Queue export</Button></DialogFooter>
    </DialogContent>
  </Dialog>
}
