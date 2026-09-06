# Next task

LTC Generator Clips — Phase 4: **MA2 + MA3 exporter wiring for
`clip_generator`** (the only remaining phase of the LTC Generator Clips
feature; domain / playback / hardening / UI are complete — see
`.ai/handoffs/2026-09-06_LtcClipsUiPhase3.md`).

**Scope:**
1. `full_track_generator`: unchanged math (existing Timecode export stays as
   is).
2. `clip_generator`:
   - Timecode Events **only for marks whose time falls inside a clip**
     (half-open `[start, end)` per `ltc_clips.clip_at_position()`), using the
     clip's start-TC mapping.
   - Out-of-clip marks still export their Sequence Cue but get **no
     Timecode Event** and are listed in the export **warning list**.
   - Do **NOT** create multiple MA Timecode objects per clip — one Timecode
     object per song as today; the export plan must carry the per-clip TC
     mapping.
   - Overlapping / backwards TC ranges: validate and warn in the export
     report (reuse `validate_ltc_clips` warnings + pairwise TC check).
3. Golden XML fixtures for a `clip_generator` song (MA2 + MA3) proving:
   - inside-clip marks → Timecode Events with the clip's TC base
   - out-of-clip marks → Sequence Cue only
   - warning list contents match
4. Keep the existing invariants: main marks export as Go+ with explicit
   CueDestination; Top Button marks reuse one 2-cue self-release sequence;
   MA2 full export keeps the executor-assign Plugin before Timecode import;
   MA3 full export keeps the import-sequences → assign-executors →
   import-timecode Macro; timecode-only re-export after executors assigned
   still works; never write Chinese into MA XML labels.

**Carry-over (not blocking):**
- PySide6 intermittent `LOAD_ATTR` AttributeError on direct private reads of
  TimelineWidget from test code (worked around with `getattr()` in tests;
  see `.ai/REPORT.md` architecture decision 6).
- Reset audio callback continuity counters on stream open (small planned
  diagnostic fix).
- Physical loopback 440 Hz + long-capture drift check (parked by user).
- Pre-existing failures unrelated to the LTC clip work (verified on clean
  tree): `test_ndi_probe` DLL-path test, 2× `test_song_use_left_ltc`
  routing assertions, `test_video_sync` flake, `test_clock_fit_narrow_panel`
  font failures, occasional `webrtc_listen` asyncio stack-overflow crash in
  `tests/ui` (Windows), `test_cue_list_playhead_scroll` Windows stack
  overflow (hard crash).
