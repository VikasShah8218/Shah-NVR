/** One in-flight pulse, no motion retries, and an ordered Stop on every exit. */
export type Velocity = { pan?: number; tilt?: number; zoom?: number }
export type MotionCommand = Velocity & { action: "move" | "stop"; sequence: number }

export class PtzHoldController {
  private send: (command: MotionCommand) => Promise<unknown>
  private onError: (error: unknown) => void
  private held = false
  private running = false
  private blocked = false
  private disposed = false
  private sequence = 0
  private stopPending: Promise<void> | undefined

  constructor(send: (command: MotionCommand) => Promise<unknown>, onError: (error: unknown) => void) {
    this.send = send
    this.onError = onError
  }

  nextSequence() { return ++this.sequence }
  get available() { return !this.blocked && !this.disposed && !this.running && !this.stopPending }

  async start(velocity: Velocity) {
    if (this.running || this.stopPending || this.blocked || this.disposed) return
    this.held = true
    this.running = true
    try {
      while (this.held && !this.disposed) {
        await this.send({ action: "move", sequence: this.nextSequence(), ...velocity })
      }
    } catch (error) {
      // A Stop that overtakes a not-yet-dispatched move is expected on a quick release.
      if (this.held || (error as { code?: string })?.code !== "ptz_stale_command") {
        this.blocked = true
        this.onError(error)
      }
    } finally {
      this.running = false
      await this.stop()
    }
  }

  stop(): Promise<void> {
    this.held = false // synchronous: a delayed response cannot start another pulse
    if (this.stopPending) return this.stopPending
    this.stopPending = this.send({ action: "stop", sequence: this.nextSequence() })
      .then(() => undefined)
      .catch((error: unknown) => { this.blocked = true; this.onError(error) })
      .finally(() => { this.stopPending = undefined })
    return this.stopPending
  }

  dispose() { this.disposed = true; return this.stop() }
}
