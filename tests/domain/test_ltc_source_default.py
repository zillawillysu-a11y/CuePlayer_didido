"""Default LTC source is From file — auto-detect L/R."""

from __future__ import annotations

from cueplayer.domain.models import AudioOutputSettings
from cueplayer.persistence.audio_prefs import default_machine_audio_output
from cueplayer.persistence.project_store import dict_to_audio_output


def test_audio_output_default_ltc_source_is_auto() -> None:
    assert AudioOutputSettings().ltc_source == "auto"
    assert AudioOutputSettings().ltc_enabled is False
    assert AudioOutputSettings().ltc_gain == 0.8


def test_machine_default_ltc_source_is_auto() -> None:
    settings = default_machine_audio_output()
    assert settings.ltc_source == "auto"


def test_dict_missing_ltc_source_falls_back_to_auto() -> None:
    settings = dict_to_audio_output({"output_device_name": ""})
    assert settings.ltc_source == "auto"
