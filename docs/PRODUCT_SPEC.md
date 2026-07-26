# CuePlayer 專案交接文件

更新日期：2026-07-26  
狀態：需求定義完成，尚未開始實作  
平台：Windows 11  
主要使用者：演唱會／劇場燈光設計與編程人員

## 1. 專案目標（一句話）

打造一套 Windows 桌面程式，讓燈光編程人員能在同一時間軸上精準對齊多版本音訊、LTC、VJ 影片與快捷鍵標記，並匯出可直接匯入 grandMA2／grandMA3 的 Sequence 與 Timecode XML。

## 2. 主要功能清單（依優先順序）

### P0：可用的第一版核心

- 專案／Setlist：
  - 一個 Project 可包含多首歌曲。
  - 每首歌曲有獨立起始 Timecode、FPS、素材、Marks 與 MA 匯出設定。
  - 專案需完整支援中文名稱、中文資料夾及中文媒體檔名。
- 多音訊軌：
  - 同一首歌可加入不限一軌的新版／舊版音檔，保留並排比較，不採 Replace-only 工作流。
  - 每軌顯示獨立波形，可移動、鎖定、隱藏、Mute、Solo、命名及改顏色。
  - 可指定其中一軌為 Main Audio，其餘為 Reference。
  - A/B Solo 比較時保持同一播放位置。
- 音訊來源解析與單裝置多聲道路由：
  - 使用者可逐一指定來源 Left／Right／其他 Channel 是 Music、LTC 或忽略。
  - 不假設 LTC 永遠在左聲道；每首歌可不同。
  - 一首歌只允許選擇一張 Audio Output Device，避免跨聲卡時鐘漂移。
  - 可将來源送至該裝置任意 Output Channel。
  - 典型路由：
    - Stereo Music：L → Focusrite CH1、R → CH2、LTC → CH3。
    - L=LTC、R=Mono Music：L → CH3、R → CH1+CH2。
  - 裝置輸出不足時顯示明確警告。
- LTC：
  - 若素材已有 striped LTC，可指定 LTC 位於哪個來源 Channel。
  - 若沒有 LTC 檔，依歌曲長度、起始 Timecode、FPS、Pre-roll 自動產生 LTC。
  - 生成 LTC 建議快取成內部音訊，以利穩定播放、Seek 與重複使用。
  - LTC Gain 與 Music Gain 分離；一般音量控制不得誤調 LTC。
- 共用 Master Timeline：
  - Music、LTC、Video、Marks 共用同一時間基準。
  - Play、Pause、Stop、Seek、Loop、從 Mark 開始播放皆需同步。
  - 以音訊 sample position 作為主要播放時鐘，避免 UI timer 漂移。
- 波形與對齊：
  - 顯示 Music 波形；LTC 波形可縮小或隱藏。
  - 水平／垂直縮放、波形 Gain、Audio Scrubbing、精確游標。
  - 多版本波形上下排列，並預留半透明疊圖模式。
  - 可在兩軌各設 Anchor，執行 Align Anchors。
  - 可依 Frame 或毫秒微調。
- Video Timeline：
  - 支援一支完整 VJ 影片，或多個 VJ Clips 排列於同一首歌。
  - Clip 可拖曳、Trim、Split、複製、刪除、鎖定、隱藏及 Frame 微調。
  - 沒有 Clip 的區段自動輸出純黑。
  - 第一版同時間只允許一個有效 Video Clip；重疊時警告，不做多層合成。
  - 第一版只需 Hard Cut，不需要 Crossfade、特效或正式演出播放功能。
  - 影片原始音軌預設 Mute。
- 影片顯示：
  - 主畫面內建 Preview。
  - 另有固定名稱的 Clean Video Output 視窗，供 OBS Window Capture。
  - Output 可視窗化／全螢幕，提供 Fit／Fill，未播放區域維持純黑。
  - 關閉主 Preview 不得中斷 OBS Output。
  - OBS 再透過 NDI 將畫面送入 Depence；程式本身第一版不必直接輸出 NDI。
