"""Clean Video Output aspect sizing helpers."""

from __future__ import annotations

from cueplayer.ui.video_output_window import content_size_for_aspect


def test_content_size_for_aspect_prefers_width() -> None:
    assert content_size_for_aspect(160, 120, prefer_width=True) == (160, 90)


def test_content_size_for_aspect_prefers_height() -> None:
    assert content_size_for_aspect(200, 90, prefer_width=False) == (160, 90)
