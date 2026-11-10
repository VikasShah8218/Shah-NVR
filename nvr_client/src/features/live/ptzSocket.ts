/**
 * Direct client -> media_node PTZ control over one WebSocket.
 *
 * Hold = send `move` immediately, then re-send it every KEEPALIVE_MS while the button is held
 * (the node auto-stops the camera if the keepalives stop). Release = send `stop`. The node
 * pushes `pose` telemetry (pan/tilt/zoom, the zoom-derived speed, zoom %) a few times a second.
 *
 * This class never reconnects itself; it reports a close and lets the caller re-mint a ticket.
 */
export type Dir = -1 | 0 | 1

export type PtzStatus = {
  pan: number | null
  tilt: number | null
  zoom: number | null
  pan_tilt_state?: string | null
  zoom_state?: string | null
  position_valid?: boolean
}

export type PtzCaps = {
  pan_tilt?: boolean
  zoom?: boolean
  focus?: boolean
  presets?: boolean
  home?: boolean
  home_set?: boolean
  camera_timeout_seconds?: number | null
}

export type PtzTelemetry = { speed: number; zoom_pct: number | null; status: PtzStatus; moving?: boolean }
export type PtzReady = { capabilities: PtzCaps; status: PtzStatus; speed: number; zoom_pct: number | null }

export interface PtzSocketHandlers {
  onReady: (ready: PtzReady) => void
  onTelemetry: (telemetry: PtzTelemetry) => void
  onError: (message: string) => void
  onClosed: (byUser: boolean) => void
}

const KEEPALIVE_MS = 300 // < the node's watchdog (~0.9 s) and ONVIF timeout (>= 1 s)
export const SPEED_MAX = 0.5 // mirrors ptz_ws.SPEED_MAX, for the speed meter scale only

export class PtzSocket {
  private ws: WebSocket
  private handlers: PtzSocketHandlers
  private keepalive: ReturnType<typeof setInterval> | null = null
  private held: { move: object; stop: object } | null = null
  private byUser = false

  constructor(wsUrl: string, handlers: PtzSocketHandlers) {
    this.handlers = handlers
    this.ws = new WebSocket(wsUrl)
    this.ws.onmessage = (e) => this.onMessage(e)
    this.ws.onclose = () => {
      this.clearKeepalive()
      this.handlers.onClosed(this.byUser)
    }
  }

  private onMessage(event: MessageEvent) {
    let msg: { t?: string; message?: string } & Partial<PtzReady> & Partial<PtzTelemetry>
    try {
      msg = JSON.parse(event.data as string)
    } catch {
      return
    }
    if (msg.t === "ready") this.handlers.onReady(msg as PtzReady)
    else if (msg.t === "pose" || msg.t === "status") this.handlers.onTelemetry(msg as PtzTelemetry)
    else if (msg.t === "error") this.handlers.onError(msg.message ?? "PTZ error")
    // "stopped" is an acknowledgement; nothing to do.
  }

  private send(obj: unknown) {
    if (this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj))
  }

  private clearKeepalive() {
    if (this.keepalive) {
      clearInterval(this.keepalive)
      this.keepalive = null
    }
  }

  // Hold any motion: send it now, re-send every KEEPALIVE_MS while held, send its stop on release.
  private begin(move: object, stop: object) {
    this.held = { move, stop }
    this.send(move)
    this.clearKeepalive()
    this.keepalive = setInterval(() => {
      if (this.held) this.send(this.held.move)
    }, KEEPALIVE_MS)
  }

  hold(pan: Dir, tilt: Dir, zoom: Dir) {
    this.begin({ t: "move", pan, tilt, zoom }, { t: "stop" })
  }

  holdFocus(dir: Dir) {
    this.begin({ t: "focus", dir }, { t: "focus_stop" })
  }

  release() {
    const held = this.held
    this.held = null
    this.clearKeepalive()
    if (held) this.send(held.stop)
  }

  refresh() {
    this.send({ t: "refresh" })
  }

  close() {
    this.byUser = true
    this.release()
    this.send({ t: "stop" })
    this.send({ t: "focus_stop" })
    this.ws.close()
  }
}
