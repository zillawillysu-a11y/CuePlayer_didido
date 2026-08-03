# CuePlayer Architecture Review

**範圍：** `src/cueplayer` 現況（約 106 支 `.py`、~44k LOC）  
**性質：** 只分析、不修改程式  
**日期：** 2026-08  
**相關：** 現行目標見 [`ARCHITECTURE.md`](ARCHITECTURE.md)；漸進目標架構見 [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md)

---

## 總評

套件邊界大致符合 `ARCHITECTURE.md`（Domain 中心、Audio sample clock 為唯一播放時鐘、Exporters 相對乾淨），但實際依賴是 **UI 中心星狀架構**：`MainWindow` 同時是 composition root、應用服務、背景工作排程器與 Remote host。真正危險的耦合在 **共享可變 `Song`、全域 `av_path_lock`、以及 Persistence→UI 的反向依賴**。

---

## 1. 專案資料夾結構

```text
CuePlayer_didido/
├── AGENTS.md / README.md / pyproject.toml
├── docs/                  # ARCHITECTURE, PRODUCT_SPEC, DISTRIBUTION…
├── fixtures/              # ma2/ma3 golden、media、export_test
├── packaging/             # Windows PyInstaller / Inno
├── scripts/
├── tests/                 # 約鏡射 src 套件（ui 測試最多）
└── src/cueplayer/
    ├── app.py, __main__.py
    ├── domain/            # 5 py  — 模型 / undo / cue-id / relink
    ├── playback/          # 13 py — AudioEngine、video sync/mix、NDI、devices
    ├── media/             # 14 py — 解碼、快取、BPM、LTC detect、av_lock
    ├── exporters/         # ma2/ ma3/ + common / plan / show_patch
    ├── persistence/       # project JSON、bundle、backup、media layout
    ├── ui/                # 32 py  — ~54% LOC；MainWindow 為中心
    ├── web_remote/        # HTTP/WS + bridge + static app.js (~3316 行)
    ├── timecode/          # SMPTE / LTC / MTC helpers
    ├── routing/           # 路由矩陣
    ├── util/              # frozen runtime、thread priority
    ├── spikes/            # 早期實驗
    ├── timeline/          # 空 stub（實際在 ui/timeline_*）
    └── ltc/               # 空 stub（實際在 timecode/）
```

**體積重心：** `ui/` ≈ 23.7k LOC；其次 `playback`、`media`、`web_remote`。空的 `timeline/`、`ltc/` 顯示早期 scaffold 未清乾淨。

### 最大檔案（Top）

| 行數 | 路徑 |
|-----:|------|
| 7637 | `ui/main_window.py` |
| 4507 | `ui/timeline_widget.py` |
| 3316 | `web_remote/static/app.js` |
| 2760 | `ui/cue_monitor_panel.py` |
| 2146 | `playback/audio_engine.py` |
| 1338 | `web_remote/bridge.py` |
| 1323 | `ui/mark_manager_dialog.py` |
| 1080 | `domain/models.py` |
| 989 | `media/bpm_analyzer.py` |
| 870 | `persistence/project_store.py` |

---

## 2. 各個 Module 的責任

| 套件 | 應有責任 | 現況摘要 |
|------|----------|----------|
| **domain** | 純資料與規則：`Project`/`Song`/`Mark`/`VideoClip`、undo、Cue ID | 大致正確；`media_relink` 已拉到 media/persistence |
| **playback** | 唯一 sample clock、裝置 I/O、LTC/MTC/MIDI、video 音訊混音、video sync | `AudioEngine` 過寬；`clock.py` 為遺留牆鐘 stub |
| **media** | 解碼、波形/PCM/LTC/scrub 快取、BPM、PyAV 鎖 | 清楚；全域 path lock 是跨模組契約 |
| **exporters** | Song → MA2/MA3 XML/Macro/Plugin | 最乾淨一層；UI 直接 new exporter |
| **persistence** | UTF-8 JSON、migration、bundle、backup、media 目錄 | 功能齊；但依賴 UI column util + exporter naming |
| **ui** | 畫面與互動 | 承擔應用協調、背景 job、遠端 host |
| **web_remote** | LAN 控制 / Listen | 套件獨立，但 bridge duck-type `MainWindow` 私有 API |
| **timecode / routing / util** | TC 工具、路由、runtime | 小而清楚 |

