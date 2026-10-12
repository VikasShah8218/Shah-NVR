/**
 * Minimal WHEP (WebRTC-HTTP Egress Protocol) reader for MediaMTX.
 * POST an SDP offer to {path}/whep, receive the SDP answer, play the incoming tracks.
 * Non-trickle: we wait for local ICE gathering so a single request is enough.
 */
export interface WhepSession {
  pc: RTCPeerConnection
  close: () => void
}

function waitIceGathering(pc: RTCPeerConnection, timeoutMs: number): Promise<void> {
  if (pc.iceGatheringState === "complete") return Promise.resolve()
  return new Promise((resolve) => {
    const done = () => {
      pc.removeEventListener("icegatheringstatechange", check)
      clearTimeout(timer)
      resolve()
    }
    const check = () => pc.iceGatheringState === "complete" && done()
    const timer = setTimeout(done, timeoutMs)
    pc.addEventListener("icegatheringstatechange", check)
  })
}

function waitConnected(pc: RTCPeerConnection, timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("WebRTC connection timed out")), timeoutMs)
    const check = () => {
      if (pc.connectionState === "connected") {
        clearTimeout(timer)
        resolve()
      } else if (pc.connectionState === "failed" || pc.connectionState === "closed") {
        clearTimeout(timer)
        reject(new Error(`WebRTC ${pc.connectionState}`))
      }
    }
    pc.addEventListener("connectionstatechange", check)
    check()
  })
}

export async function startWhep(whepUrl: string, video: HTMLVideoElement, timeoutMs = 12_000): Promise<WhepSession> {
  const pc = new RTCPeerConnection()
  let sessionUrl: string | null = null
  const close = () => {
    pc.close()
    if (sessionUrl) fetch(sessionUrl, { method: "DELETE" }).catch(() => {})
  }
  try {
    pc.addTransceiver("video", { direction: "recvonly" })
    pc.addTransceiver("audio", { direction: "recvonly" })
    const stream = new MediaStream()
    pc.ontrack = (ev) => {
      stream.addTrack(ev.track)
      if (video.srcObject !== stream) video.srcObject = stream
    }

    await pc.setLocalDescription(await pc.createOffer())
    await waitIceGathering(pc, 1500)

    const controller = new AbortController()
    const abort = setTimeout(() => controller.abort(), timeoutMs)
    let res: Response
    try {
      res = await fetch(whepUrl, {
        method: "POST",
        headers: { "Content-Type": "application/sdp" },
        body: pc.localDescription!.sdp,
        signal: controller.signal,
      })
    } finally {
      clearTimeout(abort)
    }
    if (!res.ok) throw new Error(res.status === 404 ? "Stream not available" : `WHEP HTTP ${res.status}`)
    const location = res.headers.get("Location")
    if (location) sessionUrl = new URL(location, whepUrl).toString()
    await pc.setRemoteDescription({ type: "answer", sdp: await res.text() })
    await waitConnected(pc, timeoutMs)
    return { pc, close }
  } catch (err) {
    close()
    throw err
  }
}

/** Approximate playout delay (ms) of the inbound video: jitter-buffer delay per emitted frame. */
export async function webrtcDelayMs(pc: RTCPeerConnection): Promise<number | null> {
  const stats = await pc.getStats()
  let delay: number | null = null
  stats.forEach((s) => {
    if (s.type === "inbound-rtp" && s.kind === "video" && s.jitterBufferEmittedCount > 0) {
      delay = Math.round((s.jitterBufferDelay / s.jitterBufferEmittedCount) * 1000)
    }
  })
  return delay
}
