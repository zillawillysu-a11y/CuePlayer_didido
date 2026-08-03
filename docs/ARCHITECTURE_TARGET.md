# CuePlayer 目標架構（漸進搬移、不重寫）

**性質：** 設計文件；描述目標資料夾與「一次搬一個 Module」的順序。  
**約束：** 不能影響目前功能；所有功能必須可逐步搬移；不要一次重寫。  
**相關：** 現況分析見 [`ARCHITECTURE_REVIEW.md`](ARCHITECTURE_REVIEW.md)；現行簡圖見 [`ARCHITECTURE.md`](ARCHITECTURE.md)。  
**永久規則：** 依賴方向見 [`BOUNDARY_RULES.md`](BOUNDARY_RULES.md)；搬移手法見 [`MIGRATION_RULES.md`](MIGRATION_RULES.md)（Step 1 之前已插入 Guardrails）。  
**AI 執行：** 每次只做 [`.ai/NEXT_TASK.md`](../.ai/NEXT_TASK.md) 寫的那一步；強制流程 [`WORKFLOW.md`](../.ai/WORKFLOW.md)（計畫 → 實作 → [`REPORT.md`](../.ai/REPORT.md) + [`handoffs/`](../.ai/handoffs/) → 停止）。  
**日期：** 2026-08

---

## 設計原則

1. **Strangler Fig：** 新套件長在旁邊，舊 `ui/main_window.py` 先當 composition root，功能逐個搬走後再瘦身。
2. **一次一個 Module：** 每個 PR 只建立／遷入一個邊界清楚的模組，並保留舊 import 的 **shim 轉發**，直到呼叫端改完再刪 shim。
3. **不碰行為：** 搬移以「剪貼 + 轉發」為主，不順手改邏輯。
4. **時鐘不變：** `AudioEngine` 仍是唯一 sample clock；新架構只重新分層，不另造第二時鐘。
5. **先縫線、後搬家：** 先抽出窄介面（Protocol），再搬實作檔案。

---

## 目標依賴方向

```text
app/                         # composition root（最後才瘦）
  └── ui/                    # 只畫面接線，不擁有業務編排
        └── application/     # use-cases / session（逐步從 MainWindow 抽出）
              ├── domain/           # 純模型（已有，微調）
              ├── ports/            # Protocol 介面（新建，極薄）
              └── adapters/         # 實作 ports
                    ├── playback/
                    ├── media/
                    ├── persistence/
                    ├── exporters/
                    ├── timecode/
                    ├── routing/
                    └── remote/     # 現 web_remote
```

**允許：** `application` → `domain` + `ports`  
**允許：** `adapters.*` → `domain` + `ports`  
**禁止（目標態）：** `persistence` → `ui`、`domain` → `media`、`remote` → `MainWindow` 私有 API  

過渡期可暫時違反，但每個 Module 搬完要消掉自己的違規邊。

---

## 新資料夾架構（目標態）

