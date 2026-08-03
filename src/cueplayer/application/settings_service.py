"""Application service: machine-level preferences (not project JSON).

Design contract
---------------
**Responsibilities**
- Own the machine ``QSettings`` store (``CuePlayer`` / ``CuePlayer``).
- Audio device / MIDI / timecode machine prefs (via existing ``audio_prefs``).
- Window / UI chrome session keys (geometry, splitters, view mode, NOW/cue list).
- Recent files / last project / last song keys (raw machine prefs).
- Autosave preference keys (enabled / interval / backup keep).
- Report the fixed app theme id (no persisted theme switch today).

**Non-responsibilities**
- Does **not** own Project JSON / song / mark / setlist state.
- Does not redesign ``persistence.audio_prefs`` schemas or key names.
- Does not redesign AudioEngine, Timeline, Waveform, Playback, or RemoteHost.
- Does not apply audio to the engine (UI still calls ``engine.apply_audio_settings``).
- Does not filter recent paths for existence (``ProjectService`` + repository do).
- Does not own Web Remote prefs or color-dialog custom slots (separate modules).

**Dependencies**
- ``PySide6.QtCore.QSettings`` (or an injected ``SettingsStore`` for tests)
- ``cueplayer.persistence.audio_prefs`` (unchanged implementation)
- ``cueplayer.domain.models.AudioOutputSettings`` / ``Project``
- Key constants shared with ``ProjectService`` for autosave / recent / last session

**Why this design**
- Machine State and Project State stay separate: this service never writes show
  content into QSettings, and never reads Project fields as settings source.
- Strangler: wrap existing keys and ``audio_prefs`` so runtime behavior and
  schema stay identical while MainWindow stops creating/owning ``QSettings``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings

from cueplayer.application.project_service import (
    DEFAULT_AUTOSAVE_INTERVAL_SEC,
    KEY_AUTOSAVE_ENABLED,
    KEY_AUTOSAVE_INTERVAL_SEC,
    KEY_BACKUP_KEEP,
    KEY_LAST_PROJECT,
    KEY_LAST_SONG_ID,
    KEY_RECENT_PROJECTS,
)
from cueplayer.domain.models import AudioOutputSettings, Project
from cueplayer.persistence import audio_prefs

SETTINGS_ORG = "CuePlayer"
SETTINGS_APP = "CuePlayer"

# Fixed visual theme — there is no QSettings theme switch yet.
THEME_ID = "pitch_black"

# Window / UI chrome (machine session) — same string keys as before.
KEY_CLEAN_OUTPUT_WAS_OPEN = "clean_output/was_open"
KEY_CLEAN_OUTPUT_GEOMETRY = "clean_output/geometry"
KEY_MAIN_GEOMETRY = "mainwindow/geometry"
KEY_MAIN_STATE = "mainwindow/state"
KEY_MAIN_SPLITTER = "ui/main_splitter"
KEY_TIMELINE_SPLITTER = "ui/timeline_splitter"
KEY_TIMELINE_PREVIEW_SPLITTER = "ui/timeline_preview_splitter"
KEY_TIMELINE_HEADER_WIDTH = "ui/timeline_header_width"
KEY_NOW_SPLITTER = "ui/now_splitter"
KEY_NOW_SECONDARY_PLACEMENT = "ui/now_secondary_placement"
KEY_NOW_SPLITTER_RIGHT = "ui/now_splitter_right"
KEY_NOW_SPLITTER_BELOW = "ui/now_splitter_below"
KEY_NOW_BODY_SPLITTER = "ui/now_body_splitter"
KEY_NOW_PRIMARY_VISIBLE = "ui/now_primary_visible"
KEY_NOW_SECONDARY_VISIBLE = "ui/now_secondary_visible"
KEY_CUE_LIST_VISIBLE = "ui/cue_list_visible"
KEY_NOW_PRIMARY_SHOW_CUE_ID = "ui/now_primary_show_cue_id"
KEY_NOW_PRIMARY_SINGLE_LINE = "ui/now_primary_single_line"
KEY_CUE_LIST_SHOW_CUE_ID = "ui/cue_list_show_cue_id"
KEY_CUE_LIST_COLUMN_ORDER = "ui/cue_list_column_order"
KEY_CUE_LIST_HEADER = "ui/cue_list_header"
KEY_VIEW_MODE = "ui/view_mode"
KEY_SETLIST_VISIBLE = "ui/setlist_visible"
KEY_SETLIST_WIDTH = "ui/setlist_width"


class SettingsService:
    """Machine prefs façade: UI → this → QSettings / audio_prefs."""

    def __init__(self, store: Any | None = None) -> None:
        self._store = store if store is not None else QSettings(SETTINGS_ORG, SETTINGS_APP)

    # --- QSettings surface (SettingsStore-compatible) ------------------------

    @property
    def store(self) -> Any:
        """Underlying store (``QSettings`` or test double)."""
        return self._store

    def value(self, key: str, default: Any = None, **kwargs: Any) -> Any:
        return self._store.value(key, default, **kwargs)

    def setValue(self, key: str, value: Any) -> None:
        self._store.setValue(key, value)

    def contains(self, key: str) -> bool:
        contains = getattr(self._store, "contains", None)
        if callable(contains):
            return bool(contains(key))
        # Test doubles without contains(): treat missing as absent.
        sentinel = object()
        return self._store.value(key, sentinel) is not sentinel

    def sync(self) -> None:
        sync = getattr(self._store, "sync", None)
        if callable(sync):
            sync()

    # --- Theme ---------------------------------------------------------------

    def theme_id(self) -> str:
        """Return the active theme id.

        CuePlayer currently ships a single pitch-black theme applied in code
        (``ui.theme``); there is no QSettings theme key to preserve.
        """
        return THEME_ID

    # --- Audio device (machine) ----------------------------------------------

    def load_audio_output(self) -> AudioOutputSettings:
        """Load machine audio / MIDI / timecode prefs (existing schema)."""
        return audio_prefs.load_global_audio_output()

    def save_audio_output(self, settings: AudioOutputSettings) -> None:
        """Persist machine audio prefs (existing ``audio/output_settings_json``)."""
        audio_prefs.save_global_audio_output(settings)

    def apply_audio_to_project(self, project: Project) -> AudioOutputSettings:
        """Overlay machine audio prefs onto ``project.audio_output``."""
        return audio_prefs.apply_global_audio_to_project(project)

    # --- Autosave preferences (machine keys) ---------------------------------

    def autosave_enabled(self) -> bool:
        return bool(self.value(KEY_AUTOSAVE_ENABLED, True, type=bool))

    def set_autosave_enabled(self, enabled: bool) -> None:
        self.setValue(KEY_AUTOSAVE_ENABLED, bool(enabled))

    def autosave_interval_seconds(self) -> int:
        raw = self.value(KEY_AUTOSAVE_INTERVAL_SEC, DEFAULT_AUTOSAVE_INTERVAL_SEC)
        try:
            seconds = int(raw)
        except (TypeError, ValueError):
            seconds = DEFAULT_AUTOSAVE_INTERVAL_SEC
        return max(60, seconds)

    def set_autosave_interval_seconds(self, seconds: int) -> None:
        self.setValue(KEY_AUTOSAVE_INTERVAL_SEC, max(60, int(seconds)))

    def backup_keep(self) -> int:
        from cueplayer.repository.project_repository import DEFAULT_KEEP

        raw = self.value(KEY_BACKUP_KEEP, DEFAULT_KEEP)
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return DEFAULT_KEEP

    def set_backup_keep(self, keep: int) -> None:
        self.setValue(KEY_BACKUP_KEEP, max(1, int(keep)))

    # --- Recent / last project (raw machine prefs) ---------------------------

    def last_project_path_text(self) -> str | None:
        raw = self.value(KEY_LAST_PROJECT)
        return str(raw) if raw else None

    def set_last_project_path_text(self, path: str) -> None:
        self.setValue(KEY_LAST_PROJECT, str(path))

    def last_song_id(self) -> str | None:
        raw = self.value(KEY_LAST_SONG_ID)
        return str(raw) if raw else None

    def set_last_song_id(self, song_id: str) -> None:
        self.setValue(KEY_LAST_SONG_ID, str(song_id))

    def recent_projects_json(self) -> Any:
        """Raw recent-list value (JSON string or list); ProjectService interprets."""
        return self.value(KEY_RECENT_PROJECTS)

    def set_recent_projects_json(self, payload: str) -> None:
        self.setValue(KEY_RECENT_PROJECTS, payload)
