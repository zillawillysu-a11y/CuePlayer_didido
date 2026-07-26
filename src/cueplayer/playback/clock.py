"""Simple playback clock for Timeline UI milestone.

Audio-sample master clock comes later; this keeps UI playhead / marking usable now.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal


class PlaybackClock(QObject):
    position_changed = Signal(float)
    playing_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._position = 0.0
        self._duration = 60.0
        self._playing = False
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30 fps UI refresh
        self._timer.timeout.connect(self._on_tick)

    @property
    def position(self) -> float:
        return self._position

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def playing(self) -> bool:
        return self._playing

    def set_duration(self, seconds: float) -> None:
        self._duration = max(1.0, seconds)
        if self._position > self._duration:
            self.seek(self._duration)

    def play(self) -> None:
        if self._position >= self._duration:
            self.seek(0.0)
        self._playing = True
        self._timer.start()
        self.playing_changed.emit(True)

    def pause(self) -> None:
        self._playing = False
        self._timer.stop()
        self.playing_changed.emit(False)

    def stop(self) -> None:
        self.pause()
        self.seek(0.0)

    def toggle(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def seek(self, seconds: float) -> None:
        self._position = min(max(0.0, seconds), self._duration)
        self.position_changed.emit(self._position)

    def nudge(self, delta_seconds: float) -> None:
        self.seek(self._position + delta_seconds)

    def _on_tick(self) -> None:
        self._position += self._timer.interval() / 1000.0
        if self._position >= self._duration:
            self._position = self._duration
            self.pause()
        self.position_changed.emit(self._position)
