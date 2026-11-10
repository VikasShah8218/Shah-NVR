import Hls from "hls.js"
import { Loader2, Pause, RotateCw, VideoOff, Volume2, VolumeX } from "lucide-react"
import type { CSSProperties } from "react"
import { useCallback, useEffect, useId, useRef, useState } from "react"
import { useLive } from "@/api/queries"
import type { LiveInfo } from "@/api/types"
import { useSettings, type LiveProtocol } from "@/lib/settings"
import { cn } from "@/lib/utils"
import { noPictureLimitMs, pushEvent, WATCHDOG_INTERVAL_MS } from "./watchdog"
import { startWhep, webrtcDelayMs, type WhepSession } from "./whep"

type Phase = "loading" | "playing" | "error"

export interface PlayerInfo {
  protocol: "WebRTC" | "HLS" | null
  phase: Phase
  width: number
  height: number
  delayMs: number | null
  error: string | null
}

const EMPTY: PlayerInfo = { protocol: null, phase: "loading", width: 0, height: 0, delayMs: null, error: null }
const AUDIO_FOCUS_EVENT = "shah-nvr:live-audio-focus"

/** Pick the stream URLs for `profile`, falling back to the camera's first stream. */
export function pickStream(live: LiveInfo | undefined, profile: string) {
  return live?.streams.find((s) => s.profile === profile) ?? live?.streams[0]
}

/**
 * Live video for one camera profile. Tries WebRTC (MediaMTX WHEP) first and falls back to
 * LL-HLS; reconnects with backoff when the stream drops or the camera moves to another node.
 *
 * "No picture" watchdog: every 2 s it compares the browser's decoded-frame counter and the playback
 * position with the previous check (no pixel analysis). A stream that connected but shows no new frame
 * for 8 s (LL-HLS: buffer x2 + 4 s) reconnects. Before, a WebRTC session that was "connected" without
 * video, or an HLS stall without a fatal error, stayed black forever. ↻ (corner button, the error overlay or
 * `reconnectSignal` from the parent) starts a fresh connection at once.
 */
