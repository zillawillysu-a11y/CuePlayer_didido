# Next task

LTC Generator Clips — Phase 3: per-song clip create/edit UI + exporter wiring.
Playback wiring is complete — see
`.ai/handoffs/2026-09-06_LtcClipsPlaybackPhase2.md` (LTC audio inside clips
only, MTC re-anchoring per clip, `--:--:--:--` display outside clips, 20 new
regression tests passing).

1. UI: create/edit LTC Generator Clips per song (start position, duration,
   start TC), e.g. in the timeline / song edit surfaces:
   - Creating the first clip switches the song to `clip_generator` (stops
     full-track generator; stripes can't coexist).
   - Show `validate_ltc_clips` errors (block save/use) and warnings
     (overlapping timeline ranges, overlapping/backwards TC ranges).
   - Removing the last clip keeps `clip_generator`; never auto-restore
     `full_track_generator`.
   - After any clip table change call
     `AudioEngine.refresh_song_ltc_routing()` (re-arms the async clip PCM
     cache, the MTC TC source, file-LTC routing and the output stream).
2. Exporter (MA2 + MA3, per user spec):
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
- Pre-existing test failures unrelated to the LTC clip work (verified on
  clean tree): `test_ndi_probe` DLL-path test, 2× `test_song_use_left_ltc`
  routing assertions, `test_video_sync` flake (1 failure + occasional AV in
  the video-decoder thread), `test_clock_fit_narrow_panel` font-rendering
  failures.
