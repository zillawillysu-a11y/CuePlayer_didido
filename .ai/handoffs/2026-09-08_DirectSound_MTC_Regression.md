# DirectSound + MTC Regression — Pre/Post MTC Thread Comparison

Date: 2026-09-08. Branch: `technical-audit-0815-028d`.

## Task objective

比較 `fe509766`（parent `9e899ff`）前後 MTC scheduler，找出 DirectSound + MTC ON
severe stutter regression，並在保留 title-bar continuity下做最小修正。

## What was implemented

- Diff證明 protocol/backend未變；差異是 GUI 4 ms QTimer改為 dedicated Python thread
  `Event.wait(0.004)`，讓近 250/s Python/GIL/clock work變成獨立 thread固定喚醒。
- 24/25/29.97/30只需 96/100/119.88/120 QF/s；over-poll為
  2.604×/2.500×/2.086×/2.083×。
- Sender改為 GUI-independent、sample-clock deadline-driven wait；MTC/Cue Notes只在下一
  deadline或 seek/song/source wake執行。
- 排除 QTimer+daemon雙 scheduler。找到 shared Event+timed join可復活 stale thread的 latent
  漏洞；實機 send max不支持它是此次主因，但已用 per-generation Events、guard與
  no-overlap start修正。
- 加入 wake/clock/send rate與 thread lifecycle diagnostics。完整 evidence見 REPORT。

## Files changed

`audio_engine.py`、`mtc_output.py`、`midi_cue_notes.py`、新的 deadline scheduler tests、
更新的 GUI-independence test，以及 `.ai/REPORT.md`、`.ai/NEXT_TASK.md`、本 handoff。

## Architecture decisions

AudioEngine sample position仍是唯一 clock；dedicated sender不依賴 Qt。沒有 callback MIDI
send、fixed polling、buffer workaround或 LTC/Video/Timeline/Art-Net變更。QF math/order與
play/seek full-frame semantics保持不變。

## Tests performed

- Focused：42 passed。
- Playback+timecode（排除 known native-crash video_sync）：357 passed，3 known/environment
  failures；排除該 3 files後 351 passed。
- 四 FPS exact order/no duplicate/no skip；old vs deadline same bytes；transport/lifecycle/
  Song/device switch；stale generation；lock release；zero Qt event-loop。
- compileall/diff-check passed；repo venv無 ruff。

## Remaining issues

需同一劇場 Focusrite DirectSound + MTC ON做 post-fix硬體確認；CI只能確認 scheduler
pressure移除、callback cursor continuity與 protocol equivalence。

## Suggested next task

依 `.ai/NEXT_TASK.md` 驗證 stutter消失、title-bar MTC不中斷、wake/clock rate為 FPS×4、
duplicate sender為 0；驗證後停止。
