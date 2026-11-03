import {
  ArrowDown,
  ArrowDownLeft,
  ArrowDownRight,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ArrowUpLeft,
  ArrowUpRight,
  Crosshair,
  Loader2,
  Square,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react"
import { type ReactNode, useEffect, useRef, useState } from "react"
import { ptzApi } from "@/api/ptz"
import { useResolvedAccess } from "@/api/queries"
import { useSettings } from "@/lib/settings"
import { cn } from "@/lib/utils"
import { type Dir, type PtzCaps, PtzSocket, type PtzStatus, SPEED_MAX } from "./ptzSocket"

type Phase = "idle" | "connecting" | "ready" | "reconnecting" | "error"
const MAX_RECONNECTS = 4

/**
 * PTZ control cluster overlaid on the main-stream (big view). Opens a direct WebSocket to the
 * media node; holding a pad button pans/tilts continuously, released or window-blur stops.
 * Pan/tilt speed is chosen by the node from the live zoom (shown in the meter); zoom is fixed.
 */
export function PtzOverlay({ cameraId }: { cameraId: number }) {
  const { settings } = useSettings()
  const access = useResolvedAccess(cameraId)
  const [open, setOpen] = useState(false)
  const [phase, setPhase] = useState<Phase>("idle")
  const [caps, setCaps] = useState<PtzCaps>({})
  const [speed, setSpeed] = useState(SPEED_MAX)
  const [zoomPct, setZoomPct] = useState<number | null>(null)
  const [status, setStatus] = useState<PtzStatus | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [error, setError] = useState("")
  const [reconnectTick, setReconnectTick] = useState(0)
  const socketRef = useRef<PtzSocket | null>(null)
  const attempts = useRef(0)

  useEffect(() => {
    if (!open) {
      setPhase("idle")
      attempts.current = 0
      return
    }
    let live = true
    let reconnect: ReturnType<typeof setTimeout> | null = null
    setPhase((p) => (p === "reconnecting" ? p : "connecting"))
    setError("")
    const api = ptzApi(settings.centralUrl, cameraId, "main")
    api
      .session(access)
      .then((ticket) => {
        if (!live) return
        setWarnings(ticket.warnings ?? [])
        socketRef.current = new PtzSocket(ticket.ws_url, {
          onReady: (r) => {
            attempts.current = 0
            setCaps(r.capabilities ?? {})
            setSpeed(r.speed)
            setZoomPct(r.zoom_pct)
            setStatus(r.status)
            setPhase("ready")
          },
          onTelemetry: (t) => {
            setSpeed(t.speed)
            setZoomPct(t.zoom_pct)
            setStatus(t.status)
          },
          onError: (m) => setError(m),
          onClosed: (byUser) => {
            socketRef.current = null
            if (byUser || !live) return
            if (attempts.current >= MAX_RECONNECTS) {
              setPhase("error")
              setError("PTZ connection lost. Close and reopen to retry.")
              return
            }
            attempts.current += 1
            setPhase("reconnecting")
            reconnect = setTimeout(() => live && setReconnectTick((n) => n + 1), 1000)
          },
        })
      })
      .catch((e) => {
        if (live) {
          setPhase("error")
          setError(e instanceof Error ? e.message : "Could not start PTZ.")
        }
      })
    return () => {
      live = false
      if (reconnect) clearTimeout(reconnect)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [open, settings.centralUrl, cameraId, access, reconnectTick])

  // Any loss of focus must stop the camera — a held button whose pointerup never arrives otherwise pans on.
  useEffect(() => {
    if (!open) return
    const stop = () => socketRef.current?.release()
    const onHidden = () => document.hidden && stop()
    window.addEventListener("blur", stop)
    window.addEventListener("pagehide", stop)
    document.addEventListener("visibilitychange", onHidden)
    return () => {
      window.removeEventListener("blur", stop)
      window.removeEventListener("pagehide", stop)
      document.removeEventListener("visibilitychange", onHidden)
    }
  }, [open])

  const ready = phase === "ready"
  const hold = (pan: Dir, tilt: Dir, zoom: Dir) => ready && socketRef.current?.hold(pan, tilt, zoom)
  const release = () => socketRef.current?.release()

  return (
    <div className="pointer-events-none absolute inset-0 z-20">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="pointer-events-auto absolute bottom-3 left-3 flex items-center gap-1.5 rounded-full border border-white/15 bg-black/55 px-3 py-1.5 text-xs font-medium text-white backdrop-blur transition-colors hover:bg-black/70"
        >
          <Crosshair className="size-4" /> PTZ
        </button>
      ) : (
        <div className="pointer-events-auto absolute bottom-3 left-3 w-56 select-none rounded-2xl border border-white/15 bg-black/55 p-3 text-white shadow-xl backdrop-blur">
          <div className="mb-2 flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-xs font-semibold">
              <Crosshair className="size-3.5" /> PTZ
              {phase === "connecting" && <Loader2 className="size-3 animate-spin text-white/70" />}
              {phase === "reconnecting" && <span className="text-[10px] font-normal text-warning">reconnecting…</span>}
            </span>
            <button type="button" aria-label="Close PTZ" onClick={() => setOpen(false)} className="rounded p-0.5 text-white/70 hover:bg-white/15 hover:text-white">
              <X className="size-4" />
            </button>
          </div>

          <div className="flex gap-2">
            {/* 8-way pad + centre stop */}
            <div className="grid grid-cols-3 gap-1">
              <HoldButton label="Up-left" disabled={!caps.pan_tilt || !ready} onHold={() => hold(-1, 1, 0)} onRelease={release}><ArrowUpLeft className="size-4" /></HoldButton>
              <HoldButton label="Up" disabled={!caps.pan_tilt || !ready} onHold={() => hold(0, 1, 0)} onRelease={release}><ArrowUp className="size-4" /></HoldButton>
              <HoldButton label="Up-right" disabled={!caps.pan_tilt || !ready} onHold={() => hold(1, 1, 0)} onRelease={release}><ArrowUpRight className="size-4" /></HoldButton>
              <HoldButton label="Left" disabled={!caps.pan_tilt || !ready} onHold={() => hold(-1, 0, 0)} onRelease={release}><ArrowLeft className="size-4" /></HoldButton>
              <button type="button" aria-label="Stop" disabled={!ready} onClick={release}
                className="flex size-11 items-center justify-center rounded-lg border border-white/15 bg-white/5 text-white/80 hover:bg-white/15 disabled:opacity-40 md:size-9">
                <Square className="size-3.5" />
              </button>
              <HoldButton label="Right" disabled={!caps.pan_tilt || !ready} onHold={() => hold(1, 0, 0)} onRelease={release}><ArrowRight className="size-4" /></HoldButton>
              <HoldButton label="Down-left" disabled={!caps.pan_tilt || !ready} onHold={() => hold(-1, -1, 0)} onRelease={release}><ArrowDownLeft className="size-4" /></HoldButton>
              <HoldButton label="Down" disabled={!caps.pan_tilt || !ready} onHold={() => hold(0, -1, 0)} onRelease={release}><ArrowDown className="size-4" /></HoldButton>
              <HoldButton label="Down-right" disabled={!caps.pan_tilt || !ready} onHold={() => hold(1, -1, 0)} onRelease={release}><ArrowDownRight className="size-4" /></HoldButton>
            </div>
            {/* zoom */}
            <div className="flex flex-col gap-1">
              <HoldButton label="Zoom in" disabled={!caps.zoom || !ready} onHold={() => hold(0, 0, 1)} onRelease={release}><ZoomIn className="size-4" /></HoldButton>
              <HoldButton label="Zoom out" disabled={!caps.zoom || !ready} onHold={() => hold(0, 0, -1)} onRelease={release}><ZoomOut className="size-4" /></HoldButton>
            </div>
          </div>

          {/* auto-speed meter (node-derived from zoom) */}
          <div className="mt-2.5">
            <div className="mb-1 flex justify-between text-[10px] text-white/70">
              <span>speed (auto)</span>
              <span>{speed.toFixed(2)}{zoomPct != null && ` · zoom ${zoomPct}%`}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-white/15">
              <div className="h-full rounded-full bg-primary transition-[width] duration-200" style={{ width: `${Math.min(100, (speed / SPEED_MAX) * 100)}%` }} />
            </div>
          </div>

          {error && <p role="alert" className="mt-2 text-[11px] text-danger">{error}</p>}
          {!error && warnings.map((w) => <p key={w} className="mt-2 text-[11px] text-warning">{w}</p>)}
          {ready && status && (
            <p className="mt-1.5 text-[10px] text-white/50">pan/tilt {status.pan_tilt_state ?? "?"} · zoom {status.zoom_state ?? "?"}</p>
          )}
        </div>
      )}
    </div>
  )
}

function HoldButton({ label, disabled, onHold, onRelease, children }: {
  label: string
  disabled?: boolean
  onHold: () => void
  onRelease: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={`Hold: ${label}`}
      disabled={disabled}
      className={cn(
        "flex size-11 touch-none items-center justify-center rounded-lg border border-white/15 bg-white/5 text-white",
        "hover:bg-white/15 active:bg-primary active:text-primary-foreground disabled:opacity-40 md:size-9",
      )}
      onContextMenu={(e) => e.preventDefault()}
      onPointerDown={(e) => {
        if (e.button !== 0 || disabled) return
        e.preventDefault()
        e.currentTarget.setPointerCapture(e.pointerId)
        onHold()
      }}
      onPointerUp={onRelease}
      onPointerCancel={onRelease}
      onLostPointerCapture={onRelease}
      onBlur={onRelease}
      onKeyDown={(e) => {
        if ((e.key === " " || e.key === "Enter") && !e.repeat && !disabled) {
          e.preventDefault()
          onHold()
        }
      }}
      onKeyUp={(e) => {
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault()
          onRelease()
        }
      }}
    >
      {children}
    </button>
  )
}
