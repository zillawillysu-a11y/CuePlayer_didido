"""Cue List Cue ID column visibility preference."""

from __future__ import annotations

from cueplayer.domain.models import Project
from cueplayer.persistence.project_store import project_from_dict, project_to_dict


def test_cue_list_show_cue_id_defaults_true() -> None:
    song = Project.create("P").songs[0]
    assert song.cue_list_show_cue_id is True


def test_cue_list_show_cue_id_roundtrip() -> None:
    project = Project.create("P")
    project.songs[0].cue_list_show_cue_id = False
    restored = project_from_dict(project_to_dict(project))
    assert restored.songs[0].cue_list_show_cue_id is False
    # Legacy projects without the key keep the column visible.
    data = project_to_dict(project)
    del data["songs"][0]["cue_list_show_cue_id"]
    legacy = project_from_dict(data)
    assert legacy.songs[0].cue_list_show_cue_id is True
