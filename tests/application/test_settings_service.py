"""Unit tests for application.SettingsService (machine prefs only)."""

from __future__ import annotations

import importlib
import inspect
import json

from cueplayer.application.settings_service import (
    KEY_AUTOSAVE_ENABLED,
    KEY_AUTOSAVE_INTERVAL_SEC,
    KEY_LAST_PROJECT,
    KEY_MAIN_GEOMETRY,
    KEY_SETLIST_WIDTH,
    SETTINGS_APP,
    SETTINGS_ORG,
    THEME_ID,
    SettingsService,
)
from cueplayer.domain.models import AudioOutputSettings, Project
from cueplayer.persistence import audio_prefs


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

    def contains(self, key: str) -> bool:
        return key in self._data

    def sync(self) -> None:
        return None


def test_settings_service_does_not_import_ui_or_engine() -> None:
    source = inspect.getsource(
        importlib.import_module("cueplayer.application.settings_service")
    )
    assert "import cueplayer.ui" not in source
    assert "from cueplayer.ui" not in source
    assert "audio_engine" not in source
    assert "from cueplayer.web_remote" not in source
    assert "import cueplayer.web_remote" not in source


def test_org_app_and_theme_stable() -> None:
    assert SETTINGS_ORG == "CuePlayer"
    assert SETTINGS_APP == "CuePlayer"
    svc = SettingsService(_MemSettings())
    assert svc.theme_id() == THEME_ID == "pitch_black"


def test_window_keys_roundtrip() -> None:
    store = _MemSettings()
    svc = SettingsService(store)
    svc.setValue(KEY_MAIN_GEOMETRY, b"geo")
    svc.setValue(KEY_SETLIST_WIDTH, 320)
    assert svc.value(KEY_MAIN_GEOMETRY) == b"geo"
    assert svc.value(KEY_SETLIST_WIDTH, 240, type=int) == 320
    assert svc.contains(KEY_MAIN_GEOMETRY) is True


def test_autosave_and_recent_raw_prefs() -> None:
    svc = SettingsService(_MemSettings())
    assert svc.autosave_enabled() is True
    svc.set_autosave_enabled(False)
    assert svc.autosave_enabled() is False
    svc.set_autosave_interval_seconds(900)
    assert svc.autosave_interval_seconds() == 900
    svc.set_last_project_path_text("/tmp/a.cueplayer.json")
    assert svc.last_project_path_text() == "/tmp/a.cueplayer.json"
    svc.set_last_song_id("song-1")
    assert svc.last_song_id() == "song-1"
    svc.set_recent_projects_json(json.dumps(["/tmp/a.cueplayer.json"]))
    assert KEY_AUTOSAVE_ENABLED in ("autosave/enabled",)
    assert KEY_AUTOSAVE_INTERVAL_SEC == "autosave/interval_seconds"
    assert KEY_LAST_PROJECT == "session/last_project_path"


def test_audio_delegates_to_audio_prefs(monkeypatch) -> None:  # noqa: ANN001
    calls: list[str] = []

    def _load():
        calls.append("load")
        return AudioOutputSettings(output_device_name="X")

    def _save(settings: AudioOutputSettings) -> None:
        calls.append(f"save:{settings.output_device_name}")

    def _apply(project: Project) -> AudioOutputSettings:
        calls.append("apply")
        ao = AudioOutputSettings(output_device_name="Y")
        project.audio_output = ao
        return ao

    monkeypatch.setattr(audio_prefs, "load_global_audio_output", _load)
    monkeypatch.setattr(audio_prefs, "save_global_audio_output", _save)
    monkeypatch.setattr(audio_prefs, "apply_global_audio_to_project", _apply)

    svc = SettingsService(_MemSettings())
    assert svc.load_audio_output().output_device_name == "X"
    svc.save_audio_output(AudioOutputSettings(output_device_name="Z"))
    project = Project.create("P", with_song=False)
    assert svc.apply_audio_to_project(project).output_device_name == "Y"
    assert project.audio_output.output_device_name == "Y"
    assert calls == ["load", "save:Z", "apply"]
