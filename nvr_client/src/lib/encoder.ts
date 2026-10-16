import type { EncoderOption, EncoderValues } from "../api/encoder"

/** Decimal GB, video only, at the configured bitrate ceiling; not a VBR guarantee. */
export function videoGBPerDay(kbps: number | null | undefined): number | null {
  return kbps != null && Number.isFinite(kbps) && kbps > 0 && kbps < 1_000_000 ? kbps / 1000 * 10.8 : null
}

export function changedValues(current: EncoderValues, draft: EncoderValues): EncoderValues {
  return Object.fromEntries(Object.entries(draft).filter(([k, v]) => v != null && v !== current[k as keyof EncoderValues]))
}

export type Preset = "Storage saver" | "Best quality" | "Low-bandwidth substream"

/** Presets are editable proposals, keep the codec, and use only advertised values. */
export function presetValues(current: EncoderValues, option: EncoderOption, preset: Preset): EncoderValues {
  const out = { ...current }
  const best = preset === "Best quality"
  const low = preset === "Low-bandwidth substream"
  if (option.bitrate_range && current.bitrate_kbps != null && current.bitrate_kbps < 1_000_000) {
    out.bitrate_kbps = Math.round(Math.max(option.bitrate_range[0],
      Math.min(option.bitrate_range[1], current.bitrate_kbps * (best ? 1.5 : low ? 0.25 : 0.6))))
  }
  const desiredFps = best ? current.fps : low ? 10 : 15
  if (current.fps != null && desiredFps != null) {
    const rates = option.frame_rates ?? []
    if (rates.length) {
      const candidates = rates.filter(f => f <= desiredFps)
      out.fps = candidates.length ? Math.max(...candidates) : Math.min(...rates)
    } else if (option.fps_range) {
      out.fps = Math.max(option.fps_range[0], Math.min(option.fps_range[1], desiredFps))
    }
  }
  if (low && option.resolutions?.length) {
    const [w, h] = [...option.resolutions].sort((a, b) => a[0] * a[1] - b[0] * b[1])[0]
    out.width = w; out.height = h
  }
  if (best && option.quality_range && current.quality != null) out.quality = option.quality_range[1]
  return out
}
