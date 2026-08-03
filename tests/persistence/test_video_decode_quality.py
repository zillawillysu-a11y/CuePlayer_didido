"""Video decode-quality (Preview / Clean Output shared decode cap) persistence."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.persistence.project_store import (
    load_project,
    project_from_dict,
    save_project,
)


def test_video_decode_quality_defaults_to_1080p() -> None:
    project = Project.create("預設專案")
    assert project.video_decode_quality == "1080p"


def test_video_decode_quality_roundtrip(tmp_path: Path) -> None:
    project = Project.create("解析度測試")
    project.video_decode_quality = "720p"
    path = tmp_path / "中文專案" / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.video_decode_quality == "720p"


def test_video_decode_quality_missing_field_uses_default() -> None:
    """Old project files predating this feature must load with a sensible default."""
    data = {
        "schema_version": 1,
        "id": "proj-1",
        "name": "Legacy Project",
        "songs": [],
    }
    project = project_from_dict(data)
    assert project.video_decode_quality == "1080p"


def test_video_decode_quality_rejects_unknown_value() -> None:
    data = {
        "schema_version": 1,
        "id": "proj-2",
        "name": "Bad Quality",
        "songs": [],
        "video_decode_quality": "8k-please",
    }
    project = project_from_dict(data)
    assert project.video_decode_quality == "1080p"
