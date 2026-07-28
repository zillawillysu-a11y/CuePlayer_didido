"""MIDI cue note edge-detect (Main/Button marks → Note On/Off)."""

from __future__ import annotations

from cueplayer.domain.models import Mark, MarkLane, Song
from cueplayer.playback.midi_cue_notes import MidiCueNotes, default_note_for_lane


class _Capture:
    def __init__(self) -> None:
        self.messages: list[bytes] = []

    def __call__(self, msg) -> None:  # noqa: ANN001
        self.messages.append(bytes(msg.bytes()))


def _song_with_marks() -> Song:
    song = Song.create("MIDI Test")
    song.mark_lanes = [
        MarkLane(
            index=1,
            name="Main",
            lane_type="main",
            cue_id_enabled=True,
            midi_note_enabled=True,
        ),
        MarkLane(
            index=2,
            name="Btn",
            lane_type="top_button",
            midi_note_enabled=True,
        ),
        MarkLane(
            index=3,
            name="Silent",
            lane_type="top_button",
            midi_note_enabled=False,
        ),
    ]
    song.marks = [
        Mark.create(1, 1.0, "m1"),
        Mark.create(2, 2.0, "b1"),
        Mark.create(3, 1.5, "skip"),
    ]
    return song


def test_default_note_for_lane() -> None:
    main = MarkLane(index=1, name="M", lane_type="main")
    btn = MarkLane(index=2, name="B", lane_type="top_button")
    assert default_note_for_lane(main, main_base=36, button_base=48) == 36
    assert default_note_for_lane(btn, main_base=36, button_base=48) == 49


def test_fires_notes_on_crossing_enabled_lanes() -> None:
    cap = _Capture()
    cues = MidiCueNotes()
    cues.set_send_function(cap)
    err = cues.configure(
        enabled=True,
        port_name="",
        channel=1,
        velocity=100,
        main_base_note=36,
        button_base_note=48,
    )
    assert err is None
    song = _song_with_marks()
    cues.set_song(song)
    cues.on_play(0.0)
    cues.update(0.5)
    assert cap.messages == []
    cues.update(1.2)
    # Main at 1.0 → note 36; Silent at 1.5 not yet; Button at 2.0 not yet.
    # Only main fired; silent lane disabled so mark at 1.5 ignored when crossed later.
    assert len(cap.messages) == 2  # Note On + Note Off
    assert cap.messages[0] == bytes((0x90, 36, 100))
    assert cap.messages[1] == bytes((0x80, 36, 0))
    cues.update(2.5)
    # Button lane index 2 → base 48 + 1 = 49; silent mark skipped.
    assert len(cap.messages) == 4
    assert cap.messages[2] == bytes((0x90, 49, 100))
    assert cap.messages[3] == bytes((0x80, 49, 0))


def test_seek_does_not_fire_skipped_marks() -> None:
    cap = _Capture()
    cues = MidiCueNotes()
    cues.set_send_function(cap)
    cues.configure(enabled=True, port_name="", channel=1)
    cues.set_song(_song_with_marks())
    cues.on_play(0.0)
    cues.on_seek(3.0)
    cues.update(3.1)
    assert cap.messages == []


def test_custom_lane_note_override() -> None:
    cap = _Capture()
    cues = MidiCueNotes()
    cues.set_send_function(cap)
    cues.configure(enabled=True, port_name="", channel=2, velocity=64)
    song = Song.create("Override")
    song.mark_lanes = [
        MarkLane(
            index=1,
            name="Main",
            lane_type="main",
            midi_note_enabled=True,
            midi_note=60,
        )
    ]
    song.marks = [Mark.create(1, 0.5, "hit")]
    cues.set_song(song)
    cues.on_play(0.0)
    cues.update(1.0)
    assert cap.messages[0] == bytes((0x91, 60, 64))
