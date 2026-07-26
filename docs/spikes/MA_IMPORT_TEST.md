# onPC 匯出測試說明（修正版）

依你的實測回饋調整：

## 問題與對策

| 問題 | 對策 |
|------|------|
| MA2 Sequence 可 import，但 Timecode 認不到（Seq 沒掛 Executor） | 產生 **Plugin**：Import Seq → Assign Exec → Import TC |
| MA3 Sequence 認不到（先前 XML 屬性不完整） | Sequence 屬性對齊你可 import 的 golden |
| MA3 Timecode 可 import | 保留；改用 **Macro** 一次裝好 Seq+Exec+TC |
| 希望之後只更新 Timecode | 支援 `export_mode="timecode_only"` |

## 這次測試檔位置

專案：

- `fixtures/export_test/ma2/`
- `fixtures/export_test/ma3/`

### MA3（建議先測）

1. 把下列檔案放到 library：
   - Sequence：`datapools/sequences/cueplayer_test_main.xml`
   - Sequence：`datapools/sequences/cueplayer_test_button.xml`
   - Timecode：`datapools/timecodes/cueplayer_test_timecode.xml`
   - Macro：`datapools/macros/cueplayer_install_macro.xml`
2. Import Macro `CuePlayer Export` 後執行  
   （或手動 Import Sequence → Assign 到 Page 1.101 / 1.201 → Import Timecode）

Macro 內設定 Key 的正確語法：

- `Assign Go+ At Page 1.101`
- `Assign Top At Page 1.201`

（舊版錯誤的 `/Key=Top` 會停在 Handle 頁面，已修正）

預設：

- Main Seq 1 → Page **1.101** Key=Go+
- Button Seq 2 → Page **1.201** Key=Top
- Timecode 1

### MA2

建議優先用 **Macro**（比較穩，不必靠 Lua runtime）：

1. Sequence / Timecode XML 放到 `gma2_V_3.9.61/importexport/`
2. Macro：`cueplayer_install_macro.xml`  
   Import 到 Macro pool 後執行 `CuePlayer Export`

也可選 Plugin（CuePoints 同款 `.xml` + `.lua`）：

1. 兩個檔必須同名配套：
   - `cueplayer_export.xml`（內含 `luafile="cueplayer_export.lua"`）
   - `cueplayer_export.lua`
2. 放到 `plugins/`，Import 的是 **.xml**，再 Go+ Plugin

先前自動產生的 Plugin XML 誤用了 MA3 的 `ComponentLua` 結構，已改成真正 MA2 的 `luafile=` 格式。

3. Plugin／Macro 都會：Import Seq → Assign Exec → Assign Go/Top → Import TC

## Timecode-only 更新（之後正式流程）

第一次用 full 裝好 Seq+Exec。  
之後在 CuePlayer 改 Marks，只匯出 Timecode，再 Import／覆蓋同一個 Timecode pool。  
前提：Sequence 名稱與 Executor 綁定維持不變。

## LTC 延遲補償（重要）

用 LTC 觸發 MA 時，常會覺得 cue 晚了約 **0.1s～0.2s**（CuePoints 也有類似 Global Latency Negative Offset）。

CuePlayer 匯出：

- **起始 Timecode**（如 `01:00:00:00`）寫進 Timecode 物件的 **Offset**，事件時間維持歌曲相對時間（與 CuePoints 相同）。
- `ltc_latency_compensation_seconds = -0.10` / `-0.15` / `-0.20`：負值 = 事件提前，抵消 MA／LTC 延遲；只影響 Timecode 事件時間，不改 Marks。

之後 UI 會做成可選補償值；現在程式層已支援。

## 請回報

1. MA3 Sequence 這次能否 import？
2. MA3 Macro 能否跑完並讓 TC 對到 Exec？
3. MA2 Plugin 能否把 Seq 掛上 Exec 且 TC 可用？
4. 指令語法若 onPC 報錯，把錯誤原文貼給我。
