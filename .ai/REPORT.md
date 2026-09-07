# DirectSound + MTC Regression — Pre/Post MTC Thread Comparison

Date: 2026-09-08

Branch: `technical-audit-0815-028d`

Regression commit: `fe5097667b8ef48b087f20b511f3b48b2e9c75e7`

Parent: `9e899ffcd627926335177f7e4cf161d1a6545384`

## Task objective

以 Git history、hardware PERF 與 deterministic fake-clock/fake-MIDI 比較，找出
`fe509766` 將 MTC 從 GUI `QTimer` 移到 fixed 4 ms daemon thread 後，為何只在
DirectSound + MTC ON 發生 severe stutter；在不恢復 GUI dependency、不降低 MTC
正確性、不改 LTC/AudioEngine 大架構的前提下做最小 production fix。

## What was implemented

### `fe509766` 前後精確差異

| 行為 | Parent `9e899ff`（修改前） | `fe509766`（修改後） |
|---|---|---|
| scheduler | `QTimer(self)`，interval 4 ms | daemon `Thread` + shared `Event.wait(0.004)` |
| thread | QObject 所屬 GUI thread | 每次 play/resume 新建 Python thread `mtc-tick` |
| wake | nominal 250/s；實際受 Qt event loop/coalescing/modal loop 影響 | 接近 250/s，與 GUI 無關，固定喚醒 Python thread |
| clock read | 每個實際 timer timeout 讀一次 `raw_position` | 每個 4 ms wake 讀一次，接近 250 lock attempts/s |
| generation/send | 每 tick 檢查 `int(position×fps×4)`；只為到期 QF 建 message/send | 完全相同；該 commit 未改 `MtcOutput.tick()` 或 backend |
| locks | 短暫讀 AudioEngine lock；MTC lock 包 tick/send | 同一 clock lock改由 sender thread取得；send前 AudioEngine lock已釋放 |
| allocations | engine init 建一個 QTimer並重用 | 每次 play/resume 建 Thread；Event在 init建；每個 wake有 Python call/context switch |
| stop/start | 同一 QTimer start/stop，無 join | Event set、join最多 1 s、清 reference；下一次建新 Thread |
| seek | GUI直接 `on_seek`，下一 timer繼續 | 同一 `on_seek`，可與 sender並行；sender仍每 4 ms醒來 |
| pause | playing false → timer stop → `on_pause` | playing false → Event set/join → `on_pause` |
| title-bar/modal | GUI timer停，MTC/Cue Notes中斷 | sender繼續，不依賴 GUI |

舊 QTimer不是 deadline-only scheduler：GUI event loop正常時也標稱每 4 ms完整執行
`_mtc_tick()`，包含 clock read、source/loop checks、`MtcOutput.tick()`及
`MidiCueNotes.update()`。舊資料沒有真實 timer callback counter，所以不能聲稱歷史實際
恆為 250/s；可確定設定值是 250/s，且 GUI busy/coalescing會降低、modal loop會歸零。
`fe509766` 則把近 250/s變成固定的 Python thread wake/context-switch壓力。

### Regression cause 與逐項排除

- **A/B/C/E 是 confirmed architecture cause**：hardware regression boundary正是
  `fe509766` 前後；該 commit唯一新增的持續 runtime壓力是 dedicated Python thread每
  4 ms取得 GIL、讀 sample clock/lock、跑 MTC/Cue Note logic。DirectSound callback
  period約 15.29 ms，平均每 period插入約 3.82次 Python wake；此 scheduling/GIL壓力
  能解釋 B4 unique regression。
- **D MIDI backend不是 primary root cause**：commit未改 Mido/python-rtmidi/WinMM或
  send math；send仍只有 96–120 QF/s。實機 send mean約 0.278 ms、max約 8.755 ms，
  backend latency可能放大 thread cost，但不是新機制。
- **AudioEngine lock不是 primary root cause**：send前已釋放該 lock；deterministic test
  證明 port.send時 lock可立即取得。實機 callback lock wait mean約 0.00128 ms、max
  約 0.259 ms，不支持 severe blocker。fixed polling確實造成多餘 clock reads，修正後降低。
- **沒有兩個 scheduler**：production source已無 `_mtc_timer`；唯一 start call在 `play()`。
- **duplicate generation不是本次 hardware主因，但有真實 latent漏洞**：舊 shared Event
  在 tick/send卡超過 1 s時，stop timeout後清 reference；下一 start會 clear同一 Event，
  舊 thread可復活。實機 send max 8.755 ms沒有 evidence它曾觸發。blocked-tick test已證明
  hazard；現改為 per-generation Events、generation guard、舊代 alive時拒絕新 start。

