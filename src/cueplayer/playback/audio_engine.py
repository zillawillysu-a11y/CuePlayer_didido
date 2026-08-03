"""Audio playback engine (sample clock) for Timeline UI."""

from __future__ import annotations

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("SD_ENABLE_ASIO", "1")

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, QTimer, Signal

from cueplayer.domain.models import (
    AudioOutputSettings,
    Song,
    clamp_output_channels,
    coerce_file_ltc_side,
    default_ltc_channels_for_device,
)
from cueplayer.media.ltc_detect import detect_ltc_channel
from cueplayer.playback.devices import (
    find_output_device,
    iter_output_samplerate_candidates,
    list_output_devices,
    probe_supported_output_channels,
    required_output_channels,
    resolve_output_endpoint_for_channels,
    resolve_output_hostapi,
    resolve_output_samplerate,
    upgrade_device_for_channels,
)
from cueplayer.playback.routing_parse import (
    SRC_FILE_LTC,
    SRC_FILE_MUSIC,
    SRC_LTC_BUS,
    SRC_MUSIC_L,
    SRC_MUSIC_R,
    build_stereo_route_map,
    exclusive_ltc_route,
    is_ltc_route,
    is_music_source_route,
    ltc_output_channels_from_settings,
    parse_stereo_route,
    speaker_channels_without_ltc,
)
from cueplayer.playback.mtc_output import MtcOutput
from cueplayer.playback.midi_cue_notes import MidiCueNotes
from cueplayer.playback.resample import resample_hold_segment, resample_linear
from cueplayer.playback.video_audio_mixer import VideoAudioMixer
from cueplayer.routing.matrix import apply_routing, warn_if_outputs_insufficient
from cueplayer.timecode.ltc import LtcPlaybackCursor, generate_ltc_pcm
from cueplayer.timecode.ltc_decode import decode_ltc_timecode
from cueplayer.timecode.smpte import Timecode, parse_timecode


@dataclass(frozen=True, slots=True)
class OutputTimecodeState:
    """LTC/MTC output status for the monitor timecode clock."""

    timecode: str
    outputs: tuple[str, ...]
    sending: bool


