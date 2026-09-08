"""Application service: project lifecycle orchestration.

Owns new/open/save path state, dirty flag, autosave preferences, and recent
project paths. Document I/O goes through ``ProjectRepository`` (not persistence
directly). Qt widgets / dialogs stay in the UI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from cueplayer.domain.models import Project
from cueplayer.repository.project_repository import DEFAULT_KEEP, ProjectRepository

# Machine-local settings keys (QSettings org/app = CuePlayer / CuePlayer).
KEY_AUTOSAVE_ENABLED = "autosave/enabled"
KEY_AUTOSAVE_INTERVAL_SEC = "autosave/interval_seconds"
KEY_BACKUP_KEEP = "autosave/backup_keep"
KEY_LAST_PROJECT = "session/last_project_path"
KEY_LAST_SONG_ID = "session/last_song_id"
KEY_RECENT_PROJECTS = "session/recent_project_paths"

DEFAULT_AUTOSAVE_INTERVAL_SEC = 300  # 5 minutes
AUTOSAVE_INTERVAL_MINUTES = (5, 15, 30, 60, 120)
RECENT_PROJECTS_MAX = 10


class SettingsStore(Protocol):
    """Minimal settings surface (satisfied by ``QSettings``)."""

    def value(self, key: str, default: Any = None, **kwargs: Any) -> Any: ...

    def setValue(self, key: str, value: Any) -> None: ...

    def sync(self) -> None: ...


class ProjectService:
    """Project lifecycle — path, dirty, autosave prefs, recent list, I/O."""

    def __init__(
        self,
        settings: SettingsStore,
        repository: ProjectRepository | None = None,
    ) -> None:
        self._settings = settings
        self._repo = repository if repository is not None else ProjectRepository()
        self._path: Path | None = None
        self._dirty = False

    @property
    def repository(self) -> ProjectRepository:
        return self._repo

    # --- state ---------------------------------------------------------------

    @property
    def path(self) -> Path | None:
        return self._path

    def set_path(self, path: Path | None) -> None:
        self._path = Path(path) if path is not None else None

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self) -> bool:
        """Set dirty. Returns True if this call newly dirtied the project."""
        if self._dirty:
            return False
        self._dirty = True
        return True

    def mark_clean(self) -> None:
        self._dirty = False

    # --- new / open / save ---------------------------------------------------

    def new_project(
        self,
        *,
        name: str = "Untitled Project",
        with_song: bool = False,
    ) -> Project:
        """Create a blank project and clear path / dirty."""
        self._path = None
        self._dirty = False
        return Project.create(name, with_song=with_song)

    def open_project(self, path: Path) -> Project:
        """Load via repository; set path; clear dirty; record recent."""
        path = Path(path)
        project = self._repo.load(path)
        self._path = path
        self._dirty = False
        self.remember_recent(path)
        return project

    def save_project(self, project: Project, path: Path | None = None) -> Path:
        """
        Write ``project`` via repository.

        Uses ``path`` when given (Save As), otherwise the current path.
        Updates path, clears dirty, records recent. Does **not** run media
        layout / bundle — callers do those before invoking this.
        """
        target = Path(path) if path is not None else self._path
        if target is None:
            raise ValueError("No project path for save")
        self._repo.save(project, target)
        self._path = target
        self._dirty = False
        self.remember_recent(target)
        return target

    def autosave_project(self, project: Project) -> Path:
        """
        Quiet overwrite of the current path via ``repository.autosave``.

        Raises ``ValueError`` when there is no path or the project is not dirty
        in a way that should autosave — callers normally gate with
        ``should_autosave()`` first.
        """
        if self._path is None:
            raise ValueError("No project path for autosave")
        self._repo.autosave(project, self._path)
        self._dirty = False
        self.remember_recent(self._path)
        return self._path

    def normalize_save_as_path(self, path: Path) -> Path:
        """Ensure ``*.cueplayer.json`` naming (identical to prior MainWindow rules)."""
        path = Path(path)
        name_lower = path.name.lower()
        if name_lower.endswith(".cueplayer.json"):
            return path
        if path.suffix.lower() == ".json":
            return path.with_name(f"{path.stem}.cueplayer.json")
        return path.with_name(f"{path.name}.cueplayer.json")

    def is_save_as_beside_original(self, new_path: Path) -> bool:
        """True when Save As targets another file in the same folder as current."""
        if self._path is None:
            return False
        try:
            return (
                new_path.resolve() != self._path.resolve()
                and new_path.parent.resolve() == self._path.parent.resolve()
            )
        except OSError:
            return False

    def apply_name_from_path(self, project: Project, path: Path) -> None:
        """Set ``project.name`` from a ``*.cueplayer.json`` (or stem) path."""
        stem = path.name
        if stem.endswith(".cueplayer.json"):
            project.name = stem[: -len(".cueplayer.json")] or project.name
        else:
            project.name = path.stem or project.name

    # --- recent / last session -----------------------------------------------

    def remember_recent(self, path: Path) -> None:
        """Update last-project key and the recent-projects list."""
        path = Path(path)
        text = str(path)
        self._settings.setValue(KEY_LAST_PROJECT, text)
        recent = [p for p in self.recent_projects() if p.resolve() != path.resolve()]
        recent.insert(0, path)
        recent = recent[:RECENT_PROJECTS_MAX]
        payload = [str(p) for p in recent]
        self._settings.setValue(KEY_RECENT_PROJECTS, json.dumps(payload, ensure_ascii=False))

    def remember_last_song_id(self, song_id: str) -> None:
        self._settings.setValue(KEY_LAST_SONG_ID, song_id)

    def last_project_path(self) -> Path | None:
        raw = self._settings.value(KEY_LAST_PROJECT)
        if not raw:
            return None
        path = Path(str(raw))
        return path if self._repo.exists(path) else None

    def last_song_id(self) -> str | None:
        raw = self._settings.value(KEY_LAST_SONG_ID)
        return str(raw) if raw else None

    def recent_projects(self) -> list[Path]:
        """Recently opened/saved project paths (newest first); missing files dropped."""
        raw = self._settings.value(KEY_RECENT_PROJECTS)
        items: list[str] = []
        if isinstance(raw, str) and raw.strip():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, list):
                items = [str(x) for x in data]
        elif isinstance(raw, list):
            items = [str(x) for x in raw]
        # Seed from legacy last-project when the list is empty.
        if not items:
            legacy = self._settings.value(KEY_LAST_PROJECT)
            if legacy:
                items = [str(legacy)]
        out: list[Path] = []
        seen: set[str] = set()
        for item in items:
            path = Path(item)
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            if self._repo.exists(path):
                out.append(path)
        return out[:RECENT_PROJECTS_MAX]

    # --- autosave / backup prefs ---------------------------------------------

    def autosave_enabled(self) -> bool:
        return bool(self._settings.value(KEY_AUTOSAVE_ENABLED, True, type=bool))

    def autosave_interval_seconds(self) -> int:
        raw = self._settings.value(
            KEY_AUTOSAVE_INTERVAL_SEC, DEFAULT_AUTOSAVE_INTERVAL_SEC
        )
        try:
            seconds = int(raw)
        except (TypeError, ValueError):
            seconds = DEFAULT_AUTOSAVE_INTERVAL_SEC
        return max(60, seconds)

    def autosave_interval_minutes(self) -> int:
        minutes = int(round(self.autosave_interval_seconds() / 60.0))
        if minutes in AUTOSAVE_INTERVAL_MINUTES:
            return minutes
        return min(AUTOSAVE_INTERVAL_MINUTES, key=lambda m: abs(m - minutes))

    def set_autosave_choice(self, minutes: int | None) -> None:
        """``None`` = Off; otherwise enable Auto-Save every ``minutes``."""
        if minutes is None:
            self._settings.setValue(KEY_AUTOSAVE_ENABLED, False)
        else:
            minutes = max(1, int(minutes))
            self._settings.setValue(KEY_AUTOSAVE_ENABLED, True)
            self._settings.setValue(KEY_AUTOSAVE_INTERVAL_SEC, minutes * 60)

    def set_autosave_enabled(self, enabled: bool) -> None:
        self._settings.setValue(KEY_AUTOSAVE_ENABLED, bool(enabled))

    def backup_keep_count(self) -> int:
        raw = self._settings.value(KEY_BACKUP_KEEP, DEFAULT_KEEP)
        try:
            keep = int(raw)
        except (TypeError, ValueError):
            keep = DEFAULT_KEEP
        return max(1, keep)

    def should_autosave(self) -> bool:
        """True when the autosave timer should overwrite the current file."""
        return self.autosave_enabled() and self._dirty and self._path is not None

    def backup_before_overwrite(self, path: Path) -> None:
        """Copy previous on-disk file into ``.cueplayer_backups/``. May raise OSError."""
        self._repo.backup(path, keep=self.backup_keep_count())