```text
src/cueplayer/
│
├── app.py                         # 入口（暫時仍 new MainWindow）
├── __main__.py
│
├── ports/                         # 【新建】只有 Protocol / 型別，零實作
│   ├── __init__.py
│   ├── clock.py                   # PlaybackClock
│   ├── audio_device.py             # AudioDevicePort
│   ├── video_decoder.py           # VideoDecoderPort
│   ├── video_audio.py             # VideoAudioSource
│   ├── frame_sink.py              # FrameSink (Preview/Clean/NDI/Remote)
│   ├── project_store.py           # ProjectStore
│   ├── exporter.py                # ShowExporter
│   ├── remote_host.py             # RemoteHost（給 Web Remote）
│   ├── media_jobs.py              # MediaJobQueue
│   └── song_session.py            # SongSession refresh 契約
│
├── domain/                        # 【既有】保持；微遷檔案即可
│   ├── models/                    # 最終可拆：project.py song.py marks.py …
│   │   └── …                      # 過渡：仍可先是 models.py + shim
│   ├── undo/
│   ├── main_cue_id.py
│   └── cue_list_columns.py        # ← 從 ui 遷入（切斷 persistence→ui）
│
├── application/                   # 【新建】用例／編排（從 MainWindow 逐個搬）
│   ├── __init__.py
│   ├── project_service.py         # open/save/save-as/dirty/bundle
│   ├── autosave_service.py
│   ├── song_session.py            # 換歌、set_song 到 clock/sync/timeline
│   ├── media_job_service.py       # load/prefetch/BPM/LTC detect 佇列
│   ├── video_output_service.py    # Preview/Clean/NDI 扇出與可見性
│   ├── mark_edit_service.py       # renumber / undo 協調（薄）
│   └── export_service.py          # 呼叫 exporters port
│
├── adapters/                      # 【新建目錄】實作；內容多半「搬現有檔」
│   ├── playback/                  # 現 src/cueplayer/playback/
│   │   ├── audio_engine.py
│   │   ├── video_sync.py
│   │   ├── video_audio_mixer.py
│   │   ├── devices.py
│   │   ├── ndi_output.py
│   │   ├── mtc_output.py
│   │   ├── midi_cue_notes.py
│   │   └── …
│   ├── media/                     # 現 media/
│   ├── persistence/               # 現 persistence/
│   ├── exporters/                 # 現 exporters/
│   ├── timecode/                  # 現 timecode/
│   ├── routing/                   # 現 routing/
│   └── remote/                    # 現 web_remote/ → 改名 remote（可分兩步）
│       ├── bridge.py
│       ├── server.py
│       ├── state.py
│       ├── webrtc_listen.py
│       └── static/
│
├── ui/                            # 【既有】只留 widgets；編排改呼叫 application
│   ├── main_window.py             # 逐步變薄的 shell
│   ├── timeline/
│   │   ├── widget.py              # 現 timeline_widget 最終落點
│   │   ├── paint.py
│   │   └── interaction.py
│   ├── monitor/
│   │   ├── cue_monitor_panel.py
│   │   ├── cue_list_table.py
│   │   └── now_display.py
│   ├── setlist/
│   ├── transport/
│   ├── dialogs/
│   ├── video/                     # preview / clean window / ndi dialog
│   └── theme.py …
│
└── util/                          # 既有
```

### 過渡期 shim（舊路徑暫時保留）

```text
src/cueplayer/playback/audio_engine.py  →  re-export adapters.playback.audio_engine
src/cueplayer/web_remote/bridge.py      →  re-export adapters.remote.bridge
# ui.cue_list_columns shim — deleted Sprint 1 Task 2 (use domain.cue_list_columns)
```

這樣「搬 Module」不強迫一次改完全部 import。

---

## 架構圖（目標）

```text
┌─────────────────────────────────────────────────────────┐
│  ui/  (widgets only)                                     │
│  MainWindow shell · Timeline · Monitor · Dialogs         │
└───────────────────────────┬─────────────────────────────┘
                            │ signals / method calls
                            ▼
┌─────────────────────────────────────────────────────────┐
│  application/  (one use-case module at a time)           │
│  Project · SongSession · MediaJobs · VideoOutputs · …  │
└─────────────┬───────────────────────────────┬───────────┘
              │                               │
              ▼                               ▼
        domain/                          ports/
   models undo cue-id              Clock Store Exporter
                                              │
                                              ▼
┌─────────────────────────────────────────────────────────┐
│  adapters/                                               │
│  playback │ media │ persistence │ exporters │ remote │ … │
└─────────────────────────────────────────────────────────┘

唯一時鐘：adapters.playback.AudioEngine  ──position──► VideoSync
                                                      │
                                              FrameBus / sinks
                                      Preview · Clean · NDI · Remote
```

---

## 「一次搬一個 Module」的建議順序

每個步驟 = **一個可合併的 Module 搬移**（可含 shim，行為不變）。

