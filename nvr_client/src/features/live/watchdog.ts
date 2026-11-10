/** "No picture" watchdog of the live player (pure helpers: node --test runs them). */

export const WATCHDOG_INTERVAL_MS = 2000
/** WebRTC: no new decoded frame this long -> reconnect. */
export const NO_PICTURE_MS = 8000
/** LL-HLS fills its safety buffer before it shows frames: buffer x2 + this. */
export const NO_PICTURE_HLS_MARGIN_MS = 4000
const MAX_EVENTS = 16

export function noPictureLimitMs(mode: "webrtc" | "hls", hlsBufferSeconds: number): number {
  return mode === "hls" ? Math.max(NO_PICTURE_MS, hlsBufferSeconds * 2000 + NO_PICTURE_HLS_MARGIN_MS) : NO_PICTURE_MS
}

/** Keep the last steps of a player, e.g. "webrtc@0.0s webrtc-connected@0.4s no-picture@8.1s". */
export function pushEvent(events: string[], step: string, elapsedMs: number): void {
  events.push(`${step}@${(elapsedMs / 1000).toFixed(1)}s`)
  if (events.length > MAX_EVENTS) events.splice(0, events.length - MAX_EVENTS)
}
