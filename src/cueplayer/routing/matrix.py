"""Audio channel routing matrix helpers for the playback spike."""

from __future__ import annotations

import numpy as np


def apply_routing(
    source_frames: np.ndarray,
    route: dict[int, list[int]],
    output_channels: int,
) -> np.ndarray:
    """
    Map source channels to device output channels.

    Parameters
    ----------
    source_frames:
        Shape (frames, source_channels), float32 preferred.
    route:
        Mapping of source_channel_index -> list of output_channel_indices.
        Example: {0: [2], 1: [0, 1]} means L->CH3, R->CH1+CH2 (0-based).
    output_channels:
        Number of channels to open on the output device.
    """
    if source_frames.ndim != 2:
        raise ValueError("source_frames must be shaped (frames, channels)")

    frames, source_count = source_frames.shape
    out = np.zeros((frames, output_channels), dtype=np.float32)
    src = np.asarray(source_frames, dtype=np.float32)

    for src_ch, destinations in route.items():
        if src_ch < 0 or src_ch >= source_count:
            raise ValueError(f"source channel {src_ch} out of range 0..{source_count - 1}")
        for dest_ch in destinations:
            if dest_ch < 0 or dest_ch >= output_channels:
                raise ValueError(
                    f"output channel {dest_ch} out of range 0..{output_channels - 1}"
                )
            out[:, dest_ch] += src[:, src_ch]

    # Soft clip to keep spike safe on speakers / interfaces.
    np.clip(out, -1.0, 1.0, out=out)
    return out


def warn_if_outputs_insufficient(needed: list[int], available: int) -> str | None:
    missing = [ch for ch in needed if ch >= available]
    if not missing:
        return None
    human = ", ".join(str(ch + 1) for ch in missing)
    return (
        f"Output device only has {available} channel(s); "
        f"requested channel(s) {human} are unavailable."
    )