| # | 搬哪個 Module | 做什麼（仍不改功能） | 完成定義 |
|---|---------------|----------------------|----------|
| **0** | `ports/` Protocol 套件 | ✅ 已落地：`src/cueplayer/ports/` 僅 Protocol（見 handoff `PortsPackageStep0`） | `import cueplayer.ports` |
| **G** | Architecture Guardrails | ✅ `BOUNDARY_RULES.md` + `MIGRATION_RULES.md`（docs only；插在 step 1 前） | 兩份永久規則文件 |
| **1S** | `cue_list_columns` safety net | ✅ 行為測試 + 依賴圖 + 風險（見 handoff `CueListColumnsSafetyNet`） | tests green；未改 production 邏輯 |
| **1** | `domain/cue_list_columns` | ✅ domain only; UI shim **removed** Sprint 1 Task 2; persistence→domain | single import path `domain.cue_list_columns` |
| **1b** | Transitional cleanup | ✅ ports on tip; stubs/aliases cleared (handoff `Sprint1TransitionalCleanup`) | no dual shims for columns |
| **2** | `ports.remote_host` + bridge 適配 | 定義介面；bridge 改打公開方法（MainWindow 先實作介面） | bridge 零私有 `_` 存取 |
| **3** | `application/project_service` *(Sprint 1 Task 3)* | ✅ 從 MainWindow 剪出 open/save/dirty/autosave/recent | MainWindow 持有 service；dialogs 仍在 UI |
| **3b** | `application/autosave_service` | 可併入 project_service（已併入 prefs）或隨後拆 | — |
| **4** | `repository/project_repository` *(Sprint 1 Task 4)* | ✅ 薄包裝 load/save/autosave/backup/exists；ProjectService 注入 | Service 不再 import persistence |
| **5** | `application/playback_service` + `domain/song_session` *(Sprint 2 Task 5)* | ✅ Play/Pause/Stop/Seek 經 PlaybackService；SongSession 快照 | AudioEngine 仍是唯一 clock |
| **6** | `application/settings_service` | 機器/專案設定 façade | 行為不變 |
| **7** | `adapters/` 目錄 + **playback 整包搬** | `playback/` → `adapters/playback/` + 頂層 shim | 測試/UI import 仍綠 |
| **8** | **media 整包搬** | 同上 | 同上 |
| **9** | **exporters 整包搬** | 同上 | 同上 |
| **10** | **timecode + routing 搬** | 小包 | 同上 |
| **11** | `web_remote` → `adapters/remote` | 改名+shim | Remote 行為不變 |
| **12** | `application/media_job_service` | 合併 UI 側 load/BPM/LTC 佇列入口 | MainWindow 少多個 executor 欄位 |
| **13** | `application/video_output_service` | `_on_video_frame` 扇出搬出 | sinks 註冊制 |
| **14** | `application/export_service` | ShowPatch/單曲匯出入口 | UI 不直接 new exporter |
| **15** | UI 子目錄化 | `timeline_widget`→`ui/timeline/` 等（可再拆多步，一步一檔） | 仍 shim 舊路徑 |
| **16** | 刪 shim、瘦 `MainWindow` | 只留組裝 | 目標依賴圖成立 |

**刻意延後、且仍可一步一步做：** 拆 `AudioEngine` 內部、拆 `TimelineWidget` 繪製——那是 Module **內部** 再切，不阻擋上面的套件搬移。

---

## 每個 Module 搬移的固定手法

```text
1. 建新路徑（或 ports 介面）
2. 把檔案移過去（git mv）
3. 舊路徑留：
     from cueplayer.adapters.xxx import *   # shim
4. 跑既有該模組測試
5. 下一個 PR 再改呼叫端 import（可選，可很慢）
6. 確認無引用後刪 shim
```

**禁止在同一步：** 改行為、改鎖策略、改 Remote 協議、重寫 BPM、合併 LTC 雙軌邏輯（另案「行為等價重構」再做）。

---

## 與現況對照（什麼不動）

| 現況 | 新架構中的位置 |
|------|----------------|
| `AudioEngine` 當 master clock | 保留；最終在 `adapters/playback/` |
| 一套 video decode → 多 sink | 保留；扇出改由 `video_output_service` 編排 |
| MA2/MA3 exporters | 原樣進 `adapters/exporters/` |
| Web Remote static JS | 仍在 remote/static；先不拆 JS |
| `MainWindow` | 長期存在，但職責只剩「組裝 + Qt 視窗」 |

---

## Ports 清單（目標）

| Protocol | 用途 |
|----------|------|
| `PlaybackClock` | position / play / pause / seek |
| `AudioDevicePort` | 裝置列舉與串流 |
| `VideoDecoderPort` | `frame_at(t)` |
| `VideoAudioSource` | 嵌入音訊 PCM |
| `FrameSink` | Preview / Clean / NDI / Remote 收幀 |
| `ProjectStore` | load / save / migrate |
| `ShowExporter` | MA2 / MA3 show 匯出 |
| `RemoteHost` | Web Remote 唯一宿主 API |
| `MediaJobQueue` | BPM / LTC / load / prefetch |
| `SongSession` | 換歌與 refresh 契約 |

---

## 成功樣貌（全部搬完後）

- 新功能預設加在 `application/` 或對應 `adapters/`，不再堆進 `main_window.py`。
- 改 Remote 不必怕 MainWindow 私有方法改名。
- 改存檔不必 import `ui`。
- 仍可「只開一個 Module 的 PR」繼續演化。

---

## 一句話

新架構是在現有套件外加 **`ports/` + `application/` + `adapters/`**，用 shim 做 strangler；搬移順序先修依賴方向（columns、RemoteHost），再整包搬 adapters，最後才瘦 UI——全程不要求一次重寫、也不要求一次搬完。
