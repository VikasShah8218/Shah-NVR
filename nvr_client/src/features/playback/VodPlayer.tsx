import Hls from "hls.js"
import { FastForward, Loader2, Maximize, Pause, Play, Rewind, SkipBack, SkipForward } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { fmtDateTime } from "@/lib/time"

const RATES = [0.5, 1, 2, 4, 8]

/**
 * Plays a recorded HLS VOD playlist. Reports the real recorded wall-clock time of the playhead
 * (from EXT-X-PROGRAM-DATE-TIME via hls.js `playingDate`).
 */
export function VodPlayer({ src, onTime, onEnded }: { src: string | null; onTime: (t: Date | null) => void; onEnded?: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const hlsRef = useRef<Hls | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [playing, setPlaying] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rate, setRate] = useState(1)
  const [wall, setWall] = useState<Date | null>(null)

  useEffect(() => {
    const video = videoRef.current
    if (!video || !src) return
    setError(null)
    setLoading(true)
    let hls: Hls | null = null
    if (Hls.isSupported()) {
      hls = new Hls({ maxBufferLength: 30, enableWorker: true })
      hlsRef.current = hls
      hls.on(Hls.Events.ERROR, (_e, data) => {
        if (!data.fatal) return
        if (data.response?.code === 404) setError("No playable recordings from this time.")
        else setError(`Playback error: ${data.details}`)
        setLoading(false)
      })
      hls.loadSource(src)
      hls.attachMedia(video)
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src
    } else {
      setError("HLS is not supported by this browser")
    }
    video.playbackRate = rate
    video.play().catch(() => {})
    return () => {
      hls?.destroy()
      hlsRef.current = null
      video.removeAttribute("src")
      video.load()
    }
    // rate is applied separately; only a new playlist reloads the player
  }, [src])

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = rate
  }, [rate])

  const onTimeUpdate = () => {
    const d = hlsRef.current?.playingDate ?? null
    setWall(d)
    onTime(d)
  }

  const seekBy = (seconds: number) => {
    const v = videoRef.current
    if (v) v.currentTime = Math.max(0, Math.min(v.duration || Infinity, v.currentTime + seconds))
  }
  const toggle = () => {
    const v = videoRef.current
    if (!v) return
    if (v.paused) v.play().catch(() => {})
    else v.pause()
  }

  return (
    <div ref={wrapRef} className="overflow-hidden rounded-lg border bg-video">
      {/* Height-capped so the timeline below stays on screen. */}
      <div className="relative mx-auto aspect-video w-full max-w-[calc(55vh*16/9)]">
        <video
          ref={videoRef}
          className="size-full object-contain"
          playsInline
          muted
          onClick={toggle}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onPlaying={() => setLoading(false)}
          onWaiting={() => setLoading(true)}
          onTimeUpdate={onTimeUpdate}
          onEnded={onEnded}
        />
        {!src && (
          <div className="absolute inset-0 grid place-items-center text-sm text-muted-foreground">
            Click on the timeline to start playback
          </div>
        )}
        {src && loading && !error && (
          <div className="absolute inset-0 grid place-items-center">
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        )}
        {error && <div className="absolute inset-0 grid place-items-center p-4 text-center text-sm text-muted-foreground">{error}</div>}
        {wall && (
          <div className="pointer-events-none absolute top-2 right-2 rounded bg-black/55 px-2 py-1 text-sm font-medium text-white tabular-nums">
            {fmtDateTime(wall)}
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 border-t bg-card/60 px-3 py-2">
        <Button variant="ghost" size="icon" className="size-8" onClick={() => seekBy(-60)} title="Back 1 min" disabled={!src}>
          <SkipBack className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" className="size-8" onClick={() => seekBy(-10)} title="Back 10 s" disabled={!src}>
          <Rewind className="size-4" />
        </Button>
        <Button size="icon" className="size-9 rounded-full" onClick={toggle} disabled={!src}>
          {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
        </Button>
        <Button variant="ghost" size="icon" className="size-8" onClick={() => seekBy(10)} title="Forward 10 s" disabled={!src}>
          <FastForward className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" className="size-8" onClick={() => seekBy(60)} title="Forward 1 min" disabled={!src}>
          <SkipForward className="size-4" />
        </Button>
        <span className="ml-2 text-sm tabular-nums text-muted-foreground">{wall ? fmtDateTime(wall) : "—"}</span>
        <div className="ml-auto flex items-center gap-2">
          <Select value={String(rate)} onValueChange={(v) => setRate(Number(v))}>
            <SelectTrigger size="sm" className="w-20">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RATES.map((r) => (
                <SelectItem key={r} value={String(r)}>
                  {r}×
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="ghost" size="icon" className="size-8" onClick={() => wrapRef.current?.requestFullscreen?.()} title="Fullscreen">
            <Maximize className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}
