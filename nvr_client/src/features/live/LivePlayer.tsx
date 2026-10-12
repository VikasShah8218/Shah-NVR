import Hls from "hls.js"
import { Loader2, VideoOff } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useLive } from "@/api/queries"
import type { LiveInfo } from "@/api/types"
import type { LiveProtocol } from "@/lib/settings"
import { cn } from "@/lib/utils"
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

/** Pick the stream URLs for `profile`, falling back to the camera's first stream. */
export function pickStream(live: LiveInfo | undefined, profile: string) {
  return live?.streams.find((s) => s.profile === profile) ?? live?.streams[0]
}

/**
 * Live video for one camera profile. Tries WebRTC (MediaMTX WHEP) first and falls back to
 * LL-HLS; reconnects with backoff when the stream drops or the camera moves to another node.
 */
export function LivePlayer({
  cameraId,
  profile,
  protocol,
  className,
  onVideo,
  overlay = true,
}: {
  cameraId: number
  profile: string
  protocol: LiveProtocol
  className?: string
  onVideo?: (video: HTMLVideoElement | null) => void
  overlay?: boolean
}) {
  const live = useLive(cameraId)
  const stream = pickStream(live.data, profile)
  const videoRef = useRef<HTMLVideoElement>(null)
  const [info, setInfo] = useState<PlayerInfo>(EMPTY)
  const [attempt, setAttempt] = useState(0) // bumping it reconnects
  const failures = useRef(0)

  useEffect(() => {
    onVideo?.(videoRef.current)
    return () => onVideo?.(null)
  }, [onVideo])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !stream) return
    let cancelled = false
    let whep: WhepSession | null = null
    let hls: Hls | null = null
    let retryTimer: ReturnType<typeof setTimeout> | undefined
    let statsTimer: ReturnType<typeof setInterval> | undefined

    const retry = (message: string) => {
      if (cancelled) return
      setInfo((i) => ({ ...i, phase: "error", error: message }))
      const backoff = Math.min(30_000, 2000 * 2 ** Math.min(failures.current++, 4))
      retryTimer = setTimeout(() => !cancelled && setAttempt((a) => a + 1), backoff)
    }

    const playHls = () => {
      setInfo((i) => ({ ...i, protocol: "HLS", phase: "loading", error: null }))
      if (Hls.isSupported()) {
        hls = new Hls({ lowLatencyMode: true, backBufferLength: 10, liveDurationInfinity: true })
        hls.on(Hls.Events.ERROR, (_e, data) => {
          if (data.fatal) {
            hls?.destroy()
            hls = null
            retry(`HLS: ${data.details}`)
          }
        })
        hls.loadSource(stream.hls)
        hls.attachMedia(video)
        statsTimer = setInterval(() => {
          const latency = hls?.latency
          if (latency != null && Number.isFinite(latency)) setInfo((i) => ({ ...i, delayMs: Math.round(latency * 1000) }))
        }, 2000)
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = stream.hls // Safari: native HLS
      } else {
        retry("HLS is not supported by this browser")
      }
      video.play().catch(() => {})
    }

    const playWebrtc = async () => {
      setInfo((i) => ({ ...i, protocol: "WebRTC", phase: "loading", error: null }))
      try {
        const session = await startWhep(`${stream.webrtc}/whep`, video)
        if (cancelled) {
          session.close()
          return
        }
        whep = session
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

    video.muted = true
    if (protocol === "hls") playHls()
    else void playWebrtc()

    return () => {
      cancelled = true
      clearTimeout(retryTimer)
      clearInterval(statsTimer)
      whep?.close()
      hls?.destroy()
      video.removeAttribute("src")
      video.srcObject = null
    }
    // `attempt` re-runs the effect for reconnects; URLs change when the camera moves node.
  }, [stream?.webrtc, stream?.hls, protocol, attempt])

  const onPlaying = () => {
    failures.current = 0
    setInfo((i) => ({ ...i, phase: "playing", error: null, width: videoRef.current?.videoWidth ?? 0, height: videoRef.current?.videoHeight ?? 0 }))
  }
  const onResize = () =>
    setInfo((i) => ({ ...i, width: videoRef.current?.videoWidth ?? 0, height: videoRef.current?.videoHeight ?? 0 }))

  const liveError = live.error ? (live.error as Error).message : null
  const showSpinner = !liveError && info.phase === "loading"
  const errorText = liveError ?? (info.phase === "error" ? info.error : null)

  return (
    <div className={cn("relative overflow-hidden bg-video", className)}>
      <video
        ref={videoRef}
        className="size-full object-contain"
        playsInline
        muted
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
          </span>
        </div>
      )}
      {overlay && info.phase === "playing" && (
        <div className="pointer-events-none absolute bottom-1.5 left-1.5 rounded bg-black/55 px-1.5 py-0.5 text-[10px] text-white/85 tabular-nums">
          {info.width}×{info.height} · {info.protocol}
          {info.delayMs != null && ` · ${info.delayMs} ms`}
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
