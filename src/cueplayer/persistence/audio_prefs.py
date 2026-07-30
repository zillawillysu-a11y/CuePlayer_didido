"""Machine-global Audio / Midi / Timecode preferences (QSettings).

These follow the user across New Project / Load Project. Project JSON still
stores a copy for older builds, but the live UI always overlays this store.
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QSettings

from cueplayer.domain.models import AudioOutputSettings, Project
from cueplayer.persistence.project_store import audio_output_to_dict, dict_to_audio_output

_SETTINGS_ORG = "CuePlayer"
_SETTINGS_APP = "CuePlayer"
_KEY_AUDIO_OUTPUT = "audio/output_settings_json"


def _settings() -> QSettings:
    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def default_machine_audio_output() -> AudioOutputSettings:
    """First-run defaults: DirectSound + System default device (empty name)."""
    from cueplayer.playback.devices import default_picker_hostapi

    return AudioOutputSettings(
        output_device_name="",
        output_device_index=None,
        output_hostapi=default_picker_hostapi(),
    )


def load_global_audio_output() -> AudioOutputSettings:
    """Load saved machine prefs, or first-run DirectSound / System default."""
    raw = _settings().value(_KEY_AUDIO_OUTPUT)
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and data:
            return dict_to_audio_output(data)
    if isinstance(raw, dict) and raw:
        return dict_to_audio_output(raw)
    return default_machine_audio_output()


def save_global_audio_output(settings: AudioOutputSettings) -> None:
    payload: dict[str, Any] = audio_output_to_dict(settings)
    store = _settings()
    store.setValue(_KEY_AUDIO_OUTPUT, json.dumps(payload, ensure_ascii=False))
    store.sync()


def apply_global_audio_to_project(project: Project) -> AudioOutputSettings:
    """Overwrite ``project.audio_output`` with machine prefs and return them."""
    settings = load_global_audio_output()
    project.audio_output = settings
    return settings
