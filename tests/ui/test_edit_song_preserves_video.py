"""Edit Song rename must keep video clips / music waveform warm."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLineEdit

from cueplayer.domain.models import AudioTrack, Project, Song, VideoClip
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.song_edit_dialog import SongDraft, SongEditDialog, _COL_NAME


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_edit_dialog_preserves_both_media_on_rename_only(tmp_path: Path, app: QApplication) -> None:
    audio = tmp_path / "song.wav"
    video = tmp_path / "vj.mp4"
    audio.write_bytes(b"RIFF")
    video.write_bytes(b"ftyp")
    draft = SongDraft(
        name="舊名",
        audio_path=audio,
        video_path=video,
        song_id="s1",
    )
    dialog = SongEditDialog([draft], parent=None)
    name_edit = dialog.table.cellWidget(0, _COL_NAME)
    assert isinstance(name_edit, QLineEdit)
    name_edit.setText("新名")
    dialog._accept()
    out = dialog.result_drafts()[0]
    assert out.name == "新名"
    assert out.audio_path == audio
    assert out.video_path == video
    assert not out.media_cleared


def test_apply_draft_rename_keeps_video_clips(tmp_path: Path, app: QApplication) -> None:
    audio = tmp_path / "song.wav"
    video = tmp_path / "vj.mp4"
    audio.write_bytes(b"RIFF")
    video.write_bytes(b"ftyp")
    window = MainWindow(Project.create("P"))
    song = window.project.songs[0]
    song.name = "舊名"
    song.audio_tracks = [
        AudioTrack(id="main_audio", name="song", path=audio, role="main")
    ]
    clip = VideoClip.create(name="vj", path=video, start_seconds=0.0, duration_seconds=5.0)
    song.video_clips = [clip]
    clip_id = clip.id
    draft = SongDraft(
        name="新名",
        setlist_number=song.setlist_number,
        ma_export_name="Xin Ming",
        audio_path=audio,
        video_path=video,
        song_id=song.id,
    )
    assert not window._draft_changes_media(song, draft)
    window._apply_draft_to_song(song, draft)
    assert song.name == "新名"
    assert len(song.video_clips) == 1
    assert song.video_clips[0].id == clip_id
    assert song.audio_tracks and Path(song.audio_tracks[0].path) == audio


def test_legacy_audio_only_draft_does_not_wipe_video(tmp_path: Path, app: QApplication) -> None:
    """Old dialog behavior dropped video_path when file cell showed .wav."""
    audio = tmp_path / "song.wav"
    video = tmp_path / "vj.mp4"
    audio.write_bytes(b"RIFF")
    video.write_bytes(b"ftyp")
    window = MainWindow(Project.create("P"))
    song = window.project.songs[0]
    song.audio_tracks = [
        AudioTrack(id="main_audio", name="song", path=audio, role="main")
    ]
    clip = VideoClip.create(name="vj", path=video, start_seconds=0.0, duration_seconds=5.0)
    song.video_clips = [clip]
    clip_id = clip.id
    # Simulate pre-fix draft that only carried the audio path.
    draft = SongDraft(
        name="Renamed",
        setlist_number=song.setlist_number,
        ma_export_name="Renamed",
        audio_path=audio,
        video_path=None,
        song_id=song.id,
    )
    window._apply_draft_to_song(song, draft)
    assert len(song.video_clips) == 1
    assert song.video_clips[0].id == clip_id
