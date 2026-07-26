"""Song.row_color persistence: round-trip + migration for older projects."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.persistence.project_store import load_project, save_project


def test_row_color_roundtrip(tmp_path: Path) -> None:
    project = Project.create("演唱會")
    project.songs[0].row_color = "#ff5a5f"
    path = tmp_path / "中文專案" / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.songs[0].row_color == "#FF5A5F"


def test_row_color_default_empty(tmp_path: Path) -> None:
    project = Project.create("Untitled")
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.songs[0].row_color == ""


def test_row_color_missing_field_migrates_to_empty(tmp_path: Path) -> None:
    """Older project files simply won't have "row_color" on a song at all."""
    project = Project.create("Legacy")
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    text = path.read_text(encoding="utf-8").replace('"row_color": "",\n', "", 1)
    path.write_text(text, encoding="utf-8")
    loaded = load_project(path)
    assert loaded.songs[0].row_color == ""


def test_row_color_invalid_value_is_dropped(tmp_path: Path) -> None:
    project = Project.create("Bad Color")
    project.songs[0].row_color = "not-a-color"
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.songs[0].row_color == ""
