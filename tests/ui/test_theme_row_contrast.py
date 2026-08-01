"""Readable secondary/badge text on custom setlist row colors."""

from __future__ import annotations

from cueplayer.ui.theme import (
    badge_dim_on_background,
    badge_lit_on_background,
    contrast_text_color,
    secondary_text_on_background,
)


def test_secondary_text_on_yellow_row_is_dark() -> None:
    color = secondary_text_on_background("#ffff00")
    assert color != "#a1a1aa"
    assert color.startswith("#")


def test_badge_lit_on_colored_row_uses_contrast() -> None:
    lit = badge_lit_on_background("#336699")
    assert lit == contrast_text_color("#336699")


def test_badge_dim_differs_from_lit_on_colored_row() -> None:
    row = "#cc8844"
    assert badge_dim_on_background(row) != badge_lit_on_background(row)