### 核心執行流（實作）

```text
MainWindow
  ├─ AudioEngine（sample clock + LTC/MTC/MIDI + VideoAudioMixer）
  ├─ VideoSyncController ← engine.position
  │     └─ frame → Preview / Clean / NDI / Web Remote
  ├─ TimelineWidget / CueMonitorPanel / Setlist / Transport
  ├─ Persistence（save/load/autosave/bundle）
  └─ WebRemoteBridge → 呼叫 MainWindow 私有方法
```

### 套件細節（摘要）

**domain：** `models.py`（Project/Song/Mark/VideoClip/設定）、`undo.py`、`main_cue_id.py`、`media_relink.py`。

**playback：** `audio_engine.py`、`video_sync.py`、`video_audio_mixer.py`、`devices.py`、`ndi_output.py`、`mtc_output.py`、`midi_cue_notes.py`、`resample.py` 等。

**media：** `audio_loader.py`、`video_loader.py`、`video_audio_*`、`av_lock.py`、`bpm_analyzer.py`、`ltc_detect.py`、disk/scrub/waveform caches。

**exporters：** `common.py`、`plan_from_song.py`、`ma2/exporter.py`、`ma3/exporter.py`、`show_patch.py`。

**persistence：** `project_store.py`、`project_bundle.py`、`media_layout.py`、`backup.py`、`audio_prefs.py`。

**ui：** `main_window.py` 為上帝物件；另有 timeline、cue monitor、transport、dialogs、setlist sheet、show patch 等。

**web_remote：** `bridge.py`、`server.py`、`state.py`、`webrtc_listen.py`、`static/app.js`。

---

## 3. 哪些 Module 耦合過高

### 高耦合熱點

1. **`ui.main_window` ↔ 幾乎一切**  
   同時持有 engine、video_sync、NDI、Clean、undo、多個 `ThreadPoolExecutor`、媒體快取、Web Remote。

2. **Video 路徑三角：`VideoSyncController` × `VideoAudioMixer` × `av_path_lock`**  
   Preview/Clean/scrub/waveform/standin/mixer 都搶同一把 path lock；改 A 窗長 → 易影響 B 畫面卡頓。

3. **共享可變 `Song`**  
   engine / video_sync / timeline / monitor / remote 同一物件；漏一次 `refresh_*` 就音畫/列表不一致。

4. **`web_remote.bridge` ↔ `MainWindow` 私有表面**  
   深入 `_video_standin_cache`、`_push_song_undo`、`_ltc_channel_for_song` 等；MainWindow 改名即壞 Remote。

5. **`persistence.project_store` → `ui.cue_list_columns`**  
   反向依賴：儲存層依賴 UI 套件。

6. **`persistence` → `exporters.common`（MA 命名）**  
   載入/正規化時綁死匯出命名規則。

7. **LTC 偵測雙軌**  
   MainWindow idle detect + AudioEngine 內 detect；兩套 executor、兩套快取語意。

### 相對乾淨

`exporters/*`（不依賴 ui/playback）、`timecode/*`、`routing/*`。

### 循環

無硬循環（沒有 `playback → ui`）；軟風險在 `persistence ↔ ui`、`domain ↔ media/persistence`。

---

## 4. 哪些地方違反 Single Responsibility

| 位置 | 塞進太多職責 |
|------|----------------|
| **`MainWindow`（~7637 行）** | Composition + 專案生命週期 + setlist + 音訊載入/預取 + BPM + LTC badge + undo + video outs + NDI + Web Remote host + autosave + bundle/relink + 快捷鍵 |
| **`TimelineWidget`（~4507）** | 繪製 + 縮放捲動 + mark/clip 編輯手勢 + scrub + 波形 |
| **`CueMonitorPanel`（~2760）** | Cue 列表、NOW、欄位偏好、輸出開關、Note/Cue ID 編輯 |
| **`AudioEngine`（~2146）** | PortAudio + 路由 + 音量 + A-B + 校正 click + 產生/檔案 LTC + MTC + MIDI cues + video 音訊 |
| **`WebRemoteBridge`（~1338）** | 幾乎鏡像 MainWindow 指令面 |
| **`project_store`（~870）** | I/O + migration + 型別 coercion + UI/export 規則 |
| **`models.py`（~1080）** | 多種 domain 型別與行為堆在單檔 |
| **`static/app.js`（~3316）** | 瀏覽器端巨石：auth、波形、Listen、marks、poll |

