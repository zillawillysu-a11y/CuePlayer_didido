"""Clean Video Output window size / aspect-lock persistence."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import CleanVideoOutputSettings, Project
from cueplayer.persistence.project_store import (
    load_project,
    project_from_dict,
    save_project,
)


def test_clean_video_output_defaults_to_1080p() -> None:
    project = Project.create("預設專案")
    assert project.clean_video_output.width == 1920
    assert project.clean_video_output.height == 1080
    assert project.clean_video_output.aspect_locked is True
    assert project.clean_video_output.was_open is False


def test_clean_video_output_roundtrip(tmp_path: Path) -> None:
    project = Project.create("輸出視窗測試")
    project.clean_video_output = CleanVideoOutputSettings(
        width=1280, height=720, aspect_locked=False, was_open=True
    )
    path = tmp_path / "中文專案" / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    cvo = loaded.clean_video_output
    assert cvo.width == 1280
    assert cvo.height == 720
    assert cvo.aspect_locked is False
    assert cvo.was_open is True


def test_clean_video_output_missing_field_uses_default() -> None:
    """Old project files predating this feature must load with a sensible default."""
    data = {
        "schema_version": 1,
        "id": "proj-1",
        "name": "Legacy Project",
        "songs": [],
    }
    project = project_from_dict(data)
    assert project.clean_video_output.width == 1920
    assert project.clean_video_output.height == 1080
    assert project.clean_video_output.aspect_locked is True
    assert project.clean_video_output.was_open is False


def test_clean_video_output_rejects_invalid_dimensions() -> None:
    data = {
        "schema_version": 1,
        "id": "proj-2",
        "name": "Bad Dimensions",
        "songs": [],
        "clean_video_output": {"width": 0, "height": -5, "aspect_locked": False},
    }
    project = project_from_dict(data)
    assert project.clean_video_output.width == 1920
    assert project.clean_video_output.height == 1080
    assert project.clean_video_output.aspect_locked is False
