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

## 輸出時鐘（右側大秒數下方）

| 操作 | 說明 |
|------|------|
| **TRANS / Note / MTC / LTC** | 快速開關（開 TRANS／Note／MTC 會自動開 MIDI） |
| 右鍵時鐘區 | 顯示／隱藏時間碼、顯示／隱藏開關列；進階設定 |

## 專案檔與 Bundle

| 選單 | 說明 |
|------|------|
| **File → Collect Project Bundle…** | 複製用到的媒體到資料夾：`專案.cueplayer.json` 在根層、`Media/` 放素材 |
| **File → Relink Missing Media…** | 檔案搬走後單檔或整資料夾依檔名重新連結 |

專案資料夾內的媒體存**相對路徑**，整包搬到任何磁碟／路徑仍可開啟。

## 相關文件

- 產品規格：`docs/PRODUCT_SPEC.md`
- 架構：`docs/ARCHITECTURE.md`
