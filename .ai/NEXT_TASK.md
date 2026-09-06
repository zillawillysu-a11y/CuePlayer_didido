# Next task

LTC Generator Clips — Phase 2: playback wiring + UI + exporter.
Phase 1 (domain/mapping/persistence/tests) is complete — see
`.ai/handoffs/2026-09-06_LtcClipsDomainPhase1.md`.

1. Playback (AudioEngine + MTC):
   - When the resolved song mode is `clip_generator`, emit generated LTC
     only inside clips: LTC cache key and the realtime `LtcPlaybackCursor`
     must follow the clip table (TC restarts at each clip's
     `start_timecode`); no LTC outside clips.
   - MTC: no MTC output outside clips (respect the existing MTC toggle).
   - UI timecode clock / readouts: show `No TC` or `--:--:--:--` outside
     clips.
   - `full_track_generator` must keep today's single-offset behavior.
2. UI: create/edit LTC Generator Clips per song (start position, duration,
   start TC). Creating the first clip switches the song to
   `clip_generator` (stops full-track generator; striped can't coexist).
   Show `validate_ltc_clips` errors (block save/use) and warnings
   (overlapping timeline ranges, overlapping/backwards TC ranges).
   Removing the last clip keeps `clip_generator`; never auto-restore
   `full_track_generator`.
3. Exporter (MA2 + MA3, per user spec):
   - `full_track_generator`: unchanged math.
   - `clip_generator`: Timecode Events only for marks inside a clip;
     out-of-clip marks still export their Sequence Cue but get no Timecode
     Event and are listed in the export warning list.
   - Do NOT create multiple MA Timecode objects per clip — one Timecode
     object per song as today (plan must carry the per-clip TC mapping).
   - Overlapping/backwards TC ranges: validate and warn in the export
     report.

Carry-over (not blocking):
- Reset audio callback continuity counters on stream open (small planned
  diagnostic fix).
- Physical loopback 440 Hz + long-capture drift check were parked by the
  user (recent ASIO test clean; no clock correction).
