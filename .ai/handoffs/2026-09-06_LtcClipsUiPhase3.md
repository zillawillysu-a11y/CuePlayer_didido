# LTC Generator Clips — Phase 3：Timeline UI / 互動（不含 Exporter）
Date: 2026-09-06. Branch: technical-audit-0815-028d.
Upstream: origin/cursor/technical-audit-0815-028d.
Baseline: c105ec4（Phase 2 hardening 完成點）。
Status: complete（Phase 3 UI 層全部完成；Phase 4 Exporter 未動）。

## Task objective（使用者指定）
在 Timeline 的 LTC Track 上實作 Reaper 風格的 Generator Clip 編輯（`clip_generator`
模式）：clip 的顯示、新增、拖曳、左右 trim、雙擊編輯、删除鍵、選取、上下文選單、
undo/redo、持久化，以及 per-song 的 LTC Source 四模式切換（`off` /
`striped_file` / `full_track_generator` / `clip_generator`；舊 `auto` 只作相容
顯示）。**本 phase 不含 MA2/MA3 Exporter、不改 engine 路由邏輯。**

## What was implemented

### Domain（`src/cueplayer/domain/`）
- `undo.py`：新增 4 個 LTC 指令 + snapshot 型別
  - `LtcClipSnapshot`（clip 表 + source mode 的深拷貝）
  - `AddLtcClipCommand` / `DeleteLtcClipsCommand` / `EditLtcClipsCommand` /
    `SetLtcSourceModeCommand`（都含 redo；edit 支援批量 dict）
  - `UndoStack` 整合上述指令；新增 `last_executed_command` 屬性（不改變
    `UndoStepResult` tuple，向後相容），供 MainWindow 偵測「LTC 指令」以觸發
    `refresh_song_ltc_routing()`。
- `models.py`：`Song.ltc_clip_by_id()` 查詢輔助。

### UI — Timeline（`src/cueplayer/ui/timeline_widget.py`）
- 新增 5 個訊號：`ltc_clip_selection_changed` / `ltc_clips_changed` /
  `ltc_clip_edited` / `delete_ltc_clips_requested` / `add_ltc_clip_requested` /
  `edit_ltc_clip_requested` / `ltc_source_mode_requested`（共 7 個）。
- Clip lane 只在 `clip_generator` 且 song 有 clip 時顯示（`_ltc_lane_visible()`
  對無 stripe 音源的 clip_generator 仍顯示，因為生成的 LTC 才是 bus 來源）。
- Hit-test：clip body（拖曳移動）、左/右 8px trim 邊、空白 lane（清除選取）。
- 拖曳/trim 數學：
  - body drag：`dt = dx / pps`；start 平移、duration 不變、start TC 不變。
  - left trim：`start += dt`、`duration -= dt`、**start TC 固定不變**
    （domain 保證新頭仍送出原 start TC）。
  - right trim：`duration += dt`（修正過一個 off-by-one：以 `end0 + dt` 計算）。
  - clamp：時間軸範圍內；與相鄰 clip 不得 overlap（靠邊相接允許，tolerance
    `POS_EPS`）。
- 選取：點選 / 多選、Delete 鍵删除所選 clip、空白處點擊清除。
- 雙擊 body → `edit_ltc_clip_requested`；空白處雙擊 → `add_ltc_clip_requested`。
- 統一 LTC lane 上下文選單（stripe-inspect 與 clip-editor 狀態皆可達）：
  - **LTC Source** 子選單（4 模式，任一狀態都能切換）
  - clip_generator 時：新增 / 編輯 / 删除 clip
  - gain 線顯示切換 + 重置（保留舊功能）
- 繪製：clip 矩形（可選 gain 線）、⚠ 琥珀標記（TC overlap / backward warning，
  由 `_ltc_clip_tc_warn_ids` 成對計算）、選取 chrome。
- 拖曳期間**不**重建播放（不呼叫 engine）；commit 時才發訊號讓 MainWindow
  刷新 routing。

