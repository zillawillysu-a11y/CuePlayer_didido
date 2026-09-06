# LTC Generator Clips — Phase 2 hardening（MTC 邊界 + exact-end 語義統一）
Date: 2026-09-06. Branch: technical-audit-0815-028d.
Upstream: origin/cursor/technical-audit-0815-028d.
Status: complete（僅 Phase 2 hardening；未動 Phase 3 UI / Exporter）。

## Task objective（使用者指定，兩個邊界問題）
1. MTC Quarter Frame 在 LTC Clip 邊界的「舊 Clip TC 洩漏」：進入新 Clip
   re-anchor 後，不得再送出屬於前一個 Clip TC mapping 的 QF。
2. LTC Clip exact-end boundary 一致性：`clip_at_position()` 原把「最後一個
   Clip 的 exact end」視為 Clip 內，但 generated LTC PCM cache 是
   end-exclusive → domain/display/MTC/audio 邊界語義不一致。統一為
   half-open `[start, end)`。

同時把「回覆一律繁體中文」寫入永久 Agent 規則（AGENTS.md +
`.ai/prompts/cursor_system.md`）。

## 問題確認（都是真的）

### 問題 1：QF 洩漏 — 確認存在
`MtcOutput.tick()` 對每個逾期 QF group 用 `frame_pos = (group*2)/fps` 經
provider 取 TC。當 Clip 邊界**不落在 2-frame QF 網格**上時（例如 4.05s =
frame 121.5），engine 層 re-anchor（`on_seek(pos)` →
`_reset_qf_index = int(pos*qf_rate)-1`）**之後**的第一個 group 的
`frame_pos` 仍可能在舊 Clip 內 → re-anchor 的 Full Frame 之後立刻送出舊
Clip TC 的 QF。實測（1ms 步進模擬播放 + 假 MIDI port 捕獲）確認：
re-anchor 後送出的 QF group 解碼到 A 的 TC（01:00:xx），而非 B（02:00:xx）。
engine 層 key re-anchor 只處理「group 完全逾期」的情況，處理不了
「group index 跨越 re-anchor 點」的邊界情況。

### 問題 2：exact-end — 確認存在
舊 `clip_at_position()` 對任何 Clip 的 exact end point（無後續 Clip 接續
時）仍回傳該 Clip → `ltc_timecode_at()` / display / MTC source key 認為
「有 TC」，但 PCM cache（end-exclusive）已 silence。四層不一致。

## 修正內容

### `src/cueplayer/playback/mtc_output.py`（最小修正，僅 provider 模式生效）
`tick()` 內、送 QF group 前新增 stale guard（`self._tc_provider is not
None` 時才執行；legacy 單一 timebase 路徑零改動）：
- `tc_now = provider(current_pos)` 為 `None`（現在在 gap / 無 TC）→ 該逾期
  group 已過期 → `_reset_qf_locked(now)` 並停止本 tick 後續 group（無 Full
  Frame，因現在沒有 TC）。
- 否則連續性檢查：`add_frames(tc_of_group, round((now - frame_pos)*fps), fps)`
  與 `tc_now` 相差 > 1 frame → mapping 在 group frame 與 now 之間改變
  （跨入另一個 Clip）→ **跳過整個 stale group**
  （`_last_qf_index = (group+1)*8 - 1`；plain reset 會把該組重新排隊造成
  每 tick 重複丟棄的死鎖）→ 送 `now` 的 Full Frame → 本 tick 停止，下個
  tick 從下一個 group 再開頭（piece 0 起，receiver 乾淨 latch）。
- 容差 1 frame：同 Clip 內因 round() 產生的 ±1 frame 誤差不會誤觸發；
  連續 TC 的相鄰 Clauses（A 尾 == B 頭）不會誤殺（該 QF 本來就是對的）。

### `src/cueplayer/domain/ltc_clips.py`
`clip_at_position()` 統一 half-open `[start, end)`：
- `pos < start - POS_EPS` → 外；`pos >= end - POS_EPS` → 外。
- 共享邊界（A.end == B.start）自然屬於 B（later-start wins 規則保留，
  overlap 時仍是後起始者贏）。
- 最後一個 Clip 的 exact end → `None`（無 TC / silence），不再有
  「最後 Clip 含端點」特例。
- `POS_EPS` 只吃浮點表示噪音（±1µs），真實 sample 距離邊界至少 1 個
  sample（48kHz 下 ≈20.8µs），語義與 PCM cache 完全一致。
- `ltc_timecode_at` / display / MTC source key 都走 `clip_at_position`，
  一次修改四層同時一致。

