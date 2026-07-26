"""Metronome-style sync calibration: mute music, tap on the beat."""

from __future__ import annotations

from statistics import median

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from cueplayer.playback.audio_engine import AudioEngine

_COUNT_IN = 4
_MEASURE_TAPS = 8


class SyncCalibrationDialog(QDialog):
    """
    Plays a muted-music metronome. User taps on the beat (not after hearing).
    Measured offset = raw_write_head − click_time → sync_offset.
    """

    def __init__(self, engine: AudioEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sync Calibration")
        self.resize(500, 420)
        self._engine = engine
        self._saved_offset = engine.sync_offset_seconds
        self._all_click_times: list[float] = []
        self._measure_times: list[float] = []
        self._next_index = 0
        self._samples: list[float] = []
        self._running = False
        self._bpm = 100

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Calibration mutes the song and leaves only the metronome (BE).\n"
            "Tap the spacebar on the beat like a metronome — don't wait until you hear the click, "
            "tapping ahead of it is what measures the latency correctly.\n"
            "There are 4 count-in beats, then 8 measured taps; the median is used as the sync offset."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #c5cddb;")
        layout.addWidget(intro)

        bpm_row = QHBoxLayout()
        bpm_row.addWidget(QLabel("Tempo:"))
        self.bpm_60 = QRadioButton("60 BPM (one beat per second)")
        self.bpm_100 = QRadioButton("100 BPM (faster, easier to follow)")
        self.bpm_100.setChecked(True)
        self._bpm_group = QButtonGroup(self)
        self._bpm_group.addButton(self.bpm_60)
        self._bpm_group.addButton(self.bpm_100)
        bpm_row.addWidget(self.bpm_60)
        bpm_row.addWidget(self.bpm_100)
        bpm_row.addStretch(1)
        layout.addLayout(bpm_row)

        self.status = QLabel("Not started")
        self.status.setStyleSheet("font-size: 15px; font-weight: 600; color: #f2f5fa;")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.detail = QLabel("")
        self.detail.setStyleSheet("color: #8b949e;")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)

        row = QHBoxLayout()
        self.start_btn = QPushButton("Start Calibration")
        self.heard_btn = QPushButton("Tap (Spacebar)")
        self.heard_btn.setEnabled(False)
        row.addWidget(self.start_btn)
        row.addWidget(self.heard_btn)
        layout.addLayout(row)

        layout.addStretch(1)

        buttons = QDialogButtonBox()
        self.apply_btn = buttons.addButton("Apply Result", QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_btn = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self.apply_btn.setEnabled(False)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self._cancel)
        layout.addWidget(buttons)

        self.start_btn.clicked.connect(self._start)
        self.heard_btn.clicked.connect(self._on_tap)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self._on_tap)

    def _selected_bpm(self) -> int:
        return 60 if self.bpm_60.isChecked() else 100

    def _start(self) -> None:
        if self._engine.buffer is None:
            QMessageBox.warning(self, "Sync Calibration", "Load audio before calibrating.")
            return

        self._bpm = self._selected_bpm()
        beat = 60.0 / float(self._bpm)
        needed = 0.4 + (_COUNT_IN + _MEASURE_TAPS) * beat + 0.3
        duration = self._engine.duration
        if duration < needed:
            QMessageBox.warning(
                self,
                "Sync Calibration",
                f"Audio is too short (needs about {needed:.1f}s to run {_COUNT_IN}+{_MEASURE_TAPS} beats @ {self._bpm} BPM).\n"
                "Use a longer file, or switch to 100 BPM.",
            )
            return

        self._engine.set_sync_offset_ms(0)
        self._engine.pause()
        self._engine.set_music_muted(True)

        start = 0.4
        self._all_click_times = [start + i * beat for i in range(_COUNT_IN + _MEASURE_TAPS)]
        self._measure_times = self._all_click_times[_COUNT_IN:]
        self._next_index = 0
        self._samples = []
        self._running = True

        self._engine.seek(0.0)
        self._engine.schedule_calibration_clicks(self._all_click_times)
        self._engine.play()
        self.start_btn.setEnabled(False)
        self.bpm_60.setEnabled(False)
        self.bpm_100.setEnabled(False)
        self.heard_btn.setEnabled(True)
        self.apply_btn.setEnabled(False)
        self._update_status()

    def _update_status(self) -> None:
        if not self._running:
            if self._samples:
                med = median(self._samples) * 1000.0
                self.status.setText(f"Done: suggested sync offset {med:.0f} ms ({len(self._samples)} taps)")
                detail = ", ".join(f"{s * 1000:.0f}" for s in self._samples)
                self.detail.setText(
                    f"Individual measurements (ms): {detail}\n"
                    'Positive = audio lags behind the waveform (common). '
                    'Press "Apply Result" to align the red line/marks with what you hear.'
                )
            else:
                self.status.setText("Not started")
                self.detail.setText("")
            return

        raw = self._engine.raw_position
        # Still in count-in?
        first_measure = self._measure_times[0]
        if raw < first_measure - 0.05:
            remaining = max(0, int(round((first_measure - raw) / (60.0 / self._bpm))))
            self.status.setText(f"Count-in… about {remaining} beat(s) left (song is muted, BE only)")
            self.detail.setText(f"{self._bpm} BPM · {_COUNT_IN} count-in beats, then tap the spacebar on the beat")
            return

        n = len(self._samples)
        total = len(self._measure_times)
        self.status.setText(f"Tap along! {min(n + 1, total)} / {total} ({self._bpm} BPM)")
        if self._samples:
            detail = ", ".join(f"{s * 1000:.0f}" for s in self._samples)
            self.detail.setText(f"Recorded (ms): {detail}")
        else:
            self.detail.setText("The song is muted. Tap along with the BE clicks — don't wait to react after hearing them.")

    def _nearest_open_click(self, raw: float) -> tuple[int, float] | None:
        """Pick the measure click closest to now that isn't already used."""
        if self._next_index >= len(self._measure_times):
            return None
        beat = 60.0 / float(self._bpm)
        window = beat * 0.45
        best: tuple[int, float] | None = None
        best_abs = 1e9
        for i in range(self._next_index, len(self._measure_times)):
            click_t = self._measure_times[i]
            delta = raw - click_t
            if abs(delta) > window:
                if click_t > raw + window:
                    break
                continue
            if abs(delta) < best_abs:
                best_abs = abs(delta)
                best = (i, click_t)
        return best

    def _on_tap(self) -> None:
        if not self._running:
            return
        raw = self._engine.raw_position
        first_measure = self._measure_times[0]
        if raw < first_measure - 0.12:
            self.detail.setText("Still in the count-in, wait for the measured beats.")
            self._update_status()
            return

        hit = self._nearest_open_click(raw)
        if hit is None:
            self.detail.setText("That tap didn't line up, try the next beat.")
            self._update_status()
            return

        index, click_t = hit
        delta = raw - click_t
        self._samples.append(delta)
        self._next_index = index + 1
        if self._next_index >= len(self._measure_times):
            self._finish_run()
        else:
            self._update_status()

    def _finish_run(self) -> None:
        self._running = False
        self._engine.pause()
        self._engine.clear_calibration_clicks()
        self._engine.set_music_muted(False)
        self.heard_btn.setEnabled(False)
        self.start_btn.setEnabled(True)
        self.bpm_60.setEnabled(True)
        self.bpm_100.setEnabled(True)
        self.apply_btn.setEnabled(bool(self._samples))
        self._update_status()

    def _apply(self) -> None:
        if not self._samples:
            return
        ms = median(self._samples) * 1000.0
        self._engine.set_sync_offset_ms(ms)
        self._engine.clear_calibration_clicks()
        self._engine.set_music_muted(False)
        self.accept()

    def _cancel(self) -> None:
        self._running = False
        self._engine.clear_calibration_clicks()
        self._engine.set_music_muted(False)
        if self._engine.playing:
            self._engine.pause()
        self._engine.set_sync_offset_ms(self._saved_offset * 1000.0)
        self.reject()

    def result_offset_ms(self) -> float:
        if not self._samples:
            return self._engine.sync_offset_ms()
        return median(self._samples) * 1000.0

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._engine.clear_calibration_clicks()
        self._engine.set_music_muted(False)
        super().closeEvent(event)
