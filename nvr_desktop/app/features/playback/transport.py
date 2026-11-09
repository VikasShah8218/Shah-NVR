"""Playback transport maths (port of nvr_client/src/features/playback/transport.ts).

Frame stepping uses mpv's own `frame-step` / `frame-back-step` (exact frames), so only reverse play needs
maths here: mpv on our HLS VOD can't decode backwards cheaply, so reverse is a chain of seeks anchored to
wall time - slow decoding shows fewer frames, but the playhead still moves back at the true speed.
"""

from __future__ import annotations

from dataclasses import dataclass

RATES = [0.5, 1, 2, 4, 8, 16]
REVERSE_TICK_MS = 100
EXACT_SEEK_MAX_RATE = 2  # above this, seek to keyframes (cheap) instead of exact frames


@dataclass(frozen=True)
class ReverseAnchor:
    pos: float      # player position (s) when reverse started / the rate changed
    clock: float    # monotonic clock (s) at that moment
    rate: float


def reverse_target(anchor: ReverseAnchor, now: float, floor: float = 0.0) -> float:
    """Position to show now: anchor - rate * elapsed, never before `floor` (the playlist start)."""
    return max(floor, anchor.pos - anchor.rate * (now - anchor.clock))


def reverse_done(target: float, floor: float = 0.0) -> bool:
    return target <= floor


def seek_precision(rate: float) -> str:
    """Exact frames at slow reverse; keyframe seeks when going fast (one decode per seek)."""
    return "exact" if rate <= EXACT_SEEK_MAX_RATE else "keyframes"
