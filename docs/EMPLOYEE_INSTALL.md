# CuePlayer 員工安裝說明（給測試／使用端）

**不用裝 Git、不用裝 Python。**

---

## 1. 下載 CuePlayer（跟公司拿）

請向發測負責人索取其中一個檔案（二選一即可）：

| 檔案 | 怎麼用 |
|------|--------|
| `CuePlayer-*-win64.zip` | 解壓縮 → 打開資料夾裡的 `CuePlayer.exe` |
| `CuePlayer-Setup-*.exe` | 點兩下安裝 → 從開始功能表或桌面捷徑開啟 |

下載位置由公司提供（例如 Google Drive / NAS / 內部連結），**不是** GitHub。

系統需求：Windows 10 / 11（64 位元）

---

## 2. 若要測 NDI OUTPUT：先裝 NDI

CuePlayer 本身已含 NDI 支援，但每台電腦還要裝官方 Runtime／Tools。

請到官網下載並安裝（擇一即可，建議裝完整 Tools）：

- **NDI Tools（建議）**  
  https://ndi.video/tools/  
  選 Windows 下載安裝。

- **或只裝 NDI Runtime**  
  https://ndi.link/NDIRedistV6  

裝完後**重開 CuePlayer**，再按 NDI OUTPUT。

> 不測 NDI／不用送畫面到 OBS／Depence 的人，可跳過這一步。

---

## 3. 第一次建議這樣測

1. 開啟 CuePlayer  
2. 開一個專案或載入歌曲  
3. 播放音樂、確認 Video（若有）  
4. 需要時再開 NDI OUTPUT（需已完成第 2 步）  
5. 有問題把畫面截圖＋大約操作步驟回報給發測負責人  

---

## 4. 操作說明書（功能怎麼用）

詳細快捷鍵與介面操作見同資料夾／同 Drive 內的：

- `USER_MANUAL.md`（CuePlayer 使用說明）

或請負責人一併提供該檔。
