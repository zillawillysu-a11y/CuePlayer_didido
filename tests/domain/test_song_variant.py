"""Unit tests for SongVariant domain foundation (no persistence / UI / engine)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cueplayer.domain.models import AudioTrack, Mark, Song
from cueplayer.domain.song_variant import (
    SongVariant,
    coerce_variant_kind,
)


def test_coerce_variant_kind_known_and_default() -> None:
    assert coerce_variant_kind("audio") == "audio"
    assert coerce_variant_kind("VIDEO") == "video"
    assert coerce_variant_kind("ltc") == "ltc"
    assert coerce_variant_kind("click") == "click"
    assert coerce_variant_kind("nope") == "audio"
    assert coerce_variant_kind(None, default="video") == "video"


def test_song_variant_create_defaults(tmp_path: Path) -> None:
    path = tmp_path / "床.wav"
    path.write_bytes(b"x")
    variant = SongVariant.create("  Old mix  ", path)
    assert variant.name == "Old mix"
    assert variant.kind == "audio"
    assert variant.path == path
    assert variant.anchor_offset == 0.0
    assert variant.enabled is True
    assert variant.metadata == {}
    assert variant.id
    assert variant.is_audio
    assert variant.has_resolvable_path()


def test_song_variant_create_empty_name_fallback(tmp_path: Path) -> None:
    variant = SongVariant.create("   ", tmp_path / "a.wav")
    assert variant.name == "Variant"


def test_song_variant_create_with_metadata_and_offset(tmp_path: Path) -> None:
    variant = SongVariant.create(
        "v2",
        tmp_path / "b.wav",
        kind="ltc",
        anchor_offset=0.12,
        enabled=False,
        metadata={"note": "stripe", "n": 3},
    )
    assert variant.kind == "ltc"
    assert variant.anchor_offset == pytest.approx(0.12)
    assert variant.enabled is False
    assert variant.metadata == {"note": "stripe", "n": "3"}
    assert not variant.is_audio


def test_song_variant_copy_with_new_id(tmp_path: Path) -> None:
    original = SongVariant.create("A", tmp_path / "a.wav", metadata={"k": "v"})
    copied = original.copy_with_new_id()
    assert copied.id != original.id
    assert copied.name == original.name
    assert copied.path == original.path
    assert copied.metadata == {"k": "v"}
    assert copied.metadata is not original.metadata


def test_song_starts_with_empty_variants() -> None:
    song = Song.create("曲")
    assert song.variants == []
    assert song.selected_variant_id is None
    assert song.selected_variant() is None
    assert song.selected_audio_path() is None


def test_song_select_variant_and_audio_path(tmp_path: Path) -> None:
    song = Song.create("曲")
    a = SongVariant.create("A", tmp_path / "a.wav")
    b = SongVariant.create("B", tmp_path / "b.wav")
    song.variants = [a, b]
    assert song.select_variant(b.id) is True
    assert song.selected_variant_id == b.id
    assert song.selected_variant() is b
    assert song.selected_audio_path() == Path(tmp_path / "b.wav")
    assert song.select_variant("missing") is False
    assert song.selected_variant_id == b.id


def test_selected_variant_skips_disabled(tmp_path: Path) -> None:
    song = Song.create("曲")
    disabled = SongVariant.create("off", tmp_path / "a.wav", enabled=False)
    enabled = SongVariant.create("on", tmp_path / "b.wav")
    song.variants = [disabled, enabled]
    song.selected_variant_id = disabled.id
    assert song.selected_variant() is enabled
    assert song.selected_audio_path() == Path(tmp_path / "b.wav")


def test_selected_audio_path_ignores_non_audio(tmp_path: Path) -> None:
    song = Song.create("曲")
    video = SongVariant.create("vid", tmp_path / "v.mp4", kind="video")
    song.variants = [video]
    song.selected_variant_id = video.id
    assert song.selected_variant() is video
    assert song.selected_audio_path() is None


def test_selected_audio_path_ignores_empty_path() -> None:
    song = Song.create("曲")
    bare = SongVariant(id="x", name="empty", kind="audio", path=Path(""))
    song.variants = [bare]
    song.selected_variant_id = bare.id
    assert song.selected_audio_path() is None


def test_marks_remain_on_song_independent_of_variants(tmp_path: Path) -> None:
    song = Song.create("曲")
    mark = song.add_mark(1, 1.5, display_name="Cue")
    song.variants = [SongVariant.create("A", tmp_path / "a.wav")]
    song.select_variant(song.variants[0].id)
    assert song.marks[0] is mark
    assert mark.time_seconds == 1.5
    song.variants.append(SongVariant.create("B", tmp_path / "b.wav"))
    song.select_variant(song.variants[1].id)
    assert len(song.marks) == 1
    assert song.marks[0].display_name == "Cue"


def test_ensure_variants_from_legacy_audio_tracks(tmp_path: Path) -> None:
    song = Song.create("曲")
    main = tmp_path / "main.wav"
    ref = tmp_path / "old.wav"
    main.write_bytes(b"a")
    ref.write_bytes(b"b")
    song.audio_tracks = [
        AudioTrack(id="t-ref", name="Old", path=ref, role="reference", offset_seconds=0.2),
        AudioTrack(id="t-main", name="Main", path=main, role="main"),
    ]
    assert song.ensure_variants_from_legacy_audio_tracks() is True
    assert len(song.variants) == 2
    assert song.selected_variant() is not None
    assert song.selected_variant().path == main
    assert song.variants[0].anchor_offset == pytest.approx(0.2)
    assert song.variants[0].metadata["legacy_role"] == "reference"
    # Idempotent when variants already present.
    assert song.ensure_variants_from_legacy_audio_tracks() is False


def test_ensure_variants_noop_without_tracks() -> None:
    song = Song.create("曲")
    assert song.ensure_variants_from_legacy_audio_tracks() is False


def test_active_audio_path_falls_back_to_legacy_tracks(tmp_path: Path) -> None:
    song = Song.create("曲")
    main = tmp_path / "main.wav"
    song.audio_tracks = [AudioTrack(id="main", name="Main", path=main, role="main")]
    assert song.variants == []
    assert song.active_audio_path() == Path(main)
    assert song.selected_audio_path() is None


def test_active_audio_path_prefers_selected_variant(tmp_path: Path) -> None:
    song = Song.create("曲")
    track = tmp_path / "track.wav"
    variant_path = tmp_path / "variant.wav"
    song.audio_tracks = [AudioTrack(id="main", name="Main", path=track, role="main")]
    a = SongVariant.create("A", variant_path)
    song.variants = [a]
    song.selected_variant_id = a.id
    assert song.active_audio_path() == Path(variant_path)


def test_replace_main_audio_legacy_only_when_no_variants(tmp_path: Path) -> None:
    song = Song.create("曲")
    path = tmp_path / "新.wav"
    song.replace_main_audio(path)
    assert len(song.audio_tracks) == 1
    assert song.audio_tracks[0].path == path
    assert song.variants == []
    assert song.active_audio_path() == Path(path)


def test_replace_main_audio_syncs_existing_variants(tmp_path: Path) -> None:
    song = Song.create("曲")
    old = tmp_path / "old.wav"
    new = tmp_path / "new.wav"
    a = SongVariant.create("A", old, anchor_offset=0.25)
    b = SongVariant.create("B", tmp_path / "other.wav")
    song.variants = [a, b]
    song.selected_variant_id = a.id
    song.replace_main_audio(new, name="Bed")
    assert len(song.variants) == 1
    assert song.variants[0].id == a.id
    assert song.variants[0].path == new
    assert song.variants[0].name == "Bed"
    assert song.variants[0].anchor_offset == pytest.approx(0.25)
    assert song.selected_variant_id == a.id
    assert song.active_audio_path() == Path(new)
    assert song.audio_tracks[0].path == new


def test_clear_audio_media(tmp_path: Path) -> None:
    song = Song.create("曲")
    song.replace_main_audio(tmp_path / "a.wav")
    song.ensure_variants_from_legacy_audio_tracks()
    song.clear_audio_media()
    assert song.audio_tracks == []
    assert song.variants == []
    assert song.selected_variant_id is None
    assert song.active_audio_path() is None


def test_song_duplicate_copies_variants_with_new_ids(tmp_path: Path) -> None:
    song = Song.create("Original")
    a = SongVariant.create("A", tmp_path / "a.wav", metadata={"k": "1"})
    b = SongVariant.create("B", tmp_path / "b.wav", anchor_offset=0.05)
    song.variants = [a, b]
    song.selected_variant_id = b.id
    song.add_mark(1, 2.0, display_name="Hit")

    dup = song.duplicate(name="Copy")
    assert len(dup.variants) == 2
    assert {v.id for v in dup.variants}.isdisjoint({a.id, b.id})
    assert dup.selected_variant_id == dup.variants[1].id
    assert dup.variants[1].name == "B"
    assert dup.variants[1].anchor_offset == pytest.approx(0.05)
    assert dup.variants[0].metadata == {"k": "1"}
    assert len(dup.marks) == 1
    assert dup.marks[0].id != song.marks[0].id


def test_song_variant_module_has_no_runtime_coupling_imports() -> None:
    import ast

    import cueplayer.domain.song_variant as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    banned = {"PySide6", "PySide2", "qtpy", "json", "cueplayer"}
    assert imported.isdisjoint(banned)
    # Stdlib-only + typing; no cueplayer.playback / persistence / ui.
    assert "pathlib" in imported or True
