import Hls from "hls.js"
import { ChevronLeft, ChevronRight, FastForward, Loader2, Maximize, Pause, Play, Rewind, SkipBack, SkipForward, Undo2, Volume2, VolumeX } from "lucide-react"
import { type KeyboardEvent, useEffect, useRef, useState } from "react"
import { DigitalZoom } from "@/components/DigitalZoom"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { fmtDateTime } from "@/lib/time"
import { cn } from "@/lib/utils"
import { frameStepTarget, RATES, REVERSE_TICK_MS, type ReverseAnchor, reverseDone, reverseTarget } from "./transport"

/**
 * Plays a recorded HLS VOD playlist. Reports the real recorded wall-clock time of the playhead
 * (from EXT-X-PROGRAM-DATE-TIME via hls.js `playingDate`).
 */
export function VodPlayer({ src, audioSrc, onTime, onEnded, viewKey }: {
  src: string | null
  audioSrc: string | null
  onTime: (t: Date | null) => void
  onEnded?: () => void
  /** The digital zoom resets when this changes (camera, profile or day); seeking keeps it. */
  viewKey?: string
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const hlsRef = useRef<Hls | null>(null)
  const audioHlsRef = useRef<Hls | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [playing, setPlaying] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rate, setRate] = useState(1)
  const [wall, setWall] = useState<Date | null>(null)
  const [muted, setMuted] = useState(true)
  const [audioError, setAudioError] = useState<string | null>(null)
  const [volume, setVolume] = useState(() => Number(localStorage.getItem("shah-nvr.playback-volume") ?? 0.8))
  const [reversing, setReversing] = useState(false)
  const reverseAnchor = useRef<ReverseAnchor | null>(null)
  // A new playlist stops reverse play (adjusting state during render, as React recommends over an effect).
  const [reverseSrc, setReverseSrc] = useState(src)
  if (reverseSrc !== src) {
    setReverseSrc(src)
    setReversing(false)
  }

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
    const audio = audioRef.current
    const video = videoRef.current
    if (!audio || !video || !audioSrc || muted) return
    setAudioError(null)
    let hls: Hls | null = null
    if (Hls.isSupported()) {
      hls = new Hls({ maxBufferLength: 30, enableWorker: true })
      audioHlsRef.current = hls
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data.fatal) return
        setAudioError(data.response?.code === 404 ? "This recording has no audio." : `Recorded audio: ${data.details}`)
        setMuted(true)
      })
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        if (!video.paused) audio.play().catch(() => {})
      })
      hls.loadSource(audioSrc)
      hls.attachMedia(audio)
    } else if (audio.canPlayType("application/vnd.apple.mpegurl")) {
      audio.src = audioSrc
      if (!video.paused) audio.play().catch(() => {})
    } else {
      setAudioError("Recorded audio is not supported by this browser.")
    }
    return () => {
      hls?.destroy()
      audioHlsRef.current = null
      audio.pause()
      audio.removeAttribute("src")
      audio.load()
    }
  }, [audioSrc, muted])

  // Reverse play: MSE can't decode backwards, so pause and keep seeking back. Speed is anchored to wall
  // time (see transport.ts); a tick is skipped while the previous seek is still decoding.
  useEffect(() => {
    const v = videoRef.current
    if (!reversing || !v) return
    v.pause()
    reverseAnchor.current = { media: v.currentTime, clock: performance.now(), rate }
    const id = window.setInterval(() => {
      const a = reverseAnchor.current
      if (!a || v.seeking) return
      const target = reverseTarget(a, performance.now())
      v.currentTime = target
      if (reverseDone(target)) setReversing(false)
    }, REVERSE_TICK_MS)
    return () => window.clearInterval(id)
  }, [reversing, rate])

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = rate
    if (audioRef.current) audioRef.current.playbackRate = rate
  }, [rate])

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = volume
  }, [volume])

  const syncAudio = () => {
    if (muted) return
    const audio = audioRef.current
    const videoDate = hlsRef.current?.playingDate
    const audioDate = audioHlsRef.current?.playingDate
    if (!audio || !videoDate || !audioDate) return
    const drift = (videoDate.getTime() - audioDate.getTime()) / 1000
    if (Math.abs(drift) > 0.2 && Number.isFinite(audio.duration)) {
      audio.currentTime = Math.max(0, Math.min(audio.duration, audio.currentTime + drift))
    }
  }

  const onTimeUpdate = () => {
    const d = hlsRef.current?.playingDate ?? null
    setWall(d)
    onTime(d)
    syncAudio()
  }

  const seekBy = (seconds: number) => {
    const v = videoRef.current
    if (v) v.currentTime = Math.max(0, Math.min(v.duration || Infinity, v.currentTime + seconds))
  }
  const toggle = () => {
    const v = videoRef.current
    if (!v) return
    if (reversing) { setReversing(false); return }
    if (v.paused) v.play().catch(() => {})
    else v.pause()
  }
  /** Pause and move one frame (negative = back). */
  const stepFrame = (frames: number) => {
    const v = videoRef.current
    if (!v) return
    setReversing(false)
    v.pause()
    v.currentTime = frameStepTarget(v.currentTime, frames, v.duration)
  }
  const toggleReverse = () => {
    const v = videoRef.current
    if (!v) return
    if (reversing) { setReversing(false); return }
    if (v.currentTime > 0) setReversing(true)
  }
  // , / . step a frame (like most players); k / space play-pause. Arrow keys stay with the digital zoom.
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!src || (e.target as HTMLElement).closest("input, textarea, select, [role=combobox]")) return
    if (e.key === ",") stepFrame(-1)
    else if (e.key === ".") stepFrame(1)
    else if (e.key === "k" || e.key === " ") toggle()
    else return
    e.preventDefault()
  }

  return (
    <div ref={wrapRef} className="overflow-hidden rounded-lg border bg-video" onKeyDown={onKeyDown}>
      {/* Height-capped so the timeline below stays on screen. */}
      {/* Digital zoom: wheel / drag / keys zoom and pan the video; a click still plays/pauses. */}
      <DigitalZoom className="aspect-video max-h-[55vh] w-full" onTap={src ? toggle : undefined} resetKey={viewKey}>
        {(videoStyle) => <>
        <video
          ref={videoRef}
          className="size-full object-contain"
          style={videoStyle}
          playsInline
          muted
          onPlay={() => { setPlaying(true); if (!muted) audioRef.current?.play().catch(() => {}) }}
          onPause={() => { setPlaying(false); audioRef.current?.pause() }}
          onPlaying={() => { setLoading(false); syncAudio(); if (!muted) audioRef.current?.play().catch(() => {}) }}
          onWaiting={() => { setLoading(true); audioRef.current?.pause() }}
          onTimeUpdate={onTimeUpdate}
          onEnded={onEnded}
        />
        <audio ref={audioRef} preload="none" />
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
        </>}
      </DigitalZoom>
      <div className="flex flex-wrap items-center gap-1 border-t bg-card/60 px-2 py-2 sm:gap-1.5 sm:px-3">
        <Button variant="ghost" size="icon" className="size-10 sm:size-8" onClick={() => seekBy(-60)} title="Back 1 min" disabled={!src}>
          <SkipBack className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" className="size-10 sm:size-8" onClick={() => seekBy(-10)} title="Back 10 s" disabled={!src}>
          <Rewind className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" className={cn("size-10 sm:size-8", reversing && "bg-primary/15 text-primary")}
          onClick={toggleReverse} title={reversing ? "Stop reverse play" : `Play backwards (${rate}×)`} disabled={!src}>
          <Undo2 className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" className="size-10 sm:size-8" onClick={() => stepFrame(-1)} title="Previous frame ( , )" disabled={!src}>
          <ChevronLeft className="size-4" />
        </Button>
        <Button size="icon" className="size-11 rounded-full sm:size-9" onClick={toggle} disabled={!src}>
          {playing || reversing ? <Pause className="size-4" /> : <Play className="size-4" />}
        </Button>
        <Button variant="ghost" size="icon" className="size-10 sm:size-8" onClick={() => stepFrame(1)} title="Next frame ( . )" disabled={!src}>
          <ChevronRight className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" className="size-10 sm:size-8" onClick={() => seekBy(10)} title="Forward 10 s" disabled={!src}>
          <FastForward className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" className="size-10 sm:size-8" onClick={() => seekBy(60)} title="Forward 1 min" disabled={!src}>
          <SkipForward className="size-4" />
        </Button>
        <span className="order-last w-full px-1 pt-1 text-xs tabular-nums text-muted-foreground sm:order-none sm:ml-2 sm:w-auto sm:pt-0 sm:text-sm">{wall ? fmtDateTime(wall) : "—"}</span>
        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="size-10 sm:size-8"
            disabled={!audioSrc}
            title={muted ? "Listen to recorded audio" : "Mute recorded audio"}
            onClick={() => setMuted((value) => !value)}
          >
            {muted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
          </Button>
          {!muted && (
            <input
              aria-label="Recorded audio volume"
              className="hidden w-20 accent-primary sm:block"
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={volume}
              onChange={(event) => {
                const next = Number(event.target.value)
                setVolume(next)
                localStorage.setItem("shah-nvr.playback-volume", String(next))
              }}
            />
          )}
          <Select value={String(rate)} onValueChange={(v) => setRate(Number(v))}>
            <SelectTrigger size="sm" className="w-20">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RATES.map((r) => (
                <SelectItem key={r} value={String(r)}>
                  {reversing ? "−" : ""}{r}×
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="ghost" size="icon" className="size-10 sm:size-8" onClick={() => wrapRef.current?.requestFullscreen?.()} title="Fullscreen">
            <Maximize className="size-4" />
          </Button>
        </div>
      </div>
      {audioError && <div className="border-t px-3 py-1.5 text-xs text-warning">{audioError}</div>}
    </div>
  )
}
