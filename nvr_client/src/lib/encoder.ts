import type { EncoderOption, EncoderValues } from "../api/encoder"

/** Decimal GB, video only, at the configured bitrate ceiling; not a VBR guarantee. */
export function videoGBPerDay(kbps: number | null | undefined): number | null {
  return kbps != null && Number.isFinite(kbps) && kbps > 0 && kbps < 1_000_000 ? kbps / 1000 * 10.8 : null
}

export function changedValues(current: EncoderValues, draft: EncoderValues): EncoderValues {
  return Object.fromEntries(Object.entries(draft).filter(([k, v]) => v != null && v !== current[k as keyof EncoderValues]))
}

/** Match the node's whole-alternative check; unadvertised unchanged values may be preserved. */
export function encoderOptionErrors(option: EncoderOption, current: EncoderValues, target: EncoderValues): string[] {
  const changes = changedValues(current, target)
  const switched = "encoding" in changes
  const errors: string[] = []
  if ((option.resolutions?.length || switched || "width" in changes || "height" in changes)
    && !option.resolutions?.some(([w, h]) => w === target.width && h === target.height)) {
    errors.push("Resolution is not supported by this option")
  }
  const bounds = { fps: "fps_range", bitrate_kbps: "bitrate_range", gop: "gop_range", quality: "quality_range" } as const
  for (const key of Object.keys(bounds) as (keyof typeof bounds)[]) {
    const value = target[key]
    if (value == null) continue
    const range = option[bounds[key]]
    const rates = key === "fps" ? option.frame_rates : []
    const valid = rates?.length ? rates.includes(value)
      : range ? value >= range[0] && value <= range[1] : !(key in changes) && !switched
    if (!valid) errors.push(`${key}=${value} is outside this option's advertised limits (or limits are unavailable)`)
  }
  for (const [key, choices] of [["codec_profile", "codec_profiles"], ["rate_control", "rate_controls"]] as const) {
    const value = target[key]
    const allowed = option[choices] ?? []
    if (value != null && (allowed.length || key in changes || switched) && !allowed.includes(value)) {
      errors.push(`${key}=${value} is not supported by this option`)
    }
  }
  return errors
}

/** Keep alternatives separate. Identical entries need only one selection in the UI. */
export function encoderAlternatives(options: EncoderOption[], encoding: EncoderValues["encoding"]): EncoderOption[] {
  const seen = new Set<string>()
  return options.filter(option => {
    if (option.encoding !== encoding) return false
    const key = JSON.stringify(option)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function preferredEncoderOption(options: EncoderOption[], current: EncoderValues, target: EncoderValues): number {
  let best = 0
  let count = Infinity
  let resolutionMatches = false
  options.forEach((option, index) => {
    const errors = encoderOptionErrors(option, current, target).length
    const matches = option.resolutions?.some(([w, h]) => w === target.width && h === target.height) ?? false
    if (errors < count || (errors === count && matches && !resolutionMatches)) {
      best = index; count = errors; resolutionMatches = matches
    }
  })
  return best
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
