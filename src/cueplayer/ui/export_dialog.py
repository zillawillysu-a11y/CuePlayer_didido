"""Export one or more songs to grandMA2 / grandMA3 XML."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.models import Song
from cueplayer.exporters.common import sanitize_ma_name
from cueplayer.exporters.ma2 import Ma2Exporter
from cueplayer.exporters.ma3 import Ma3Exporter
from cueplayer.exporters.ma_default_dirs import resolve_export_dir
from cueplayer.exporters.plan_from_song import (
    build_export_plan,
    plan_summary_text,
    timecode_to_seconds,
)
from cueplayer.ui.row_color import ROLE_ROW_COLOR, RowColorDelegate
from cueplayer.ui.spinboxes import NoWheelDoubleSpinBox, NoWheelSpinBox

_SETTINGS_ORG = "CuePlayer"
_SETTINGS_APP = "CuePlayer"
_KEY_MA2_DIR = "export/ma2_out_dir"
_KEY_MA3_DIR = "export/ma3_out_dir"
_KEY_CONSOLE = "export/last_console"


class ExportDialog(QDialog):
    """Export settings → write MA2/MA3 XML for one or more songs."""

    def __init__(
        self,
        songs: list[Song],
        parent: QWidget | None = None,
        *,
        selected_indexes: list[int] | None = None,
        current_index: int = 0,
    ) -> None:
        super().__init__(parent)
        if not songs:
            raise ValueError("ExportDialog requires at least one song")
        self._songs = list(songs)
        self._last_paths: dict[str, Path] = {}
        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._updating_out = False

        self.setWindowTitle("Export to grandMA")
        self.resize(560, 720)

        root = QVBoxLayout(self)

        song_box = QGroupBox("Songs to Export")
        song_layout = QVBoxLayout(song_box)
        self.song_list = QListWidget()
        # Single-select so clicking a row highlights it with the same accent-blue
        # selection the setlist/timeline use (checkbox state stays independent —
        # this is just "which row you're looking at", not "which songs export").
        self.song_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.song_list.setItemDelegate(RowColorDelegate(self.song_list))
        preselect = set(selected_indexes or [])
        if not preselect and 0 <= current_index < len(self._songs):
            preselect = {current_index}
        for i, song in enumerate(self._songs):
            ma = f"  ·  {song.ma_export_name}" if song.ma_export_name else ""
            item = QListWidgetItem(f"{i + 1}. {song.name}{ma}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if i in preselect else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setData(ROLE_ROW_COLOR, song.row_color or "")
            self.song_list.addItem(item)
        song_layout.addWidget(self.song_list)
        pick_row = QHBoxLayout()
        all_btn = QPushButton("Select All")
        none_btn = QPushButton("Select None")
        all_btn.clicked.connect(lambda: self._set_all_songs(True))
        none_btn.clicked.connect(lambda: self._set_all_songs(False))
        pick_row.addWidget(all_btn)
        pick_row.addWidget(none_btn)
        pick_row.addStretch(1)
        song_layout.addLayout(pick_row)
        root.addWidget(song_box)

        console_box = QGroupBox("Console")
        console_layout = QHBoxLayout(console_box)
        self.ma2_radio = QRadioButton("grandMA2")
        self.ma3_radio = QRadioButton("grandMA3")
        last_console = str(self._settings.value(_KEY_CONSOLE, "ma2"))
        if last_console == "ma3":
            self.ma3_radio.setChecked(True)
        else:
            self.ma2_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.ma2_radio)
        group.addButton(self.ma3_radio)
        console_layout.addWidget(self.ma2_radio)
        console_layout.addWidget(self.ma3_radio)
        console_layout.addStretch(1)
        root.addWidget(console_box)

        form_box = QGroupBox("Export Settings")
        form = QFormLayout(form_box)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Full (Sequence + Timecode)", "full")
        self.mode_combo.addItem("Timecode Only (update events)", "timecode_only")
        form.addRow("Mode", self.mode_combo)

        self.seq_pool = NoWheelSpinBox()
        self.seq_pool.setRange(1, 9999)
        self.seq_pool.setValue(1)
        form.addRow("Sequence Pool Start", self.seq_pool)

        self.tc_pool = NoWheelSpinBox()
        self.tc_pool.setRange(1, 9999)
        self.tc_pool.setValue(1)
        form.addRow("Timecode Pool Start", self.tc_pool)

        self.auto_increment = QCheckBox("Auto-increment pool for multiple songs (Seq +2, TC +1 per song)")
        self.auto_increment.setChecked(True)
        form.addRow("", self.auto_increment)

        self.main_exec = QLineEdit("1.101")
        self.main_exec.setToolTip("Page.Executor, e.g. 1.101")
        form.addRow("Main Executor", self.main_exec)

        self.button_exec = QLineEdit("1.201")
        self.button_exec.setToolTip("Starting Button Executor; multiple lanes increment by 1")
        form.addRow("Button Executor Start", self.button_exec)

        self.tc_slot = NoWheelSpinBox()
        self.tc_slot.setRange(1, 99)
        self.tc_slot.setValue(1)
        form.addRow("Timecode Slot", self.tc_slot)

        self.fps = NoWheelDoubleSpinBox()
        self.fps.setRange(1.0, 120.0)
        self.fps.setDecimals(3)
        seed = self._songs[current_index if 0 <= current_index < len(self._songs) else 0]
        self.fps.setValue(float(seed.fps or 30.0))
        form.addRow("FPS", self.fps)

        self.latency_ms = NoWheelDoubleSpinBox()
        self.latency_ms.setRange(-500.0, 500.0)
        self.latency_ms.setDecimals(1)
        self.latency_ms.setSuffix(" ms")
        self.latency_ms.setValue(0.0)
        self.latency_ms.setToolTip("Negative = events fire earlier (offsets LTC→MA latency; commonly -100 to -200)")
        form.addRow("Latency Compensation", self.latency_ms)

        self.data_pool = QLineEdit("Default")
        self.data_pool.setToolTip("MA3 Data Pool name")
        form.addRow("MA3 Data Pool", self.data_pool)

        self.name_hint = QLabel("File names / Sequence names are generated automatically from each song's MA English name.")
        self.name_hint.setWordWrap(True)
        self.name_hint.setStyleSheet("color: #8b949e;")
        form.addRow(self.name_hint)

        root.addWidget(form_box)

        out_row = QHBoxLayout()
        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText("Choose output folder…")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_out)
        use_default = QPushButton("Restore Default")
        use_default.setToolTip("Fills in the detected MA2 importexport / MA3 library path")
        use_default.clicked.connect(self._restore_detected_default)
        out_row.addWidget(self.out_dir, stretch=1)
        out_row.addWidget(browse)
        out_row.addWidget(use_default)
        root.addLayout(out_row)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: #8b949e;")
        root.addWidget(self.summary)

        self.ma2_radio.toggled.connect(self._on_console_changed)
        self.ma3_radio.toggled.connect(self._on_console_changed)
        self.mode_combo.currentIndexChanged.connect(self._refresh_summary)
        self.seq_pool.valueChanged.connect(self._refresh_summary)
        self.tc_pool.valueChanged.connect(self._refresh_summary)
        self.auto_increment.toggled.connect(self._refresh_summary)
        self.button_exec.textChanged.connect(self._refresh_summary)
        self.fps.valueChanged.connect(self._refresh_summary)
        self.latency_ms.valueChanged.connect(self._refresh_summary)
        self.song_list.itemChanged.connect(self._refresh_summary)
        self._refresh_ma3_enabled()
        self._apply_console_out_dir(initial=True)
        self._refresh_summary()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.accepted.connect(self._export)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def last_export_paths(self) -> dict[str, Path]:
        return dict(self._last_paths)

    def _console(self) -> str:
        return "ma3" if self.ma3_radio.isChecked() else "ma2"

    def _settings_key_for_console(self) -> str:
        return _KEY_MA3_DIR if self._console() == "ma3" else _KEY_MA2_DIR

    def _apply_console_out_dir(self, *, initial: bool = False) -> None:
        key = self._settings_key_for_console()
        remembered = self._settings.value(key)
        remembered_str = str(remembered) if remembered else None
        path = resolve_export_dir(self._console(), remembered_str)
        self._updating_out = True
        self.out_dir.setText(path)
        self._updating_out = False
        if not initial:
            self._refresh_ma3_enabled()
            self._refresh_summary()

    def _on_console_changed(self, checked: bool) -> None:
        if not checked:
            return
        self._apply_console_out_dir()

    def _restore_detected_default(self) -> None:
        path = resolve_export_dir(self._console(), remembered=None)
        if not path:
            QMessageBox.information(
                self,
                "Default Folder Not Found",
                "No grandMA install path was detected on this computer; choose a folder manually.",
            )
            return
        self.out_dir.setText(path)

    def _refresh_ma3_enabled(self) -> None:
        self.data_pool.setEnabled(self.ma3_radio.isChecked())

    def _browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose Export Folder", self.out_dir.text())
        if path:
            self.out_dir.setText(path)

    def _set_all_songs(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.song_list.blockSignals(True)
        for row in range(self.song_list.count()):
            item = self.song_list.item(row)
            if item is not None:
                item.setCheckState(state)
        self.song_list.blockSignals(False)
        self._refresh_summary()

    def _checked_songs(self) -> list[Song]:
        out: list[Song] = []
        for row in range(self.song_list.count()):
            item = self.song_list.item(row)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            idx = int(item.data(Qt.ItemDataRole.UserRole))
            out.append(self._songs[idx])
        return out

    def _build_plan(
        self,
        song: Song,
        *,
        sequence_pool_start: int,
        timecode_pool: int,
    ):
        console = self._console()
        mode = self.mode_combo.currentData()
        fps = float(self.fps.value())
        offset = timecode_to_seconds(song.start_timecode or "01:00:00:00", fps)
        return build_export_plan(
            song,
            console=console,  # type: ignore[arg-type]
            export_mode=mode,  # type: ignore[arg-type]
            sequence_pool_start=sequence_pool_start,
            timecode_pool=timecode_pool,
            main_executor=self.main_exec.text().strip() or "1.101",
            button_executor_start=self.button_exec.text().strip() or "1.201",
            timecode_slot=self.tc_slot.value(),
            ltc_latency_compensation_seconds=float(self.latency_ms.value()) / 1000.0,
            data_pool=self.data_pool.text().strip() or "Default",
            start_offset_seconds=offset,
            fps=fps,
        )

    def _pool_plan(self, songs: list[Song]) -> list[tuple[Song, int, int]]:
        seq = self.seq_pool.value()
        tc = self.tc_pool.value()
        auto = self.auto_increment.isChecked() and len(songs) > 1
        rows: list[tuple[Song, int, int]] = []
        for song in songs:
            rows.append((song, seq, tc))
            if auto:
                seq += 2
                tc += 1
        return rows

    def _refresh_summary(self) -> None:
        songs = self._checked_songs()
        if not songs:
            self.summary.setText("Check at least one song.")
            return
        try:
            lines: list[str] = []
            for song, seq, tc in self._pool_plan(songs):
                plan = self._build_plan(song, sequence_pool_start=seq, timecode_pool=tc)
                base = sanitize_ma_name(song.ma_export_name or song.name, fallback="Song")
                lines.append(
                    f"· {song.name} ({base}) Seq {seq}/{seq + 1} · TC {tc} — "
                    f"{plan_summary_text(plan)}"
                )
                lines.extend(f"  ⚠ {warning}" for warning in plan.warnings)
            self.summary.setText("\n".join(lines))
        except Exception as exc:  # noqa: BLE001
            self.summary.setText(f"Unable to preview: {exc}")

    def _export(self) -> None:
        songs = self._checked_songs()
        if not songs:
            QMessageBox.warning(self, "No Songs Selected", "Check at least one song.")
            return

        out = self.out_dir.text().strip()
        if not out:
            QMessageBox.warning(self, "Missing Folder", "Choose an output folder first.")
            return
        directory = Path(out)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Unable to Create Folder", str(exc))
            return

        empty_main = [
            song
            for song, seq, tc in self._pool_plan(songs)
            if not self._build_plan(song, sequence_pool_start=seq, timecode_pool=tc).main_cues
        ]
        if empty_main and self.mode_combo.currentData() == "full":
            names = ", ".join(s.name for s in empty_main[:5])
            more = "…" if len(empty_main) > 5 else ""
            answer = QMessageBox.question(
                self,
                "No Main Cues",
                f"These songs have no Marks on the Main lane: {names}{more}\nExport anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        all_paths: dict[str, Path] = {}
        errors: list[str] = []
        export_warnings: list[str] = []
        try:
            for song, seq, tc in self._pool_plan(songs):
                plan = self._build_plan(song, sequence_pool_start=seq, timecode_pool=tc)
                if plan.profile.console == "ma3":
                    paths = Ma3Exporter().export_to_directory(plan, directory)
                else:
                    paths = Ma2Exporter().export_to_directory(plan, directory)
                export_warnings.extend(plan.warnings)
                prefix = sanitize_ma_name(song.ma_export_name or song.name, fallback="Song")
                for key, path in paths.items():
                    all_paths[f"{prefix}:{key}"] = path
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

        if errors and not all_paths:
            QMessageBox.warning(self, "Export Failed", "\n".join(errors))
            return

        self._last_paths = all_paths
        self._settings.setValue(self._settings_key_for_console(), str(directory))
        self._settings.setValue(_KEY_CONSOLE, self._console())

        names = "\n".join(f"· {p.name}" for p in all_paths.values())
        if len(names) > 1200:
            names = "\n".join(f"· {p.name}" for p in list(all_paths.values())[:20])
            names += f"\n…{len(all_paths)} files total"
        warning_text = ""
        if export_warnings:
            warning_text = "\n\nWarnings:\n" + "\n".join(
                f"· {warning}" for warning in export_warnings
            )
        QMessageBox.information(
            self,
            "Export Complete",
            f"Exported {len(songs)} song(s) →\n{directory}\n\n{names}{warning_text}",
        )
        self.accept()
