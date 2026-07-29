"""Output timecode clock under the seconds display."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioOutputSettings, Project
from cueplayer.persistence.project_store import project_from_dict, project_to_dict
from cueplayer.playback.audio_engine import AudioEngine
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel
from cueplayer.ui.mark_display_dialog import MarkDisplayDialog
from cueplayer.ui.output_quick_toggles import OutputQuickToggles


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_output_timecode_clock_prefs_persist() -> None:
    project = Project.create("TC Clock")
    project.show_output_timecode_clock = False
    project.output_timecode_clock_color = "#ff00aa"
    restored = project_from_dict(project_to_dict(project))
    assert restored.show_output_timecode_clock is False
    assert restored.output_timecode_clock_color.lower() == "#ff00aa"


def test_monitor_configure_output_timecode_clock(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.configure_output_timecode_clock(visible=False, color="#aabbcc")
    assert panel.show_output_timecode_clock is False
    assert not panel._tc_output_block.isVisible()  # noqa: SLF001

    panel.configure_output_timecode_clock(visible=True, color="#112233")
    assert panel.show_output_timecode_clock is True
    assert panel._tc_clock_color.lower() == "#112233"  # noqa: SLF001


def test_monitor_set_output_timecode_sending_vs_idle(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.configure_output_timecode_clock(visible=True, color="#3dd68c")
    panel.set_output_timecode(
        timecode="01:00:05:12",
        outputs=("LTC", "MTC"),
        sending=True,
    )
    assert panel.tc_output_status.text() == "LTC · MTC"
    assert panel.tc_output_value.text() == "01:00:05:12"
    assert "#3dd68c" in panel.tc_output_value.styleSheet().lower()

    panel.set_output_timecode(
        timecode="01:00:05:12",
        outputs=("LTC",),
        sending=False,
    )
    assert "#71717a" in panel.tc_output_status.styleSheet().lower()
    assert "#a1a1aa" in panel.tc_output_value.styleSheet().lower()


def test_monitor_tc_off_state(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.set_output_timecode(timecode="—", outputs=(), sending=False)
    assert panel.tc_output_status.text() == "TC off"
    assert panel.tc_output_value.text() == "—"


def test_output_quick_toggles_reflect_settings(app: QApplication) -> None:
    toggles = OutputQuickToggles()
    settings = AudioOutputSettings(
        midi_enabled=True,
        mtc_enabled=True,
        ltc_to_mtc_translate=True,
        ltc_enabled=False,
        midi_cue_notes_enabled=True,
    )
    toggles.apply_settings(settings)
    assert toggles._translate.isChecked()  # noqa: SLF001
    assert toggles._note.isChecked()  # noqa: SLF001
    assert toggles._mtc.isChecked()  # noqa: SLF001
    assert not toggles._ltc.isChecked()  # noqa: SLF001


def test_output_quick_toggles_prefs_persist() -> None:
    project = Project.create("TC Clock")
    project.show_output_quick_toggles = False
    restored = project_from_dict(project_to_dict(project))
    assert restored.show_output_quick_toggles is False


def test_monitor_output_quick_toggles_visibility(app: QApplication) -> None:
    panel = CueMonitorPanel()
    panel.show()
    app.processEvents()
    panel.configure_output_quick_toggles(visible=False)
    assert panel.show_output_quick_toggles is False
    assert not panel.output_quick_toggles.isVisible()
    panel.configure_output_quick_toggles(visible=True)
    assert panel.show_output_quick_toggles is True
    assert panel.output_quick_toggles.isVisible()


def test_display_dialog_tc_clock_settings_apply_live(app: QApplication) -> None:
    project = Project.create("TC Clock")
    dialog = MarkDisplayDialog(project.songs[0], project=project)
    dialog.tc_clock_box.setChecked(False)
    dialog.output_toggles_box.setChecked(False)
    dialog.tc_clock_color._on_chosen("#445566")
    assert project.show_output_timecode_clock is False
    assert project.show_output_quick_toggles is False
    assert project.output_timecode_clock_color.lower() == "#445566"
    dialog.close()


def test_engine_output_timecode_state_ltc_only() -> None:
    engine = AudioEngine()
    engine.set_song_timebase("01:00:00:00", 30.0)
    engine.apply_audio_settings(
        AudioOutputSettings(ltc_enabled=True, mtc_enabled=False)
    )
    state = engine.output_timecode_state(2.5)
    assert state.outputs == ("LTC",)
    assert state.timecode == "01:00:02:15"
    assert state.sending is False

    engine._playing = True  # noqa: SLF001
    state = engine.output_timecode_state(2.5)
    assert state.sending is True


def test_engine_output_timecode_state_off() -> None:
    engine = AudioEngine()
    engine.apply_audio_settings(
        AudioOutputSettings(ltc_enabled=False, mtc_enabled=False)
    )
    state = engine.output_timecode_state(0.0)
    assert state.outputs == ()
    assert state.timecode == "—"
    assert state.sending is False


def test_engine_output_timecode_state_notes_only_no_running_tc() -> None:
    """Cue notes do not send SMPTE — clock shows Notes status but not HH:MM:SS:FF."""
    engine = AudioEngine()
    engine.set_song_timebase("04:00:00:00", 30.0)
    engine.apply_audio_settings(
        AudioOutputSettings(
            midi_enabled=True,
            midi_cue_notes_enabled=True,
            ltc_enabled=False,
            mtc_enabled=False,
        )
    )
    state = engine.output_timecode_state(38.5)
    assert state.outputs == ("Notes",)
    assert state.timecode == "—"
    assert state.sending is False

    engine._playing = True  # noqa: SLF001
    state = engine.output_timecode_state(38.5)
    assert state.outputs == ("Notes",)
    assert state.timecode == "—"
    assert state.sending is True