文件宣稱「UI → Domain → 各層」；實作為「UI 直連各層」，Domain 未形成 façade。

---

## 5. 哪些檔案超過建議大小

實務建議：單一模組 **~400–600 行** 宜拆；**>1000** 視為重構候選；**>2000** 為高優先。

| 行數 | 檔案 | 建議 |
|-----:|------|------|
| 7637 | `ui/main_window.py` | 必拆（應用服務層） |
| 4507 | `ui/timeline_widget.py` | 必拆（paint / interaction / model adapter） |
| 3316 | `web_remote/static/app.js` | 必拆 |
| 2760 | `ui/cue_monitor_panel.py` | 高優先 |
| 2146 | `playback/audio_engine.py` | 高優先（時鐘 vs TC/MIDI vs device） |
| 1338 | `web_remote/bridge.py` | 中高（對齊 Host protocol） |
| 1323 | `ui/mark_manager_dialog.py` | 中 |
| 1080 | `domain/models.py` | 中（按聚合拆檔） |
| 989 | `media/bpm_analyzer.py` | 可維持演算法單檔，但 API 面宜薄 |
| 870 | `persistence/project_store.py` | 中（store vs migration vs coerce） |
| 847–500 | ma2 exporter、setlist sheet、show patch、devices、media_layout、ndi、video_sync… | 觀察／按功能切 |

空 stub：`timeline/`、`ltc/` — 應刪或遷入真實套件。

---

## 6. 哪些功能可以拆成獨立 Service

| 候選 Service | 現況 | 價值 |
|--------------|------|------|
| **`ProjectApplicationService`** | 散在 MainWindow | 開檔/存檔/dirty/autosave/bundle |
| **`PlaybackSession` / Clock façade** | `AudioEngine` 過大 | UI/Remote 只依賴窄介面 |
| **`MediaJobQueue`** | 多個 executor 分屬 UI/Engine | 統一 BPM/LTC/prefetch/load |
| **`VideoFrameBus`** | `_on_video_frame` 扇出 | Preview/Clean/NDI/Remote 訂閱 |
| **`VideoAudioDecodeService`** | mixer + cache + lock 策略 | 與 Preview 解耦策略集中 |
| **`WebRemote` + `RemoteHost` API** | duck-type 私有方法 | 最大解耦收益之一 |
| **`ExportService`** | UI 直接 new Ma2/Ma3 | Show patch / 單曲匯出同一入口 |
| **`BpmDetectService`** | MainWindow 佇列 + setlist cell | 易測、易重試 |
| **`LtcService`** | Engine 產生 + UI idle detect | 消除雙軌 |
| **`AutosaveService`** | MainWindow QTimer | 薄且獨立 |
| **`MissingMediaRelinkService`** | domain helper 已跨層 | 移出 domain 純層 |

已接近獨立、拆成本低：**exporters**、**project_bundle**、**timecode 工具函式**。

---

## 7. 哪些地方容易造成「修改 A 壞 B」

| 改動 A | 容易壞的 B | 原因 |
|--------|------------|------|
| Mixer 窗長／prefetch 策略 | Preview/Clean 卡頓、靜音島 | 共用 `av_path_lock` + GIL |
| 新增任何 PyAV 讀取 | 上述全部 | 全域 per-path lock |
| `Song.marks` / `video_clips` 突變漏 refresh | 音畫不同步、Cue List 舊資料 | 無 domain event bus |
| 換歌順序（engine/video_sync teardown） | 崩潰／殘影 | 必須先拆 PortAudio |
| Cue list refresh 節流（150ms） | Remote/時間軸編輯後列表過期 | 單一 debounce 路徑 |
| Main Cue ID renumber 順序 | 時間軸 / Cue List / MA export 不一致 | 多入口（timeline、monitor、remote、undo） |
| Web Remote 密碼／token 輪詢 | 輸入被清／指令面過寬 | auth 與巨大 command surface 綁在一起 |
| LTC 偵測／路由私有 API | 檔案 LTC → MTC 鏡像錯誤 | UI 呼叫 engine 私有方法 |
| `project_store` 欄位 schema | 舊專案打不開或 Cue 欄亂序 | migration + UI normalizer 交織 |
| NDI 模組快取旗標 | 裝完 Runtime 仍顯示缺套件 | process-level probe cache |

