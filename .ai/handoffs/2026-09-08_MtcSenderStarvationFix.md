# MTC Sender Starvation / Clock-Read Lock Contention Fix

Date: 2026-09-08. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

依使用者 30 秒壓力實測（Video decode submissions 523、Audio underflow 0，但 MTC
仍 drop），加入 per-wakeup lateness / missed-QF / catch-up 證據並做最小 sender
修正；不降低 QF cadence、不改 audio buffer、不使用 GUI `QTimer`。

## What was implemented

- 診斷確認 0 underflow 只排除 PortAudio callback miss，不能證明 Python MTC sender
  準時。舊 ticker 的實際週期是 `4 ms wait + tick work`，工作時間會永久累積成
  scheduling drift。
- 舊 MTC clock read 會取得 `AudioEngine._lock`；同一把鎖包住 audio callback 的
  position advance、music/LTC/video mix、routing 與 write-head stamp。0 underflow
  並不等於 MTC lock wait 為 0。
- 4 ms ticker 改用 monotonic absolute deadline；錯過 wake slot 時前進到下一個
  future deadline，由既有 sample-clock QF reconciliation 做 bounded catch-up，
  不緊密重播 sender wake backlog。
- Audio callback／seek／pause 在既有 lock-held stamp 點發布 immutable
  `_mtc_clock_snapshot`；MTC lock-free 讀取同一 sample clock 並沿用 80 ms
  extrapolation cap。這不是第二個 playback clock。
- `CUEPLAYER_PERF=1` 新增 scheduler lateness/missed slots、clock read/snapshot age、
  file-LTC/QF/cue/tick phase timing、missed QF、catch-up、re-anchor、QF sent/failure
  與 debt peak。新增 `record_batch()` 降低 instrumentation lock 干擾。
- 30 fps 仍是 120 QF/s；QF rate、4 ms cadence、8-QF overdue policy、audio buffer、
  PortAudio callback、GUI timer 與 Video pipeline 均未變更。

## Files changed

- `src/cueplayer/playback/audio_engine.py`
- `src/cueplayer/playback/mtc_output.py`
- `src/cueplayer/diagnostics/perf.py`
- `tests/playback/test_mtc_gui_stall_independence.py`
- `tests/playback/test_mtc_discontinuity.py`
- `tests/playback/test_ltc_clip_playback.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-09-08_MtcSenderStarvationFix.md`
- `.ai/NEXT_TASK.md`

## Architecture decisions

- `AudioEngine._position_frame` 仍是唯一 Playback Clock；snapshot 只是一份由同一
  writer 發布的 immutable view，monotonic deadline 也只負責喚醒。
- 未重構 show-critical audio mix lock critical section，只移除 MTC reader 的鎖依賴。
- 未碰 audio buffer、LTC routing、GUI timer、Video/Timeline 或 exporter。
- 523 Video submissions 是 CPU/GIL load correlation，不能證明 Video decoder 直接
  持有 playback lock。

## Tests performed

- MTC GUI-stall + discontinuity：**9 passed**。
- MTC/LTC targeted set：**45 passed**。
- Audio callback/device-rate/stream/crash targeted set：**36 passed**。
- Playback suite（排除三個文件化、無關的 baseline test files）：**272 passed**。
- Production modules `compileall`：passed。
- `git diff --check`：clean。

## Remaining issues

- 本環境無真實 WinMM MIDI receiver／Focusrite；需要新 build 的 30–60 秒實機壓力
  run。舊 log 無法回填新增 metrics。
- 若仍 drop：`qf_send_failures` 指 backend；高 wake lateness + 低 tick exec 指
  OS/GIL；高 tick exec 再比 file-LTC/QF/cue phase；高 snapshot age 加 audio
  callback miss 指 clock publisher；`qf_due_max > 8` / overdue re-anchor 指真正長 gap。
- 修正後 `clock_read_ms` 應接近 0；它不能反推舊 build 當時實際 lock wait。

## Suggested next task

在 Windows 以 `CUEPLAYER_PERF=1` 重跑相同 30–60 秒 MTC 壓力情境，用 MIDI monitor
確認是否仍有 gap，寫出 performance report，回傳 `MTC sender continuity` 與
`Audio callback continuity`。若仍 drop，只修 metrics 指向的單一長尾來源；驗證前
不要開始 Phase B/C 或 Ripple Edit。
