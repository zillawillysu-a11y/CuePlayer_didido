# Phase 3 hardening — 保留 legacy LTC Source auto
Date: 2026-09-06. Branch: technical-audit-0815-028d.
Baseline: a05c823. Upstream: origin/cursor/technical-audit-0815-028d.

## Task objective
修正 SongEditDialog 未操作 LTC Source、只按 OK 就將 legacy `auto` 永久改為解析後模式的相容性問題。

## What was implemented
- 每列記錄 QComboBox `activated` 使用者選擇事件；未操作的 legacy `auto` 在接受後仍保留 `auto`。
- UI 維持四個 explicit 選項，legacy auto 仍顯示 resolved result。
- 使用者明確選取（含重新選取目前顯示模式）後才轉為 explicit mode；程式設定 index 不視為使用者操作。
- 原本 explicit mode 的接受行為不變；多列編輯互不影響。

## Files changed
- `src/cueplayer/ui/song_edit_dialog.py`
- `tests/ui/test_song_edit_dialog.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-09-06_LtcSourceAutoPhase3Hardening.md`
- `.ai/NEXT_TASK.md`（補交接連結、修正舊 REPORT 引用；下一步仍為 Phase 4）

## Architecture decisions
修改僅限 dialog 的使用者操作追蹤與 draft 讀回，不改 Timeline LTC interaction、playback engine、Phase 2 mapping、MA2/MA3 exporter 或 unrelated flaky tests。以 `activated` 區分顯示初始化與明確選擇，並涵蓋選回同一模式的情況。

## Tests performed
- `python -m pytest tests/ui/test_song_edit_dialog.py -q`：18 passed（14 個新增參數化 regression cases）；pytest cache 路徑權限警告，後續停用 cache plugin。
- `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/ui/test_song_edit_dialog.py tests/ui/test_edit_song_preserves_video.py tests/ui/test_song_edit_bpm_auto.py tests/ui/test_add_song_browse_and_new.py tests/domain/test_ltc_clips.py tests/persistence/test_ltc_clips_schema.py -q`：57 passed。
- `git diff --check` 通過。

## Remaining issues
本次修正無未完成項目；既有無關測試與硬體驗證事項維持原交接。Phase 3 原 handoff 所述「接受時寫回明確模式」由本 hardening 的相容性規則取代。

## Suggested next task
LTC Generator Clips — Phase 4：MA2 + MA3 exporter wiring for `clip_generator`，完整範圍依 `.ai/NEXT_TASK.md`。本次未開始 Phase 4；完成 commit、push、remote 驗證後停止。
