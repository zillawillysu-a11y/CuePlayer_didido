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
| 軌道由上到下 | **Music → Video → LTC → Marks**（拉開 Music／Video 高度可把 Marks 往下擠；往下捲可看到 Marks） |
| Music／Video 底部分隔線 | 上下拖可改高度；對齊完可用眼睛隱藏 Video+LTC |
| 下方細時間軸 | 整首歌總覽；拖曳可跳轉，亮區＝目前主時間軸可視範圍 |
| 分隔拉桿 | 平常接近黑色、滑鼠過去變灰色（主介面所有 QSplitter） |

## 選單 View

| 項目 | 說明 |
|------|------|
| **Show Set List** | 顯示／隱藏左側 Set List（歌單／資料夾） |
| **Show Video / LTC Tracks** | 顯示／隱藏時間軸上的 Video + LTC 軌道（Preview／Clean Output 仍會播） |
| **Video Preview Panel** | 嵌入式預覽面板 |
| **Clean Video Output** | 開 OBS 用乾淨輸出視窗 |

## Cue List（右側）

| 操作 | 說明 |
|------|------|
| **Shift / Ctrl** | 多選 |
| **Del / Backspace** | 刪除選取 |
| 點 **Time** | 跳到該 Mark |
| 右鍵 Cue List | 顯示／隱藏 Cue List |
| 右鍵 PRIMARY NOW | **Show Cue ID**＝開關主顯示上的 Cue ID；**Single-line NOW**＝Primary／Secondary 的 Type / Cue / Note 同一行（並排時兩邊一致）；**Secondary on the right / below**＝Secondary 在右或下方；也可顯示／隱藏 Primary／Secondary |

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
| **File → Collect Project Bundle…** | 另存成 Bundle 資料夾：可命名 `.cueplayer.json`，並切換成用該檔繼續工作。`Media/<Setlist>/<歌名>/` 放素材。再次選同一個 Bundle 資料夾時，已在裡面的檔案會沿用／搬到正確 Folder，只拷貝新增的媒體。舊的專案檔／資料夾不會被改動，之後仍可分開開啟。 |
| **File → Relink Missing Media…** | 檔案搬走後單檔或整資料夾依檔名重新連結（遞迴掃媒體副檔名）；同名多份需手動指定。Relink 後請 Save。若檔案是搬移／拷貝且 mtime 相同，波形與 LTC 快取也會沿用。 |

專案資料夾內的媒體存**相對路徑**，整包搬到任何磁碟／路徑仍可開啟。

**Save 時偵測外部媒體：** 若你從專案資料夾外（例如 Downloads）拖進音訊／影片，按 Save／另存時會問要不要拷貝進 `Media/<Setlist>/<歌名>/`。選 Yes＝拷貝後存檔（原檔不動）；No＝仍用絕對路徑存。Auto-save 不會跳出詢問。完整另存整包仍可用 **Collect Project Bundle**。已在 `Media/` 內的檔案可被多首歌共用（不會因 Save 被拆成複本）；搬 Folder 後空的舊資料夾會清掉。Bundle／搬移會沿用波形與 LTC 快取，避免重測。開啟專案或 Bundle 前會自動嘗試用 `Media/` 內同名檔接回因搬 Folder 而斷掉的路徑；若仍缺檔會列出檔名，可用 **Relink Missing Media**。

在程式裡搬歌曲到 Setlist Folder／改 Folder 名：只改專案記憶體；**磁碟上的 `Media/` 要等 Save／另存／Auto-save／Bundle 才會跟著排**。

### 另存新檔後再開舊檔？

| 你做了什麼 | 再開「舊的」`.cueplayer.json` |
|------------|-------------------------------|
| 只在記憶體裡改 Folder／歌名，**還沒 Save** | 舊檔與舊 `Media/` 都沒動，照常開。 |
| **另存到別的資料夾**（一般 Save As） | 舊檔不被覆寫；媒體通常仍留在原專案旁，舊檔可照常開。新檔多半用**絕對路徑**指回原媒體（兩份專案檔共用同一批檔）。 |
| **Collect Project Bundle** | 舊資料夾完全不動；Bundle 內是獨立 `Media/` 副本。舊檔、Bundle 可分開開。 |
| **對原檔 Save**（或 Auto-save） | 舊檔被更新，且 `Media/` 會排成與目前 Setlist 一致；再開的就是這個新狀態。 |
| 另存到**同一個資料夾**但換檔名 | 與舊檔共用同一棵 `Media/`；程式**不會**在另存當下重排媒體，舊檔可照常開。之後若對**新檔**按 Save 且要排資料夾，仍可能動到共用 `Media/`。要真正獨立副本請用 Bundle。 |

## 相關文件

- 員工安裝／下載：`docs/EMPLOYEE_INSTALL.md`（給測試端，不含 Git）
- 產品規格：`docs/PRODUCT_SPEC.md`
- 架構：`docs/ARCHITECTURE.md`
