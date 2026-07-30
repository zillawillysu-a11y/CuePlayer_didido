# CuePlayer 使用說明（操作提示）

畫面上不再放長說明文字；常用操作記在這裡。

## Timeline

| 操作 | 說明 |
|------|------|
| 左上 **S** | 拖曳 Mark |
| 虛線框 | 框選 Marks |
| **A / B** | 隨時可拖（Loop 區間） |
| **Ctrl+Z** / **Ctrl+Y** | Undo / Redo |
| **Space** | Play / Pause |
| **← / →** | 微調 playhead（配合修飾鍵可改秒數／Frame） |
| **1–9** | 在 playhead 打對應 Mark |

## Cue List（右側）

| 操作 | 說明 |
|------|------|
| **Shift / Ctrl** | 多選 |
| **Del / Backspace** | 刪除選取 |
| 點 **Time** | 跳到該 Mark |
| 右鍵標題列 | 欄位顯示、Cue List 顯示／隱藏等 |

## 左側 Setlist

| 操作 | 說明 |
|------|------|
| 雙擊 **No. / Name / BPM** | 編輯 |
| 拖欄寬 | 調整欄位寬度 |
| 右鍵 | 資料夾、完整編輯、欄位顯示（Song English / BPM / LTC·Video Output Status） |
| 拖歌曲 | 排序，或拖到 Folder |
| 拖 Folder 標題 | 整夾（含歌曲）上下移動 |
| 拖入音訊／影片 | 新增多首歌 |
| **Ctrl / Shift** | 多選 |

## Set List Sheet

| 操作 | 說明 |
|------|------|
| 欄位 | 曲序、曲名、英文名、Seq、Cue ID、Timecode Generator、BPM、Note |
| Folder 列 ▸/▾ | 展開／收合（與左側 Setlist 獨立） |
| 雙擊儲存格 | 編輯 |
| **Copy All** / **Ctrl+C** | 複製到 Excel / grandMA3 |

## 輸出時鐘（右側大秒數下方）

| 操作 | 說明 |
|------|------|
| **TRANS / Note / MTC / LTC** | 快速開關（開 TRANS／Note／MTC 會自動開 MIDI） |
| 右鍵時鐘區 | 顯示／隱藏時間碼、顯示／隱藏開關列；進階設定 |

## 專案檔與 Bundle

| 選單 | 說明 |
|------|------|
| **File → Collect Project Bundle…** | 複製用到的媒體到資料夾：`專案.cueplayer.json` 在根層、`Media/<Setlist 資料夾>/<歌名>/` 放素材（未分類進 `_Unfiled/<歌名>/`）；波形與 LTC L/R 快取一併沿用。建議選空資料夾。 |
| **File → Relink Missing Media…** | 檔案搬走後單檔或整資料夾依檔名重新連結（遞迴掃媒體副檔名）；同名多份需手動指定。Relink 後請 Save。若檔案是搬移／拷貝且 mtime 相同，波形與 LTC 快取也會沿用。 |

專案資料夾內的媒體存**相對路徑**，整包搬到任何磁碟／路徑仍可開啟。

已存檔且存在 `Media/` 時，在程式裡把歌曲移到 Setlist Folder、或重新命名／刪除 Folder，會同步搬移或重新命名磁碟上的對應資料夾（僅限已在 `Media/` 內的檔；外部絕對路徑不動）。同磁碟搬移／改名是檔案系統 metadata，不會重解碼波形，耗資源很低。
## 相關文件

- 產品規格：`docs/PRODUCT_SPEC.md`
- 架構：`docs/ARCHITECTURE.md`
