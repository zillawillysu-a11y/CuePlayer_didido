"""Tests for frozen-vs-source runtime helpers."""

from __future__ import annotations

from cueplayer.util.runtime import (
    app_dir,
    app_icon_path,
    is_frozen,
    package_root,
    ui_assets_dir,
)


def test_runtime_paths_resolve_in_source_tree() -> None:
    assert is_frozen() is False
    root = package_root()
    assert root.name == "cueplayer"
    assert (root / "app.py").is_file()
    assert ui_assets_dir().is_dir()
    assert app_dir().name == "cueplayer"
    # Icon is optional until design assets are added.
    icon = app_icon_path()
    assert icon is None or icon.is_file()
