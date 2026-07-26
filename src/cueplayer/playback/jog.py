"""Arrow-key jog / scrub acceleration curve.

Extracted as a pure function so the Left/Right key-repeat acceleration used
by the main window can be unit-tested without a Qt event loop.
"""

from __future__ import annotations

MIN_HOLD_FRAMES = 1
MAX_HOLD_FRAMES = 30
RAMP_SECONDS = 4.0


def hold_step_frames(
    elapsed_seconds: float,
    *,
    min_frames: int = MIN_HOLD_FRAMES,
    max_frames: int = MAX_HOLD_FRAMES,
    ramp_seconds: float = RAMP_SECONDS,
) -> int:
    """Frames to move for one arrow-key repeat, given how long the key has
    been held (seconds since the key first went down).

    - A fresh tap (``elapsed_seconds <= 0``) always steps exactly one frame.
    - While held, the step size ramps up along an ease-in (quadratic) curve
      from ``min_frames`` to ``max_frames`` over ``ramp_seconds``, then stays
      pegged at ``max_frames`` for as long as the key remains down.

    This makes the transport feel like a single-frame nudge on a tap but
    accelerate smoothly (not one abrupt jump) into a fast scrub the longer
    the key is held — useful for moving across long songs.
    """
    if elapsed_seconds <= 0 or ramp_seconds <= 0:
        return min_frames
    t = min(elapsed_seconds, ramp_seconds) / ramp_seconds
    frames = min_frames + (max_frames - min_frames) * (t * t)
    return max(min_frames, int(round(frames)))
