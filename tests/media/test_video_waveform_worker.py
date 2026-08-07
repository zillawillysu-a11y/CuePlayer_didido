from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cueplayer.media.video_waveform_artifact import empty_artifact
from cueplayer.media.video_waveform_worker import main


def test_worker_builds_and_saves_complete_artifact(tmp_path: Path) -> None:
    media = tmp_path / "影片.mp4"
    media.write_bytes(b"x")
    art = empty_artifact(media, duration_seconds=2.0)
    assert art is not None
    art.complete = True
    with (
        patch(
            "cueplayer.media.video_waveform_worker.build_artifact_continuous",
            return_value=art,
        ),
        patch("cueplayer.media.video_waveform_worker.save_artifact_to_disk") as save,
    ):
        result = main([str(media), "2.0", "0"])
    assert result == 0
    save.assert_called_once()