### UI — 對話框（`src/cueplayer/ui/ltc_clip_dialog.py`，新檔）
- `LtcClipEditDialog`：Timeline Start / Duration / Start Timecode 三欄位
  （`parse_time` / `parse_timecode` 驗證）。
- 時間軸 overlap → **阻止**（回傳 error）；TC overlap / backward → **允許**
  但回傳 warning（由呼叫端顯示）。
- 編輯既有 clip 時可保留自身範圍（overlap 檢查排除自己）。

### UI — 歌曲編輯（`src/cueplayer/ui/song_edit_dialog.py`）
- `SongDraft.ltc_source_mode` 欄位；新增 **LTC Source** 欄
  （Off / Striped File / Full Track Generator / Clip Generator）。
- 舊 `auto` 歌曲在對話框中顯示「解析後結果」，但下拉選單只給 4 個正式模式；
  接受時寫回**明確**模式。
- 三個建立點都傳 `project=self`（讓 auto 解析取得 ltc_enabled 設定）。

### UI — Setlist（`src/cueplayer/ui/setlist_delegate.py` + main_window）
- `ROLE_LTC_MODE` 角色；無 L/R 頻道時徽章顯示 `LTC C`（clip_generator）或
  `LTC G`（full_track_generator）；tooltip 依模式說明。
- `clip_generator` 歌曲的 L/R 頻道 cell 為空（不顯示 file stripe 頻道）。

### UI — MainWindow（`src/cueplayer/ui/main_window.py`）
- 輔助：`_resolved_ltc_mode_for_song()`（legacy `auto` → 依 `ltc_enabled` 解析為
  `off` / `striped_file`）、`_ltc_display_channel_for_song()`、
  `_push_ltc_mode_to_timeline()`。
- 所有 timeline LTC 訊號接到 handler：`_on_ltc_clip_edited` /
  `_on_ltc_clips_changed` / `_add_ltc_clip_at` / `_edit_ltc_clip` /
  `_delete_ltc_clips` / `_on_ltc_source_mode_requested`；commit 後一律
  `AudioEngine.refresh_song_ltc_routing()` + `invalidate_static_layers` +
  setlist LTC cells 刷新。
- undo/redo：`_LTC_COMMAND_TYPES` + `_is_ltc_command()` 偵測 LTC 指令 →
  同樣 routing refresh（含 `last_executed_command`）。
- `_refresh_timeline_waveform_for_ltc()`：clip_generator 時不畫 file stripe
  lane（若先前有則還原完整 waveform）；其餘模式維持 stripe inspect。
  **關鍵決策：只有 `clip_generator` 抑制 stripe 顯示**（`off` 是 factory
  預設 + 舊 auto 解譯結果，仍是「檔案檢查」指標）。
- `_apply_draft_to_song` / `_song_to_draft` 帶 `ltc_source_mode`；
  `_delete_current_selection` 增 LTC clip 分支；`_on_output_quick_toggle` /
  `_open_audio_timecode` / `_apply_empty_project_workspace` 補 push mode。

### 測試
- `tests/domain/test_ltc_clip_undo.py`（新，5）：add/delete/edit/mode 的
  undo+redo + `last_executed_command`。
- `tests/ui/test_ltc_clip_timeline.py`（新，11）：lane 依模式顯示、body drag
  emit 一次、left trim 保 TC、right trim、drag/trim clamp、選取、雙擊
  edit、Delete 鍵。
- `tests/ui/test_ltc_clip_dialog.py`（新，7）：round-trip、不可解析欄位、
  超出歌曲長度、時間軸 overlap 阻止、edit 保留自身範圍、TC overlap /
  backward 允許（warning）。
- `tests/ui/test_setlist_ltc_indicator.py`（修 1）：清 in-memory
  `window._audio_ltc_cache` 強制冷 cache（舊 disk cache 造成 flaky，非本
  phase 引入）。

