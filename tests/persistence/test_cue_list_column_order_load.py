"""Persistence applies cue-list column normalize on load (behavior lock)."""

from __future__ import annotations

import json
from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.persistence.project_store import load_project, save_project
from cueplayer.ui.cue_list_columns import (
    DEFAULT_CUE_LIST_COLUMN_ORDER,
    normalize_cue_list_column_order,
)


def test_load_project_normalizes_cue_list_column_order(tmp_path: Path) -> None:
    project = Project.create("欄位順序")
    song = project.new_song("一號")
    song.cue_list_column_order = ["note", "time"]
    path = tmp_path / "cols.cueplayer.json"
    save_project(project, path)

    # Legacy / dirty order on disk must be normalized on load.
    data = json.loads(path.read_text(encoding="utf-8"))
    data["songs"][0]["cue_list_column_order"] = [" NOTE ", "bogus", "note", "time"]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    loaded = load_project(path)
    assert len(loaded.songs) == 1
    assert loaded.songs[0].cue_list_column_order == normalize_cue_list_column_order(
        [" NOTE ", "bogus", "note", "time"]
    )
    assert loaded.songs[0].cue_list_column_order == [
        "note",
        "time",
        "type",
        "cue_id",
    ]


def test_load_project_missing_column_order_uses_default(tmp_path: Path) -> None:
    project = Project.create("預設欄位")
    project.new_song("二號")
    path = tmp_path / "default_cols.cueplayer.json"
    save_project(project, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["songs"][0].pop("cue_list_column_order", None)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    loaded = load_project(path)
    assert loaded.songs[0].cue_list_column_order == list(DEFAULT_CUE_LIST_COLUMN_ORDER)
