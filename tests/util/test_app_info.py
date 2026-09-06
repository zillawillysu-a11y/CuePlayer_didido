"""Canonical version/copyright source: constants and derived strings."""

from __future__ import annotations

from cueplayer import __version__
from cueplayer.app_info import (
    APP_NAME,
    APP_TITLE,
    APP_VERSION,
    COMPANY_NAME,
    COPYRIGHT,
    COPYRIGHT_YEAR,
    version_tuple,
)


def test_app_name_and_version() -> None:
    assert APP_NAME == "Cue Player"
    assert APP_VERSION == "1.14"
    assert APP_VERSION == __version__


def test_app_title_combines_name_and_version() -> None:
    assert APP_TITLE == "Cue Player 1.14"


def test_copyright_text() -> None:
    assert COMPANY_NAME == "DiDiDo Design Co., Ltd."
    assert COPYRIGHT_YEAR == "2026"
    assert COPYRIGHT == "Copyright © 2026 DiDiDo Design Co., Ltd. All rights reserved."


def test_version_tuple_parses_two_part_version() -> None:
    assert version_tuple() == (1, 14, 0, 0)
