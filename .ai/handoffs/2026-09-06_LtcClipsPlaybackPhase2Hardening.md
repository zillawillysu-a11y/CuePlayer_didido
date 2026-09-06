# LTC Generator Clips — Phase 2 hardening（MTC 邊界 + exact-end 語義統一）
Date: 2026-09-06. Branch: technical-audit-0815-028d.
Upstream: origin/cursor/technical-audit-0815-028d.
Status: complete（僅 Phase 2 hardening；未動 Phase 3 UI / Exporter）。

## Task objective
使用者指定兩個 Phase 2 邊界問題（不帶進正式劇場使用）：
1. MTC QF 在 Clip 邊界的舊 Clip TC 洩漏：進入新 Clip re-anchor 後，不得
   再送出屬於前一個 Clip TC mapping 的 QF。
2. exact-end boundary 一致性：domain `clip_at_position()` 原把 Clip 的
   exact end 視為「內」（最後 Clip 特例），但 generated LTC PCM 是
   end-exclusive → audio / MTC / display 不一致。統一 half-open
   `[start, end)`。

另：把「與使用者聊天回覆 / Phase 完成摘要 / 問題說明一律繁體中文」寫入
永久 Agent 規則。

Out of scope（使用者明確排除）：LTC Clip UI、timeline drag/trim、
Exporter、Export Preview、任何 Phase 3+ 功能。

## What was implemented

### 問題確認（兩者都是真的）
- **QF 洩漏**：`MtcOutput.tick()` 對逾期 QF group 用
  `frame_pos = (group*2)/fps` 經 provider 取 TC。當邊界不在 2-frame 網格
  上（如 4.05s = frame 121.5），engine re-anchor（
  `_last_qf_index = int(pos*qf_rate) - 1`）後的第一個 group 的 `frame_pos`
  仍可能在舊 Clip → Full Frame 後立刻送出舊 Clip TC 的 QF。1ms 步進模擬
  + 假 port 實測確認（解碼到 A 的 01:00:xx，非 B 的 02:00:xx）。
- **exact-end**：舊 `clip_at_position()` 對 exact end（無後續 Clip）回傳
  該 Clip → display/MTC 認為有 TC，PCM 卻已 silence。

### `src/cueplayer/playback/mtc_output.py`（最小修正）
`tick()` 送 QF group 前新增 stale guard（只在 `self._tc_provider is not
None` 時生效；legacy timebase 路徑零改動）：
- 現在位置無 TC（`tc_now is None`，gap/clip 外）→ 逾期 group 過期 →
  `_reset_qf_locked(now)` + 停止本 tick（無 Full Frame）。
- 連續性檢查：`add_frames(tc, round((now-frame_pos)*fps), fps)` 與
  `tc_now` 差 > 1 frame → mapping 改變（跨 Clip）→ **跳過整組**
  （`_last_qf_index = (group+1)*8 - 1`；plain reset 會讓該組重排隊 → 每
  tick 重複丟棄死鎖）→ Full Frame（`now` 的 TC）→ 本 tick 停，下 tick 從
  下一組 piece 0 再開。
- 容差 1 frame 避免 round() 誤觸發；TC 連續的相鄰 Clauses 不會誤殺。

### `src/cueplayer/domain/ltc_clips.py`
`clip_at_position()` → half-open `[start, end)`：`pos < start - POS_EPS`
或 `pos >= end - POS_EPS` 皆為外；共享邊界屬於後一個 Clip（later-start
wins 保留）；最後 Clip 的 exact end → `None`。`POS_EPS`（1µs）只吃浮點
噪音，真實 sample 距邊界 ≥ 1 sample。`ltc_timecode_at` / display / MTC
key 全走同一函數 → 四層一次一致。

### 永久規則
- `AGENTS.md`：新增「Communication language (permanent)」。
- `.ai/prompts/cursor_system.md`：Language section 改為同一規則。

### Tests
`tests/playback/test_ltc_clip_playback.py`（+6）：
- `test_mtc_adjacent_clips_no_previous_clip_qf_leak`（A=[2,4.05) @01:00 →
  B=[4.05,6.05) @02:00，off-grid 邊界；斷言含邊界後 piece 的完整 QF group
  必須是 B 的 TC — 抓「跨邊界 group」）。*移除 guard 時此測試失敗。*
- `test_mtc_gap_then_clip_b_only_b_qf`（gap 零 MTC；B 後只有 B）。
- `test_mtc_backward_tc_clip_no_forward_leak`（backward jump 無 A 洩漏）。
- `test_exact_end_boundary_consistent_across_audio_display_mtc`（exact
  start / end 前 1 frame / exact end 四層一致；5.0 後 MTC 零輸出）。
- `test_adjacent_exact_boundary_belongs_to_b_in_all_layers`（3.0 屬 B；
  前 1 frame 屬 A）。

`tests/domain/test_ltc_clips.py`：+`test_clip_at_position_half_open_boundaries`；
`test_last_clip_includes_its_end_point` → `test_exact_clip_end_has_no_timecode`；
`test_gap_between_clips_has_no_timecode` 改 30.0 → None。

## Files changed
- `src/cueplayer/playback/mtc_output.py`
- `src/cueplayer/domain/ltc_clips.py`
- `tests/playback/test_ltc_clip_playback.py`
- `tests/domain/test_ltc_clips.py`
- `AGENTS.md`、`.ai/prompts/cursor_system.md`

## Architecture decisions
- Guard 放 `MtcOutput.tick()` 內（而非只靠 engine key re-anchor）：MTC
  自身對「mapping 改變」自保護，engine re-anchor 仍是第一線；兩者皆
  冪等（重複 Full Frame 對 receiver 無害）。
- 不改變 provider 契約（仍 `pos -> Timecode | None`）；用「連續性 + 1
  frame 容差」判斷 mapping 改變，避免引入 segment id 的 API 擴充。
- exact-end 採 `[start, end)` 與 PCM cache、`LtcClipTcRange`
  （start inclusive, end exclusive）及一般 timeline/audio 慣例一致。
- 繁體中文規則寫 AGENTS.md（每個 session 都會讀）+ system prompt 雙保險。

## Tests performed
- `test_ltc_clip_playback.py` **25/25**；`test_ltc_clips.py` **21/21**。
- Guard 有效性 A/B：移除 guard → adjacent + backward 測試失敗；還原 → 綠。
- 全相關 regression（除 flaky video_sync / ui）：**951 passed, 3 failed**
  （3 個皆 clean tree 既有：`test_ndi_probe`、2× `test_song_use_left_ltc`）。
- `test_video_sync.py`：82 passed / 1 failed（同 clean tree）。
- `tests/ui`：既有 font failure + 偶發 `webrtc_listen` asyncio stack
  overflow crash（既有環境性 flake）。

## Remaining issues
- `tests/ui` 偶發 `webrtc_listen` asyncio stack overflow（既有）。
- 上述既有 failures 未在本次 scope。
- Guard 容差 1 frame：TC 恰差 1 frame 的 degenerate backward 設定下 stale
  group 可能不被丟棄（該設定會被 `validate_ltc_clips` 警告）。
- Clip UI（Phase 3）未開始。

## Suggested next task
Phase 3：LTC Generator Clip UI only（timeline 顯示 / create / drag / trim /
start TC edit / validation & warnings / source mode UI /
`refresh_song_ltc_routing` 接線）。MA2/MA3 Exporter → Phase 4。
See `.ai/NEXT_TASK.md`.