class AudioEngine(QObject):
    """
    Plays a loaded AudioBuffer and reports playhead from sample position.

    sync_offset_seconds is the single calibration knob:
      audible / UI / mark time = write-head − sync_offset
    Run Sync Calibration (hear click → tap) to measure it on this machine.

    Master volume applies to music (and calib clicks) only — never to LTC.
    """

    position_changed = Signal(float)
    playing_changed = Signal(bool)
    timecode_status_changed = Signal()  # LTC/MTC toggles / warnings

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._buffer: AudioBuffer | None = None
        self._position_frame = 0
        self._duration_seconds = 60.0
        self._playing = False
        self._scrubbing = False
        self._resume_after_scrub = False
        self._lock = threading.Lock()
        self._stream: sd.OutputStream | None = None
        # Total monitoring offset (seconds). Prefer calibration over guessing.
        self.sync_offset_seconds = 0.0
        self.loop_a: float | None = None
        self.loop_b: float | None = None
        self.loop_enabled = False
        # When False, play/seek outside A–B freely; wrap only after entering the region.
        self._loop_engage = False
        self._calib_click_frames: list[int] = []
        self._click_waveform: np.ndarray | None = None
        self._mute_music = False
        self._volume = 1.0  # 0.0 … 1.0 master gain (music + video clip audio)
        # Dedicated music-bed gain for Video/Music alignment balancing —
        # stacks with master volume but never touches video clip audio or
        # LTC (see Song.music_volume / _music_chunk / _video_chunk).
        self._music_volume = 1.0
        self._audio_gain_db = 0.0
        self._song: Song | None = None
        self._video_mixer = VideoAudioMixer()
        self._ltc_mirror_last_pos = -1e9
        self._ltc_mirror_last_ok = False
        self._audio_settings = AudioOutputSettings()
        self._ltc_pcm: np.ndarray | None = None
        self._ltc_cache_key: tuple | None = None
        self._ltc_cache_future = None
        self._ltc_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ltc-cache")
        self._ltc_cursor = LtcPlaybackCursor(48000, 30.0, "01:00:00:00")
        self._detected_ltc_channel: int | None = None
        self._ltc_detect_ran = False
        self._cached_music_indices: tuple[int, int] = (0, 1)
        self._cached_file_ltc_idx: int | None = None
        self._song_start_tc = "01:00:00:00"
        self._song_fps = 30.0
        self._output_channel_count = 2
        self._device_index: int | None = None
        self._route: dict[int, list[int]] = {0: [0], 1: [1]}
        self._routing_warning: str | None = None
        # The rate we actually open the stream at (device-compatible; may
        # differ from the loaded media's native rate). All frame bookkeeping
        # (position, LTC, calibration clicks) runs in this rate. See
        # _resolve_device_and_route() / _playback_source().
        self._playback_rate = 48000
        self._playback_samples: np.ndarray | None = None
        self._playback_cache_key: tuple | None = None
        self._playback_resample_future = None
        self._resample_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio-resample")
        self._ltc_detect_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ltc-detect")
        self._buffer_setup_token = 0
        self._resume_play_after_buffer = False
        self._active_stream_token: tuple | None = None
        self._mtc = MtcOutput()
        self._midi_cues = MidiCueNotes()
        self._poll = QTimer(self)
        self._poll.setInterval(16)
        self._poll.timeout.connect(self._emit_position)
        self._silent_timer = QTimer(self)
        self._silent_timer.setInterval(16)
        self._silent_timer.timeout.connect(self._silent_tick)
        self._mtc_timer = QTimer(self)
        self._mtc_timer.setInterval(4)
        self._mtc_timer.timeout.connect(self._mtc_tick)

    @property
    def buffer(self) -> AudioBuffer | None:
        return self._buffer

    @property
    def audio_settings(self) -> AudioOutputSettings:
        return self._audio_settings

    @property
    def ltc_enabled(self) -> bool:
        return bool(self._audio_settings.ltc_enabled)

    @property
    def mtc_enabled(self) -> bool:
        return bool(self._audio_settings.effective_mtc_output())

    @property
    def midi_enabled(self) -> bool:
        return bool(self._audio_settings.midi_enabled)

    def output_timecode_state(
        self, position_seconds: float | None = None
    ) -> OutputTimecodeState:
        """Timecode the engine would output at ``position_seconds`` (default: playhead)."""
        from cueplayer.timecode.mtc import absolute_timecode

        pos = self.position if position_seconds is None else float(position_seconds)
        outputs: list[str] = []
        if self.ltc_enabled:
            outputs.append("LTC")
        s = self._audio_settings
        translate_active = (
            s.midi_enabled
            and not s.ltc_enabled
            and s.effective_ltc_to_mtc_translate()
            and s.ltc_source != "generator"
        )
        if s.midi_enabled and s.mtc_enabled:
            outputs.append("LTC → MTC" if translate_active else "MTC")
        elif translate_active:
            outputs.append("LTC → MTC")
        if s.effective_midi_cue_notes():
            outputs.append("Notes")

        tc_str = "—"
        tc_active = (
            self.ltc_enabled
            or (s.midi_enabled and s.mtc_enabled)
            or translate_active
        )
        if tc_active:
            # When LTC source is from-file, the actual timecode numbers come from
            # decoding the stripe — regardless of whether LTC output is enabled.
            # MTC mirrors the same source, so show file-decoded TC when available.
            decode_ch = self._decode_source_channel()
            decoded = self._decode_file_ltc_timecode(pos) if decode_ch is not None else None
            if decoded is not None:
                tc_str = decoded.format()
            elif self.mtc_enabled:
                tc_str = self._mtc.timecode_at(pos).format()
            else:
                start = parse_timecode(self._song_start_tc) or Timecode(1, 0, 0, 0)
                tc_str = absolute_timecode(start, pos, self._song_fps).format()

        sending = bool(self._playing and outputs)
        return OutputTimecodeState(
            timecode=tc_str,
            outputs=tuple(outputs),
            sending=sending,
        )

    @property
    def detected_ltc_channel(self) -> int | None:
        """0=left, 1=right when auto-detect finds striped LTC in the loaded file."""
        return self._detected_ltc_channel

    @property
    def ltc_source_mode(self) -> str:
        return str(self._audio_settings.ltc_source)

    def _song_file_ltc_channel(self) -> int | None:
        """Per-song override: which file channel feeds the project LTC bus."""
        song = self._song
        if song is None:
            return None
        side = coerce_file_ltc_side(getattr(song, "file_ltc_side", "auto"))
        if side == "off":
            return None
        if side == "left":
            return 0
        if side == "right":
            return 1
        # auto — prefer live detection, else run detect once
        if self._detected_ltc_channel is not None:
            return int(self._detected_ltc_channel)
        return self._autodetect_ltc_channel()

    def _song_uses_file_ltc(self) -> bool:
        return self._song_file_ltc_channel() is not None

    def _uses_generated_ltc(self) -> bool:
        if self._song_uses_file_ltc():
            return False
        return bool(
            self._audio_settings.ltc_enabled
            and self._audio_settings.ltc_source == "generator"
            and self._audio_settings.ltc_generator_enabled
        )

    def _autodetect_ltc_channel(self) -> int | None:
        if self._ltc_detect_ran:
            return self._detected_ltc_channel
        self._ltc_detect_ran = True
        buf = self._buffer
        if buf is not None and buf.samples.ndim == 2 and buf.samples.shape[1] >= 2:
            self._detected_ltc_channel = detect_ltc_channel(
                buf.samples, int(buf.sample_rate)
            )
        else:
            self._detected_ltc_channel = None
        return self._detected_ltc_channel

    def _is_ltc_file_channel(self, channel: int) -> bool:
        ch = self._file_ltc_channel()
        if ch is not None and ch == channel:
            return True
        eff = self._effective_ltc_source_channel()
        return eff is not None and eff == channel

    def _file_ltc_channel(self) -> int | None:
        """Loaded-file channel carrying striped LTC (for bus or L/R leg routing)."""
        song_ch = self._song_file_ltc_channel()
        if song_ch is not None:
            return song_ch if self._audio_settings.ltc_enabled else None
        s = self._audio_settings
        uses_ltc_leg = is_ltc_route(s.music_l_route) or is_ltc_route(s.music_r_route)
        uses_file_bus = bool(s.ltc_enabled and s.ltc_source != "generator")
        if not uses_ltc_leg and not uses_file_bus:
            return None
        return self._resolved_file_ltc_channel(require_settings=True)

    def _resolved_file_ltc_channel(self, *, require_settings: bool = False) -> int | None:
        """Which loaded-file channel carries striped LTC (0=L, 1=R)."""
        song_ch = self._song_file_ltc_channel()
        if song_ch is not None:
            if require_settings and not self._audio_settings.ltc_enabled:
                return None
            return song_ch
        s = self._audio_settings
        if require_settings:
            uses_ltc_leg = is_ltc_route(s.music_l_route) or is_ltc_route(s.music_r_route)
            uses_file_bus = bool(s.ltc_enabled and s.ltc_source != "generator")
            if not uses_ltc_leg and not uses_file_bus:
                return None
        mode = s.ltc_source
        if mode == "generator":
            # Generated LTC uses the dedicated bus — both file channels are music.
            return None
        if mode == "source_left":
            return 0
        if mode == "source_right":
            return 1
        if mode == "auto":
            if self._detected_ltc_channel is not None:
                return self._detected_ltc_channel
            return self._autodetect_ltc_channel()
        return None

    def _effective_ltc_source_channel(self) -> int | None:
        """Source file channel for the dedicated LTC output bus."""
        if not self._audio_settings.ltc_enabled:
            return None
        song_ch = self._song_file_ltc_channel()
        if song_ch is not None:
            return song_ch
        if self._audio_settings.ltc_source == "generator":
            return None
        return self._file_ltc_channel()

    def _decode_source_channel(self) -> int | None:
        """File channel to decode timecode from for MTC/display purposes.

        Returns a channel only when translation is actually wanted:
        - LTC output enabled with a from-file source, OR
        - TRANS + MTC are both on (mirror file LTC into MTC without LTC output).
        Generator source always returns None.
        """
        s = self._audio_settings
        if s.ltc_source == "generator":
            return None
        if not s.ltc_enabled and not s.effective_ltc_to_mtc_translate():
            return None
        return self._resolved_file_ltc_channel(require_settings=False)

    def _decode_file_ltc_timecode(self, position_seconds: float) -> Timecode | None:
        """
        Read HH:MM:SS:FF from striped file LTC at the playhead.

        Used so MTC can mirror the same numbers as the incoming LTC audio.
        Returns None for generator-only LTC or when decode fails.
        """
        ch = self._decode_source_channel()
        if ch is None or self._buffer is None:
            return None
        sr = int(self._sample_rate())
        fps = float(self._song_fps) if self._song_fps > 0 else 30.0
        frame_len = max(160, int(round(sr / fps)))
        window = frame_len * 4
        center = max(0, int(round(max(0.0, float(position_seconds)) * sr)))
        start = max(0, center - frame_len // 2)
        # Decode from the raw file channel (no LTC output gain).
        pcm = self._source_channel_chunk(ch, start, window)
        return decode_ltc_timecode(pcm, sr, fps)

    def _sync_mtc_to_file_ltc(
        self, position_seconds: float, *, force: bool = False
    ) -> None:
        """When file LTC is active, lock MTC origin to the decoded stripe TC."""
        if not self._audio_settings.effective_mtc_output():
            return
        if self._decode_source_channel() is None:
            return
        # Re-decode about twice per second (or on play/seek). QF pacing still
        # runs every timer tick from the mirrored origin.
        if (
            not force
            and abs(float(position_seconds) - self._ltc_mirror_last_pos) < 0.45
        ):
            return
        decoded = self._decode_file_ltc_timecode(position_seconds)
        self._ltc_mirror_last_pos = float(position_seconds)
        if decoded is not None:
            self._mtc.set_mirror_origin(decoded, position_seconds)
            self._ltc_mirror_last_ok = True
        else:
            self._ltc_mirror_last_ok = False

    def _music_source_indices(self) -> tuple[int, int]:
        """Which loaded-file channels feed the music L/R bus (mono duplicates when needed)."""
        samples = self._playback_samples
        if samples is None:
            return 0, 1
        ch_count = int(samples.shape[1]) if samples.ndim == 2 else 1
        if ch_count <= 1:
            return 0, 0
        strip_ltc = (
            self._song_uses_file_ltc()
            or is_music_source_route(self._audio_settings.music_l_route)
            or is_music_source_route(self._audio_settings.music_r_route)
            or is_ltc_route(self._audio_settings.music_l_route)
            or is_ltc_route(self._audio_settings.music_r_route)
            or self._resolved_file_ltc_channel() is not None
        )
        if not strip_ltc:
            return 0, 1
        ltc_ch = self._resolved_file_ltc_channel()
        if ltc_ch is None and strip_ltc and self._audio_settings.ltc_source != "generator":
            ltc_ch = self._autodetect_ltc_channel()
        if ltc_ch is not None:
            music_chs = [i for i in range(ch_count) if i != ltc_ch]
            if len(music_chs) >= 2:
                return music_chs[0], music_chs[1]
            if len(music_chs) == 1:
                return music_chs[0], music_chs[0]
        return 0, 1

    @property
    def routing_warning(self) -> str | None:
        return self._routing_warning

    @property
    def monitoring_latency_extra(self) -> float:
        return self.sync_offset_seconds

    @monitoring_latency_extra.setter
    def monitoring_latency_extra(self, value: float) -> None:
        self.sync_offset_seconds = float(value)

    @property
    def output_latency_seconds(self) -> float:
        return self.sync_offset_seconds

    @property
    def raw_position(self) -> float:
        """Write-head time (no sync offset). Used for calibration math."""
        return self._frame_to_seconds(self._position_frame)

    @property
    def position(self) -> float:
        """Audible / UI playhead (sync-offset compensated while playing)."""
        raw = self.raw_position
        if self._playing and self._stream is not None and not self._scrubbing:
            return max(0.0, raw - self.sync_offset_seconds)
        return raw

    @property
    def duration(self) -> float:
        if self._buffer is not None:
            return self._buffer.duration_seconds
        return self._duration_seconds

    @property
    def playing(self) -> bool:
        return self._playing

    def set_monitoring_latency_ms(self, ms: float) -> None:
        self.sync_offset_seconds = float(ms) / 1000.0

    def set_sync_offset_ms(self, ms: float) -> None:
        self.sync_offset_seconds = float(ms) / 1000.0

    def sync_offset_ms(self) -> float:
        return self.sync_offset_seconds * 1000.0

    def set_music_muted(self, muted: bool) -> None:
        """Silence the loaded track (clicks / metronome still audible)."""
        with self._lock:
            self._mute_music = bool(muted)

    def set_volume(self, volume: float) -> None:
        """Master music gain (0.0 … 1.0). Does not affect generated LTC."""
        with self._lock:
            self._volume = float(min(1.0, max(0.0, volume)))

    def volume(self) -> float:
        with self._lock:
            return float(self._volume)

    def set_music_volume(self, volume: float) -> None:
        """
        Dedicated music-bed gain for Video/Music alignment balancing (0.0…1.0).
        Independent of Master Volume and per-clip Video volume; never applied
        to LTC (AGENTS.md: Master Vol must not affect LTC gain).
        """
        with self._lock:
            self._music_volume = float(min(1.0, max(0.0, volume)))

    def set_audio_gain_db(self, gain_db: float) -> None:
        """Per-file waveform gain in dB (-12…+12); does not affect LTC."""
        with self._lock:
            self._audio_gain_db = float(max(-12.0, min(12.0, gain_db)))

    def music_volume(self) -> float:
        with self._lock:
            return float(self._music_volume)

    def set_song(self, song: Song | None) -> None:
        """
        Reference used only to look up video clips for audio mixing (see
        `VideoAudioMixer`) — a read-only lookup, not a second playback clock.
        Call whenever the active song changes.
        """
        self._song = song
        self._video_mixer.set_song(song)
        self._video_mixer.set_muted(bool(song.video_track_muted) if song is not None else False)
        self.set_music_volume(float(song.music_volume) if song is not None else 1.0)
        self.set_audio_gain_db(float(song.audio_gain_db) if song is not None else 0.0)
        self._midi_cues.set_song(song)
        self.refresh_video_clips()
        self._refresh_source_routing_cache()

    def set_video_track_muted(self, muted: bool) -> None:
        """Silence every video clip's own embedded audio (picture keeps showing)."""
        self._video_mixer.set_muted(bool(muted))

    def refresh_video_clips(self) -> None:
        """Call after video clips are added / removed / trimmed / re-pathed."""
        clips = list(self._song.video_clips) if self._song is not None else []
        self._video_mixer.preload(clips)

    def set_song_timebase(self, start_timecode: str, fps: float) -> None:
        self._song_start_tc = start_timecode or "01:00:00:00"
        self._song_fps = float(fps) if fps > 0 else 30.0
        self._mtc.set_timebase(self._song_start_tc, self._song_fps)
        self._invalidate_ltc_cache()

    def apply_audio_settings(self, settings: AudioOutputSettings) -> str | None:
        """
        Apply device / routing / LTC / MTC settings. Returns a warning or MTC error.
        Restarts the stream if currently playing.
        """
        was_playing = self._playing
        pos = self.position
        if was_playing:
            self.pause()

        self._routing_warning = None
        self._audio_settings = AudioOutputSettings(
            output_device_name=settings.output_device_name,
            output_device_index=settings.output_device_index,
            output_hostapi=str(settings.output_hostapi or ""),
            music_l_route=str(settings.music_l_route or "1"),
            music_r_route=str(settings.music_r_route or "2"),
            music_left_channels=list(settings.music_left_channels),
            music_right_channels=list(settings.music_right_channels),
            ltc_enabled=bool(settings.ltc_enabled),
            ltc_source=str(settings.ltc_source),
            ltc_generator_enabled=bool(settings.ltc_generator_enabled),
            ltc_gain=float(min(1.5, max(0.0, settings.ltc_gain))),
            ltc_channels=list(settings.ltc_channels),
            ltc_to_mtc_translate=bool(getattr(settings, "ltc_to_mtc_translate", False)),
            midi_enabled=bool(getattr(settings, "midi_enabled", False)),
            mtc_enabled=bool(settings.mtc_enabled),
            midi_port_name=settings.midi_port_name,
            midi_cue_notes_enabled=bool(getattr(settings, "midi_cue_notes_enabled", False)),
            midi_cue_channel=int(getattr(settings, "midi_cue_channel", 1) or 1),
            midi_cue_velocity=int(getattr(settings, "midi_cue_velocity", 100) or 100),
            midi_main_base_note=int(getattr(settings, "midi_main_base_note", 36) or 36),
            midi_button_base_note=int(getattr(settings, "midi_button_base_note", 48) or 48),
            output_channel_modes=list(getattr(settings, "output_channel_modes", []) or []),
        )
        self._resolve_device_and_route()
        if self._uses_generated_ltc():
            self._ensure_ltc_cache()
        else:
            with self._lock:
                self._ltc_pcm = None
                self._ltc_cache_key = None
        if not self._audio_settings.ltc_enabled:
            with self._lock:
                self._ltc_pcm = None
                self._ltc_cache_key = None

        # When switching away from generator source, allow auto-detect to re-run.
        if self._audio_settings.ltc_source != "generator":
            self._ltc_detect_ran = False

        self._refresh_source_routing_cache()

        mtc_err = self._mtc.configure(
            midi_master=bool(self._audio_settings.midi_enabled),
            enabled=bool(self._audio_settings.effective_mtc_output()),
            port_name=self._audio_settings.midi_port_name,
            start_timecode=self._song_start_tc,
            fps=self._song_fps,
        )
        # Share the MTC port for cue notes whenever MIDI is on.
        share_midi_port = bool(
            self._audio_settings.midi_enabled
            and (self._audio_settings.midi_port_name or "").strip()
        )
        self._midi_cues.set_send_function(
            self._mtc.send_message if share_midi_port else None
        )
        cue_err = self._midi_cues.configure(
            enabled=bool(self._audio_settings.effective_midi_cue_notes()),
            port_name=self._audio_settings.midi_port_name,
            channel=int(self._audio_settings.midi_cue_channel),
            velocity=int(self._audio_settings.midi_cue_velocity),
            main_base_note=int(self._audio_settings.midi_main_base_note),
            button_base_note=int(self._audio_settings.midi_button_base_note),
        )
        if self._song is not None:
            self._midi_cues.set_song(self._song)
        self.timecode_status_changed.emit()

        if was_playing:
            self.seek(pos)
            self.play()
        else:
            self._rebuild_output_stream()
        warning = self._routing_warning
        if (
            self._audio_settings.ltc_enabled
            and self._audio_settings.ltc_source == "auto"
            and self._effective_ltc_source_channel() is None
            and self._buffer is not None
            and self._buffer.channels >= 2
        ):
            auto_warn = (
                "Could not auto-detect LTC in the loaded file — "
                "choose Left or Right manually to avoid LTC on Music CH1–2."
            )
            warning = f"{warning} {auto_warn}" if warning else auto_warn
        for err in (mtc_err, cue_err):
            if err:
                warning = f"{warning} {err}" if warning else err
        return warning

    def clear_calibration_clicks(self) -> None:
        with self._lock:
            self._calib_click_frames = []

    def schedule_calibration_clicks(self, times_seconds: list[float]) -> None:
        sr = self._sample_rate()
        ch = 2
        frames = sorted({max(0, int(round(t * sr))) for t in times_seconds})
        with self._lock:
            self._calib_click_frames = frames
            self._click_waveform = self._make_click(sr, ch)

    def _make_click(self, sample_rate: int, channels: int) -> np.ndarray:
        n = max(32, int(sample_rate * 0.012))
        t = np.arange(n, dtype=np.float32) / float(sample_rate)
        wave = 0.9 * np.sin(2 * np.pi * 1500.0 * t) * np.exp(-t * 80.0)
        return np.repeat(wave[:, None], max(1, channels), axis=1).astype(np.float32)

    def set_loop_points(self, a: float | None, b: float | None) -> None:
        self.loop_a = a
        self.loop_b = b
        if self.loop_enabled:
            self.engage_ab_loop()
        else:
            self._refresh_loop_engage()

    def set_loop_enabled(self, enabled: bool) -> None:
        self.loop_enabled = bool(enabled)
        if self.loop_enabled:
            self.engage_ab_loop()
        else:
            with self._lock:
                self._loop_engage = False

    def engage_ab_loop(self, *, seek_if_outside: bool = True) -> None:
        """Arm A–B loop.

        When ``seek_if_outside`` is True (Loop checkbox / explicit engage), jump
        to A if the playhead is outside the region. Point placement (tapping A/B)
        must pass ``seek_if_outside=False`` so re-marking never yanks playback.
        """
        bounds = self._loop_bounds()
        if not self.loop_enabled or bounds is None:
            return
        a, b = bounds
        if seek_if_outside:
            pos = self._raw_seconds()
            if pos > b + 1e-4 or pos < a - 1e-4:
                self.seek(a)
        with self._lock:
            self._loop_engage = True

    def clear_loop(self) -> None:
        self.loop_a = None
        self.loop_b = None
        self.loop_enabled = False
        self._loop_engage = False

    def _loop_bounds(self) -> tuple[float, float] | None:
        if self.loop_a is None or self.loop_b is None:
            return None
        a, b = float(self.loop_a), float(self.loop_b)
        if abs(b - a) < 0.01:
            return None
        return (min(a, b), max(a, b))

    def _sample_rate(self) -> int:
        """
        Rate used for all frame bookkeeping (position/LTC/clicks) and for
        opening the output stream. Resolved against the selected device in
        _resolve_device_and_route(); may differ from the media file's
        native rate if the device doesn't support it (see _playback_rate).
        """
        return int(self._playback_rate)

    def _frame_to_seconds(self, frame: int) -> float:
        return frame / float(self._sample_rate())

    def _raw_seconds(self) -> float:
        """Write-head time for loop math (ignore sync-offset UI compensation)."""
        return self._frame_to_seconds(self._position_frame)

    def _refresh_loop_engage(self) -> None:
        """Engage only while the write-head is inside A–B; seek outside clears it."""
        bounds = self._loop_bounds()
        if not self.loop_enabled or bounds is None:
            self._loop_engage = False
            return
        a, b = bounds
        pos = self._raw_seconds()
        self._loop_engage = a - 1e-4 <= pos < b - 1e-4

    def _maybe_wrap_loop(self) -> bool:
        bounds = self._loop_bounds()
        if not self.loop_enabled or bounds is None or not self._playing:
            return False
        a, b = bounds
        pos = self._raw_seconds()
        if not self._loop_engage and a - 1e-4 <= pos < b - 1e-4:
            self._loop_engage = True
        if self._loop_engage and pos + 1e-4 >= b:
            self.seek(a)
            return True
        return False

    def set_buffer(self, buffer: AudioBuffer | None) -> None:
        was_playing = self._playing
        if was_playing:
            self.stop()
        else:
            self._position_frame = 0
            self.clear_calibration_clicks()
        self._buffer = buffer
        # Always clear stripe detection — a new buffer must not inherit the
        # previous song's Left/Right LTC result (setlist badge + routing).
        self._detected_ltc_channel = None
        self._ltc_detect_ran = False
        if buffer is not None:
            self._duration_seconds = buffer.duration_seconds
        self._position_frame = 0
        self.clear_calibration_clicks()
        self._invalidate_ltc_cache()
        if buffer is not None and int(buffer.sample_rate) == int(self._playback_rate):
            self._playback_samples = buffer.samples
            self._playback_cache_key = (id(buffer), int(buffer.sample_rate), int(self._playback_rate))
        else:
            self._playback_samples = None
            self._playback_cache_key = None
        self.position_changed.emit(0.0)
        self._resume_play_after_buffer = was_playing and buffer is not None
        self._buffer_setup_token += 1
        token = self._buffer_setup_token
        if buffer is not None:
            QTimer.singleShot(0, lambda t=token: self._complete_buffer_setup(t))
        elif was_playing:
            self._resume_play_after_buffer = False

    def _complete_buffer_setup(self, token: int) -> None:
        """Finish routing / LTC detect / stream prewarm off the setlist click path."""
        if token != self._buffer_setup_token or self._buffer is None:
            return
        if self._uses_generated_ltc():
            self._ensure_ltc_cache()
        self._resolve_device_and_route()
        self._refresh_ltc_detection()
        self._prewarm_output_stream()
        if self._resume_play_after_buffer:
            self._resume_play_after_buffer = False
            self._wait_for_playback_samples()
            self.play()

    def flush_deferred_buffer_setup(self) -> None:
        """Block until the latest deferred buffer routing finishes (tests)."""
        self._complete_buffer_setup(self._buffer_setup_token)
        self._wait_for_playback_samples()
        future = getattr(self, "_playback_resample_future", None)
        if future is not None:
            future.result()

    def ensure_playback_ready(self) -> None:
        """Finish routing/resample so the first Play on a new song is not silent."""
        self._complete_buffer_setup(self._buffer_setup_token)
        self._wait_for_playback_samples()

    def _apply_resampled_pcm(self, built_key: tuple, pcm: np.ndarray) -> None:
        with self._lock:
            if self._playback_cache_key != built_key:
                return
            self._playback_samples = pcm
        self._refresh_source_routing_cache()

    def _wait_for_playback_samples(self) -> None:
        """Block until async rate conversion finishes (music is silent until then)."""
        future = getattr(self, "_playback_resample_future", None)
        if future is None:
            return
        if future.done():
            try:
                built_key, pcm = future.result()
            except Exception:
                return
            self._apply_resampled_pcm(built_key, pcm)
            return
        try:
            built_key, pcm = future.result(timeout=120.0)
        except Exception:
            return
        self._apply_resampled_pcm(built_key, pcm)

    def _needs_output_stream(self) -> bool:
        has_video_audio = self._song is not None and bool(self._song.video_clips)
        return (
            self._buffer is not None
            or self._audio_settings.ltc_enabled
            or has_video_audio
        )

    def _prewarm_output_stream(self) -> None:
        """Open the device stream after load so Play does not hitch on ASIO open."""
        if not self._needs_output_stream():
            return
        if self._uses_generated_ltc():
            self._ensure_ltc_cache()
        try:
            self._ensure_stream()
        except Exception:
            # Song switches defer prewarm; a missing/test device must not block load.
            pass

    def _rebuild_output_stream(self) -> None:
        """Apply new routing/device settings to the open PortAudio stream."""
        self._stop_stream()
        if self._needs_output_stream():
            self._prewarm_output_stream()

    def set_duration(self, seconds: float) -> None:
        if self._buffer is not None:
            return
        self._duration_seconds = max(1.0, seconds)
        self._invalidate_ltc_cache()
        if self.position > self._duration_seconds:
            self.seek(self._duration_seconds)

    def play(self) -> None:
        # Request 1ms Windows timer resolution to reduce MIDI/Qt timer jitter.
        try:
            from cueplayer.playback.winmm_midi import request_timer_resolution
            request_timer_resolution()
        except Exception:  # noqa: BLE001
            pass
        # Do not snap into A–B; allow previewing outside while keeping loop marks.
        self._refresh_loop_engage()
        if self.position >= self.duration - 1e-4:
            self.seek(0.0)
        self._scrubbing = False
        self._wait_for_playback_samples()
        # A real output stream is required whenever anything could be audible:
        # loaded music, LTC, or a video clip with its own embedded audio.
        # Without this, a video-only song (no music track loaded yet) fell
        # back to the silent bookkeeping timer and its clips' audio was never
        # actually rendered — this was the root cause of "no video audio".
        has_video_audio = self._song is not None and bool(self._song.video_clips)
        needs_stream = self._needs_output_stream()
        if needs_stream:
            if self._uses_generated_ltc():
                self._ensure_ltc_cache()
            if not self._ensure_stream():
                self._playing = False
                self._silent_timer.stop()
                self._poll.stop()
                self._mtc_timer.stop()
                self._mtc.on_pause()
                self._midi_cues.on_pause()
                self.playing_changed.emit(False)
                self.timecode_status_changed.emit()
                self._emit_position()
                return
            self._wait_for_playback_samples()
            self._playing = True
            self._poll.start()
            self._silent_timer.stop()
        else:
            self._playing = True
            self._stop_stream()
            self._silent_timer.start()
            self._poll.stop()
        self._sync_mtc_to_file_ltc(self.raw_position, force=True)
        self._mtc.on_play(self.raw_position)
        self._midi_cues.on_play(self.position)
        if self._audio_settings.effective_mtc_output() or self._audio_settings.effective_midi_cue_notes():
            self._mtc_timer.start()
        self.playing_changed.emit(True)

    def pause(self, *, for_scrub: bool = False) -> None:
        has_video_audio = self._song is not None and bool(self._song.video_clips)
        has_source_ltc = self._effective_ltc_source_channel() is not None
        if (
            not for_scrub
            and (
                self._buffer is not None
                or self._ltc_pcm is not None
                or has_source_ltc
                or has_video_audio
            )
            and self._stream is not None
        ):
            lat = self.sync_offset_seconds
            if lat > 0:
                lat_frames = int(lat * self._sample_rate())
                with self._lock:
                    self._position_frame = max(0, self._position_frame - lat_frames)
        self._playing = False
        self._silent_timer.stop()
        self._poll.stop()
        self._mtc_timer.stop()
        self._mtc.on_pause()
        self._midi_cues.on_pause()
        if not for_scrub:
            self.playing_changed.emit(False)
            try:
                from cueplayer.playback.winmm_midi import release_timer_resolution
                release_timer_resolution()
            except Exception:  # noqa: BLE001
                pass
        self._emit_position()

    def stop(self) -> None:
        self._resume_after_scrub = False
        self._scrubbing = False
        self.clear_calibration_clicks()
        self.pause()
        self.seek(0.0)

    def toggle(self) -> None:
        if self._playing or (self._scrubbing and self._resume_after_scrub):
            self._resume_after_scrub = False
            self._scrubbing = False
            self.pause()
        else:
            self.play()

    def begin_scrub(self) -> None:
        if self._scrubbing:
            return
        self._scrubbing = True
        self._resume_after_scrub = self._playing
        if self._playing:
            self.pause(for_scrub=True)

    def end_scrub(self) -> None:
        if not self._scrubbing:
            return
        self._scrubbing = False
        # Land MTC / file-LTC mirror on the exact release position once.
        self._sync_mtc_to_file_ltc(self.raw_position, force=True)
        if self._resume_after_scrub:
            self._resume_after_scrub = False
            self.play()
        else:
            self._emit_position()

    def seek(self, seconds: float) -> None:
        seconds = min(max(0.0, seconds), self.duration)
        sr = self._sample_rate()
        with self._lock:
            self._position_frame = int(seconds * sr)
            # Update under lock so the audio callback cannot wrap to A
            # after a seek that intentionally left the A–B region.
            self._refresh_loop_engage()
        self._sync_mtc_to_file_ltc(seconds, force=not self._scrubbing)
        self._mtc.on_seek(seconds, playing=self._playing)
        self._midi_cues.on_seek(self.position)
        self.position_changed.emit(self.position)

    def nudge(self, delta_seconds: float) -> None:
        self.seek(self.position + delta_seconds)

    def shutdown_midi_outputs(self) -> None:
        """Release MTC / MIDI cue note ports (call on app exit)."""
        self._mtc_timer.stop()
        self._mtc.close()
        self._midi_cues.close()

    def _mtc_tick(self) -> None:
        if self._playing:
            pos = self.raw_position
            self._sync_mtc_to_file_ltc(pos)
            self._mtc.tick(pos)
            self._midi_cues.update(pos)

    def _emit_position(self) -> None:
        if self._maybe_wrap_loop():
            return
        pos = self.position
        self.position_changed.emit(pos)
        with self._lock:
            # `_position_frame` is bookkept in playback-rate frames (see
            # `_sample_rate()` docstring), so EOF must compare against the
            # resampled buffer length (`_playback_samples`, same rate) —
            # never `self._buffer.frames`, which is native-rate and would
            # make playback stop early whenever native != playback rate
            # (e.g. 44.1kHz media on a 48kHz-locked device).
            if self._playback_samples is not None:
                end_frame = self._playback_samples.shape[0]
            elif self._buffer is not None:
                end_frame = self._playback_end_frame()
            else:
                end_frame = int(self._duration_seconds * self._sample_rate())
            at_end = self._position_frame >= end_frame
        # The stream callback may clear `_playing` before this poll tick runs;
        # still call `pause()` so transport UI and MTC stop cleanly.
        if at_end and (self._playing or self._poll.isActive()):
            self.pause()

    def _silent_tick(self) -> None:
        with self._lock:
            self._position_frame += int(0.016 * self._sample_rate())
            pos = self._frame_to_seconds(self._position_frame)
        bounds = self._loop_bounds()
        if self.loop_enabled and bounds is not None:
            a, b = bounds
            if not self._loop_engage and a - 1e-4 <= pos < b - 1e-4:
                self._loop_engage = True
            if self._loop_engage and pos >= b:
                self.seek(a)
                return
        if pos >= self._duration_seconds:
            self.seek(self._duration_seconds)
            self.pause()
            return
        self.position_changed.emit(pos)

    def _mix_clicks(self, music: np.ndarray, start: int) -> None:
        click = self._click_waveform
        if click is None or not self._calib_click_frames:
            return
        frames = music.shape[0]
        end = start + frames
        remaining: list[int] = []
        for cf in self._calib_click_frames:
            if cf >= end:
                remaining.append(cf)
                continue
            if cf + click.shape[0] <= start:
                continue
            src0 = max(0, start - cf)
            dst0 = max(0, cf - start)
            n = min(click.shape[0] - src0, frames - dst0)
            if n > 0:
                ch = min(music.shape[1], click.shape[1])
                music[dst0 : dst0 + n, :ch] += click[src0 : src0 + n, :ch]
                np.clip(music[dst0 : dst0 + n], -1.0, 1.0, out=music[dst0 : dst0 + n])
            if cf + click.shape[0] > end:
                remaining.append(cf)
        self._calib_click_frames = remaining

    def _invalidate_ltc_cache(self) -> None:
        self._ltc_cache_future = None
        with self._lock:
            self._ltc_pcm = None
            self._ltc_cache_key = None
            self._ltc_cursor.reset()

    def _sync_ltc_cursor(self) -> None:
        self._ltc_cursor.configure(
            sample_rate=self._sample_rate(),
            fps=self._song_fps,
            start_timecode=self._song_start_tc,
            amplitude=1.0,
        )

    def _ensure_ltc_cache(self) -> None:
        if not self._uses_generated_ltc():
            return
        sr = self._sample_rate()
        dur = self.duration
        key = (sr, round(dur, 6), self._song_start_tc, round(self._song_fps, 4))
        with self._lock:
            if self._ltc_cache_key == key and self._ltc_pcm is not None:
                return
        if self._ltc_cache_future is not None and not self._ltc_cache_future.done():
            return

        def _build() -> tuple[tuple, np.ndarray]:
            try:
                pcm = generate_ltc_pcm(
                    dur,
                    sr,
                    self._song_start_tc,
                    self._song_fps,
                    amplitude=1.0,
                )
            except ValueError:
                pcm = np.zeros(max(1, int(dur * sr)), dtype=np.float32)
            return key, pcm

        future = self._ltc_executor.submit(_build)
        self._ltc_cache_future = future

        def _done(fut) -> None:
            try:
                built_key, pcm = fut.result()
            except Exception:
                return
            with self._lock:
                if not self._uses_generated_ltc():
                    return
                cur_key = (
                    self._sample_rate(),
                    round(self.duration, 6),
                    self._song_start_tc,
                    round(self._song_fps, 4),
                )
                if cur_key == built_key:
                    self._ltc_pcm = pcm
                    self._ltc_cache_key = built_key

        future.add_done_callback(_done)

    def _ltc_bus_active(self, *, max_ch: int | None = None) -> bool:
        s = self._audio_settings
        if not s.ltc_enabled:
            return False
        ch = max_ch if max_ch is not None else max(1, int(self._output_channel_count or 2))
        if ltc_output_channels_from_settings(s, max_ch=ch):
            return True
        # Legacy 3.5mm split: LTC on a stereo leg instead of the dedicated bus.
        if is_ltc_route(s.music_l_route) or is_ltc_route(s.music_r_route):
            if s.ltc_source == "generator":
                return bool(s.ltc_generator_enabled)
            return self._file_ltc_channel() is not None
        return False

    def refresh_song_ltc_routing(self) -> None:
        """Re-resolve LTC/music routing after per-song Left-LTC flag changes."""
        was_playing = self._playing
        pos = self.raw_position
        if was_playing:
            self.pause()
        if self._uses_generated_ltc():
            self._ensure_ltc_cache()
        else:
            self._invalidate_ltc_cache()
        self._resolve_device_and_route()
        self._refresh_source_routing_cache()
        self._rebuild_output_stream()
        self.timecode_status_changed.emit()
        if was_playing:
            self.seek(pos)
            self.play()

    def _parsed_stereo_routes(
        self, max_ch: int
    ) -> tuple[str, list[int], str, list[int]] | None:
        left = parse_stereo_route(self._audio_settings.music_l_route, side="l", max_ch=max_ch)
        right = parse_stereo_route(self._audio_settings.music_r_route, side="r", max_ch=max_ch)
        if left is None or right is None:
            return None
        return left[0], left[1], right[0], right[1]

    def _resolve_device_and_route(self) -> None:
        try:
            raw_devices = list_output_devices(dedupe=False)
        except TypeError:
            raw_devices = list_output_devices()
        requested_api = str(self._audio_settings.output_hostapi or "")
        hostapi = resolve_output_hostapi(requested_api)
        if hostapi != requested_api and requested_api:
            note = (
                f"Driver '{requested_api.replace('Windows ', '')}' unavailable; "
                f"using {hostapi.replace('Windows ', '')}."
            )
            self._routing_warning = (
                f"{self._routing_warning} {note}" if self._routing_warning else note
            )
        devices = list_output_devices()
        if hostapi:
            api_devices = [d for d in raw_devices if d.hostapi_name == hostapi]
            if api_devices:
                devices = api_devices

        chosen = None
        prefer_name = self._audio_settings.output_device_name
        if prefer_name:
            chosen = find_output_device(devices, name=prefer_name)
        prefer_idx = self._audio_settings.output_device_index
        if chosen is None and prefer_idx is not None:
            for d in raw_devices:
                if d.index == prefer_idx and (not hostapi or d.hostapi_name == hostapi):
                    chosen = d
                    break
        if chosen is None:
            chosen = find_output_device(devices, name=prefer_name)
        self._device_index = chosen.index if chosen is not None else None

        max_ch = chosen.max_output_channels if chosen is not None else 2
        parsed = self._parsed_stereo_routes(max_ch)
        if parsed is None:
            left_kind, left_ch = "channels", [0]
            right_kind, right_ch = "channels", [min(1, max_ch - 1)] if max_ch > 0 else [0]
        else:
            left_kind, left_ch, right_kind, right_ch = parsed

        ltc = (
            ltc_output_channels_from_settings(self._audio_settings, max_ch=max_ch)
            if self._ltc_bus_active(max_ch=max_ch)
            else []
        )
        if ltc and len(ltc) > 1:
            ltc = [max(ltc)]

        prelim = build_stereo_route_map(
            left_kind=left_kind,
            left_channels=left_ch,
            right_kind=right_kind,
            right_channels=right_ch,
            ltc_channels=ltc,
            ltc_bus_active=bool(ltc),
        )
        needed = required_output_channels(prelim)
        native_rate_guess = float(
            self._buffer.sample_rate if self._buffer is not None else 48000
        )
        if needed > 1:
            endpoint = resolve_output_endpoint_for_channels(
                preferred_name=self._audio_settings.output_device_name,
                min_channels=needed,
                samplerate=native_rate_guess,
                raw_devices=raw_devices,
                hostapi=hostapi,
            )
            if endpoint is not None:
                chosen = endpoint
                self._device_index = endpoint.index
        if chosen is not None and needed > chosen.max_output_channels:
            chosen = upgrade_device_for_channels(
                chosen,
                min_channels=needed,
                raw_devices=raw_devices,
                hostapi=hostapi,
            )
            self._device_index = chosen.index

        max_ch = chosen.max_output_channels if chosen is not None else 2
        parsed = self._parsed_stereo_routes(max_ch)
        if parsed is None:
            left_kind, left_ch = "channels", [0]
            right_kind, right_ch = "channels", [min(1, max_ch - 1)] if max_ch > 0 else [0]
        else:
            left_kind, left_ch, right_kind, right_ch = parsed

        if self._ltc_bus_active(max_ch=max_ch):
            ltc = ltc_output_channels_from_settings(self._audio_settings, max_ch=max_ch)
        else:
            ltc = []

        # File-LTC songs: both speaker legs are Music Source (LTC-stripped music)
        # on channels that do not share the dedicated LTC wire.
        if self._song_uses_file_ltc() and ltc:
            preferred = list(dict.fromkeys([*left_ch, *right_ch]))
            speakers = speaker_channels_without_ltc(
                preferred=preferred or [0, min(1, max_ch - 1)],
                ltc_channels=ltc,
                max_ch=max_ch,
            )
            if speakers:
                left_kind = "music_source"
                right_kind = "music_source"
                left_ch = [speakers[0]]
                right_ch = [speakers[1]] if len(speakers) > 1 else [speakers[0]]

        route = build_stereo_route_map(
            left_kind=left_kind,
            left_channels=left_ch,
            right_kind=right_kind,
            right_channels=right_ch,
            ltc_channels=ltc,
            ltc_bus_active=bool(ltc),
        )
        # LTC outs must stay timecode-only — never sum music onto the same wire.
        route, cleared_for_ltc = exclusive_ltc_route(route)
        if cleared_for_ltc:
            human = "+".join(str(c + 1) for c in cleared_for_ltc)
            note = (
                f"LTC CH{human} is exclusive (music moved off that output so "
                f"timecode stays clean)."
            )
            self._routing_warning = (
                f"{self._routing_warning} {note}" if self._routing_warning else note
            )
        needed = required_output_channels(route)
        all_dests = [ch for dests in route.values() for ch in dests]
        warn = warn_if_outputs_insufficient(all_dests, max_ch)
        if warn:
            self._routing_warning = (
                f"{self._routing_warning} {warn}" if self._routing_warning else warn
            )
        self._output_channel_count = min(max(needed, 1), max_ch) if max_ch > 0 else needed
        clamped: dict[int, list[int]] = {}
        for src, dests in route.items():
            keep = [d for d in dests if 0 <= d < self._output_channel_count]
            if keep:
                clamped[src] = keep
        if clamped:
            self._route = clamped
        else:
            self._route = {SRC_MUSIC_L: [0], SRC_MUSIC_R: [min(1, self._output_channel_count - 1)]}

        native_rate = self._buffer.sample_rate if self._buffer is not None else 48000
        self._playback_rate = int(
            round(
                resolve_output_samplerate(
                    device_index=self._device_index,
                    channels=max(1, self._output_channel_count),
                    preferred_rate=float(native_rate),
                    device_default_rate=chosen.default_samplerate if chosen is not None else None,
                )
            )
        )
        if self._device_index is not None:
            probed = probe_supported_output_channels(
                self._device_index,
                min_channels=self._output_channel_count,
                samplerate=float(self._playback_rate),
            )
            if probed < self._output_channel_count:
                if needed > probed:
                    alt = resolve_output_endpoint_for_channels(
                        preferred_name=self._audio_settings.output_device_name,
                        min_channels=needed,
                        samplerate=float(self._playback_rate),
                        raw_devices=raw_devices,
                        hostapi=hostapi,
                    )
                    if alt is not None and alt.index != self._device_index:
                        alt_probed = probe_supported_output_channels(
                            alt.index,
                            min_channels=needed,
                            samplerate=float(self._playback_rate),
                        )
                        if alt_probed >= needed:
                            chosen = alt
                            self._device_index = alt.index
                            max_ch = alt.max_output_channels
                            probed = alt_probed
                            self._output_channel_count = min(max(needed, 1), max_ch)
                            clamped = {}
                            for src, dests in route.items():
                                keep = [
                                    d
                                    for d in dests
                                    if 0 <= d < self._output_channel_count
                                ]
                                if keep:
                                    clamped[src] = keep
                            self._route = (
                                clamped
                                if clamped
                                else {
                                    0: [0],
                                    1: [min(1, self._output_channel_count - 1)],
                                }
                            )
                if probed < self._output_channel_count:
                    self._routing_warning = warn_if_outputs_insufficient(all_dests, probed)
                    self._output_channel_count = max(1, probed)
                    reclamped: dict[int, list[int]] = {}
                    for src, dests in route.items():
                        keep = [d for d in dests if 0 <= d < self._output_channel_count]
                        if keep:
                            reclamped[src] = keep
                    self._route = reclamped if reclamped else self._route
        self._video_mixer.set_playback_rate(self._playback_rate)
        self.refresh_video_clips()
        self._refresh_playback_samples()
        self._refresh_source_routing_cache()
        self._refresh_ltc_detection()

    def _refresh_ltc_detection(self) -> None:
        """Re-run LTC auto-detect on the native file buffer (not resampled music)."""
        buf = self._buffer
        if buf is None or buf.channels < 2:
            self._detected_ltc_channel = None
            self._ltc_detect_ran = False
            self._refresh_source_routing_cache()
            return
        samples = buf.samples
        sample_rate = int(buf.sample_rate)
        buf_id = id(buf)

        def _run() -> tuple[int, int | None]:
            return buf_id, detect_ltc_channel(samples, sample_rate)

        future = self._ltc_detect_executor.submit(_run)

        def _done(fut) -> None:
            try:
                loaded_id, detected = fut.result()
            except Exception:
                return
            if self._buffer is None or id(self._buffer) != loaded_id:
                return
            self._detected_ltc_channel = detected
            self._ltc_detect_ran = True
            self._refresh_source_routing_cache()
            self.timecode_status_changed.emit()

        future.add_done_callback(_done)

    def _refresh_source_routing_cache(self) -> None:
        """Precompute routing indices so the realtime callback stays O(chunk)."""
        self._cached_music_indices = self._music_source_indices()
        self._cached_file_ltc_idx = self._file_ltc_channel()

    def _playback_end_frame(self) -> int:
        """Timeline length in playback-rate frames (resampled buffer when present)."""
        if self._playback_samples is not None:
            return int(self._playback_samples.shape[0])
        if self._buffer is not None:
            return int(
                round(
                    self._buffer.frames
                    * float(self._playback_rate)
                    / float(self._buffer.sample_rate)
                )
            )
        return max(1, int(self._duration_seconds * self._playback_rate))

    def _refresh_playback_samples(self) -> None:
        """
        Keep a copy of the loaded buffer resampled to _playback_rate.

        Rate mismatches resample in a background thread so song switches stay
        responsive. The realtime callback reads ``_playback_samples`` only
        (silence until the cache is ready — never per-buffer resample).
        """
        buf = self._buffer
        if buf is None:
            self._playback_samples = None
            self._playback_cache_key = None
            self._playback_resample_future = None
            return
        key = (id(buf), int(buf.sample_rate), int(self._playback_rate))
        if self._playback_cache_key == key and self._playback_samples is not None:
            return
        if int(buf.sample_rate) == int(self._playback_rate):
            self._playback_samples = buf.samples
            self._playback_cache_key = key
            self._playback_resample_future = None
            return
        self._playback_cache_key = key
        self._playback_samples = None
        native = buf.samples
        src_rate = float(buf.sample_rate)
        dst_rate = float(self._playback_rate)

        def _build() -> tuple[tuple, np.ndarray]:
            return key, resample_linear(native, src_rate, dst_rate)

        future = self._resample_executor.submit(_build)
        self._playback_resample_future = future

        def _done(fut) -> None:
            try:
                built_key, pcm = fut.result()
            except Exception:
                return
            self._apply_resampled_pcm(built_key, pcm)

        future.add_done_callback(_done)

    def _music_chunk(self, start: int, frames: int, sample_rate: int) -> np.ndarray:
        """Return stereo music (frames, 2), applying mute + master volume."""
        del sample_rate  # all bookkeeping is in _playback_rate frames
        out = np.zeros((frames, 2), dtype=np.float32)
        samples = self._playback_samples
        if samples is None:
            return out
        end = min(start + frames, samples.shape[0])
        if end <= start:
            return out
        chunk = samples[start:end]
        n = chunk.shape[0]
        if chunk.ndim == 1:
            out[:n, 0] = chunk
            out[:n, 1] = chunk
        elif chunk.shape[1] == 1:
            out[:n, 0] = chunk[:, 0]
            out[:n, 1] = chunk[:, 0]
        else:
            left_idx, right_idx = self._cached_music_indices
            out[:n, 0] = chunk[:, left_idx]
            out[:n, 1] = chunk[:, right_idx]
        if self._mute_music:
            out[:] = 0.0
        # Master (all-bus) gain, then the dedicated music-bed gain used for
        # Video/Music alignment balancing — video clip audio only gets the
        # former (see _video_chunk), so the two faders are independent.
        vol = self._volume * self._music_volume * (10.0 ** (self._audio_gain_db / 20.0))
        if vol <= 1e-6:
            out[:] = 0.0
        elif abs(vol - 1.0) > 1e-6:
            out *= vol
        return out

    def _video_chunk(self, start: int, frames: int) -> np.ndarray:
        """
        Video clips' own embedded audio for playback-rate frames starting at
        `start` — the same write-head frame used for music/LTC (see
        `VideoAudioMixer`), so it stays sample-locked with the music without
        any extra offset math.
        """
        out = self._video_mixer.chunk_at(start, frames)
        if self._mute_music:
            return np.zeros_like(out)
        vol = self._volume
        if vol < 1.0 - 1e-6:
            out = out * vol
        return out

    def _source_channel_chunk(self, channel: int, start: int, frames: int) -> np.ndarray:
        out = np.zeros(frames, dtype=np.float32)
        buf = self._buffer
        if self._is_ltc_file_channel(channel) and buf is not None:
            native = buf.samples
            if native.ndim == 1:
                mono = native
            else:
                idx = min(max(0, int(channel)), int(native.shape[1]) - 1)
                mono = native[:, idx]
            if int(buf.sample_rate) != int(self._playback_rate):
                return resample_hold_segment(
                    mono,
                    float(buf.sample_rate),
                    float(self._playback_rate),
                    start,
                    frames,
                )
            end = min(start + frames, mono.shape[0])
            if end > start:
                out[: end - start] = mono[start:end]
            return out
        samples = self._playback_samples
        if samples is None:
            return out
        end = min(start + frames, samples.shape[0])
        if end <= start:
            return out
        chunk = samples[start:end]
        n = chunk.shape[0]
        if chunk.ndim == 1:
            out[:n] = chunk
        else:
            idx = min(max(0, int(channel)), int(chunk.shape[1]) - 1)
            out[:n] = chunk[:, idx]
        return out

    def _ltc_chunk(self, start: int, frames: int) -> np.ndarray:
        out = np.zeros(frames, dtype=np.float32)
        if not self._audio_settings.ltc_enabled:
            return out
        gain = float(self._audio_settings.ltc_gain)
        src_ch = self._effective_ltc_source_channel()
        if src_ch is not None:
            out = self._source_channel_chunk(src_ch, start, frames)
            if gain < 1.0 - 1e-6:
                out *= gain
            elif gain <= 1e-6:
                out[:] = 0.0
            return out
        if not self._uses_generated_ltc():
            return out
        pcm = self._ltc_pcm
        if pcm is not None:
            end = min(start + frames, pcm.size)
            if end <= start:
                return out
            out[: end - start] = pcm[start:end] * gain
            return out
        # Cache not ready yet — stream LTC incrementally (must stay O(chunk)).
        self._sync_ltc_cursor()
        seg = self._ltc_cursor.render(start, frames)
        if gain < 1.0 - 1e-6:
            seg = seg * gain
        elif gain <= 1e-6:
            seg = np.zeros_like(seg)
        out[: seg.size] = seg
        return out

    def _stream_token(self) -> tuple:
        # Do not key on id(_playback_samples): the callback reads the live
        # buffer, so song switches should not force an ASIO reopen on Play.
        return (
            self._device_index,
            self._output_channel_count,
            self._playback_rate,
            tuple(sorted((k, tuple(v)) for k, v in self._route.items())),
            bool(self._audio_settings.ltc_enabled),
        )

    def _append_routing_warning(self, note: str) -> None:
        self._routing_warning = f"{self._routing_warning} {note}" if self._routing_warning else note

    def _clamp_route_to_channels(self, ch: int) -> None:
        reclamped: dict[int, list[int]] = {}
        for src, dests in self._route.items():
            keep = [d for d in dests if 0 <= d < ch]
            if keep:
                reclamped[src] = keep
        if reclamped:
            self._route = reclamped
        else:
            self._route = {
                SRC_MUSIC_L: [0],
                SRC_MUSIC_R: [min(1, max(0, ch - 1))],
            }

    def _ensure_stream(self) -> bool:
        """Open or keep the output stream; recreate only when routing/rate changes."""
        token = self._stream_token()
        if self._stream is not None and self._active_stream_token == token:
            return True
        return self._start_stream()

    def _make_stream_callback(self, sample_rate: int):
        def callback(outdata, frames, time_info, status) -> None:  # noqa: ANN001
            del status, time_info
            with self._lock:
                if not self._playing:
                    outdata.fill(0)
                    return
                loop_on = (
                    self.loop_enabled
                    and self.loop_a is not None
                    and self.loop_b is not None
                    and abs(self.loop_b - self.loop_a) >= 0.01
                )
                a_frame = b_frame = 0
                if loop_on:
                    a_frame = int(min(self.loop_a, self.loop_b) * sample_rate)
                    b_frame = int(max(self.loop_a, self.loop_b) * sample_rate)
                    if self._loop_engage:
                        if self._position_frame >= b_frame:
                            self._position_frame = a_frame
                    elif a_frame <= self._position_frame < b_frame:
                        self._loop_engage = True
                start = self._position_frame
                total_frames = self._playback_end_frame()
                end = min(start + frames, total_frames)
                if loop_on and self._loop_engage and start < b_frame:
                    end = min(end, b_frame)

                # Advance / wrap position bookkeeping (music may pad).
                if end - start < frames:
                    if loop_on and self._loop_engage and end >= b_frame:
                        need = frames - (end - start)
                        self._position_frame = a_frame + need
                        # Rebuild as contiguous logical block starting at `start`.
                        music = self._assemble_looped_music(start, frames, a_frame, b_frame, sample_rate)
                        ltc = self._assemble_looped_ltc(start, frames, a_frame, b_frame)
                        video = self._assemble_looped_video(start, frames, a_frame, b_frame)
                    else:
                        music = self._music_chunk(start, frames, sample_rate)
                        ltc = self._ltc_chunk(start, frames)
                        video = self._video_chunk(start, frames)
                        self._position_frame = total_frames
                        self._playing = False
                else:
                    music = self._music_chunk(start, frames, sample_rate)
                    ltc = self._ltc_chunk(start, frames)
                    video = self._video_chunk(start, frames)
                    self._position_frame = end

                # Video clips' own audio shares the music bus/output channels
                # (so it's audible wherever Music is routed) — mixed in at the
                # exact write-head frame, i.e. the same sample clock as music.
                music[:, :2] += video[:, :2]
                np.clip(music, -1.0, 1.0, out=music)

                self._mix_clicks(music, start)
                sources = np.zeros((frames, 5), dtype=np.float32)
                sources[:, SRC_MUSIC_L] = music[:, 0]
                sources[:, SRC_MUSIC_R] = music[:, 1]
                sources[:, SRC_LTC_BUS] = ltc
                ltc_idx = self._cached_file_ltc_idx
                if ltc_idx is not None:
                    sources[:, SRC_FILE_LTC] = self._source_channel_chunk(
                        ltc_idx, start, frames
                    )
                # Music Source destinations must hear the *processed* bed
                # (LTC-stripped + music_volume + video clip audio), not a raw
                # file channel — otherwise Video Track audio vanishes and the
                # Music fader appears dead whenever L/R routes are Music Source
                # or File-LTC remaps speakers onto that bus.
                sources[:, SRC_FILE_MUSIC] = 0.5 * (music[:, 0] + music[:, 1])
                routed = apply_routing(sources, self._route, self._output_channel_count)
            outdata[:] = routed

        return callback

    def _open_output_stream(
        self,
        *,
        device: int | None,
        channels: int,
        sample_rate: int,
        latency: str | float | None = "low",
    ) -> bool:
        kwargs: dict = {
            "samplerate": sample_rate,
            "channels": channels,
            "dtype": "float32",
            "callback": self._make_stream_callback(sample_rate),
            "blocksize": 0,
        }
        if latency is not None:
            kwargs["latency"] = latency
        if device is not None:
            kwargs["device"] = device
        try:
            self._stream = sd.OutputStream(**kwargs)
            self._stream.start()
            self._active_stream_token = self._stream_token()
            return True
        except sd.PortAudioError:
            self._stream = None
            self._active_stream_token = None
            return False

    def _device_default_rate(self, device: int | None) -> float | None:
        if device is None:
            return None
        try:
            return float(sd.query_devices(device)["default_samplerate"])
        except Exception:
            return None

    def _try_open_stream_variant(
        self,
        *,
        device: int | None,
        channels: int,
        sample_rate: int,
    ) -> bool:
        for latency in ("low", None):
            if self._open_output_stream(
                device=device,
                channels=channels,
                sample_rate=sample_rate,
                latency=latency,
            ):
                return True
        return False

    def _start_stream(self) -> bool:
        self._stop_stream()
        base_device = self._device_index
        base_channels = self._output_channel_count
        base_rate = self._playback_rate
        saved_route = {k: list(v) for k, v in self._route.items()}
        device = base_device
        rate_candidates = iter_output_samplerate_candidates(
            device_index=device,
            preferred_rate=float(base_rate),
            device_default_rate=self._device_default_rate(device),
        )

        def try_open(
            dev: int | None,
            ch: int,
            rate: float,
            *,
            route: dict[int, list[int]] | None = None,
        ) -> bool:
            sr = int(round(rate))
            prev_rate = self._playback_rate
            prev_ch = self._output_channel_count
            prev_route = {k: list(v) for k, v in self._route.items()}
            self._output_channel_count = ch
            if route is not None:
                self._route = {k: list(v) for k, v in route.items()}
                self._clamp_route_to_channels(ch)
            if self._try_open_stream_variant(device=dev, channels=ch, sample_rate=sr):
                if sr != prev_rate:
                    self._playback_rate = sr
                    self._refresh_playback_samples()
                return True
            self._playback_rate = prev_rate
            self._output_channel_count = prev_ch
            self._route = prev_route
            return False

        for rate in rate_candidates:
            if try_open(device, base_channels, rate):
                if int(round(rate)) != base_rate:
                    self._append_routing_warning(
                        f"Opened output at {int(round(rate))} Hz."
                    )
                return True

        if device is not None:
            for rate in rate_candidates:
                probed = probe_supported_output_channels(
                    device,
                    min_channels=1,
                    samplerate=float(rate),
                )
                for ch in range(min(base_channels, probed), 0, -1):
                    if ch == base_channels:
                        continue
                    route = {k: list(v) for k, v in saved_route.items()}
                    clamped: dict[int, list[int]] = {}
                    for src, dests in route.items():
                        keep = [d for d in dests if 0 <= d < ch]
                        if keep:
                            clamped[src] = keep
                    if try_open(device, ch, rate, route=clamped or saved_route):
                        if int(round(rate)) != base_rate:
                            self._append_routing_warning(
                                f"Opened output at {int(round(rate))} Hz."
                            )
                        self._append_routing_warning(
                            f"Reduced output to {ch} channel(s) for this device."
                        )
                        return True

        stereo_ch = min(2, max(1, base_channels))
        stereo_route = {k: list(v) for k, v in saved_route.items()}
        for rate in rate_candidates:
            if try_open(device, stereo_ch, rate, route=stereo_route):
                if int(round(rate)) != base_rate:
                    self._append_routing_warning(
                        f"Opened output at {int(round(rate))} Hz."
                    )
                self._append_routing_warning("Fell back to stereo Music L/R routing.")
                return True

        if device is not None:
            self._device_index = None
            default_route = {SRC_MUSIC_L: [0], SRC_MUSIC_R: [1]}
            for rate in iter_output_samplerate_candidates(
                device_index=None,
                preferred_rate=float(base_rate),
                device_default_rate=None,
            ):
                if try_open(None, 2, rate, route=default_route):
                    if int(round(rate)) != base_rate:
                        self._append_routing_warning(
                            f"Opened output at {int(round(rate))} Hz."
                        )
                    self._append_routing_warning("Using system default output device.")
                    return True

        self._device_index = base_device
        self._output_channel_count = base_channels
        self._route = saved_route
        self._playback_rate = base_rate
        self._refresh_playback_samples()
        self._stream = None
        self._active_stream_token = None
        self._append_routing_warning("Could not open audio output stream.")
        return False

    def _assemble_looped_music(
        self,
        start: int,
        frames: int,
        a_frame: int,
        b_frame: int,
        sample_rate: int,
    ) -> np.ndarray:
        first_n = max(0, min(frames, b_frame - start))
        music = self._music_chunk(start, frames, sample_rate)
        if first_n >= frames:
            return music
        need = frames - first_n
        wrap = self._music_chunk(a_frame, need, sample_rate)
        music[first_n:] = wrap[:need]
        return music

    def _assemble_looped_ltc(
        self, start: int, frames: int, a_frame: int, b_frame: int
    ) -> np.ndarray:
        first_n = max(0, min(frames, b_frame - start))
        ltc = self._ltc_chunk(start, frames)
        if first_n >= frames:
            return ltc
        need = frames - first_n
        wrap = self._ltc_chunk(a_frame, need)
        ltc[first_n:] = wrap[:need]
        return ltc

    def _assemble_looped_video(
        self, start: int, frames: int, a_frame: int, b_frame: int
    ) -> np.ndarray:
        first_n = max(0, min(frames, b_frame - start))
        video = self._video_chunk(start, frames)
        if first_n >= frames:
            return video
        need = frames - first_n
        wrap = self._video_chunk(a_frame, need)
        video[first_n:] = wrap[:need]
        return video

    def _stop_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._active_stream_token = None
