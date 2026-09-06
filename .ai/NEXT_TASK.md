# Next task

LTC Generator Clips — Phase 3: **per-song LTC Generator Clip UI only**.
Playback wiring + hardening are complete — see
`.ai/handoffs/2026-09-06_LtcClipsPlaybackPhase2.md` and
`.ai/handoffs/2026-09-06_LtcClipsPlaybackPhase2Hardening.md`
(LTC audio inside clips only, MTC re-anchoring per clip with no stale-QF
leak, half-open `[start, end)` boundary semantics unified across audio /
MTC / display, 46 domain+playback tests passing).

**Phase 3 scope (no exporter):**
1. Timeline display of the active song's LTC Generator Clips (read-only
   overlay is acceptable first; drag/trim next).
2. Create a clip (start position, duration, start TC); the first clip
   switches the song to `clip_generator` (stops full-track generator;
   stripes can't coexist) — `add_ltc_clip()` already does this in the
   domain.
3. Drag (move) and trim (start/duration) edits.
4. Start-TC edit (string field with `parse_timecode` validation).
5. Validation display: `validate_ltc_clips` errors block save/use;
   warnings (overlapping timeline ranges, overlapping/backwards TC ranges)
   are shown but allowed.
6. Source mode UI: per-song `ltc_source_mode` selection
   (`auto` / `striped_file` / `full_track_generator` / `clip_generator` /
   `off`); removing the last clip keeps `clip_generator` (never
   auto-restore full-track).
7. After any clip-table or mode change call
   `AudioEngine.refresh_song_ltc_routing()` (re-arms the async clip PCM
   cache, the MTC TC source, file-LTC routing, and the output stream).
   `seek()`/playback already re-anchor MTC per clip; no engine changes
   expected for Phase 3.

**Phase 4 (NOT in Phase 3): MA2 + MA3 exporter wiring**
- `full_track_generator`: unchanged math.
- `clip_generator`: Timecode Events only for marks inside a clip;
  out-of-clip marks still export their Sequence Cue but get no Timecode
  Event and are listed in the export warning list.
- Do NOT create multiple MA Timecode objects per clip — one Timecode
  object per song as today (plan must carry the per-clip TC mapping).
- Overlapping/backwards TC ranges: validate and warn in the export report.

Carry-over (not blocking):
- Reset audio callback continuity counters on stream open (small planned
  diagnostic fix).
- Physical loopback 440 Hz + long-capture drift check were parked by the
  user (recent ASIO test clean; no clock correction).
- Pre-existing failures unrelated to the LTC clip work (verified on clean
  tree): `test_ndi_probe` DLL-path test, 2× `test_song_use_left_ltc`
  routing assertions, `test_video_sync` flake (1 failure + occasional AV),
  `test_clock_fit_narrow_panel` font failures, occasional
  `webrtc_listen` asyncio stack-overflow crash in `tests/ui` (Windows).
