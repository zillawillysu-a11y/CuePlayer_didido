"""Align Anchors dialog — draft, preview session, Apply/Commit (Sprint 5 Tasks 4–6).

Draft state is temporary. Preview drives PlaybackService with an ephemeral
offset and never mutates the project. Apply is the **only** commit point:
``draft_offset`` → ``SongVariant.anchor_offset`` via
:class:`~cueplayer.domain.undo.SetVariantAnchorOffsetCommand`.

Marks / cue times are never moved. Does not redesign Timeline/Waveform.
Draft offset uses ``domain.anchor_mapping.offset_from_anchors`` exclusively
(``draft = song_anchor − variant_anchor``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.anchor_mapping import (
    coerce_anchor_offset,
    offset_from_anchors,
    song_to_variant_time,
    variant_to_song_time,
)
from cueplayer.domain.models import Song
from cueplayer.domain.song_variant import SongVariant
from cueplayer.domain.undo import SetVariantAnchorOffsetCommand
from cueplayer.ui.transport_bar import format_time

_STATUS_HINT = "Preview is temporary; Apply commits (marks unchanged)."


class AlignAnchorsDialog(QDialog):
    """Modal Align Anchors dialog with draft, ephemeral preview, and Apply.

    Temporary state model
    ---------------------
    ``_song_anchor`` / ``_variant_anchor``
        Optional captured times (Song Time / Variant Time).
    ``_draft_offset``
        Working offset shown in the spin box; not persisted until Apply.
    ``applied`` (read-only display)
        Current ``SongVariant.anchor_offset`` for the selected variant.
    Playback preview
        Ephemeral offset on PlaybackService; cleared on Cancel / Apply / close.

    Draft lifecycle
    ---------------
    1. Open / variant change → draft initialized from applied offset.
    2. Capture both anchors → draft = ``offset_from_anchors`` (live).
    3. Nudge / type draft → draft updates; live-updates preview if active.
    4. Reset → draft = 0.0 (still not persisted until Apply).
    5. Preview → temporary PlaybackService mapping (no project write).
    6. Apply → ``SetVariantAnchorOffsetCommand.redo``; emit ``offset_committed``.
    7. Cancel → end preview + discard draft; no project write.
    """

    #: Emitted after Apply mutates the song via the undo command.
    #: MainWindow should ``_push_song_undo`` + ``_mark_dirty``.
    offset_committed = Signal(object)

    def __init__(
        self,
        song: Song,
        parent: QWidget | None = None,
        *,
        get_song_playhead: Callable[[], float] | None = None,
        get_media_playhead: Callable[[], float] | None = None,
        begin_preview: Callable[[float], None] | None = None,
        end_preview: Callable[[], None] | None = None,
        is_preview_active: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Align Anchors")
        self.setModal(True)
        self.resize(560, 460)
        self._song = song
        self._get_song_playhead = get_song_playhead
        self._get_media_playhead = get_media_playhead
        self._begin_preview = begin_preview
        self._end_preview = end_preview
        self._is_preview_active = is_preview_active
        self._song_anchor: float | None = None
        self._variant_anchor: float | None = None
        self._draft_offset = 0.0
        self._updating_draft_ui = False
        self._suppress_variant_change = False

        root = QVBoxLayout(self)

        intro = QLabel(
            "Cues stay fixed on Song Time — only the mix shifts.\n"
            "Preview auditions the draft; Apply commits it."
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
        self.draft_offset_spin.setEnabled(True)
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
            btn.setEnabled(True)
            nudge.addWidget(btn)
        offset_layout.addRow("Nudge:", nudge)
        root.addWidget(offset_box)

        # --- preview (live draft values; optional playback session) ---------
        preview_box = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_box)
        self.preview_area = QLabel("")
        self.preview_area.setObjectName("alignPreviewArea")
        self.preview_area.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.preview_area.setMinimumHeight(88)
        self.preview_area.setWordWrap(True)
        self.preview_area.setStyleSheet(
            "background: #1a1d23; border: 1px dashed #3d4450; color: #c5cddb; padding: 12px;"
        )
        preview_layout.addWidget(self.preview_area)
        root.addWidget(preview_box)

        self.shell_status = QLabel(_STATUS_HINT)
        self.shell_status.setObjectName("alignShellStatus")
        self.shell_status.setWordWrap(True)
        self.shell_status.setStyleSheet("color: #8b949e;")
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
        self.apply_btn.setAutoDefault(False)
        self.apply_btn.setDefault(False)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._populate_variants()
        self.variant_combo.currentIndexChanged.connect(self._on_variant_index_changed)
        self._on_variant_index_changed(self.variant_combo.currentIndex())

        self.use_playhead_btn.clicked.connect(self._capture_song_playhead)
        self.use_mark_btn.clicked.connect(self._capture_song_mark)
        self.use_media_playhead_btn.clicked.connect(self._capture_media_playhead)
        self.preview_btn.clicked.connect(self._on_preview_session)
        self.reset_btn.clicked.connect(self._reset_draft)
        self.apply_btn.clicked.connect(self._on_apply)
        self.draft_offset_spin.valueChanged.connect(self._on_draft_spin_changed)
        self.nudge_minus_1f.clicked.connect(lambda: self._nudge_draft(-self._frame_seconds()))
        self.nudge_plus_1f.clicked.connect(lambda: self._nudge_draft(self._frame_seconds()))
        self.nudge_minus_10ms.clicked.connect(lambda: self._nudge_draft(-0.01))
        self.nudge_plus_10ms.clicked.connect(lambda: self._nudge_draft(0.01))
        self.finished.connect(lambda *_: self._end_preview_session())

        self._install_shortcuts()
        self._refresh_preview_panel()

    # --- public helpers ------------------------------------------------------

    def selected_variant(self) -> SongVariant | None:
        data = self.variant_combo.currentData()
        if data is None:
            return None
        return self._song.variant_by_id(str(data))

    def song_anchor_seconds(self) -> float | None:
        return self._song_anchor

    def variant_anchor_seconds(self) -> float | None:
        return self._variant_anchor

    def draft_offset(self) -> float:
        return float(self._draft_offset)

    def applied_offset(self) -> float:
        variant = self.selected_variant()
        if variant is None:
            return 0.0
        return coerce_anchor_offset(variant.anchor_offset)

    def is_draft_dirty(self) -> bool:
        return abs(self.draft_offset() - self.applied_offset()) > 1e-9

    def is_preview_session_active(self) -> bool:
        if self._is_preview_active is None:
            return False
        try:
            return bool(self._is_preview_active())
        except Exception:  # noqa: BLE001
            return False

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

    def _on_variant_index_changed(self, index: int) -> None:
        if self._suppress_variant_change:
            return
        # Confirm discard when leaving a dirty draft for another variant.
        previous = getattr(self, "_last_variant_index", None)
        if (
            previous is not None
            and previous != index
            and self.is_draft_dirty()
        ):
            reply = QMessageBox.question(
                self,
                "Align Anchors",
                "Discard draft offset for this variant?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._suppress_variant_change = True
                try:
                    self.variant_combo.setCurrentIndex(previous)
                finally:
                    self._suppress_variant_change = False
                return
        if previous is not None and previous != index:
            self._end_preview_session()
        self._last_variant_index = index
        variant = self.selected_variant()
        if variant is None:
            self.path_label.setText("")
            self.status_label.setText("No variant")
            self.applied_offset_label.setText("+0.000 s")
            self._set_draft_offset(0.0, recompute_from_anchors=False)
            self._set_song_anchor(None)
            self._set_variant_anchor(None)
            self._refresh_preview_panel()
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
        self._refresh_applied_label()
        # New variant selection: reset draft to applied (no project write).
        self._set_song_anchor(None)
        self._set_variant_anchor(None)
        self._set_draft_offset(self.applied_offset(), recompute_from_anchors=False)
        self._refresh_preview_panel()

    def _refresh_applied_label(self) -> None:
        applied = self.applied_offset()
        sign = "+" if applied >= 0 else ""
        self.applied_offset_label.setText(f"{sign}{applied:.3f} s")

    def _frame_seconds(self) -> float:
        fps = float(getattr(self._song, "fps", 0.0) or 0.0)
        if fps <= 0:
            fps = 30.0
        return 1.0 / fps

    # --- draft model ---------------------------------------------------------

    def _set_draft_offset(self, value: float, *, recompute_from_anchors: bool) -> None:
        del recompute_from_anchors  # reserved for call-site clarity
        self._draft_offset = coerce_anchor_offset(value)
        self._updating_draft_ui = True
        try:
            self.draft_offset_spin.setValue(self._draft_offset)
        finally:
            self._updating_draft_ui = False

    def _on_draft_spin_changed(self, value: float) -> None:
        if self._updating_draft_ui:
            return
        self._draft_offset = coerce_anchor_offset(value)
        self._sync_live_preview()
        self._refresh_preview_panel()
        self._set_status("Draft edited (typed)")

    def _nudge_draft(self, delta: float) -> None:
        self._set_draft_offset(self._draft_offset + float(delta), recompute_from_anchors=False)
        self._sync_live_preview()
        self._refresh_preview_panel()
        self._set_status(f"Draft nudged {delta:+.4f}s")

    def _reset_draft(self) -> None:
        self._set_draft_offset(0.0, recompute_from_anchors=False)
        self._sync_live_preview()
        self._refresh_preview_panel()
        self._set_status("Draft reset to 0.000 s (not applied)")

    def _recompute_draft_from_anchors(self) -> bool:
        if self._song_anchor is None or self._variant_anchor is None:
            self._set_status("Set both anchors to compute draft")
            return False
        draft = offset_from_anchors(self._song_anchor, self._variant_anchor)
        self._set_draft_offset(draft, recompute_from_anchors=True)
        self._sync_live_preview()
        self._refresh_preview_panel()
        self._set_status("Draft computed from anchors")
        return True

    def _set_song_anchor(self, seconds: float | None) -> None:
        self._song_anchor = None if seconds is None else float(seconds)
        if self._song_anchor is None:
            self.song_anchor_label.setText("—")
        else:
            self.song_anchor_label.setText(format_time(self._song_anchor))

    def _set_variant_anchor(self, seconds: float | None) -> None:
        self._variant_anchor = None if seconds is None else float(seconds)
        if self._variant_anchor is None:
            self.variant_anchor_label.setText("—")
        else:
            self.variant_anchor_label.setText(format_time(self._variant_anchor))

    def _set_status(self, message: str) -> None:
        hint = _STATUS_HINT
        if self.is_preview_session_active():
            hint = "Previewing — Cancel restores applied mapping."
            self.shell_status.setStyleSheet("color: #58a6ff;")
        else:
            self.shell_status.setStyleSheet("color: #8b949e;")
        self.shell_status.setText(f"{message}. {hint}")

    # --- capture -------------------------------------------------------------

    def _capture_song_playhead(self) -> None:
        if self._get_song_playhead is None:
            self._set_status("Song playhead source not available")
            return
        try:
            t = float(self._get_song_playhead())
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Could not read song playhead ({exc})")
            return
        if not _finite(t):
            self._set_status("Song playhead invalid")
            return
        self._set_song_anchor(t)
        self._recompute_draft_from_anchors()
        if self._variant_anchor is None:
            self._refresh_preview_panel()
            self._set_status(f"Song anchor = {format_time(t)}")

    def _capture_media_playhead(self) -> None:
        if self._get_media_playhead is None:
            self._set_status("Media playhead source not available")
            return
        try:
            t = float(self._get_media_playhead())
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Could not read media playhead ({exc})")
            return
        if not _finite(t):
            self._set_status("Media playhead invalid")
            return
        self._set_variant_anchor(t)
        self._recompute_draft_from_anchors()
        if self._song_anchor is None:
            self._refresh_preview_panel()
            self._set_status(f"Variant anchor = {format_time(t)}")

    def _capture_song_mark(self) -> None:
        marks = sorted(self._song.marks, key=lambda m: (m.time_seconds, m.lane_index))
        if not marks:
            QMessageBox.information(self, "Align Anchors", "No marks on this song.")
            return
        labels = [
            f"{format_time(m.time_seconds)}  ·  L{m.lane_index}  ·  "
            f"{(m.display_name or m.main_cue_id or m.id)}"
            for m in marks
        ]
        choice, ok = QInputDialog.getItem(
            self,
            "Use mark",
            "Song Anchor from mark:",
            labels,
            0,
            False,
        )
        if not ok:
            return
        index = labels.index(choice)
        self._set_song_anchor(float(marks[index].time_seconds))
        self._recompute_draft_from_anchors()
        if self._variant_anchor is None:
            self._refresh_preview_panel()
            self._set_status("Song anchor from mark")

    # --- preview panel + playback session ------------------------------------

    def _refresh_preview_panel(self) -> None:
        draft = self.draft_offset()
        applied = self.applied_offset()
        song_dur = float(getattr(self._song, "duration_seconds", 0.0) or 0.0)
        previewing = self.is_preview_session_active()
        lines = [
            f"Draft offset:  {draft:+.3f} s",
            f"Applied:       {applied:+.3f} s"
            + ("  (dirty)" if self.is_draft_dirty() else "  (clean)"),
            f"Playback:      {'PREVIEW (ephemeral)' if previewing else 'committed mapping'}",
            f"Song duration: {format_time(song_dur)}",
        ]
        if self._song_anchor is not None:
            lines.append(f"Song anchor:   {format_time(self._song_anchor)}")
            lines.append(
                f"  → maps to media {format_time(song_to_variant_time(self._song_anchor, draft))}"
            )
        else:
            lines.append("Song anchor:   —")
        if self._variant_anchor is not None:
            lines.append(f"Variant anchor:{format_time(self._variant_anchor)}")
            lines.append(
                f"  → maps to song {format_time(variant_to_song_time(self._variant_anchor, draft))}"
            )
        else:
            lines.append("Variant anchor:—")
        if self._song_anchor is None or self._variant_anchor is None:
            lines.append("")
            lines.append("Set both anchors to recompute draft from the pair.")
        self.preview_area.setText("\n".join(lines))

    def _on_preview_session(self) -> None:
        """Start/refresh ephemeral playback mapping with current draft."""
        if self._begin_preview is None:
            self._refresh_preview_panel()
            self._set_status("Preview playback not available in this context")
            return
        try:
            self._begin_preview(self.draft_offset())
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Could not preview ({exc})")
            return
        self._refresh_preview_panel()
        self._set_status(f"Previewing draft {self.draft_offset():+.3f} s")

    def _sync_live_preview(self) -> None:
        """If a preview session is active, push the new draft into PlaybackService."""
        if not self.is_preview_session_active():
            return
        if self._begin_preview is None:
            return
        try:
            self._begin_preview(self.draft_offset())
        except Exception:  # noqa: BLE001
            return

    def _end_preview_session(self) -> None:
        """Restore committed mapping — never touches project / undo."""
        if self._end_preview is None:
            return
        try:
            self._end_preview()
        except Exception:  # noqa: BLE001
            return

    def _on_apply(self) -> None:
        """Commit draft_offset → SongVariant.anchor_offset via undo command."""
        variant = self.selected_variant()
        if variant is None:
            self._set_status("No variant selected")
            return
        new_offset = coerce_anchor_offset(self.draft_offset())
        old_offset = coerce_anchor_offset(variant.anchor_offset)
        if abs(new_offset - old_offset) <= 1e-9:
            self._end_preview_session()
            self._refresh_preview_panel()
            self._set_status("Draft already matches applied")
            return

        command = SetVariantAnchorOffsetCommand(
            variant_id=variant.id,
            old_offset=old_offset,
            new_offset=new_offset,
        )
        # Commit is the only mutation point — redo applies to the live song.
        command.redo(self._song)
        # End preview so playback uses the newly committed offset (same value).
        self._end_preview_session()
        self._refresh_applied_label()
        self._refresh_preview_panel()
        self._set_status(f"Applied {new_offset:+.3f} s")
        self.shell_status.setStyleSheet("color: #3fb950;")
        self.offset_committed.emit(command)
        # Keep dialog open so the user can refine (UX §19).

    def reject(self) -> None:
        """Discard draft; end preview; no SongVariant write."""
        if not self._confirm_discard_draft():
            return
        self._end_preview_session()
        super().reject()

    def _confirm_discard_draft(self) -> bool:
        if not self.is_draft_dirty():
            return True
        reply = QMessageBox.question(
            self,
            "Align Anchors",
            "Discard draft offset? Applied offset will not change.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    # --- shortcuts (§19.5) ---------------------------------------------------

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence(Qt.Key.Key_Return), self, activated=self._on_preview_session)
        QShortcut(QKeySequence(Qt.Key.Key_Enter), self, activated=self._on_preview_session)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._on_apply)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._on_apply)
        QShortcut(
            QKeySequence("["),
            self,
            activated=lambda: self._nudge_draft(-self._frame_seconds()),
        )
        QShortcut(
            QKeySequence("]"),
            self,
            activated=lambda: self._nudge_draft(self._frame_seconds()),
        )
        QShortcut(
            QKeySequence("Shift+["),
            self,
            activated=lambda: self._nudge_draft(-10.0 * self._frame_seconds()),
        )
        QShortcut(
            QKeySequence("Shift+]"),
            self,
            activated=lambda: self._nudge_draft(10.0 * self._frame_seconds()),
        )
        QShortcut(QKeySequence("A"), self, activated=self._capture_song_playhead)
        QShortcut(QKeySequence("Shift+A"), self, activated=self._capture_media_playhead)


def _finite(value: float) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