### 永久規則
- `AGENTS.md` 新增「Communication language (permanent)」section。
- `.ai/prompts/cursor_system.md` 的 Language section 改為同一規則。

## 新增 regression tests

`tests/playback/test_ltc_clip_playback.py`（+6 tests）：
- `test_mtc_adjacent_clips_no_previous_clip_qf_leak`：A=[2,4.05) @01:00:00:00
  → B=[4.05,6.05) @02:00:00:00（無 gap、TC 差 1 小時、邊界 off-grid）。
  1ms 步進模擬播放 + 假 port 捕獲；斷言：進入 B 後有 B Full Frame + B QF；
  **任何含邊界後 piece 的完整 QF group 都必須是 B 的 TC**（含「前 6 piece
  在邊界前已送出」的跨邊界 group — 這正是舊實作會漏的情況）。
  *已驗證：移除 guard 時此測試失敗（抓到洩漏）。*
- `test_mtc_gap_then_clip_b_only_b_qf`：gap 期間零 MTC（無 Full Frame、無
  QF）；進入 B 後只有 B 的 Full Frame / QF。
- `test_mtc_backward_tc_clip_no_forward_leak`：B 的 start TC 比 A 更早
  （backward jump）；進入 B 後不得出現 A 的前進 TC QF。
- `test_exact_end_boundary_consistent_across_audio_display_mtc`：單 Clip
  [2,5)：exact start 四層都有 TC；end 前 1 frame（4.9667s）四層都有 TC
  （01:00:02:29）；exact end（5.0）四層全部「無 TC / silence / key=none」；
  MTC 在 5.0 之後零輸出。
- `test_adjacent_exact_boundary_belongs_to_b_in_all_layers`：A=[1,3)、
  B=[3,5)：3.0 在 domain / audio / MTC key 三層都是 B；3.0 前 1 frame 仍
  是 A。

`tests/domain/test_ltc_clips.py`（+1 test，2 個既有測試改語義）：
- `test_clip_at_position_half_open_boundaries`（新增）。
- `test_last_clip_includes_its_end_point` → `test_exact_clip_end_has_no_timecode`
  （exact end 改斷 None；end 前 1 frame 仍 inside）。
- `test_gap_between_clips_has_no_timecode`（30.0 由「01:00:30:00」改為
  None；補 29.966 仍 inside）。

## Files changed
- `src/cueplayer/playback/mtc_output.py`（stale guard）
- `src/cueplayer/domain/ltc_clips.py`（half-open `clip_at_position`）
- `tests/playback/test_ltc_clip_playback.py`、`tests/domain/test_ltc_clips.py`
- `AGENTS.md`、`.ai/prompts/cursor_system.md`（繁體中文永久規則）

## Tests performed
- 新文件全綠：`tests/playback/test_ltc_clip_playback.py` **25/25**、
  `tests/domain/test_ltc_clips.py` **21/21**。
- Guard 有效性：暫時移除 guard → adjacent + backward 兩測試失敗（證明測試
  抓得到洩漏）；還原 → 全綠。
- 全相關 regression（除 flaky 的 `test_video_sync.py` 與 `tests/ui`）：
  **951 passed, 3 failed** — 3 個 failed 全部為 clean tree 既有的
  （`test_ndi_probe` DLL-path、2× `test_song_use_left_ltc` route-map），
  已於先前 session 以 `git stash` 驗證與本次改動無關。
- `tests/playback/test_video_sync.py`：82 passed / 1 failed
  （`test_duplicate_decoded_frame_is_not_reemitted`，與 clean tree 相同）。
- `tests/ui`：崩潰前 2 個 F 為既有 font-rendering failure
  （`test_clock_fit_narrow_panel`）；其後 `webrtc_listen` asyncio 線程
  Windows stack overflow crash — 既有環境性 flake（web_remote + asyncio，
  與本次改動無關模組）。

## Remaining issues
- `tests/ui` 在 Windows 上偶發 `webrtc_listen` asyncio stack overflow
  crash（既有、環境性，未在本次 scope）。
- 上述 3+1+2 個既有 test failures 與本次無關，留待後續清理。
- MTC guard 的連續性容差為 1 frame：TC 差恰為 1 frame 的 degenerate
  backward 設定下，stale group 可能不被丟棄（該設定本身會被
  `validate_ltc_clips` 警告）。
- Phase 3（Clip UI）尚未開始 — 見 `.ai/NEXT_TASK.md`。

## Suggested next task
Phase 3：LTC Generator Clip UI（timeline 顯示 / create / drag / trim /
start TC 編輯 / validation / source mode / `refresh_song_ltc_routing`
接線）。MA2/MA3 Exporter 移到 Phase 4。
