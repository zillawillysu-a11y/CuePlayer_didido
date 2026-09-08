"""Audio output device enumeration / resolution boundary.

Structural stand-in for ``cueplayer.playback.devices.OutputDeviceInfo`` and
the list/find helpers — ports must not import the playback package.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AudioOutputDeviceInfo(Protocol):
    """Minimal device identity used by routing UI and the engine."""

    @property
    def index(self) -> int: ...

    @property
    def name(self) -> str: ...

    @property
    def max_output_channels(self) -> int: ...

    @property
    def default_samplerate(self) -> float: ...

    @property
    def hostapi_name(self) -> str: ...


@runtime_checkable
class AudioDevicePort(Protocol):
    """Enumerate and resolve a single output device (one device per song)."""

    def list_output_devices(self, *, dedupe: bool = True) -> list[AudioOutputDeviceInfo]:
        """Return host output devices suitable for CuePlayer routing."""
        ...

    def find_output_device(
        self,
        *,
        name: str | None = None,
        index: int | None = None,
    ) -> AudioOutputDeviceInfo | None:
        """Resolve a device by saved name and/or index."""
        ...
