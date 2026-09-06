"""Canonical app identity: name, version, and copyright.

Every UI surface (splash, main window title, About dialog) and packaging
metadata (PyInstaller Windows version resource, Inno Setup installer) reads
these constants instead of hard-coding its own copy. To ship a new version,
change ``__version__`` in ``cueplayer/__init__.py`` — nothing else.
"""

from __future__ import annotations

from cueplayer import __version__

APP_NAME = "Cue Player"
APP_VERSION = __version__
COMPANY_NAME = "DiDiDo Design Co., Ltd."
COPYRIGHT_YEAR = "2026"

APP_TITLE = f"{APP_NAME} {APP_VERSION}"

COPYRIGHT = f"Copyright © {COPYRIGHT_YEAR} {COMPANY_NAME} All rights reserved."


def version_tuple() -> tuple[int, int, int, int]:
    """Parse ``APP_VERSION`` (e.g. "1.14") into a 4-int Windows VersionInfo tuple."""
    parts = [int(p) for p in APP_VERSION.split(".") if p.isdigit()]
    parts = (parts + [0, 0, 0, 0])[:4]
    return (parts[0], parts[1], parts[2], parts[3])