- `1–9 Manager`：
  - `1–9` 各自代表一種 Mark 軌道，可改快捷鍵、名稱、顏色、順序、顯示／隱藏、鎖定及是否匯出。
  - 預設 `1 = Main`，`2–9 = Top Button`，但 Manager 可修改類型。
  - 設定可儲存為 Template，並允許每首歌覆寫。
- 即時打標：
  - 播放時按 `1–9`，在目前 playhead 建立對應類型的 Mark。
  - 預設連續打點時不彈出命名視窗；之後選取 Mark 再補名稱。
  - Space：Play／Pause。
  - 上／下：上一個／下一個 Mark。
  - 左／右配合修飾鍵：依自訂秒數或 Frame 移動。
  - 支援框選、Shift 多選、複製、刪除、Undo／Redo。
- 批次修訂：
  - 可整體位移所選 Marks。
  - 可精確輸入 `+/- 秒數` 或 `+/- Frames`。
  - 可執行「移動 Playhead 之後的全部 Marks／Video Clips」。
  - 移動時可選擇 Main、Button、Video 或全部。
- grandMA2／grandMA3 匯出：
  - 目標版本先固定：
    - grandMA2 3.9.61.5
    - grandMA3 2.3.2
  - MA2 與 MA3 使用獨立 Exporter，不共用 XML schema。
  - 產生 Sequence XML 與 Timecode XML。
  - Main Marks：
    - 每個 Mark 產生下一個 Sequence Cue。
    - Timecode Event 使用 **Go+ 並指定目標 Cue**（CueDestination），符合燈光編程實務習慣。
    - 不是「裸 Go+」；每個 Main Mark 必須對應到明確 Cue，中段進 Timecode 仍能到正確 Cue。
  - Top Button Marks：
    - 每個 Button Track 只產生一條固定的兩 Cue、自我 Release Sequence。
    - Cue 2 內部使用 Follow Cue 1 + 0.1 秒並 Release。
    - 0.1 秒屬於隱藏的內部預設，不顯示在主要 UI。
    - 每個 Mark 只在 Timecode Show 中新增一次對該 Executor／Sequence 的 Top 觸發，不因 Mark 數量增加 Sequence Cue 數。
  - 匯出設定包含 Sequence Pool 起始編號、Timecode Pool 編號、Page／Executor、Timecode Slot、FPS、起始 Offset，以及 MA3 Data Pool。
- 中文與 MA 名稱：
  - 程式內所有資料完整支援 Unicode／中文。
  - MA XML 僅輸出安全英數名稱，不可直接輸出中文。
  - 每個 Cue／Track 保存 `Display Name` 與 `MA Export Name`。
  - 有手動 MA Export Name 時永遠優先使用。
  - 沒有手動英文名時可選：
    1. 使用 Cue ID／Sequence ID（預設且最安全）。
    2. 自動中翻英。
    3. 自動轉拼音。
  - 自動轉換結果必須先進入可編輯的 Export Preview；轉換失敗時回退 Cue ID。
  - 不可自動覆蓋已手動修改的 MA Export Name。
- 穩定性：
  - Auto Save／Auto Backup。
  - Missing Media 偵測及 Relink。
  - 專案相對路徑與絕對路徑皆需合理處理。
  - 中文路徑必須納入第一天起的自動測試，不可最後才補。

### P1：核心可用後加入

- MA Export Preview／Validation：
  - 預覽所有 Cue、Sequence、Executor 與實際 MA Label。
  - 檢查非法字元、重複 Sequence／Executor、超出範圍或未設定的輸出。
- 更完整的版本修訂：
  - 舊／新波形半透明 Overlay。
  - 改動區段前後多 Anchor。
  - Ripple Move／Range Conform。
- 自訂標記延遲補償，例如 `-50 ms`、`-100 ms`。
- 專案 Bundle：專案檔、媒體索引、快取與設定可攜式打包。
- CSV 匯入／匯出，供人工檢查與其他工具交換。
- 影片輸出解析度與顯示器記憶。

