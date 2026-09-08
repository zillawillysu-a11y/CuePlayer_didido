# Timecode Settings Source/Output Separation

Date: 2026-09-08. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

Make Art-Net Timecode fps/type follow the current Song timebase and move file-LTC
TRANS out of MIDI settings into an independent translation section with clear targets.

## What was implemented

- Reordered timecode settings as requested: Timecode Translation, MIDI / MTC Output,
  Art-Net Timecode Output, then LTC Output.
- Moved `Translate file LTC → enabled TC outputs` into the independent translation
  section and added live Targets status: Off, No TC output enabled, MTC, Art-Net TC,
  or MTC + Art-Net TC.
- TRANS can be armed before either destination and is no longer visually or logically
  gated by MIDI.
- Replaced the Art-Net fps selector with a read-only `Follow Song FPS` label including
  the official ArtTimeCode Type meaning.
- AudioEngine now configures Art-Net from its current Song fps, ignoring the legacy
  stored Art-Net fps value. Song changes update both Art-Net start TC and fps/type.
- Kept the legacy persisted fps field readable/writable for project/global preference
  compatibility; it is no longer a user choice or runtime authority.

## Files changed

- `src/cueplayer/ui/audio_timecode_dialog.py`
- `src/cueplayer/ui/main_window.py`
- `src/cueplayer/playback/audio_engine.py`
- `src/cueplayer/playback/artnet_timecode.py`
- `tests/playback/test_artnet_audio_engine.py`
- `tests/ui/test_audio_timecode_midi_port_always_enabled.py`
- `docs/ARTNET_TIMECODE_DESIGN.md`
- `docs/PRODUCT_SPEC.md`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-09-08_TimecodeSettingsSeparation.md`

## Architecture decisions

- Song Timebase is the single fps/type authority for internal TC, MTC/LTC mapping, and
  ArtTimeCode. No second Art-Net timebase is exposed.
- The legacy settings field remains solely as a compatibility bridge; runtime code
  uses `AudioEngine._song_fps`.
- TRANS represents the decoded file-LTC source and MTC/Art-Net remain independent
  destinations, matching the existing sender architecture.
- No sender scheduling, MTC implementation, audio callback, buffer, or UDP placement
  changed in this task.

## Tests performed

- Targeted Art-Net/TRANS/settings/persistence/UI batch: **41 passed**.
- Broad safe playback regression subset: **248 passed**.
- Persistence + changed UI + Web Remote batch: **141 passed**.
- `python -m compileall -q src`: passed.

## Remaining issues

- Physical Wireshark/DMX-Workshop and external Art-Net receiver verification remains
  required for the ArtTimeCode feature.
- The build should confirm each Song fps renders the correct read-only label and packet
  Type, including 29.97 DF.

## Suggested next task

Build on Windows and run the hardware matrix in `.ai/NEXT_TASK.md`: verify normal
ArtTC and TRANS ArtTC-only/MTC+ArtTC through Play/Pause/Stop/Seek, then repeat with
Video + Timeline Zoom stress while capturing PERF and receiver evidence.
