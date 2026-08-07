from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cueplayer.media.video_waveform_artifact import empty_artifact
from cueplayer.media.video_waveform_artifact import _build_artifact_isolated
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


def test_isolated_decode_keeps_running_when_playback_pause_policy_is_true(
    tmp_path: Path,
) -> None:
    media = tmp_path / "play-through.mp4"
    media.write_bytes(b"x")
    art = empty_artifact(media, duration_seconds=2.0)
    assert art is not None
    art.complete = True

    class FakeProcess:
        returncode = 0

        def __init__(self) -> None:
            self.polls = 0
            self.terminated = False

        def poll(self) -> int | None:
            self.polls += 1
            return None if self.polls == 1 else 0

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float) -> int:
            del timeout
            return 0

        def kill(self) -> None:
            self.terminated = True

    proc = FakeProcess()
    with (
        patch("cueplayer.media.video_waveform_artifact.subprocess.Popen", return_value=proc),
        patch("cueplayer.media.video_waveform_artifact.time.sleep"),
        patch(
            "cueplayer.media.video_waveform_artifact.load_artifact_from_disk",
            return_value=art,
        ),
    ):
        result = _build_artifact_isolated(
            media,
            duration_seconds=2.0,
            stream_index=0,
            cancel_check=lambda: False,
            pause_check=lambda: True,
        )
    assert result is art
    assert proc.terminated is False