export function LivePlayer({
  cameraId,
  profile,
  protocol,
  className,
  videoStyle,
  onVideo,
  overlay = true,
  suspended = false,
  showRefresh = false,
  reconnectSignal = 0,
}: {
  cameraId: number
  profile: string
  protocol: LiveProtocol
  className?: string
  videoStyle?: CSSProperties
  onVideo?: (video: HTMLVideoElement | null) => void
  overlay?: boolean
  /** The expand / main-stream dialog is open: tear the stream down (no network, no decode) until it closes. */
  suspended?: boolean
  /** ↻ in the top-right corner (on hover). Tiles put theirs in their own header and use `reconnectSignal`. */
  showRefresh?: boolean
  /** Bump to force a fresh connection from outside (a tile's header button). */
  reconnectSignal?: number
}) {
  const { settings } = useSettings()
  const hlsBufferSeconds = Math.max(2, Math.min(10, Number(settings.hlsBufferSeconds) || 5))
  const live = useLive(cameraId)
  const stream = pickStream(live.data, profile)
  const containerRef = useRef<HTMLDivElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const [info, setInfo] = useState<PlayerInfo>(EMPTY)
  const [attempt, setAttempt] = useState(0) // bumping it reconnects
  const failures = useRef(0)
  const audioId = useId()
  const [muted, setMuted] = useState(true)
  const [active, setActive] = useState(() => typeof document === "undefined" || !document.hidden)
  const [volume, setVolume] = useState(() => Number(localStorage.getItem("shah-nvr.live-volume") ?? 0.8))
  const mutedRef = useRef(muted)
  const volumeRef = useRef(volume)
  const webrtcUrl = stream?.webrtc
  const hlsUrl = stream?.hls
  const events = useRef<string[]>([]) // recent player steps, logged when the watchdog fires (diagnosis)
  const startedAt = useRef(0) // when the current connection attempt started (step times are relative to it)

  /** ↻: drop the connection and start a fresh one now (preferred protocol, no backoff). */
  const reconnect = useCallback(() => {
    console.info(`[live] reconnect requested: camera ${cameraId} ${profile}`, events.current.join(" "))
    failures.current = 0
    setInfo(EMPTY)
    setAttempt((a) => a + 1)
  }, [cameraId, profile])

  const lastSignal = useRef(reconnectSignal)
  useEffect(() => {
    if (reconnectSignal === lastSignal.current) return // only a new bump reconnects
    lastSignal.current = reconnectSignal
    reconnect()
  }, [reconnectSignal, reconnect])

  useEffect(() => {
    const container = containerRef.current
    let inViewport = true
    const update = () => setActive(!document.hidden && inViewport)
    const observer = container && "IntersectionObserver" in window
      ? new IntersectionObserver(([entry]) => { inViewport = entry.isIntersecting; update() }, { threshold: 0.01 })
      : null
    if (container && observer) observer.observe(container)
    document.addEventListener("visibilitychange", update)
    return () => {
      observer?.disconnect()
      document.removeEventListener("visibilitychange", update)
    }
  }, [])

  useEffect(() => {
    const takeFocus = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== audioId) setMuted(true)
    }
    window.addEventListener(AUDIO_FOCUS_EVENT, takeFocus)
    return () => window.removeEventListener(AUDIO_FOCUS_EVENT, takeFocus)
  }, [audioId])

  useEffect(() => {
    mutedRef.current = muted
    volumeRef.current = volume
    const video = videoRef.current
    if (video) {
      video.muted = muted
      video.volume = volume
    }
  }, [muted, volume])

  useEffect(() => {
    onVideo?.(videoRef.current)
    return () => onVideo?.(null)
  }, [onVideo])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !webrtcUrl || !hlsUrl || !active || suspended) return
    let cancelled = false
    let retrying = false // one retry per attempt (a lost WebRTC link and the watchdog may both fire)
    let whep: WhepSession | null = null
    let hls: Hls | null = null
    let retryTimer: ReturnType<typeof setTimeout> | undefined
    let statsTimer: ReturnType<typeof setInterval> | undefined
    let hlsStartTimer: ReturnType<typeof setTimeout> | undefined
    let watchdogTimer: ReturnType<typeof setInterval> | undefined
    let mode: "webrtc" | "hls" = protocol === "hls" ? "hls" : "webrtc"
    startedAt.current = performance.now()
    const note = (step: string) => pushEvent(events.current, step, performance.now() - startedAt.current)

    const retry = (message: string) => {
      if (cancelled || retrying) return
      retrying = true
      note(`retry(${message})`)
      setInfo((i) => ({ ...i, phase: "error", error: message }))
      const backoff = Math.min(30_000, 2000 * 2 ** Math.min(failures.current++, 4))
      retryTimer = setTimeout(() => !cancelled && setAttempt((a) => a + 1), backoff)
    }

    const playHls = () => {
      mode = "hls"
      lastProgress = performance.now()
      note("hls")
      setInfo((i) => ({ ...i, protocol: "HLS", phase: "loading", error: null }))
      if (Hls.isSupported()) {
        // Stay deliberately behind the live edge. The configured safety window absorbs short
        // camera/network delivery variations; this player values continuity over minimum delay.
        hls = new Hls({
          lowLatencyMode: true,
          liveSyncMode: "buffered",
          liveSyncDuration: hlsBufferSeconds,
          liveMaxLatencyDuration: Math.max(hlsBufferSeconds * 2, hlsBufferSeconds + 3),
          liveSyncOnStallIncrease: 1,
          maxLiveSyncPlaybackRate: 1,
          maxBufferLength: Math.max(15, hlsBufferSeconds * 3),
          maxMaxBufferLength: Math.max(30, hlsBufferSeconds * 4),
          maxBufferHole: 0.5,
          backBufferLength: 10,
          liveDurationInfinity: true,
        })
        hls.on(Hls.Events.ERROR, (_e, data) => {
          if (data.fatal) {
            clearTimeout(hlsStartTimer)
            hls?.destroy()
            hls = null
            retry(`HLS: ${data.details}`)
          }
        })
        hls.loadSource(hlsUrl)
        hls.attachMedia(video)
        let started = false
        const startWhenBuffered = (force = false) => {
          if (started || cancelled) return
          const ranges = video.buffered
          let bufferedAhead = 0
          for (let index = 0; index < ranges.length; index += 1) {
            if (ranges.end(index) >= video.currentTime && ranges.start(index) <= video.currentTime + 0.5) {
              bufferedAhead = ranges.end(index) - Math.max(video.currentTime, ranges.start(index))
              break
            }
          }
          // Before the media timeline selects its initial position, currentTime can be zero while
          // the buffered live range uses large timestamps. Its duration is still a valid gate.
          if (!bufferedAhead && ranges.length) {
            const last = ranges.length - 1
            bufferedAhead = ranges.end(last) - ranges.start(last)
          }
          if (force || bufferedAhead >= hlsBufferSeconds) {
            started = true
            clearTimeout(hlsStartTimer)
            video.play().catch(() => {})
          }
        }
        hls.on(Hls.Events.BUFFER_APPENDED, () => startWhenBuffered())
        // A malformed timeline must not leave the tile waiting forever.
        hlsStartTimer = setTimeout(() => startWhenBuffered(true), Math.max(8000, hlsBufferSeconds * 2000))
        statsTimer = setInterval(() => {
          const latency = hls?.latency
          if (latency != null && Number.isFinite(latency)) setInfo((i) => ({ ...i, delayMs: Math.round(latency * 1000) }))
        }, 2000)
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = hlsUrl // Safari: native HLS
        video.play().catch(() => {})
      } else {
        retry("HLS is not supported by this browser")
      }
    }

    const playWebrtc = async () => {
      note("webrtc")
      setInfo((i) => ({ ...i, protocol: "WebRTC", phase: "loading", error: null }))
      try {
        const session = await startWhep(`${webrtcUrl}/whep`, video)
        if (cancelled) {
          session.close()
          return
        }
        whep = session
        note("webrtc-connected")
        video.play().catch(() => {})
        session.pc.addEventListener("connectionstatechange", () => {
          const st = session.pc.connectionState
          if (st === "failed" || st === "disconnected") retry("WebRTC connection lost")
        })
        statsTimer = setInterval(async () => {
          const d = await webrtcDelayMs(session.pc).catch(() => null)
          if (d != null) setInfo((i) => ({ ...i, delayMs: d }))
        }, 2000)
      } catch (err) {
        if (cancelled) return
        if (protocol === "auto") playHls()
        else retry((err as Error).message)
      }
    }

    // "No picture" watchdog: new decoded frames = alive. Only the frame counter: with WebRTC (a MediaStream)
    // currentTime keeps running in real time even when no frame arrives. currentTime is the fallback only for
    // browsers without getVideoPlaybackQuality.
    const progressMark = () => video.getVideoPlaybackQuality ? video.getVideoPlaybackQuality().totalVideoFrames : video.currentTime
    let lastMark = progressMark()
    let lastProgress = performance.now()
    watchdogTimer = setInterval(() => {
      if (cancelled || retrying) return
      const mark = progressMark()
      const now = performance.now()
      if (mark !== lastMark) {
        lastMark = mark
        lastProgress = now
        return
      }
      const limit = noPictureLimitMs(mode, hlsBufferSeconds)
      if (now - lastProgress < limit) return
      note("no-picture")
      console.info(`[live] no picture for ${Math.round((now - lastProgress) / 1000)} s (${mode}, camera ${cameraId} ${profile}): reconnecting`,
        events.current.join(" "))
      whep?.close()
      whep = null
      hls?.destroy()
      hls = null
      retry("No picture. Reconnecting…")
    }, WATCHDOG_INTERVAL_MS)

    video.muted = mutedRef.current
    video.volume = volumeRef.current
    if (protocol === "hls") playHls()
    else void playWebrtc()

    return () => {
      cancelled = true
      clearTimeout(retryTimer)
      clearTimeout(hlsStartTimer)
      clearInterval(statsTimer)
      clearInterval(watchdogTimer)
      whep?.close()
      hls?.destroy()
      video.removeAttribute("src")
      video.srcObject = null
    }
    // `attempt` re-runs the effect for reconnects; URLs change when the camera moves node.
  }, [webrtcUrl, hlsUrl, protocol, attempt, active, suspended, hlsBufferSeconds, cameraId, profile])

  const showAudio = stream?.audio_state === "available" || stream?.audio_state === "advertised_not_observed" || stream?.audio_state === "unsupported"
  const audioPlayable = showAudio && stream?.audio_state !== "unsupported" && (info.protocol !== "HLS" || stream.audio_codec === "aac")
  const toggleAudio = () => {
    if (!audioPlayable) return
    const next = !muted
    if (!next) window.dispatchEvent(new CustomEvent(AUDIO_FOCUS_EVENT, { detail: audioId }))
    setMuted(next)
    if (!next) videoRef.current?.play().catch(() => {})
  }

  const onPlaying = () => {
    pushEvent(events.current, "playing", performance.now() - startedAt.current)
    failures.current = 0
    setInfo((i) => ({ ...i, phase: "playing", error: null, width: videoRef.current?.videoWidth ?? 0, height: videoRef.current?.videoHeight ?? 0 }))
  }
  const onResize = () =>
    setInfo((i) => ({ ...i, width: videoRef.current?.videoWidth ?? 0, height: videoRef.current?.videoHeight ?? 0 }))

  const liveError = live.error ? (live.error as Error).message : null
  const showSpinner = !liveError && info.phase === "loading" && !suspended
  const errorText = suspended ? null : (liveError ?? (info.phase === "error" ? info.error : null))

  return (
    <div ref={containerRef} className={cn("group/player relative overflow-hidden bg-video", className)}>
      <video
        ref={videoRef}
        className="size-full object-contain"
        style={videoStyle}
        playsInline
        muted={muted}
        autoPlay
        onPlaying={onPlaying}
        onResize={onResize}
      />
      {showSpinner && (
        <div className="absolute inset-0 grid place-items-center text-xs text-muted-foreground">
          <span className="flex items-center gap-2">
            <Loader2 className="size-4 animate-spin" /> Connecting{info.protocol ? ` (${info.protocol})` : ""}…
          </span>
        </div>
      )}
      {errorText && (
        <div className="absolute inset-0 grid place-items-center p-3 text-center text-xs text-muted-foreground">
          <span className="flex flex-col items-center gap-1.5">
            <VideoOff className="size-5" />
            {errorText}
            {!liveError && <span className="text-[11px]">Retrying…</span>}
            {!liveError && (
              <button type="button" className="mt-1 flex items-center gap-1 rounded bg-white/10 px-2 py-0.5 text-[11px] text-white/90 hover:bg-white/20"
                onPointerDown={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); reconnect() }}>
                <RotateCw className="size-3" /> Reconnect now
              </button>
            )}
          </span>
        </div>
      )}
      {showRefresh && !suspended && (
        <button
          type="button"
          className="absolute top-2 right-2 z-10 grid size-7 place-items-center rounded bg-black/55 text-white opacity-0 transition-opacity group-hover/player:opacity-100 hover:bg-white/20 focus-visible:opacity-100"
          title="Reconnect (fresh connection)"
          aria-label="Reconnect"
          onPointerDown={(e) => e.stopPropagation()}
          onDoubleClick={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); reconnect() }}
        >
          <RotateCw className="size-4" />
        </button>
      )}
      {suspended && (
        <div className="absolute inset-0 grid place-items-center bg-video/60 text-xs text-white/85">
          <span className="flex items-center gap-1.5 rounded bg-black/55 px-2 py-1">
            <Pause className="size-3.5" /> Paused
          </span>
        </div>
      )}
      {overlay && info.phase === "playing" && !suspended && (
        <div className="pointer-events-none absolute bottom-1.5 left-1.5 rounded bg-black/55 px-1.5 py-0.5 text-[10px] text-white/85 tabular-nums">
          {info.width}×{info.height} · {info.protocol}
          {info.delayMs != null && ` · ${info.delayMs} ms`}
        </div>
      )}
      {showAudio && !suspended && (
        <div className="absolute right-2 bottom-2 flex items-center gap-1 rounded bg-black/60 p-1 text-white">
          <button
            type="button"
            className="grid size-7 place-items-center rounded hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-45"
            onClick={(e) => { e.stopPropagation(); toggleAudio() }}
            disabled={!audioPlayable}
            aria-label={muted ? "Unmute camera audio" : "Mute camera audio"}
            title={!audioPlayable ? "This codec requires WebRTC for live audio" : muted ? "Listen to camera audio" : "Mute camera audio"}
          >
            {muted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
          </button>
          {!muted && (
            <input
              aria-label="Camera audio volume"
              className="w-20 accent-primary"
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={volume}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => {
                const next = Number(e.target.value)
                setVolume(next)
                localStorage.setItem("shah-nvr.live-volume", String(next))
              }}
            />
          )}
        </div>
      )}
    </div>
  )
}

/** Save the current video frame as a PNG. */
export function saveSnapshot(video: HTMLVideoElement | null, name: string): boolean {
  if (!video || !video.videoWidth) return false
  const canvas = document.createElement("canvas")
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  canvas.getContext("2d")!.drawImage(video, 0, 0)
  canvas.toBlob((blob) => {
    if (!blob) return
    const a = document.createElement("a")
    a.href = URL.createObjectURL(blob)
    a.download = `${name}_${new Date().toISOString().replace(/[:.]/g, "-")}.png`
    a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  })
  return true
}
