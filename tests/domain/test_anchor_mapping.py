"""Unit tests for domain anchor mapping (Song Time ↔ Variant Time)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from cueplayer.domain.anchor_mapping import (
    clamp_non_negative,
    coerce_anchor_offset,
    resolve_anchor_offset,
    song_to_variant_time,
    variant_time_in_media,
    variant_to_song_time,
)
from cueplayer.domain.song_variant import SongVariant


def test_zero_offset_is_identity() -> None:
    assert song_to_variant_time(12.5, 0.0) == pytest.approx(12.5)
    assert variant_to_song_time(12.5, 0.0) == pytest.approx(12.5)


def test_positive_offset_delays_media_on_song_timeline() -> None:
    # Media sample 0 aligns with song time +0.5.
    offset = 0.5
    assert song_to_variant_time(0.0, offset) == pytest.approx(-0.5)
    assert song_to_variant_time(0.5, offset) == pytest.approx(0.0)
    assert song_to_variant_time(10.0, offset) == pytest.approx(9.5)
    assert variant_to_song_time(0.0, offset) == pytest.approx(0.5)
    assert variant_to_song_time(9.5, offset) == pytest.approx(10.0)


def test_negative_offset_advances_media_on_song_timeline() -> None:
    # Media sample 0.25 aligns with song time 0 (file starts early).
    offset = -0.25
    assert song_to_variant_time(0.0, offset) == pytest.approx(0.25)
    assert variant_to_song_time(0.25, offset) == pytest.approx(0.0)
    assert song_to_variant_time(5.0, offset) == pytest.approx(5.25)


def test_round_trip_song_variant_song() -> None:
    offset = 1.125
    for song_t in (0.0, 0.001, 3.0, 120.5, -2.0):
        v = song_to_variant_time(song_t, offset)
        assert variant_to_song_time(v, offset) == pytest.approx(song_t)


def test_round_trip_variant_song_variant() -> None:
    offset = -0.75
    for variant_t in (0.0, 0.5, 40.0, -1.0):
        s = variant_to_song_time(variant_t, offset)
        assert song_to_variant_time(s, offset) == pytest.approx(variant_t)


def test_uses_variant_anchor_offset(tmp_path: Path) -> None:
    variant = SongVariant.create("Alt", tmp_path / "a.wav", anchor_offset=0.2)
    assert song_to_variant_time(1.0, variant=variant) == pytest.approx(0.8)
    assert variant_to_song_time(0.8, variant=variant) == pytest.approx(1.0)
    # Explicit offset wins over variant.
    assert song_to_variant_time(1.0, 0.5, variant=variant) == pytest.approx(0.5)


def test_coerce_anchor_offset_edge_cases() -> None:
    assert coerce_anchor_offset(None) == 0.0
    assert coerce_anchor_offset("1.5") == pytest.approx(1.5)
    assert coerce_anchor_offset("nope") == 0.0
    assert coerce_anchor_offset(math.nan) == 0.0
    assert coerce_anchor_offset(math.inf) == 0.0
    assert coerce_anchor_offset(-math.inf) == 0.0
    assert resolve_anchor_offset() == 0.0


def test_mapping_does_not_clamp_by_default() -> None:
    # Out-of-range times remain raw floats — playback decides policy later.
    assert song_to_variant_time(0.1, 1.0) == pytest.approx(-0.9)
    assert variant_to_song_time(-0.5, 0.0) == pytest.approx(-0.5)


def test_clamp_and_in_media_helpers() -> None:
    assert clamp_non_negative(-0.1) == 0.0
    assert clamp_non_negative(2.0) == pytest.approx(2.0)
    assert variant_time_in_media(0.0, media_duration=10.0) is True
    assert variant_time_in_media(9.999, media_duration=10.0) is True
    assert variant_time_in_media(10.0, media_duration=10.0) is False
    assert variant_time_in_media(-0.01, media_duration=10.0) is False
    assert variant_time_in_media(100.0, media_duration=None) is True
    assert variant_time_in_media(0.0, media_duration=0.0) is True


def test_anchor_mapping_module_has_no_runtime_coupling_imports() -> None:
    import ast

    import cueplayer.domain.anchor_mapping as mod

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
