"""Unit tests for application.ProjectService (no UI)."""

from __future__ import annotations

import json
from pathlib import Path

from cueplayer.application.project_service import (
    AUTOSAVE_INTERVAL_MINUTES,
    KEY_AUTOSAVE_ENABLED,
    KEY_AUTOSAVE_INTERVAL_SEC,
    KEY_LAST_PROJECT,
    KEY_RECENT_PROJECTS,
    ProjectService,
)
from cueplayer.domain.models import Project
from cueplayer.persistence.project_store import load_project, save_project


class _MemSettings:
    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    def value(self, key: str, default=None, **kwargs):  # noqa: ANN001
        if key not in self._data:
            return default
        val = self._data[key]
        typ = kwargs.get("type")
        if typ is bool:
            return bool(val)
        if typ is int:
            return int(val)  # type: ignore[arg-type]
        return val

    def setValue(self, key: str, value) -> None:  # noqa: ANN001
        self._data[key] = value

    def sync(self) -> None:
        return None


def test_new_project_clears_path_and_dirty() -> None:
    svc = ProjectService(_MemSettings())
    svc.set_path(Path("/tmp/x.cueplayer.json"))
    svc.mark_dirty()
    project = svc.new_project(with_song=False)
    assert project.name == "Untitled Project"
    assert project.songs == []
    assert svc.path is None
    assert svc.is_dirty is False


def test_open_and_save_roundtrip(tmp_path: Path) -> None:
    settings = _MemSettings()
    svc = ProjectService(settings)
    project = Project.create("測試專案", with_song=True)
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)

    loaded = svc.open_project(path)
    assert loaded.name == "測試專案"
    assert svc.path == path
    assert svc.is_dirty is False
    assert settings.value(KEY_LAST_PROJECT) == str(path)
    assert path in svc.recent_projects()

    loaded.songs[0].name = "改名"
    svc.mark_dirty()
    assert svc.should_autosave() is True  # default autosave on
    svc.save_project(loaded)
    assert svc.is_dirty is False
    again = load_project(path)
    assert again.songs[0].name == "改名"


def test_normalize_save_as_path() -> None:
    svc = ProjectService(_MemSettings())
    assert svc.normalize_save_as_path(Path("a.cueplayer.json")).name == "a.cueplayer.json"
    assert svc.normalize_save_as_path(Path("a.json")).name == "a.cueplayer.json"
    assert svc.normalize_save_as_path(Path("a")).name == "a.cueplayer.json"


def test_save_as_beside_original(tmp_path: Path) -> None:
    svc = ProjectService(_MemSettings())
    original = tmp_path / "a.cueplayer.json"
    original.write_text("{}", encoding="utf-8")
    sibling = tmp_path / "b.cueplayer.json"
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    elsewhere = other_dir / "b.cueplayer.json"
    svc.set_path(original)
    assert svc.is_save_as_beside_original(sibling) is True
    assert svc.is_save_as_beside_original(elsewhere) is False
    assert svc.is_save_as_beside_original(original) is False


def test_autosave_choice_and_should_autosave(tmp_path: Path) -> None:
    settings = _MemSettings()
    svc = ProjectService(settings)
    assert AUTOSAVE_INTERVAL_MINUTES == (5, 15, 30, 60, 120)
    svc.set_autosave_choice(15)
    assert svc.autosave_enabled() is True
    assert svc.autosave_interval_seconds() == 900
    assert settings.value(KEY_AUTOSAVE_INTERVAL_SEC) == 900
    svc.set_path(tmp_path / "p.cueplayer.json")
    svc.mark_dirty()
    assert svc.should_autosave() is True
    svc.set_autosave_choice(None)
    assert svc.autosave_enabled() is False
    assert svc.should_autosave() is False
    assert settings.value(KEY_AUTOSAVE_ENABLED) is False


def test_recent_projects_dedupe_and_cap(tmp_path: Path) -> None:
    settings = _MemSettings()
    svc = ProjectService(settings)
    paths = []
    for i in range(12):
        p = tmp_path / f"p{i}.cueplayer.json"
        p.write_text("{}", encoding="utf-8")
        paths.append(p)
        svc.remember_recent(p)
    recent = svc.recent_projects()
    assert len(recent) == 10
    assert recent[0] == paths[-1]
    # re-remember older moves it to front
    svc.remember_recent(paths[0])
    assert svc.recent_projects()[0] == paths[0]
    raw = settings.value(KEY_RECENT_PROJECTS)
    assert isinstance(raw, str)
    assert len(json.loads(raw)) == 10
