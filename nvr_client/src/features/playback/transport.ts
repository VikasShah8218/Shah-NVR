/**
 * Pure playback-transport maths for VodPlayer: frame stepping and timer-driven reverse play.
 * Kept free of React / DOM so it can be unit-tested with `node --test`.
 */

/** Playback speeds offered in the rate menu (forward and reverse use the same list). */
export const RATES = [0.5, 1, 2, 4, 8, 16]

/** Cameras record ~30 fps; we don't store fps per segment, so a frame step is a fixed 1/30 s nudge. */
export const DEFAULT_FPS = 30

/** How often reverse play issues a new seek (ms). The real speed comes from wall time, not tick count. */
export const REVERSE_TICK_MS = 100

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** Media time after stepping `frames` frames (negative = back). Clamped to [0, duration]. */
export function frameStepTarget(current: number, frames: number, duration: number, fps = DEFAULT_FPS): number {
  const end = Number.isFinite(duration) && duration > 0 ? duration : Infinity
  return clamp(current + frames / fps, 0, end)
}

/**
 * Reverse play is anchored: we remember the media time and the clock when reverse started (or when the
 * rate changed) and every tick seek to `anchorMedia - rate * elapsed`. Slow decoders show fewer frames
 * but the playhead still moves backwards at the true speed instead of drifting.
 */
export interface ReverseAnchor {
  media: number
  clock: number
  rate: number
}

export function reverseTarget(anchor: ReverseAnchor, now: number): number {
  return Math.max(0, anchor.media - (anchor.rate * (now - anchor.clock)) / 1000)
}

/** True once reverse play has reached the start of the playlist and should stop. */
export function reverseDone(target: number): boolean {
  return target <= 0
}
