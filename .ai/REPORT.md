# MTC Sender Starvation / Clock-Read Lock Contention Fix

Date: 2026-09-08. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

依使用者實測（30 秒內 Video decode submissions 523、Audio underflow 0，但 MTC
仍偶發 drop），診斷 sender starvation / clock-read lock contention，加入
per-wakeup lateness、missed-QF、catch-up 證據，再做最小 production fix；不降低
QF cadence、不改 audio buffer、不把 MTC 放回 GUI `QTimer`。

## What was implemented

### Diagnosis

- `audio.callback.output_underflow_count == 0` 只證明該次 PortAudio callback 沒有
  失約，不能證明獨立的 Python `mtc-tick` thread 有準時取得執行時間。
- 舊 sender loop 是 `Event.wait(0.004)` 後再執行整個 tick，實際週期因此是
  `4 ms + clock read + LTC mirror check + MIDI send + cue-note scan`；每次工作時間
  都永久累積成 drift，負載下更容易一次欠多個 QF。
- 舊 `_mtc_tick()` 透過 `raw_position` 取得 `AudioEngine._lock`，而 PortAudio
  callback 在同一把鎖內完成 position advance、music/LTC/video mix、routing 與
  write-head stamp。0 underflow 不代表另一條 thread 的 lock wait 是 0。
- 523 次 Video decode submissions 支持 CPU/GIL load correlation，但 Video decoder
  不直接持有 `AudioEngine._lock`，不能單憑該數字宣稱它是 lock contention 的直接原因。

### Minimal production fix

- MTC thread 保持原本 4 ms wake cadence，但改成 `time.monotonic()` absolute
  deadline。tick 工時會從下一個 wait 扣除，不再永久累積；若真的錯過 wake slot，
  跳到下一個 future deadline。QF catch-up 仍由現有 sample-clock-based
  `MtcOutput.tick()` 完成，不緊密重播 sender wake backlog。
- Audio callback／seek／pause 在原本已持有 `_lock` 的 write-head stamp 點發布
  immutable `_mtc_clock_snapshot`。MTC sender 以完整 tuple snapshot 讀取同一個
  sample clock 並沿用既有最多 80 ms extrapolation，不再競爭 `AudioEngine._lock`。
- 30 fps 仍是 120 QF/s；未改 QF rate、8-QF overdue re-anchor 邊界、audio buffer、
  PortAudio callback 或任何 GUI timer。

### Evidence added (`CUEPLAYER_PERF=1`)

- Scheduler：`mtc.scheduler.wakeup_lateness_ms`、`wakeups`、`missed_wake_slots`。
- Clock：`mtc.clock_read_ms`、`mtc.clock_snapshot_age_ms`。
- Sender phases：`mtc.file_ltc_sync_ms`、`mtc.qf_dispatch_ms`、
  `mtc.cue_dispatch_ms`、`mtc.tick_exec_ms`。
- QF debt：`mtc.missed_qf`、`catch_up_wakeups`、`catch_up_qf`、
  `overdue_reanchors`、`backward_reanchors`、`qf_due_last/max`。
- Delivery：`mtc.qf_sent`、`mtc.qf_send_failures`。
- 新增 `perf.record_batch()`，讓同一 hot-path phase 的多個值只取得一次
  diagnostics lock，降低 instrumentation 本身干擾 4 ms sender 的風險。

## Files changed

- `src/cueplayer/playback/audio_engine.py` — absolute-deadline scheduler、lock-free
  sample-clock snapshot、sender phase metrics。
- `src/cueplayer/playback/mtc_output.py` — QF debt/catch-up/re-anchor/send evidence。
- `src/cueplayer/diagnostics/perf.py` — batched recording 與 MTC report section。
- `tests/playback/test_mtc_gui_stall_independence.py` — deadline、missed wake、report、
  engine-lock independence regressions。
- `tests/playback/test_mtc_discontinuity.py` — QF debt evidence regression。
- `tests/playback/test_ltc_clip_playback.py` — test sample-clock publisher helper。
- `.ai/REPORT.md`、`.ai/handoffs/2026-09-08_MtcSenderStarvationFix.md`、
  `.ai/NEXT_TASK.md`。

## Architecture decisions

- `AudioEngine._position_frame` 仍是唯一 playback clock；snapshot 只是由同一 writer
  critical section 發布的 immutable view，不是第二個 clock。
- 未縮短或搬動 PortAudio mix lock critical section，避免把 show-critical audio
  callback 重構混入本次 MTC fix。
- monotonic deadline 只負責喚醒；輸出 TC 數值仍完全由 sample-clock position 決定。
- 未建立 GUI `QTimer`，未碰 video pipeline、timeline、LTC routing 或 buffer。

## Tests performed

- MTC GUI-stall + discontinuity：**9 passed**。
- MTC/LTC targeted set：**45 passed**。
- Audio callback/device-rate/stream/crash targeted set：**36 passed**。
- `tests/playback` 排除文件化的三個無關 baseline 檔案
  (`test_video_sync.py`, `test_ndi_probe.py`, `test_song_use_left_ltc.py`)：
  **272 passed**。
- Production modules `compileall`：passed。
- `git diff --check`：clean。

## Remaining issues

- 此環境沒有實體／虛擬 MIDI receiver 與 Focusrite，尚未做真實 WinMM port 的
  30–60 秒 zoom/Mark/video-load 壓力驗證。舊 log 不含新增 metrics，必須重跑。
- 若仍 drop：`qf_send_failures` 指 backend；高 wake lateness + 低 tick exec 指
  OS/GIL starvation；高 tick exec 再比較 file-LTC/QF/cue subspan；高 snapshot age
  加 audio callback miss 指 clock publisher；`qf_due_max > 8` / overdue re-anchor
  證明 receiver-relevant 長 gap。
- `clock_read_ms` 修正後應接近零；它證明新 sender read path 無 lock contention，
  不能反推舊 build 當時實際等待了幾 ms。

## Suggested next task

在 Windows 實機以 `CUEPLAYER_PERF=1` 重跑相同 30–60 秒 MTC 壓力情境（持續播放，
密集 Timeline zoom + 建立 Mark，Video Track 保持載入），以 MIDI monitor 確認 gap，
寫出 performance report 並回傳 `MTC sender continuity` 與
`Audio callback continuity`。若仍 drop，只依 metrics 指向的單一長尾來源做下一個
最小修正。驗證前不要開始 Phase B/C 或 Ripple Edit。
