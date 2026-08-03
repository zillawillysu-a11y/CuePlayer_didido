"""Song edit dialog helpers."""

from __future__ import annotations

from cueplayer.ui.song_edit_dialog import suggest_ma_export_name


def test_suggest_ma_export_name_ascii_stem() -> None:
    assert suggest_ma_export_name("My_Song_v2") == "My_Song_v2"


def test_suggest_ma_export_name_chinese_only_is_blank() -> None:
    assert suggest_ma_export_name("純影片") == ""


def test_suggest_ma_export_name_mixed_uses_pinyin() -> None:
    result = suggest_ma_export_name("開場Intro")
    assert result
    assert "Intro" in result
