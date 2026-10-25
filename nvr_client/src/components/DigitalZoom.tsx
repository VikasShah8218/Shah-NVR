import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Minus, Plus, RotateCcw } from "lucide-react"
import type { CSSProperties, KeyboardEvent, ReactNode } from "react"
import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const STEP = 0.25
const PAN_STEP = 40
const MAX_ZOOM = 4
const DRAG_THRESHOLD = 5

/**
 * Digital zoom / pan over a video: a pure CSS transform (no extra decoding or bandwidth).
 * Mouse: wheel zooms (1x-4x), drag pans while zoomed, double-click resets. Keyboard (when the viewport has
 * focus): + / - zoom, arrows pan, 0 resets. A press that moved more than a few pixels is a pan, not a click,
 * so `onTap` (e.g. play/pause) only fires for real clicks. `children` receives the style for the video element.
 */
export function DigitalZoom({
  className,
  onTap,
  resetKey,
  children,
}: {
  className?: string
  onTap?: () => void
  /** The view resets when this changes (e.g. another camera). */
  resetKey?: unknown
  children: (videoStyle: CSSProperties) => ReactNode
}) {
  const viewport = useRef<HTMLDivElement>(null)
  const drag = useRef<{ pointerId: number; x: number; y: number; panX: number; panY: number } | null>(null)
  const moved = useRef(false)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })

  const clampPan = (next: { x: number; y: number }, scale: number) => {
    const bounds = viewport.current?.getBoundingClientRect()
    const maxX = ((bounds?.width ?? 0) * (scale - 1)) / 2
    const maxY = ((bounds?.height ?? 0) * (scale - 1)) / 2
    return {
      x: Math.max(-maxX, Math.min(maxX, next.x)),
      y: Math.max(-maxY, Math.min(maxY, next.y)),
    }
  }
  const changeZoom = (value: number) => {
    const next = Math.max(1, Math.min(MAX_ZOOM, value))
    setZoom(next)
    setPan((current) => next === 1 ? { x: 0, y: 0 } : clampPan(current, next))
  }
  const panBy = (x: number, y: number) => {
    if (zoom <= 1) return
    setPan((current) => clampPan({ x: current.x + x, y: current.y + y }, zoom))
  }
  const reset = () => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }
  const isControl = (target: EventTarget | null) => target instanceof Element && !!target.closest("button,input")

  // Reset when the key changes (adjusting state during render, as React recommends over an effect).
  const [lastResetKey, setLastResetKey] = useState(resetKey)
  if (resetKey !== lastResetKey) {
    setLastResetKey(resetKey)
    reset()
  }

  // React registers wheel listeners as passive, so preventDefault there cannot stop the page from scrolling.
  const zoomRef = useRef(zoom)
  useEffect(() => { zoomRef.current = zoom }, [zoom])
  useEffect(() => {
    const element = viewport.current
    if (!element) return
    const onWheel = (event: WheelEvent) => {
      if (isControl(event.target)) return
      event.preventDefault()
      const next = Math.max(1, Math.min(MAX_ZOOM, zoomRef.current + (event.deltaY < 0 ? STEP : -STEP)))
      setZoom(next)
      setPan((current) => next === 1 ? { x: 0, y: 0 } : clampPan(current, next))
    }
    element.addEventListener("wheel", onWheel, { passive: false })
    return () => element.removeEventListener("wheel", onWheel)
  }, [])

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (isControl(event.target)) return
    const pans: Record<string, [number, number]> = {
      ArrowLeft: [PAN_STEP, 0], ArrowRight: [-PAN_STEP, 0], ArrowUp: [0, PAN_STEP], ArrowDown: [0, -PAN_STEP],
    }
    if (event.key === "+" || event.key === "=") changeZoom(zoom + STEP)
    else if (event.key === "-" || event.key === "_") changeZoom(zoom - STEP)
    else if (event.key === "0") reset()
    else if (pans[event.key] && zoom > 1) panBy(...pans[event.key])
    else return
    event.preventDefault()
  }

  return (
    <div
      ref={viewport}
      tabIndex={0}
      className={cn("relative overflow-hidden outline-none select-none", zoom > 1 && "cursor-grab active:cursor-grabbing", className)}
      style={{ touchAction: zoom > 1 ? "none" : "auto" }}
      onKeyDown={onKeyDown}
      onClick={(event) => {
        if (!moved.current && !isControl(event.target)) onTap?.()
      }}
      onDoubleClick={(event) => {
        if (!isControl(event.target)) reset()
      }}
      onPointerDown={(event) => {
        if (isControl(event.target)) return
        moved.current = false
        drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y }
        if (zoom > 1) event.currentTarget.setPointerCapture(event.pointerId)
      }}
      onPointerMove={(event) => {
        const start = drag.current
        if (!start || start.pointerId !== event.pointerId) return
        const dx = event.clientX - start.x
        const dy = event.clientY - start.y
        if (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD) moved.current = true
        if (zoom > 1) setPan(clampPan({ x: start.panX + dx, y: start.panY + dy }, zoom))
      }}
      onPointerUp={(event) => {
        if (drag.current?.pointerId !== event.pointerId) return
        if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
        drag.current = null
      }}
      onPointerCancel={() => { drag.current = null }}
    >
      {children({
        transform: `translate3d(${pan.x}px, ${pan.y}px, 0) scale(${zoom})`,
        transformOrigin: "center",
        willChange: "transform",
      })}

      <div className="absolute top-1/2 right-3 z-20 flex -translate-y-1/2 flex-col items-center gap-0.5 rounded-md border border-white/15 bg-black/50 p-1.5 text-white shadow-lg backdrop-blur-sm">
        <span className="w-8 text-center text-[10px] tabular-nums" aria-live="polite">{zoom.toFixed(1)}×</span>
        <ZoomButton label="Digital zoom in (mouse wheel up, +)" disabled={zoom >= MAX_ZOOM} onClick={() => changeZoom(zoom + STEP)}><Plus /></ZoomButton>
        <ZoomButton label="Pan up (↑)" disabled={zoom <= 1} onClick={() => panBy(0, PAN_STEP)}><ChevronUp /></ZoomButton>
        <ZoomButton label="Pan left (←)" disabled={zoom <= 1} onClick={() => panBy(PAN_STEP, 0)}><ChevronLeft /></ZoomButton>
        <ZoomButton label="Pan right (→)" disabled={zoom <= 1} onClick={() => panBy(-PAN_STEP, 0)}><ChevronRight /></ZoomButton>
        <ZoomButton label="Pan down (↓)" disabled={zoom <= 1} onClick={() => panBy(0, -PAN_STEP)}><ChevronDown /></ZoomButton>
        <ZoomButton label="Digital zoom out (mouse wheel down, −)" disabled={zoom <= 1} onClick={() => changeZoom(zoom - STEP)}><Minus /></ZoomButton>
        <ZoomButton label="Reset digital view (double-click, 0)" disabled={zoom <= 1} onClick={reset}><RotateCcw /></ZoomButton>
      </div>
    </div>
  )
}

function ZoomButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string
  disabled: boolean
  onClick: () => void
  children: ReactNode
}) {
  return <Button type="button" variant="ghost" size="icon" className="size-8 text-white hover:bg-white/15 hover:text-white" title={label}
    aria-label={label} disabled={disabled} onClick={onClick}>{children}</Button>
}
