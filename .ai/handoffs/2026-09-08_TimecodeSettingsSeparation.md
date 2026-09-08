# Timecode Settings Source/Output Separation

Date: 2026-09-08. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

Make Art-Net fps/type follow Song FPS and separate file-LTC translation from MIDI UI.

## What was implemented

- Settings order is Timecode Translation → MIDI / MTC Output → Art-Net Timecode
  Output → LTC Output.
- TRANS has live independent destination status and can be armed without MIDI.
- Art-Net fps/type is read-only and follows the current Song timebase.
- Engine and sender update Art-Net fps on Song timebase changes; legacy persisted fps
  is compatibility-only.

## Files changed

Audio timecode dialog, MainWindow dialog invocation, AudioEngine, Art-Net sender,
focused playback/UI tests, protocol/product docs, report and handoff.

## Architecture decisions

- Song Timebase remains the sole fps authority.
- TRANS is a source control; MTC and Art-Net are independent destination controls.
- Stable MTC/audio/network scheduling architecture was not changed.

## Tests performed

- Focused batch: **41 passed**.
- Broad safe playback subset: **248 passed**.
- Persistence/changed UI/Web Remote: **141 passed**.
- Compileall passed.

## Remaining issues

Physical Wireshark/DMX-Workshop and receiver verification remains pending.

## Suggested next task

Run the hardware verification matrix in `.ai/NEXT_TASK.md`, including Song FPS
following and both TRANS output combinations under Video + Timeline Zoom stress.
