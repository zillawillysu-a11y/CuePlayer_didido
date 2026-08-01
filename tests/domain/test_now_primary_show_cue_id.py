"""PRIMARY NOW Cue ID visibility preference."""

from __future__ import annotations

from cueplayer.domain.models import Project
from cueplayer.persistence.project_store import project_from_dict, project_to_dict


def test_now_primary_show_cue_id_defaults_true() -> None:
    song = Project.create("P").songs[0]
    assert song.now_primary_show_cue_id is True


def test_now_primary_show_cue_id_roundtrip() -> None:
    project = Project.create("P")
    project.songs[0].now_primary_show_cue_id = False
    restored = project_from_dict(project_to_dict(project))
    assert restored.songs[0].now_primary_show_cue_id is False
    data = project_to_dict(project)
    del data["songs"][0]["now_primary_show_cue_id"]
    legacy = project_from_dict(data)
    assert legacy.songs[0].now_primary_show_cue_id is True


def test_now_primary_single_line_defaults_false() -> None:
    song = Project.create("P").songs[0]
    assert song.now_primary_single_line is False


def test_now_primary_single_line_roundtrip() -> None:
    project = Project.create("P")
    project.songs[0].now_primary_single_line = True
    restored = project_from_dict(project_to_dict(project))
    assert restored.songs[0].now_primary_single_line is True
    data = project_to_dict(project)
    del data["songs"][0]["now_primary_single_line"]
    legacy = project_from_dict(data)
    assert legacy.songs[0].now_primary_single_line is False