### Quarter-frame cadence

| FPS | required QF/s | deadline period | 250 Hz over-poll |
|---:|---:|---:|---:|
| 24 | 96 | 10.4167 ms | 2.604× |
| 25 | 100 | 10.0000 ms | 2.500× |
| 29.97 | 119.88 | 8.3417 ms | 2.086× |
| 30 | 120 | 8.3333 ms | 2.083× |

Controlled 1-second comparison（含 t=0 sample）為舊 scheduler 251 logic calls；新 deadline
positions分別 97/101/120/121 calls，兩邊 QF bytes完全相同。

### Production fix

- Dedicated sender保留，但改為：從唯一 Playback Engine sample position執行到期工作 →
  計算下一 QF與下一 enabled cue-note deadline → Event等到最早 deadline或明確 wake
  （seek/song/source change）→ 再讀 sample clock/send。
- 沒有 fixed polling、arbitrary sleep、audio-callback send或第二 clock。wall clock只決定
  何時醒來；訊息內容與到期判斷仍由 AudioEngine sample position決定。
- pause/stop/shutdown set stop+wake+bounded join；thread未退出就保留 reference並拒絕新代。
  每代獨立 Event，舊代不會被下一次 start `clear()`復活。
- diagnostics新增 generation id、start/stop、live/duplicate count/peak、wakeups/s、clock
  reads/s、MIDI sends/s。
- title-bar/modal continuity保留：sender完全不依賴 Qt event loop。

## Files changed

- `src/cueplayer/playback/audio_engine.py`
- `src/cueplayer/playback/mtc_output.py`
- `src/cueplayer/playback/midi_cue_notes.py`
- `tests/playback/test_mtc_deadline_scheduler.py`（new）
- `tests/playback/test_mtc_gui_stall_independence.py`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-09-08_DirectSound_MTC_Regression.md`（new）

## Architecture decisions

- AudioEngine sample position仍是唯一 clock；Event timeout不是 TC source。
- 不 revert GUI QTimer，因此 Windows title-bar/native modal loop仍不會中斷實際 MTC。
- 既有 QF index、0→7 order、bounded discontinuity re-anchor、play/seek full-frame不變。
- 29.97沿用既有 semantics（119.88 QF/s；rate bits保持既有 30 NDF handling）；不在本輪
  擴張 drop-frame redesign。
- Notes-only模式直接等下一 enabled mark deadline，不保留 4 ms mark-list polling。
- 未改 LTC、DirectSound buffer、audio callback、Timeline、Video、Art-Net、exporter或 persistence。

## Tests performed

```text
Focused MTC/scheduler/timecode: 42 passed
Playback + timecode (excluding known native-crash test_video_sync.py):
357 passed, 3 known/environment failures
- 2 existing test_song_use_left_ltc routing expectation failures
- 1 environment-specific NDI runtime search-path failure
Same set excluding those three known/environment files: 351 passed
compileall: passed
git diff --check: passed (only expected LF→CRLF notices)
ruff: unavailable in repo virtualenv; not claimed
```

Deterministic coverage：24/25/29.97/30 exact QF order/no duplicate/no skip；old polling vs
deadline same bytes；play/pause/resume/seek/stop；repeated lifecycle；Song/device switch；
blocked stale generation；AudioEngine lock release before send；zero Qt event-loop processing；
variable callback frame cursor continuity。Correctness assertion不依賴 wall-clock message count。

## Remaining issues

- CI fake backend無法聽到真實 DirectSound output；architecture differential、protocol
  equivalence與 lifecycle已證明，但仍須同一劇場 Focusrite DirectSound + MTC ON post-fix
  實機確認，才可把 hardware outcome標為 closed。
- Post-fix PERF應看到 wake/clock rate接近所選 FPS的 96–120/s，而非約 250/s；send cadence
  不應下降，duplicate sender應為 0。
- `.pytest_cache`既有 Windows access-denied warning與本輪無關。

## Suggested next task

在同一劇場 Song／Focusrite endpoint執行 post-fix DirectSound + MTC ON 10秒實機驗證：
確認 severe stutter消失、title-bar hold期間 MTC不中斷，保存 callback continuity、MTC
wake/clock/send rates與 lifecycle counters；只驗證，不再改 LTC或 buffer。
