"""Smoke tests for the ports package (interfaces only — no wiring)."""

from __future__ import annotations

import cueplayer.ports as ports
from cueplayer.ports import (
    AudioDevicePort,
    FrameSink,
    MediaJobQueue,
    PlaybackClock,
    ProjectStore,
    RemoteEnginePort,
    RemoteHost,
    ShowExporter,
    ShowHost,
    SongSession,
    VideoAudioSource,
    VideoDecoderPort,
)


def test_ports_package_exports_all_target_protocols() -> None:
    names = {
        "AudioDevicePort",
        "AudioOutputDeviceInfo",
        "FrameSink",
        "MediaJobQueue",
        "PlaybackClock",
        "ProjectStore",
        "RemoteEnginePort",
        "RemoteHost",
        "ShowExporter",
        "ShowHost",
        "SongSession",
        "VideoAudioSource",
        "VideoDecoderPort",
    }
    assert names <= set(ports.__all__)
    for name in names:
        assert hasattr(ports, name)


def test_protocols_are_runtime_checkable_types() -> None:
    for cls in (
        PlaybackClock,
        AudioDevicePort,
        VideoDecoderPort,
        VideoAudioSource,
        FrameSink,
        ProjectStore,
        ShowExporter,
        RemoteEnginePort,
        RemoteHost,
        MediaJobQueue,
        SongSession,
        ShowHost,
    ):
        assert getattr(cls, "_is_protocol", False) or issubclass(cls, type(PlaybackClock))
        # Structural: must be usable for isinstance checks when runtime_checkable.
        assert getattr(cls, "_is_runtime_protocol", False) is True
