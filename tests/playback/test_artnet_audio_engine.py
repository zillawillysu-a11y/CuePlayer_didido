from __future__ import annotations

from cueplayer.domain.models import AudioOutputSettings
from cueplayer.playback.artnet_timecode import ArtNetTimecodeStatus
from cueplayer.playback.audio_engine import AudioEngine


class _ArtNetProbe:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.enabled = False

    def configure(self, **kwargs) -> None:
        self.enabled = bool(kwargs["enabled"])
        self.calls.append(("configure", kwargs))
        return None

    def set_timebase(self, start_timecode: str, fps: float | None = None) -> None:
        self.calls.append(("timebase", start_timecode, fps))

    def on_play(self) -> None:
        self.calls.append(("play",))

    def on_pause(self) -> None:
        self.calls.append(("pause",))

    def on_seek(self, *, playing: bool) -> None:
        self.calls.append(("seek", playing))

    def close(self) -> None:
        self.calls.append(("close",))

    def status(self) -> ArtNetTimecodeStatus:
        return ArtNetTimecodeStatus(
            enabled=self.enabled,
            running=False,
            source="2.0.0.1:6454",
            destination="2.255.255.255:6454",
            error=None,
            send_count=0,
        )


def test_audio_engine_forwards_settings_and_transport_lifecycle() -> None:
    engine = AudioEngine()
    probe = _ArtNetProbe()
    engine._artnet_tc = probe
    try:
        engine.set_duration(10.0)
        engine.set_song_timebase("01:00:00:00", 25.0)
        settings = AudioOutputSettings(
            artnet_timecode_enabled=True,
            artnet_timecode_fps=30.0,  # legacy preference must not override Song FPS
            artnet_timecode_local_ip="2.0.0.1",
            artnet_timecode_destination_mode="broadcast",
            artnet_timecode_destination_ip="2.255.255.255",
        )
        assert engine.apply_audio_settings(settings) is None
        configure = next(call for call in probe.calls if call[0] == "configure")
        assert configure[1] == {
            "enabled": True,
            "fps": 25.0,
            "start_timecode": "01:00:00:00",
            "local_ip": "2.0.0.1",
            "destination_mode": "broadcast",
            "destination_ip": "2.255.255.255",
        }

        engine.play()
        assert ("play",) in probe.calls
        engine.seek(2.0)
        assert ("seek", True) in probe.calls
        engine.pause()
        assert probe.calls[-1] == ("pause",)
    finally:
        engine.shutdown_midi_outputs()
    assert probe.calls[-1] == ("close",)
