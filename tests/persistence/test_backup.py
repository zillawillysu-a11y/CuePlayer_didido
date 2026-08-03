"""Auto-backup helpers: Unicode paths, prune rotation, first-save noop."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.persistence.backup import (
    BACKUP_DIR_NAME,
    create_backup_before_save,
    list_backups,
    project_stem,
    prune_backups,
)
from cueplayer.persistence.project_store import load_project, save_project


def test_project_stem_strips_cueplayer_json() -> None:
    assert project_stem(Path("演唱會.cueplayer.json")) == "演唱會"
    assert project_stem(Path("/tmp/中文/show.cueplayer.json")) == "show"
    assert project_stem(Path("plain.json")) == "plain"


def test_create_backup_noop_when_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "尚不存在.cueplayer.json"
    assert create_backup_before_save(missing) is None
    assert not (tmp_path / BACKUP_DIR_NAME).exists()


def test_backup_preserves_chinese_stem_and_contents(tmp_path: Path) -> None:
    project = Project.create("演唱會")
    project.songs[0].name = "開場"
    project.songs[0].row_color = "#FF5A5F"
    path = tmp_path / "中文資料夾" / "演唱會.cueplayer.json"
    save_project(project, path)

    backup = create_backup_before_save(path, keep=10)
    assert backup is not None
    assert backup.parent.name == BACKUP_DIR_NAME
    assert backup.name.startswith("演唱會_")
    assert backup.name.endswith(".cueplayer.json")
    assert backup.is_file()

    loaded = load_project(backup)
    assert loaded.name == "演唱會"
    assert loaded.songs[0].name == "開場"
    assert loaded.songs[0].row_color == "#FF5A5F"


def test_backup_before_overwrite_keeps_previous_version(tmp_path: Path) -> None:
    path = tmp_path / "show.cueplayer.json"
    first = Project.create("v1")
    first.songs[0].name = "舊版歌曲"
    save_project(first, path)

    backup = create_backup_before_save(path)
    assert backup is not None

    second = Project.create("v2")
    second.songs[0].name = "新版歌曲"
    save_project(second, path)

    restored = load_project(backup)
    assert restored.songs[0].name == "舊版歌曲"
    current = load_project(path)
    assert current.songs[0].name == "新版歌曲"


def test_prune_keeps_newest_only(tmp_path: Path) -> None:
    path = tmp_path / "輪替.cueplayer.json"
    save_project(Project.create("輪替"), path)

    # Force distinct timestamps via explicit `when` so prune order is stable.
    stamps = [
        datetime(2026, 7, 27, 5, 0, 1),
        datetime(2026, 7, 27, 5, 0, 2),
        datetime(2026, 7, 27, 5, 0, 3),
        datetime(2026, 7, 27, 5, 0, 4),
    ]
    from cueplayer.persistence import backup as backup_mod

    for stamp in stamps:
        dest = backup_mod.backup_path_for(path, when=stamp)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    assert len(list_backups(path)) == 4
    removed = prune_backups(path, keep=2)
    assert removed == 2
    remaining = list_backups(path)
    assert len(remaining) == 2
    assert remaining[0].name.endswith("20260727_050004.cueplayer.json")
    assert remaining[1].name.endswith("20260727_050003.cueplayer.json")


def test_list_backups_ignores_other_project_stems(tmp_path: Path) -> None:
    a = tmp_path / "A.cueplayer.json"
    b = tmp_path / "B.cueplayer.json"
    save_project(Project.create("A"), a)
    save_project(Project.create("B"), b)
    create_backup_before_save(a)
    create_backup_before_save(b)
    only_a = list_backups(a)
    only_b = list_backups(b)
    assert len(only_a) == 1
    assert len(only_b) == 1
    assert only_a[0].name.startswith("A_")
    assert only_b[0].name.startswith("B_")
