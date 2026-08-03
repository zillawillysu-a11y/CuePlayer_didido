"""Architecture boundary Protocols (interfaces only).

These ports define stable seams for the strangler migration toward
``application/`` + ``adapters/`` (see ``docs/ARCHITECTURE_TARGET.md``).

Rules for this package:
- Protocol / typing only — no runtime behavior, no wiring, no adapters.
- May reference ``cueplayer.domain`` types in signatures.
- Must not import ``ui``, ``playback``, ``media``, ``persistence``,
  ``exporters``, or ``web_remote`` (adapters will implement these ports).
"""

from __future__ import annotations

from cueplayer.ports.audio_device import AudioDevicePort, AudioOutputDeviceInfo
from cueplayer.ports.clock import PlaybackClock
from cueplayer.ports.exporter import ShowExporter
from cueplayer.ports.frame_sink import FrameSink
from cueplayer.ports.media_jobs import MediaJobQueue
from cueplayer.ports.project_store import ProjectStore
from cueplayer.ports.remote_host import RemoteEnginePort, RemoteHost
from cueplayer.ports.show_host import (
    ShowHost,
    ShowHostEngine,
    ShowHostMonitor,
    ShowHostStatus,
    ShowHostTimeline,
    ShowHostTransport,
    ShowHostVideoSync,
)
from cueplayer.ports.song_session import SongSession
from cueplayer.ports.video_audio import VideoAudioSource
from cueplayer.ports.video_decoder import VideoDecoderPort

__all__ = [
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
    "ShowHostEngine",
    "ShowHostMonitor",
    "ShowHostStatus",
    "ShowHostTimeline",
    "ShowHostTransport",
    "ShowHostVideoSync",
    "SongSession",
    "VideoAudioSource",
    "VideoDecoderPort",
]