### P2：未來功能

- OSC Input，讓 MA3、Stream Deck／Companion 控制 Play／Pause、Seek、換歌及跳 Mark。
- BPM／Beat Grid／Tempo Map，支援 BPM 變動後依拍點調整 Marks。
- 自動波形 cross-correlation 對齊。
- 更多控台／軟體匯出格式。
- 多使用者 Cue Sync。

## 3. 技術選擇與理由

### 已決定

- 語言：Python 3.13.14 x64。
  - 開發速度快，適合 Cursor／Codex 代理式開發。
  - PySide6、PyInstaller 已支援 Python 3.13。
- GUI：PySide6／Qt 6。
  - 適合複雜 Windows 桌面 UI、多視窗、Dock、表格及自訂 Timeline。
  - 可打包成不需使用者另裝 Python 的 Windows App。
- 版本控制：Git。
  - 需求多且會反覆調整，必須保留可回退的細粒度版本。
- 專案儲存：UTF-8 JSON（MVP 不使用資料庫）。
  - 專案以檔案為單位、便於除錯、版本控制、備份與手動修復。
  - 所有文字使用 Unicode；JSON 寫入時不得轉成 ASCII escape-only 格式。
- 路徑：`pathlib.Path`，並以 Unicode 路徑作為強制測試條件。
- 架構：UI、Domain、Playback Engine、Media、Exporters、Persistence 分層。
- MA Exporter：grandMA2 與 grandMA3 分成版本化模組，以 MA onPC 實際匯出的 XML 作為 golden fixture。

### 建議採用，開工前以 Spike 驗證

- 媒體解碼：FFmpeg + PyAV。
  - 支援常見 WAV／MP3／MP4／MOV，能讀多聲道與取得精確 PTS。
- 音訊輸出：`sounddevice`／PortAudio。
  - 可建立單一多聲道 Output Stream，自行實作來源→輸出 routing matrix。
  - 必須先在 Windows + Focusrite 實測真正可見的 Output Channel 數與編號。
- 影片顯示：PyAV 解碼 frame → Qt image/render surface。
  - 避免主 Preview 與 Popout 各自建立獨立播放器而逐漸失同步。
- 波形快取：NumPy peak pyramid，儲存為專案 cache 檔。
  - 可在不同 zoom level 快速繪圖，不必每次重掃完整音檔。
- 打包：PyInstaller。
- 拼音：`pypinyin`，只生成可編輯候選值。
- LTC：優先評估重用 `libltc`（DLL + Python wrapper）產生可快取 PCM；若不適合，再做獨立 generator。

### 尚未決定

- 自動中翻英的來源：
  - 第一版不可把網路服務綁死在核心功能。
  - 應先定義 `NameTranslator` 介面；可先不實作或使用可替換 provider。
- 是否需要 SQLite：
  - MVP 不需要；只有未來大型素材索引／搜尋真的出現效能需求時才評估。

## 4. 已決定的設計／架構

- 核心資料層級：

  ```text
  Project / Setlist
  └── Song
      ├── Timebase（start TC、FPS、duration）
      ├── Audio Tracks[]（Main / Reference）
      ├── Generated or Striped LTC
      ├── Video Clips[]
      ├── Mark Lanes 1–9
      └── MA Export Profile
  ```

- 每個媒體物件只保存 timeline placement、source channel mapping、metadata 與檔案 reference；編輯採 non-destructive。
- Playback Engine 是唯一播放狀態來源；UI 不自行計時。
- Audio 為 master clock；影片按 audio sample clock 選取／丟棄 frame。
- Main Preview 與 Clean Output 共用同一 decoded video frame。
- 一次只開一張 Output Device；該裝置內自由多聲道路由。
- `1–9 Manager` 是 Mark Lane 設定，不是九個互不相干的播放器。
- Main Lane 與 Top Button Lane 的 MA 匯出邏輯不同，Domain Model 必須保存 lane type。
- Cue 的中文顯示名稱與 MA 安全名稱分欄保存。
- 自動翻譯／拼音只產生候選名稱，不修改原始中文資料。
- 所有批次移動、對齊、刪除、Split、Trim 都需進 Undo Command Stack。
- 專案自動備份與 schema version 必須從第一版存在，後續格式升級使用 migration。

