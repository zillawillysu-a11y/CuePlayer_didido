"""Align Anchors dialog shell (Sprint 5 Task 3).

Scaffolding only: layout, variant selector, anchor fields, preview placeholder,
and button/shortcut hooks. Does **not** compute or apply ``anchor_offset``,
and does not change playback or Timeline behavior.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.models import Song
from cueplayer.domain.song_variant import SongVariant
from cueplayer.ui.transport_bar import format_time

_SHELL_STATUS = "Shell only — anchor computation / Apply in the next task."


class AlignAnchorsDialog(QDialog):
    """Modal Align Anchors shell matching ``docs/song_variant_design.md`` §19.

    Widget responsibilities
    -----------------------
    ``variant_combo``
        Select which ``SongVariant`` the future Apply will edit.
    ``song_anchor_label`` / capture buttons
        Display + future capture of Song Time anchor (playhead / mark).
    ``variant_anchor_label`` / capture button
        Display + future capture of Variant (media) Time anchor.
    ``draft_offset_spin`` / nudge buttons
        Future draft offset editor (disabled computation this task).
    ``preview_area``
        Placeholder for duration chips / preview status.
    ``preview_btn`` / ``reset_btn`` / ``apply_btn`` / ``cancel_btn``
        Action hooks; Apply/Reset/Preview are no-ops; Cancel closes.

    Planned integration points (Task 4+)
    ------------------------------------
    - Capture Song/Variant anchors from PlaybackService playheads
    - ``draft = song_anchor - variant_anchor`` via ``domain.anchor_mapping``
    - Preview session: temporary draft offset without persisting
    - Apply → ``SongVariant.anchor_offset`` + dirty/undo
    """

    def __init__(self, song: Song, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Align Anchors")
        self.setModal(True)
        self.resize(560, 420)
        self._song = song
        self._song_anchor: float | None = None
        self._variant_anchor: float | None = None

        root = QVBoxLayout(self)

        intro = QLabel(
            "Cues stay fixed on Song Time — only the mix shifts.\n"
            "This dialog is a shell: Preview / Apply / Reset are not wired yet."
        )
        intro.setWordWrap(True)
        intro.setObjectName("alignAnchorsIntro")
        root.addWidget(intro)

        # --- variant selector ------------------------------------------------
        variant_row = QHBoxLayout()
        variant_row.addWidget(QLabel("Variant:"))
        self.variant_combo = QComboBox()
        self.variant_combo.setObjectName("alignVariantCombo")
        self.variant_combo.setMinimumWidth(180)
        variant_row.addWidget(self.variant_combo, stretch=1)
        self.path_label = QLabel("")
        self.path_label.setObjectName("alignVariantPath")
        self.path_label.setStyleSheet("color: #8b949e;")
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        variant_row.addWidget(self.path_label, stretch=2)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("alignVariantStatus")
        variant_row.addWidget(self.status_label)
        root.addLayout(variant_row)

        # --- anchors ---------------------------------------------------------
        anchors = QHBoxLayout()

        song_box = QGroupBox("Song Anchor (Song Time)")
        song_form = QVBoxLayout(song_box)
        song_btns = QHBoxLayout()
        self.use_playhead_btn = QPushButton("Use playhead")
        self.use_playhead_btn.setObjectName("alignUseSongPlayhead")
        self.use_mark_btn = QPushButton("Use mark…")
        self.use_mark_btn.setObjectName("alignUseMark")
        song_btns.addWidget(self.use_playhead_btn)
        song_btns.addWidget(self.use_mark_btn)
        song_form.addLayout(song_btns)
        self.song_anchor_label = QLabel("—")
        self.song_anchor_label.setObjectName("alignSongAnchorValue")
        self.song_anchor_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        song_form.addWidget(self.song_anchor_label)
        anchors.addWidget(song_box)

        var_box = QGroupBox("Variant Anchor (media)")
        var_form = QVBoxLayout(var_box)
        var_btns = QHBoxLayout()
        self.use_media_playhead_btn = QPushButton("Use media playhead")
        self.use_media_playhead_btn.setObjectName("alignUseMediaPlayhead")
        var_btns.addWidget(self.use_media_playhead_btn)
        var_form.addLayout(var_btns)
        self.variant_anchor_label = QLabel("—")
        self.variant_anchor_label.setObjectName("alignVariantAnchorValue")
        self.variant_anchor_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        var_form.addWidget(self.variant_anchor_label)
        anchors.addWidget(var_box)

        root.addLayout(anchors)

        # --- draft / applied display ----------------------------------------
        offset_box = QGroupBox("Offset")
        offset_layout = QFormLayout(offset_box)
        self.draft_offset_spin = QDoubleSpinBox()
        self.draft_offset_spin.setObjectName("alignDraftOffset")
        self.draft_offset_spin.setDecimals(3)
        self.draft_offset_spin.setRange(-3600.0, 3600.0)
        self.draft_offset_spin.setSingleStep(0.01)
        self.draft_offset_spin.setSuffix(" s")
        self.draft_offset_spin.setEnabled(False)  # computation later
        offset_layout.addRow("Draft offset:", self.draft_offset_spin)
        self.applied_offset_label = QLabel("+0.000 s")
        self.applied_offset_label.setObjectName("alignAppliedOffset")
        offset_layout.addRow("Applied:", self.applied_offset_label)

        nudge = QHBoxLayout()
        self.nudge_minus_1f = QPushButton("−1f")
        self.nudge_minus_10ms = QPushButton("−10 ms")
        self.nudge_plus_10ms = QPushButton("+10 ms")
        self.nudge_plus_1f = QPushButton("+1f")
        for btn in (
            self.nudge_minus_1f,
            self.nudge_minus_10ms,
            self.nudge_plus_10ms,
            self.nudge_plus_1f,
        ):
            btn.setEnabled(False)
            nudge.addWidget(btn)
        offset_layout.addRow("Nudge:", nudge)
        root.addWidget(offset_box)

        # --- preview placeholder --------------------------------------------
        preview_box = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_box)
        self.preview_area = QLabel(
            "Preview placeholder\n"
            "Song / media / audible-span duration chips will appear here."
        )
        self.preview_area.setObjectName("alignPreviewArea")
        self.preview_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_area.setMinimumHeight(72)
        self.preview_area.setStyleSheet(
            "background: #1a1d23; border: 1px dashed #3d4450; color: #8b949e; padding: 12px;"
        )
        preview_layout.addWidget(self.preview_area)
        root.addWidget(preview_box)

        self.shell_status = QLabel(_SHELL_STATUS)
        self.shell_status.setObjectName("alignShellStatus")
        self.shell_status.setWordWrap(True)
        self.shell_status.setStyleSheet("color: #c9a227;")
        root.addWidget(self.shell_status)

        # --- actions ---------------------------------------------------------
        action_row = QHBoxLayout()
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setObjectName("alignPreviewBtn")
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setObjectName("alignResetBtn")
        action_row.addWidget(self.preview_btn)
        action_row.addWidget(self.reset_btn)
        action_row.addStretch(1)
        root.addLayout(action_row)

        buttons = QDialogButtonBox()
        self.apply_btn = buttons.addButton(
            "Apply", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.apply_btn.setObjectName("alignApplyBtn")
        self.cancel_btn = buttons.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.cancel_btn.setObjectName("alignCancelBtn")
        # AcceptRole would close on Apply — keep Apply as no-op shell action.
        self.apply_btn.setAutoDefault(False)
        self.apply_btn.setDefault(False)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._populate_variants()
        self.variant_combo.currentIndexChanged.connect(self._on_variant_index_changed)
        self._on_variant_index_changed(self.variant_combo.currentIndex())

        # Capture / action hooks — stubs only (no playback / offset writes).
        self.use_playhead_btn.clicked.connect(self._stub_capture_song_playhead)
        self.use_mark_btn.clicked.connect(self._stub_capture_song_mark)
        self.use_media_playhead_btn.clicked.connect(self._stub_capture_media_playhead)
        self.preview_btn.clicked.connect(self._stub_preview)
        self.reset_btn.clicked.connect(self._stub_reset)
        self.apply_btn.clicked.connect(self._stub_apply)

        self._install_shortcuts()

    # --- public helpers (tests / future wiring) ------------------------------

    def selected_variant(self) -> SongVariant | None:
        data = self.variant_combo.currentData()
        if data is None:
            return None
        return self._song.variant_by_id(str(data))

    def song_anchor_seconds(self) -> float | None:
        return self._song_anchor

    def variant_anchor_seconds(self) -> float | None:
        return self._variant_anchor

    # --- populate ------------------------------------------------------------

    def _populate_variants(self) -> None:
        self.variant_combo.clear()
        variants = [v for v in self._song.variants if v.is_audio]
        if not variants:
            self.variant_combo.addItem("(no audio variants)", None)
            self.variant_combo.setEnabled(False)
            return
        selected = self._song.selected_variant_id
        select_index = 0
        for i, variant in enumerate(variants):
            label = variant.name or variant.id
            if not variant.enabled:
                label = f"{label} (disabled)"
            self.variant_combo.addItem(label, variant.id)
            if selected and variant.id == selected:
                select_index = i
        self.variant_combo.setCurrentIndex(select_index)

    def _on_variant_index_changed(self, _index: int) -> None:
        variant = self.selected_variant()
        if variant is None:
            self.path_label.setText("")
            self.status_label.setText("No variant")
            self.applied_offset_label.setText("+0.000 s")
            return
        path_text = str(variant.path) if variant.has_resolvable_path() else "(no path)"
        self.path_label.setText(path_text)
        if not variant.enabled:
            self.status_label.setText("Disabled")
        elif not variant.has_resolvable_path():
            self.status_label.setText("Missing path")
        elif not Path(variant.path).is_file():
            self.status_label.setText("Missing file")
        else:
            self.status_label.setText("Ready")
        applied = float(variant.anchor_offset)
        sign = "+" if applied >= 0 else ""
        self.applied_offset_label.setText(f"{sign}{applied:.3f} s")
        # Display only — do not write draft computation yet.
        self.draft_offset_spin.blockSignals(True)
        self.draft_offset_spin.setValue(applied)
        self.draft_offset_spin.blockSignals(False)

    def _set_song_anchor_display(self, seconds: float | None) -> None:
        self._song_anchor = seconds
        if seconds is None:
            self.song_anchor_label.setText("—")
        else:
            self.song_anchor_label.setText(format_time(seconds))

    def _set_variant_anchor_display(self, seconds: float | None) -> None:
        self._variant_anchor = seconds
        if seconds is None:
            self.variant_anchor_label.setText("—")
        else:
            self.variant_anchor_label.setText(format_time(seconds))

    # --- stubs (Task 4 will replace) -----------------------------------------

    def _note_shell(self, action: str) -> None:
        self.shell_status.setText(f"{_SHELL_STATUS} ({action})")

    def _stub_capture_song_playhead(self) -> None:
        self._note_shell("Use playhead")

    def _stub_capture_song_mark(self) -> None:
        self._note_shell("Use mark")

    def _stub_capture_media_playhead(self) -> None:
        self._note_shell("Use media playhead")

    def _stub_preview(self) -> None:
        self._note_shell("Preview")

    def _stub_reset(self) -> None:
        self._note_shell("Reset")

    def _stub_apply(self) -> None:
        self._note_shell("Apply")
        # Do not accept()/persist — shell only.

    def _stub_nudge(self, label: str) -> None:
        self._note_shell(f"Nudge {label}")

    # --- shortcuts (§19.5) ---------------------------------------------------

    def _install_shortcuts(self) -> None:
        # Esc → reject is built into QDialog.
        QShortcut(QKeySequence(Qt.Key.Key_Return), self, activated=self._stub_preview)
        QShortcut(QKeySequence(Qt.Key.Key_Enter), self, activated=self._stub_preview)
        QShortcut(
            QKeySequence("Ctrl+Return"), self, activated=self._stub_apply
        )
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._stub_apply)
        QShortcut(QKeySequence("["), self, activated=lambda: self._stub_nudge("−1f"))
        QShortcut(QKeySequence("]"), self, activated=lambda: self._stub_nudge("+1f"))
        QShortcut(
            QKeySequence("Shift+["), self, activated=lambda: self._stub_nudge("−10f")
        )
        QShortcut(
            QKeySequence("Shift+]"), self, activated=lambda: self._stub_nudge("+10f")
        )
        QShortcut(QKeySequence("A"), self, activated=self._stub_capture_song_playhead)
        QShortcut(
            QKeySequence("Shift+A"), self, activated=self._stub_capture_media_playhead
        )
