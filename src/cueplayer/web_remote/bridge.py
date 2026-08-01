"""Qt bridge: HTTP worker thread → MainWindow UI thread."""

from __future__ import annotations

import queue
import time
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from cueplayer.web_remote.prefs import WebRemotePrefs
from cueplayer.web_remote.server import WebRemoteServer
from cueplayer.web_remote.state import (
    build_state,
    build_waveform_overview,
    build_waveform_window,
    seconds_to_timecode,
    timecode_to_abs_seconds,
)


class WebRemoteBridge(QObject):
    """Owns the HTTP server and marshals commands onto the UI thread."""

    status_changed = Signal(str)
    started = Signal()
    stopped = Signal()

    def __init__(self, host_window: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._host = host_window
        self._server: WebRemoteServer | None = None
        self._prefs = WebRemotePrefs()
        self._cmd_queue: queue.Queue[tuple[dict[str, Any], queue.Queue[dict[str, Any]]]] = (
            queue.Queue()
        )
        self._wave_cache_key: tuple[str, int, int] | None = None
        self._wave_cache: dict[str, Any] | None = None
        self._wave_detail_key: tuple[Any, ...] | None = None
        self._wave_detail_cache: dict[str, Any] | None = None
        self._pump = QTimer(self)
        self._pump.setInterval(16)
        self._pump.timeout.connect(self._drain_commands)

    @property
    def prefs(self) -> WebRemotePrefs:
        return self._prefs

    @property
    def running(self) -> bool:
        return self._server is not None and self._server.running

    @property
    def listen_url(self) -> str:
        if self._server is None:
            return ""
        return self._server.base_url

    def apply_prefs(self, prefs: WebRemotePrefs, *, restart: bool = True) -> str | None:
        """Apply prefs; start/stop/restart server. Returns error message or None."""
        self._prefs = WebRemotePrefs(
            enabled=bool(prefs.enabled),
            port=prefs.normalized_port(),
            password=str(prefs.password or ""),
            bind_lan=bool(prefs.bind_lan),
        )
        if not self._prefs.enabled:
            self.stop()
            self.status_changed.emit("Web Remote off")
            return None
        if restart or not self.running:
            return self.start()
        return None

    def start(self) -> str | None:
        self.stop()
        host = "0.0.0.0" if self._prefs.bind_lan else "127.0.0.1"
        port = self._prefs.normalized_port()
        server = WebRemoteServer(
            host=host,
            port=port,
            password=self._prefs.password,
            get_state=self._safe_state,
            run_command=self._enqueue_command,
            get_waveform=self._safe_waveform,
            get_clock=self._safe_clock,
        )
        try:
            server.start()
        except OSError as exc:
            self.status_changed.emit(f"Web Remote failed: {exc}")
            return str(exc)
        self._server = server
        if not self._pump.isActive():
            self._pump.start()
        msg = f"Web Remote on :{port}"
        self.status_changed.emit(msg)
        self.started.emit()
        return None

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.stop()
        # Drain pending command waiters so HTTP threads do not hang.
        while True:
            try:
                _cmd, reply_q = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            try:
                reply_q.put({"ok": False, "error": "server_stopped"})
            except Exception:  # noqa: BLE001
                pass
        self.stopped.emit()

    def _safe_state(self) -> dict[str, Any]:
        # Domain reads are generally safe on the HTTP thread for MVP.
        # Engine position can race slightly — acceptable for 5–10 Hz poll UI.
        host = self._host
        project = host.project
        song = host.current_song
        engine = host.engine
        return build_state(project=project, song=song, engine=engine)

    def _safe_clock(self) -> dict[str, Any]:
        """Lightweight position tick for smooth remote clock correction."""
        host = self._host
        song = host.current_song
        engine = host.engine
        project = host.project
        position = float(engine.position)
        fps = float(getattr(song, "fps", None) or 30.0) or 30.0
        if fps <= 0:
            fps = 30.0
        timecode = ""
        outputs: list[str] = []
        try:
            tc_state = engine.output_timecode_state(position)
            timecode = str(getattr(tc_state, "timecode", "") or "")
            outputs = list(getattr(tc_state, "outputs", ()) or ())
        except Exception:  # noqa: BLE001
            timecode = ""
            outputs = []
        if not timecode or timecode in ("—",):
            timecode = seconds_to_timecode(
                timecode_to_abs_seconds(song.start_timecode, fps) + position,
                fps,
            ).format()
        return {
            "ok": True,
            "song_id": str(song.id),
            "playing": bool(engine.playing),
            "position": position,
            "duration": float(engine.duration),
            "server_ms": int(time.time() * 1000),
            "timecode": timecode,
            "fps": fps,
            "start_timecode": str(song.start_timecode or "00:00:00:00"),
            "tc_status": " · ".join(outputs) if outputs else "",
            "tc_accent": str(
                getattr(project, "output_timecode_clock_color", "") or "#3dd68c"
            ),
        }

    def _safe_waveform(
        self,
        start: float | None = None,
        end: float | None = None,
        buckets: int | None = None,
    ) -> dict[str, Any]:
        host = self._host
        song = host.current_song
        engine = host.engine
        buf = getattr(engine, "buffer", None)
        frames = int(getattr(buf, "frames", 0) or 0) if buf is not None else 0
        duration = float(engine.duration)
        song_id = str(song.id)

        if start is None and end is None:
            key = (song_id, frames, int(round(duration * 1000)))
            if self._wave_cache is not None and self._wave_cache_key == key:
                return self._wave_cache
            payload = build_waveform_overview(
                buf,
                song_id=song_id,
                duration=duration,
                buckets=int(buckets) if buckets else 2400,
            )
            self._wave_cache_key = key
            self._wave_cache = payload
            return payload

        t0 = float(start if start is not None else 0.0)
        t1 = float(end if end is not None else duration)
        n = int(buckets) if buckets else 1600
        # Quantize cache key so tiny pan deltas reuse the last detail slice.
        q0 = round(t0 * 20) / 20.0
        q1 = round(t1 * 20) / 20.0
        dkey = (song_id, frames, q0, q1, n)
        if self._wave_detail_cache is not None and self._wave_detail_key == dkey:
            return self._wave_detail_cache
        payload = build_waveform_window(
            buf,
            song_id=song_id,
            duration=duration,
            start=t0,
            end=t1,
            buckets=n,
        )
        self._wave_detail_key = dkey
        self._wave_detail_cache = payload
        return payload

    def _enqueue_command(self, command: dict[str, Any]) -> dict[str, Any]:
        reply: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._cmd_queue.put((command, reply))
        try:
            return reply.get(timeout=5.0)
        except queue.Empty:
            return {"ok": False, "error": "timeout"}

    def _drain_commands(self) -> None:
        handled = 0
        while handled < 32:
            try:
                command, reply_q = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            handled += 1
            try:
                result = self._dispatch(command)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc)}
            try:
                reply_q.put(result)
            except Exception:  # noqa: BLE001
                pass

    def _dispatch(self, command: dict[str, Any]) -> dict[str, Any]:
        op = str(command.get("op") or "").strip().lower()
        host = self._host
        if op in ("play",):
            host.engine.play()
            return {"ok": True, "op": op}
        if op in ("pause",):
            host.engine.pause()
            return {"ok": True, "op": op}
        if op in ("toggle", "play_pause"):
            if host.engine.playing:
                host.engine.pause()
            else:
                host.engine.play()
            return {"ok": True, "op": op, "playing": bool(host.engine.playing)}
        if op in ("stop",):
            host.engine.pause()
            host.engine.seek(0.0)
            return {"ok": True, "op": op}
        if op == "seek":
            seconds = float(command.get("seconds", 0.0))
            host.engine.seek(max(0.0, seconds))
            return {"ok": True, "op": op, "seconds": seconds}
        if op == "seek_mark":
            mark_id = str(command.get("mark_id") or "")
            mark = host.current_song.mark_by_id(mark_id)
            if mark is None:
                return {"ok": False, "error": "mark_not_found"}
            host.engine.seek(float(mark.time_seconds))
            return {"ok": True, "op": op, "mark_id": mark_id}
        if op == "select_song":
            return self._select_song(command)
        if op == "next_song":
            return self._step_song(+1)
        if op == "prev_song":
            return self._step_song(-1)
        if op == "add_mark":
            return self._add_mark(command)
        if op == "set_mark_note":
            return self._set_mark_note(command)
        if op == "set_mark_cue_id":
            return self._set_mark_cue_id(command)
        if op == "renumber_cue_ids":
            return self._renumber_cue_ids(command)
        if op == "set_output_toggle":
            return self._set_output_toggle(command)
        if op == "toggle_folder":
            return self._toggle_folder(command)
        if op == "update_lane":
            return self._update_lane(command)
        if op == "set_display":
            return self._set_display(command)
        return {"ok": False, "error": f"unknown_op:{op}"}

    def _set_display(self, command: dict[str, Any]) -> dict[str, Any]:
        host = self._host
        song = host.current_song
        project = host.project
        changed = False
        if "primary" in command:
            song.now_primary_visible = bool(command.get("primary"))
            changed = True
        if "secondary" in command:
            song.now_secondary_visible = bool(command.get("secondary"))
            changed = True
        if "timecode" in command:
            project.show_output_timecode_clock = bool(command.get("timecode"))
            changed = True
        if "toggles" in command:
            project.show_output_quick_toggles = bool(command.get("toggles"))
            changed = True
        if not changed:
            return {"ok": False, "error": "no_display_fields"}

        try:
            host.monitor.apply_now_display_settings()
        except Exception:  # noqa: BLE001
            pass
        try:
            host.monitor.configure_output_timecode_clock(
                visible=bool(project.show_output_timecode_clock),
                color=str(
                    getattr(project, "output_timecode_clock_color", "") or "#3dd68c"
                ),
            )
            host.monitor.configure_output_quick_toggles(
                visible=bool(project.show_output_quick_toggles),
            )
            host._refresh_output_timecode_clock()
        except Exception:  # noqa: BLE001
            pass
        host._mark_dirty()
        return {
            "ok": True,
            "op": "set_display",
            "display": {
                "primary": bool(song.now_primary_visible),
                "secondary": bool(song.now_secondary_visible),
                "timecode": bool(project.show_output_timecode_clock),
                "toggles": bool(project.show_output_quick_toggles),
            },
        }

    def _set_output_toggle(self, command: dict[str, Any]) -> dict[str, Any]:
        host = self._host
        key = str(command.get("key") or "").strip().lower()
        enabled = bool(command.get("enabled"))
        ao = host.project.audio_output
        if key == "translate":
            ao.ltc_to_mtc_translate = enabled
        elif key == "mtc":
            ao.mtc_enabled = enabled
        elif key == "ltc":
            ao.ltc_enabled = enabled
        elif key == "note":
            ao.midi_cue_notes_enabled = enabled
        else:
            return {"ok": False, "error": "bad_toggle_key"}

        if enabled and key in ("translate", "mtc", "note"):
            ao.midi_enabled = True
        elif not (
            ao.mtc_enabled
            or ao.midi_cue_notes_enabled
            or getattr(ao, "ltc_to_mtc_translate", False)
        ):
            ao.midi_enabled = False

        if ao.midi_enabled and not ao.midi_port_name:
            # Revert MIDI-dependent toggles when no port is configured.
            if key in ("translate", "mtc", "note"):
                if key == "translate":
                    ao.ltc_to_mtc_translate = False
                elif key == "mtc":
                    ao.mtc_enabled = False
                else:
                    ao.midi_cue_notes_enabled = False
                if not (
                    ao.mtc_enabled
                    or ao.midi_cue_notes_enabled
                    or getattr(ao, "ltc_to_mtc_translate", False)
                ):
                    ao.midi_enabled = False
            return {"ok": False, "error": "midi_port_required"}

        from cueplayer.persistence.audio_prefs import save_global_audio_output

        warning = host.engine.apply_audio_settings(ao)
        host._refresh_timecode_status()
        host._refresh_output_timecode_clock()
        if hasattr(host, "monitor"):
            host.monitor.sync_output_quick_toggles(ao)
        save_global_audio_output(ao)
        host._mark_dirty()
        return {
            "ok": True,
            "op": "set_output_toggle",
            "key": key,
            "enabled": enabled,
            "warning": warning or "",
        }

    def _toggle_folder(self, command: dict[str, Any]) -> dict[str, Any]:
        host = self._host
        cat_id = str(command.get("category_id") or command.get("id") or "")
        category = host.project.setlist_category_by_id(cat_id)
        if category is None:
            return {"ok": False, "error": "folder_not_found"}
        if "collapsed" in command:
            category.collapsed = bool(command.get("collapsed"))
        else:
            category.collapsed = not bool(category.collapsed)
        # Keep Setlist UI in sync on the PC.
        try:
            host._rebuild_song_list(select_indexes=host._selected_song_indexes() or None)
        except Exception:  # noqa: BLE001
            pass
        host._mark_dirty()
        return {
            "ok": True,
            "op": "toggle_folder",
            "category_id": cat_id,
            "collapsed": bool(category.collapsed),
        }

    def _update_lane(self, command: dict[str, Any]) -> dict[str, Any]:
        host = self._host
        song = host.current_song
        try:
            lane_index = int(command.get("lane_index"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_lane_index"}
        lane = song.lane_by_index(lane_index)
        if lane is None:
            return {"ok": False, "error": "lane_not_found"}

        if "name" in command:
            name = str(command.get("name") or "").strip()
            if name:
                lane.name = name
        if "visible" in command:
            lane.visible = bool(command.get("visible"))
        if "color" in command:
            color = str(command.get("color") or "").strip()
            if color:
                lane.color = color
        if "shortcut" in command:
            shortcut = str(command.get("shortcut") or "").strip()
            if shortcut in ("", "1", "2", "3", "4", "5", "6", "7", "8", "9"):
                # Clear duplicate shortcuts.
                if shortcut:
                    for other in song.mark_lanes:
                        if other is not lane and other.shortcut == shortcut:
                            other.shortcut = ""
                lane.shortcut = shortcut
        if "now" in command:
            role = str(command.get("now") or "off").strip().lower()
            song.now_lanes_configured = True
            primary = [i for i in song.now_primary_lanes if i != lane_index]
            secondary = [i for i in song.now_secondary_lanes if i != lane_index]
            if role == "primary":
                primary.append(lane_index)
            elif role == "secondary":
                secondary.append(lane_index)
                song.now_secondary_enabled = True
            song.now_primary_lanes = sorted(set(primary)) or (
                [song.mark_lanes[0].index] if song.mark_lanes else []
            )
            song.now_secondary_lanes = sorted(set(secondary))
        if "pause_on_mark" in command:
            lane.pause_on_mark = bool(command.get("pause_on_mark"))
        if "prompt_note_on_mark" in command:
            lane.prompt_note_on_mark = bool(command.get("prompt_note_on_mark"))
        if "show_note_on_wave" in command:
            lane.show_note_on_wave = bool(command.get("show_note_on_wave"))
        if "show_cue_id_on_wave" in command:
            lane.show_cue_id_on_wave = bool(command.get("show_cue_id_on_wave"))
        if "cue_id_enabled" in command:
            lane.cue_id_enabled = bool(command.get("cue_id_enabled"))

        host._rebuild_digit_shortcuts()
        host.timeline.apply_song_display_settings()
        host.monitor.apply_now_display_settings()
        host._refresh_marks_ui()
        host._mark_dirty()
        return {"ok": True, "op": "update_lane", "lane_index": lane_index}

    def _select_song(self, command: dict[str, Any]) -> dict[str, Any]:
        host = self._host
        songs = host.project.songs
        if not songs:
            return {"ok": False, "error": "empty_setlist"}
        index: int | None = None
        if "index" in command and command["index"] is not None:
            try:
                index = int(command["index"])
            except (TypeError, ValueError):
                return {"ok": False, "error": "bad_index"}
        song_id = command.get("id")
        if index is None and song_id:
            for i, song in enumerate(songs):
                if song.id == song_id:
                    index = i
                    break
        if index is None or index < 0 or index >= len(songs):
            return {"ok": False, "error": "song_not_found"}
        host._activate_song(index, stop_playback=False)
        host._rebuild_song_list(select_indexes=[index])
        return {"ok": True, "op": "select_song", "index": index}

    def _step_song(self, delta: int) -> dict[str, Any]:
        host = self._host
        songs = host.project.songs
        if not songs:
            return {"ok": False, "error": "empty_setlist"}
        try:
            cur = songs.index(host.current_song)
        except ValueError:
            cur = 0
        nxt = max(0, min(len(songs) - 1, cur + int(delta)))
        if nxt == cur:
            return {"ok": True, "op": "step_song", "index": cur, "unchanged": True}
        host._activate_song(nxt, stop_playback=False)
        host._rebuild_song_list(select_indexes=[nxt])
        return {"ok": True, "op": "step_song", "index": nxt}

    def _add_mark(self, command: dict[str, Any]) -> dict[str, Any]:
        host = self._host
        shortcut = str(command.get("shortcut") or "").strip()
        lane_index = command.get("lane_index")
        song = host.current_song
        if song not in host.project.songs and not host.project.songs:
            return {"ok": False, "error": "no_song"}
        lane = None
        if shortcut:
            lane = song.lane_by_shortcut(shortcut)
        elif lane_index is not None:
            try:
                lane = song.lane_by_index(int(lane_index))
            except (TypeError, ValueError):
                lane = None
        if lane is None:
            return {"ok": False, "error": "lane_not_found"}
        if lane.locked or not lane.visible:
            return {"ok": False, "error": "lane_unavailable"}
        if not getattr(song, "show_mark_tracks", True):
            return {"ok": False, "error": "mark_tracks_hidden"}
        ask_note = bool(getattr(lane, "prompt_note_on_mark", False))
        # Remote must never open a blocking Note dialog on the PC.
        saved_prompt = ask_note
        before_ids = {m.id for m in song.marks}
        try:
            lane.prompt_note_on_mark = False
            host._add_mark(lane.index)
        finally:
            lane.prompt_note_on_mark = saved_prompt

        mark = None
        for m in reversed(song.marks):
            if m.lane_index == lane.index and m.id not in before_ids:
                mark = m
                break
        if mark is None:
            for m in reversed(song.marks):
                if m.lane_index == lane.index:
                    mark = m
                    break

        note = command.get("note")
        if mark is not None and note is not None:
            mark.display_name = str(note).strip()
            host._refresh_marks_ui()
            host._mark_dirty()

        return {
            "ok": True,
            "op": "add_mark",
            "lane_index": lane.index,
            "shortcut": lane.shortcut or shortcut,
            "mark_id": mark.id if mark is not None else "",
            "ask_note": ask_note,
            "note": (mark.display_name if mark is not None else "") or "",
            "lane_name": lane.name,
        }

    def _set_mark_note(self, command: dict[str, Any]) -> dict[str, Any]:
        host = self._host
        mark_id = str(command.get("mark_id") or "").strip()
        mark = host.current_song.mark_by_id(mark_id)
        if mark is None:
            return {"ok": False, "error": "mark_not_found"}
        note = str(command.get("note") or "").strip()
        old = mark.display_name or ""
        if note == old:
            return {"ok": True, "op": "set_mark_note", "mark_id": mark_id, "note": note}
        mark.display_name = note
        try:
            host._on_note_changed(mark_id, old, note)
        except Exception:  # noqa: BLE001
            host._refresh_marks_ui()
            host._mark_dirty()
        return {
            "ok": True,
            "op": "set_mark_note",
            "mark_id": mark_id,
            "note": note,
        }

    def _set_mark_cue_id(self, command: dict[str, Any]) -> dict[str, Any]:
        from cueplayer.domain.main_cue_id import (
            is_valid_main_cue_id_text,
            main_cue_id_fits_order,
            main_cue_id_taken,
            normalize_main_cue_id_text,
        )

        host = self._host
        song = host.current_song
        mark_id = str(command.get("mark_id") or "").strip()
        mark = song.mark_by_id(mark_id)
        if mark is None:
            return {"ok": False, "error": "mark_not_found"}
        lane = song.lane_by_index(mark.lane_index)
        if lane is None or not lane.cue_id_enabled:
            return {"ok": False, "error": "cue_id_disabled"}
        raw = str(command.get("cue_id") or "").strip()
        if not is_valid_main_cue_id_text(raw):
            return {"ok": False, "error": "Cue ID must be a positive number"}
        new_id = normalize_main_cue_id_text(raw)
        old_id = mark.main_cue_id or ""
        if new_id == old_id:
            return {
                "ok": True,
                "op": "set_mark_cue_id",
                "mark_id": mark_id,
                "cue_id": new_id,
            }
        if not main_cue_id_fits_order(song, mark.id, new_id):
            if main_cue_id_taken(
                song,
                new_id,
                exclude_mark_id=mark.id,
                lane_index=mark.lane_index,
            ):
                return {"ok": False, "error": f"Cue ID {new_id} is already used"}
            return {"ok": False, "error": "Cue ID is out of time order"}
        mark.main_cue_id = new_id
        try:
            host._on_cue_id_changed(mark_id, old_id, new_id)
        except Exception:  # noqa: BLE001
            host._refresh_marks_ui()
            host._mark_dirty()
        return {
            "ok": True,
            "op": "set_mark_cue_id",
            "mark_id": mark_id,
            "cue_id": new_id,
        }

    def _renumber_cue_ids(self, command: dict[str, Any]) -> dict[str, Any]:
        from cueplayer.domain.main_cue_id import (
            capture_main_cue_ids,
            renumber_main_cue_ids_sequential,
            renumberable_cue_list_lanes,
        )
        from cueplayer.domain.undo import RenumberMainCueIdsCommand

        host = self._host
        song = host.current_song
        lanes = renumberable_cue_list_lanes(song)
        if not lanes:
            return {"ok": False, "error": "no_cue_list_main_marks"}
        lane_index = command.get("lane_index")
        if lane_index is not None and str(lane_index).strip() != "":
            try:
                lane_index = int(lane_index)
            except (TypeError, ValueError):
                return {"ok": False, "error": "bad_lane_index"}
            allowed = {item.index for item in lanes}
            if lane_index not in allowed:
                return {"ok": False, "error": "lane_not_renumberable"}
            scope: set[int] | None = {lane_index}
            lane = song.lane_by_index(lane_index)
            scope_label = lane.name if lane is not None else str(lane_index)
        else:
            scope = None
            scope_label = "all Cue List types"
        before = capture_main_cue_ids(song, lane_indices=scope)
        if not before:
            return {"ok": False, "error": "no_main_cues"}
        after = renumber_main_cue_ids_sequential(song, lane_indices=scope)
        if before == after:
            return {
                "ok": True,
                "op": "renumber_cue_ids",
                "unchanged": True,
                "count": len(before),
                "scope": scope_label,
            }
        try:
            host._push_song_undo(RenumberMainCueIdsCommand(before=before, after=after))
        except Exception:  # noqa: BLE001
            pass
        host._mark_dirty()
        host._refresh_marks_ui()
        return {
            "ok": True,
            "op": "renumber_cue_ids",
            "count": len(after),
            "scope": scope_label,
        }


def lan_urls(port: int) -> list[str]:
    """Best-effort LAN URLs for the settings dialog."""
    urls: list[str] = [f"http://127.0.0.1:{port}/"]
    try:
        import socket

        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127."):
                continue
            urls.append(f"http://{ip}:{port}/")
    except Exception:  # noqa: BLE001
        pass
    # Dedupe preserve order.
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