## 5. 已排除的方案（不要走回頭路）

- 不繼續 LTCBridge；此專案是新的 CuePlayer 類時間軸工具。
- 不做 CuePoints 的逐像素複製，也不依賴 CuePoints 專案格式。
- 不採「每首歌只能一支音訊／一支影片」。
- 不採 Replace-only 音檔流程；新版必須能新增為另一軌並與舊版比較。
- 不限制成 Primary／Secondary／Tertiary 三個媒體槽。
- 不同時輸出至多張聲卡；只選一張多輸出裝置。
- 不假設 LTC 固定在 Left 或 Right。
- 不讓 LTC 混入 CH1／CH2 喇叭輸出。
- 不用 UI timer 當媒體同步時鐘。
- 不為 OBS 分別啟動第二套影片播放器。
- 不把 Video 當正式演出 media server；它是預編程參考。
- 第一版不做 Crossfade、多層影片合成或 Resolume 類功能。
- Button Mark 不可每打一個就增加一個 Sequence Cue；它們重複 Top 同一條兩 Cue 自 Release Sequence。
- Main Timecode Event 不使用裸 Go+；必須是 Go+ + 指定 CueDestination（使用者習慣；不以 Goto 為預設）。
- `Follow 0.1s` 不顯示在主要介面。
- 程式內不可禁止中文、複製英文檔或要求使用者改英文路徑。
- MA Export 不可直接輸出中文。
- 不自動把手動 MA Export Name 覆蓋掉。
- 不預設強制拼音或自動翻譯；Cue ID 是安全 fallback。
- MVP 不導入資料庫、雲端同步或多使用者協作。

## 6. 目前進度

### 已完成

- 產品用途與主要使用情境已確認。
- 音訊來源辨識、多版本波形比較、單聲卡多聲道路由需求已確認。
- LTC striped／generated 兩種流程已確認。
- Video Timeline、黑場及 OBS Clean Output 流程已確認。
- `1–9 Manager` 與 Main／Top Button 語意已確認。
- Main 使用 Go+ + CueDestination、Top Button 兩 Cue self-release 匯出行為已確認（以使用者 golden XML 為準）。
- 中文支援與 MA 英文輸出規則已確認。
- 已研究 CuePoints 官方文件，確認可借鑑的概念：
  - CuePoint Types／Template
  - 多媒體 line-up
  - LTC routing／generator
  - 波形與快捷鍵
  - Top 兩 Cue self-release export
  - Missing Media／Auto Backup／OSC
- 開發工具方向已確認：Cursor + Codex extension + Python + Git。

### 尚未完成

- 尚未建立 Git repository。
- 尚未建立 Python project／virtual environment。
- 尚未寫任何 CuePlayer 程式碼。
- 尚未建立 UI wireframe。
- 尚未取得 MA2／MA3 golden XML 範例。
- 尚未驗證 PyAV + sounddevice 在 Windows／Focusrite 的多聲道播放。
- 尚未驗證 libltc generator 在 Python 3.13／Windows 的整合與打包。
- 尚未建立中文路徑、自動備份、schema migration 或 exporter 測試。
- 使用者尚未確認 Python 3.13.14 與 Git 已完成安裝。

## 7. 已知問題／待釐清問題

- Audio Spike：
  - Focusrite 的實際型號／驅動如何向 PortAudio 暴露 CH1–4。
  - Windows WASAPI 是否足夠，或需另外處理 ASIO；不可未驗證就承諾。
  - Focusrite Control 內 Playback 1–4 到硬體 Output 1–4 的路由需建立測試說明。
