"""Out-of-process entry point for cold video waveform decoding on Windows."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from cueplayer.media.video_waveform_artifact import (
    VideoWaveformArtifact,
    artifact_cache_key,
    build_artifact_continuous,
    save_artifact_to_disk,
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 4:
        return 2
    path = Path(args[0])
    progress_path = Path(args[3])
    try:
        duration = float(args[1])
        stream_index = int(args[2])
    except ValueError:
        return 2
    key = artifact_cache_key(
        path, duration_seconds=duration, stream_index=stream_index
    )
    if key is None:
        return 3
    last_write = 0.0

    def _progress(partial: VideoWaveformArtifact) -> None:
        nonlocal last_write
        now = time.monotonic()
        if now - last_write < 0.5:
            return
        last_write = now
        percent = max(0, min(99, int(round(partial.coverage_ratio * 100.0))))
        try:
            progress_path.write_text(str(percent), encoding="ascii")
        except OSError:
            pass

    art = build_artifact_continuous(
        path,
        duration_seconds=duration,
        stream_index=stream_index,
        on_progress=_progress,
    )
    if art is None or not art.complete:
        return 4
    save_artifact_to_disk(key, art)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
