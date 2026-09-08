"""MTC output requires the MTC toggle — TRANS alone must not send quarter-frames."""

from __future__ import annotations

from cueplayer.domain.models import AudioOutputSettings
from cueplayer.playback.audio_engine import AudioEngine
from cueplayer.timecode.smpte import Timecode


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


def test_translate_with_artnet_does_not_require_midi() -> None:
    settings = AudioOutputSettings(
        ltc_enabled=True,
        midi_enabled=False,
        mtc_enabled=False,
        artnet_timecode_enabled=True,
        ltc_to_mtc_translate=True,
    )
    assert settings.effective_ltc_to_mtc_translate() is False
    assert settings.effective_ltc_to_artnet_translate() is True
    assert settings.effective_ltc_translation_output() is True


class _MirrorProbe:
    def __init__(self) -> None:
        self.calls: list[tuple[Timecode, float]] = []

    def set_mirror_origin(self, tc: Timecode, position: float) -> None:
        self.calls.append((tc, position))

    def close(self) -> None:
        pass


def test_translate_artnet_only_routes_decoded_ltc_without_mtc(monkeypatch) -> None:
    engine = AudioEngine()
    mtc = _MirrorProbe()
    artnet = _MirrorProbe()
    engine._mtc = mtc  # noqa: SLF001
    engine._artnet_tc = artnet  # noqa: SLF001
    engine._audio_settings = AudioOutputSettings(  # noqa: SLF001
        ltc_enabled=True,
        ltc_to_mtc_translate=True,
        artnet_timecode_enabled=True,
    )
    decoded = Timecode(5, 6, 7, 8)
    monkeypatch.setattr(engine, "_decode_file_ltc_timecode", lambda _pos: decoded)

    engine._sync_mtc_to_file_ltc(12.5, force=True)  # noqa: SLF001

    assert mtc.calls == []
    assert artnet.calls == [(decoded, 12.5)]


def test_translate_routes_one_decoded_ltc_value_to_mtc_and_artnet(monkeypatch) -> None:
    engine = AudioEngine()
    mtc = _MirrorProbe()
    artnet = _MirrorProbe()
    engine._mtc = mtc  # noqa: SLF001
    engine._artnet_tc = artnet  # noqa: SLF001
    engine._audio_settings = AudioOutputSettings(  # noqa: SLF001
        ltc_enabled=True,
        ltc_to_mtc_translate=True,
        midi_enabled=True,
        mtc_enabled=True,
        artnet_timecode_enabled=True,
    )
    decoded = Timecode(9, 10, 11, 12)
    decode_calls = 0

    def decode(_position: float) -> Timecode:
        nonlocal decode_calls
        decode_calls += 1
        return decoded

    monkeypatch.setattr(engine, "_decode_file_ltc_timecode", decode)
    engine._sync_mtc_to_file_ltc(3.25, force=True)  # noqa: SLF001

    assert decode_calls == 1
    assert mtc.calls == [(decoded, 3.25)]
    assert artnet.calls == [(decoded, 3.25)]


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