- Media：
  - 必須定義首批正式支援格式與 codec，例如 WAV、MP3、MP4(H.264)、MOV。
  - 大型／高解析影片的 preview proxy 策略尚未決定。
- Timebase：
  - 29.97 DF／NDF 的顯示、換算與 XML 精度需以測試向量驗證。
  - generated LTC 的 sample rate、level、pre-roll 預設值待確認。
- MA Export：
  - 必須從 MA2 3.9.61.5、MA3 2.3.2 匯出最小可用 Sequence／Timecode XML，作為 reverse-engineering 樣本。
  - Top Button 的 Page／Executor assignment、Release 欄位與命令需逐版本實機驗證。
  - MA3 未來版本 XML syntax 可能改變，因此 exporter 需版本標記與 golden tests。
- 名稱：
  - 自動中翻英是線上、離線或暫緩，尚未決定。
  - 拼音格式預設值（PascalCase／underscore）尚未決定。
- UX：
  - 應先做 Timeline wireframe，確認 Track Header、Manager、Cue List、Video Preview 與 Export 視窗位置。
  - 是否允許同一首歌多個 Main Lane 尚未確認；目前預設一個 Main，其餘為 Button。
- 專案名稱目前暫定 `CuePlayer`，正式產品名稱尚未確認。
- 發布／授權／自動更新方式尚未決定；不影響 MVP。

## 8. 下一步建議（最該先做的 3 件事）

1. **建立最小專案骨架與測試基線**
   - 初始化 Git、Python 3.13 virtual environment、PySide6 app。
   - 建立 `src/`、`tests/`、`docs/`、`fixtures/`。
   - 先加入中文路徑／中文 JSON round-trip 測試及 schema version。
   - 建立空白主視窗，不先做漂亮 UI。

2. **先做最高風險的 Audio/Media Spike**
   - 列出 Focusrite Output Channels。
   - 載入一個 `L=LTC、R=Music` 測試檔。
   - 將 R 複製到 Output 1+2、L 送到 Output 3。
   - 同時驗證 PyAV 解碼、sounddevice callback、Seek、Stop、中文檔案路徑。
   - 此 Spike 成功後才正式建立 Playback Engine。

3. **收集 MA golden XML，先建立 Exporter 測試**
   - 在 MA2 3.9.61.5 與 MA3 2.3.2 各手動建立：
     - 一條有 2–3 個空 Cue 的 Main Sequence。
     - 一條兩 Cue、Follow 0.1、自 Release、Executor Key=Top 的 Button Sequence。
     - 一個含 Main Go+(指定 Cue) 與重複 Top Events 的 Timecode Show。
   - 分別 Export XML 放入 `fixtures/ma2/`、`fixtures/ma3/`。
   - 先寫 parser／comparison tests，再開始產生 XML。

## 建議初始目錄

```text
CuePlayer/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── src/cueplayer/
│   ├── app.py
│   ├── domain/
│   ├── persistence/
│   ├── media/
│   ├── playback/
│   ├── timeline/
│   ├── ltc/
│   ├── routing/
│   ├── exporters/
│   │   ├── ma2/
│   │   └── ma3/
│   └── ui/
├── tests/
│   ├── unicode/
│   ├── timebase/
│   ├── routing/
│   ├── persistence/
│   └── exporters/
├── fixtures/
│   ├── media/
│   ├── ma2/
│   └── ma3/
└── docs/
    ├── PRODUCT_SPEC.md
    └── ARCHITECTURE.md
```

## 給 Cursor／Codex 的開工原則

- 先讀完整份交接文件，再提出 implementation plan。
- 不得擅自縮減中文支援、多音訊版本比較、單裝置多聲道路由、Video Timeline 或 MA2／MA3 匯出。
- 任何聲稱支援 Focusrite 多聲道或 MA XML 的功能，都必須有真實裝置／onPC fixture 驗證。
- 每個階段必須可執行、可測試、可回退；不要一次生成完整巨型應用。
- 第一個 milestone 只需完成 project skeleton + Unicode persistence tests + audio routing spike。
