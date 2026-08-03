# Latest AI task report

**Date:** 2026-08-03  
**Branch:** `cursor/ports-package-step0-028d`  
**Audience:** ChatGPT / future Cursor review

---

## Task objective

Implement `ARCHITECTURE_TARGET` **step 0** with a strict interface-first approach:
create `src/cueplayer/ports/` containing only Protocol-based boundary interfaces
(no wiring, adapters, services, or behavior changes).

## What was implemented

- Added `cueplayer.ports` package with the ten target Protocols (+ `AudioOutputDeviceInfo` structural Protocol for devices).
- Package `__init__` re-exports the public surface; module docs state no imports from ui/playback/media/persistence/exporters/web_remote.
- Added `tests/ports/test_ports_package.py` import / runtime-checkable smoke tests.
- Marked step 0 complete in `docs/ARCHITECTURE_TARGET.md`; queued step 1 in `.ai/NEXT_TASK.md`.

## Files changed

| Path | Change |
|------|--------|
| `src/cueplayer/ports/__init__.py` | Package exports |
| `src/cueplayer/ports/clock.py` | `PlaybackClock` |
| `src/cueplayer/ports/audio_device.py` | `AudioDevicePort`, `AudioOutputDeviceInfo` |
| `src/cueplayer/ports/video_decoder.py` | `VideoDecoderPort` |
| `src/cueplayer/ports/video_audio.py` | `VideoAudioSource` |
| `src/cueplayer/ports/frame_sink.py` | `FrameSink` |
| `src/cueplayer/ports/project_store.py` | `ProjectStore` |
| `src/cueplayer/ports/exporter.py` | `ShowExporter` |
| `src/cueplayer/ports/remote_host.py` | `RemoteHost` |
| `src/cueplayer/ports/media_jobs.py` | `MediaJobQueue` |
| `src/cueplayer/ports/song_session.py` | `SongSession` |
| `tests/ports/test_ports_package.py` | Smoke tests |
| `docs/ARCHITECTURE_TARGET.md` | Step 0 marked done |
| `.ai/NEXT_TASK.md` | Now step 1 |
| `.ai/REPORT.md` | This report |
| `.ai/handoffs/2026-08-03_PortsPackageStep0.md` | Archive |

## Architecture decisions

- **Interface-first only:** Protocols describe seams; nothing implements or injects them yet.
- **Dependency direction:** ports may reference `domain` types (`Song`, `Project`); must not import adapter packages (playback/media/persistence/exporters/ui/web_remote). Export plans / PCM / frames use `Any` or structural Protocols where needed.
- **`PlaybackClock`** mirrors `AudioEngine` transport surface (position/duration/playing + play/pause/stop/seek/set_song) so the sample-clock rule stays explicit.
- **`RemoteHost`** is intentionally narrow (clock + project + current song) — command surface expands at step 2 without private MainWindow access.
- **`ShowExporter.export_show_to_directory`** matches the shared MA2/MA3 show entrypoint name; kwargs differences stay in adapters.

## Tests performed

- `python -c "import cueplayer.ports"` — OK
- `pytest tests/ports/test_ports_package.py` — 2 passed

## Remaining issues

- No production code implements these Protocols yet (by design).
- This workspace tip’s `master`-based tree is older than the 1.0.6 release tip (e.g. limited `web_remote` sources here); Protocol names still match the target doc used across branches.
- Step 1 (`cue_list_columns` → domain) not started.

## Suggested next task

`.ai/NEXT_TASK.md`: **Step 1 — move `cue_list_columns` into `domain/` + shims; remove `persistence → ui` import.** Then REPORT + handoff + stop.