**結論：** 最脆的不是「套件 import 圖」，而是 **執行期共享資源（鎖、Song、frame fan-out）缺少單一協調者契約**。

---

## 8. 哪些地方應該建立 Interface

現有幾乎只有：`web_remote.state._EngineView`、`domain.undo.UndoCommand`。建議補：

| Interface / Protocol | 實作方 | 消費者 |
|----------------------|--------|--------|
| **`PlaybackClock`** | `AudioEngine` | UI、Web Remote、VideoSync |
| **`AudioDevicePort`** | sounddevice 包裝 | AudioEngine |
| **`VideoDecoderPort`** | `video_loader` | VideoSync、scrub |
| **`VideoAudioSource`** | cache/loader | VideoAudioMixer |
| **`FrameSink`** | Preview / Clean / NDI / Remote | FrameBus |
| **`ProjectStore`** | `project_store` | Application service |
| **`ShowExporter`** | Ma2/Ma3 | Export UI/service |
| **`RemoteHost`** | 從 MainWindow 抽出的公開 API | `WebRemoteBridge` |
| **`MediaCache`** | disk/memory caches | load/prefetch/bundle |
| **`TimecodeOutput`** | LTC gen + MTC | Engine 組合而非繼承膨脹 |

特別急：**`RemoteHost`**、**`PlaybackClock`**、**`FrameSink`**。

---

## 9. 哪些地方應該 Dependency Injection

**現況：** Qt parent 當生命週期；MainWindow 手寫 `new`；模組級全域快取（`av_lock`、`video_audio_cache`、NDI probe）；prefs 靠 `QSettings`。

**應導入 DI 的點：**

1. Composition root 唯一化 — `app.py` / 薄 `MainWindow` 只組裝。
2. `WebRemoteBridge(host: RemoteHost)` — 明確介面。
3. `VideoSyncController(clock, decoder_factory, defer_gate)`。
4. `AudioEngine(device_port, ltc_service, mtc, midi, video_audio)`。
5. `ProjectApplicationService(store, backup, media_layout)`。
6. 共用 `WorkerPool` / `MediaJobQueue`。
7. Exporter 由 service 注入。
8. 測試用 FakeClock / FakeDecoder。

**暫不必硬 DI：** 純 widget、純函式（SMPTE format）。

---

## 10. 重構優先順序（僅建議；落地計畫見 ARCHITECTURE_TARGET）

### P0 — 降「改 A 壞 B」風險

1. 抽出 `RemoteHost` 公開 API，bridge 只打這層。
2. 文件化／集中 `av_path_lock` 消費者清單。
3. Song 變更 → 明確 `SongSession.refresh_*` 清單。
4. 切斷 `persistence → ui`：column 正規化移出 `ui`。

### P1 — 拆巨石（行為不變）

5. `MainWindow` → Application services。
6. `AudioEngine` 拆 LTC/MTC/MIDI 子元件。
7. `VideoFrameBus` 取代手動扇出。
8. 合併 LTC detect 雙軌。

### P2 — UI 可維護性

9. 拆 `TimelineWidget`。
10. 拆 `CueMonitorPanel`。
11. 模組化 `app.js`。

### P3 — 整潔與長期

12. `ExportService` façade。
13. `models.py` 按聚合拆檔。
14. 刪除空 stub；淘汰未用 `playback/clock.py`。
15. 正式 Protocol + Fake + composition-root DI。

**不建議：** 大爆炸式六角架構一次搬完、無測試網的事件總線化。

---

## 對照文件意圖 vs 實作

| `ARCHITECTURE.md` / `AGENTS.md` | 實作 |
|----------------------------------|------|
| UI → Domain → 各層 | UI → Domain **且** UI → playback/media/exporters/persistence |
| Playback Engine = 唯一 clock | **成立** |
| Video 共用一條 decode path | **成立** |
| 各層分離 | **套件存在**；依賴方向與 SRP **未嚴格遵守** |

---

## 一句話

架構骨架正確、時鐘與匯出邊界健康；最大債在 **`MainWindow` 上帝物件 + 共享 Song/PyAV 鎖的執行期耦合**。漸進搬移計畫見 [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md)。
