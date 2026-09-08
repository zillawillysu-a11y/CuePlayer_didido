"""Unit tests for ProjectRepository (wraps existing persistence)."""

from __future__ import annotations

import inspect
from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.repository.project_repository import ProjectRepository


def test_load_save_roundtrip(tmp_path: Path) -> None:
    repo = ProjectRepository()
    path = tmp_path / "show.cueplayer.json"
    project = Project.create("倉庫測試", with_song=True)
    assert repo.exists(path) is False
    repo.save(project, path)
    assert repo.exists(path) is True
    loaded = repo.load(path)
    assert loaded.name == "倉庫測試"
    assert len(loaded.songs) == 1


def test_autosave_overwrites_like_save(tmp_path: Path) -> None:
    repo = ProjectRepository()
    path = tmp_path / "auto.cueplayer.json"
    project = Project.create("A", with_song=True)
    repo.save(project, path)
    project.songs[0].name = "B"
    repo.autosave(project, path)
    assert repo.load(path).songs[0].name == "B"


def test_backup_creates_copy_before_overwrite(tmp_path: Path) -> None:
    repo = ProjectRepository()
    path = tmp_path / "live.cueplayer.json"
    project = Project.create("Live", with_song=False)
    repo.save(project, path)
    backup = repo.backup(path, keep=5)
    assert backup is not None
    assert backup.is_file()
    assert backup != path
    assert repo.backup(tmp_path / "missing.cueplayer.json") is None


def test_repository_source_uses_persistence_only() -> None:
    """Thin wrapper — implementation may import persistence, not ui/playback."""
    source = inspect.getsource(
        __import__("cueplayer.repository.project_repository", fromlist=["*"])
    )
    assert "cueplayer.persistence" in source
    assert "cueplayer.ui" not in source
    assert "cueplayer.playback" not in source
