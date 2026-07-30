"""MTC output requires the MTC toggle — TRANS alone must not send quarter-frames."""

from __future__ import annotations

from cueplayer.domain.models import AudioOutputSettings
from cueplayer.playback.audio_engine import AudioEngine


def test_translate_without_mtc_does_not_output_mtc() -> None:
    settings = AudioOutputSettings(
        midi_enabled=True,
        mtc_enabled=False,
        ltc_to_mtc_translate=True,
        midi_cue_notes_enabled=True,
    )
    assert settings.effective_mtc_output() is False
    assert settings.effective_ltc_to_mtc_translate() is False
    assert settings.effective_midi_cue_notes() is True


def test_translate_with_mtc_outputs_mtc() -> None:
    settings = AudioOutputSettings(
        midi_enabled=True,
        mtc_enabled=True,
        ltc_to_mtc_translate=True,
    )
    assert settings.effective_mtc_output() is True
    assert settings.effective_ltc_to_mtc_translate() is True


def test_engine_notes_only_does_not_report_mtc() -> None:
    engine = AudioEngine()
    engine.set_song_timebase("04:00:00:00", 30.0)
    engine.apply_audio_settings(
        AudioOutputSettings(
            midi_enabled=True,
            midi_cue_notes_enabled=True,
            ltc_to_mtc_translate=True,
            ltc_enabled=False,
            mtc_enabled=False,
        )
    )
    state = engine.output_timecode_state(12.0)
    assert state.outputs == ("Notes",)
    assert "MTC" not in " ".join(state.outputs)

    engine._playing = True  # noqa: SLF001
    assert engine.mtc_enabled is False