## Files changed
- `src/cueplayer/domain/undo.py`
- `src/cueplayer/domain/models.py`
- `src/cueplayer/ui/ltc_clip_dialog.py`（新）
- `src/cueplayer/ui/timeline_widget.py`
- `src/cueplayer/ui/song_edit_dialog.py`
- `src/cueplayer/ui/setlist_delegate.py`
- `src/cueplayer/ui/main_window.py`
- `tests/domain/test_ltc_clip_undo.py`（新）
- `tests/ui/test_ltc_clip_timeline.py`（新）
- `tests/ui/test_ltc_clip_dialog.py`（新）
- `tests/ui/test_setlist_ltc_indicator.py`

## Architecture decisions
1. **只有 `clip_generator` 抑制 file stripe 顯示**：L/R 徽章與 stripe lane 是
   「檔案檢查」指標，與輸出啟用否無關；`off`（factory 預設）保留舊 inspect
   行為。clip_generator 時生成的 LTC 擁有 bus，file stripe 不再是來源。
2. **統一 LTC lane 上下文選單**：LTC Source 子選單在 stripe-inspect 與
   clip-editor 狀態都出現 → 4 模式從任一狀態可達。
3. **拖曳不觸發 engine**：所有 live 更新只改 timeline 視覺；commit（release /
   dialog accept）才發訊號 → MainWindow 才 `refresh_song_ltc_routing()`。
4. **TC overlap / backward = warning（允許）**；時間軸 overlap = 錯誤（UI 層
   clamp + dialog 阻止）。domain `validate_ltc_clips` 的 warnings 由 timeline
   成對計算顯示 ⚠。
5. **`UndoStack.last_executed_command`**：不加進 `UndoStepResult` tuple
   （向後相容），供 undo/redo 後偵測 LTC 指令做 routing refresh。
6. **PySide6 測試取巧**：`LOAD_ATTR` 對 TimelineWidget 私有屬性的外部直讀在
   offscreen 環境間歇性 AttributeError（`getattr` / 方法呼叫穩定）→ 測試統一
   用 `getattr(timeline, ...)` 讀 `_pixels_per_second` / `_song`（有註解說明）。

## Tests performed
- 新測試 23 個全綠（5+11+7）；setlist 指標 2 綠。
- `-k "ltc"` 全組：**162 passed, 2 failed**（2 個為既有
  `test_song_use_left_ltc` routing 斷言，baseline c105ec4 已失敗，非本 phase）。
- 目標域（domain + 12 個 UI 相關檔）：**253 passed**。
- main-window / song-edit / undo 6 檔：**13 passed**。
- 新 timeline/dialog 測試連續 5 次全綠（防 flaky）。
- 既有失敗（已在多個 baseline 驗證非本 phase）：2× `test_song_use_left_ltc`、
  `test_ndi_probe` DLL 路徑、chunk-2 的 9 個 UI 測試、
  `test_cue_list_playhead_scroll` Windows stack overflow（hard crash）。

## Remaining issues
- PySide6 `LOAD_ATTR` 間歇性怪異未根治（只在測試外部讀取觸發；生產代碼方法內
  讀取未見失敗）。已用 `getattr` 規避並在測試註解記錄。
- Phase 4（Exporter）未做：MA2/MA3 對 `clip_generator` 的 Timecode Events
  分割邏輯（out-of-clip marks 無 Timecode Event + warning 清單；一 song 一個
  Timecode object）。
- 未驗證實體硬體下的 clip 邊界音頻（engine 層 Phase 2 已有 46 個
  domain+playback 測試涵蓋）。

## Suggested next task
**Phase 4：MA2/MA3 Exporter 接線（`clip_generator`）** — 依 NEXT_TASK.md 描述：
full_track_generator 數學不變；clip_generator 只對 clip 內 marks 出 Timecode
Events，out-of-clip marks 仍出 Sequence Cue 但無 Timecode Event 並列入 warning；
**不要**每 clip 建多個 MA Timecode object（一 song 一個，plan 帶 per-clip TC
mapping）；overlapping/backwards TC ranges 在 export report 驗證 + 警告。
