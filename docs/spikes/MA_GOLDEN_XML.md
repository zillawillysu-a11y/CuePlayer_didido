# grandMA Golden XML 收集清單（公司電腦做）

目標版本：

- grandMA2：**3.9.61.5**
- grandMA3：**2.3.2**

家用機沒有 onPC／控台也沒關係。這份文件是你到公司後照做的步驟。  
拿到 XML 後，放到本專案的 `fixtures/ma2/`、`fixtures/ma3/`，告訴我「XML 放好了」，我再開始寫真正的匯出產生器。

## 為什麼要先收集

CuePlayer 不能猜 MA XML 格式。  
要用 **onPC 實際 Export 出來的檔** 當標準答案（golden fixture），之後程式產生的 XML 才能對得上、測得過。

## 每套軟體都要做這 3 組

### A. Main Sequence（主歌 cue 列表）

手動建立一條 Sequence，裡面有 **2–3 個空 Cue**（有名稱即可，不必真的有燈具資料）。

建議名稱：

- Sequence：`CuePlayer_Main`
- Cue 1 / 2 / 3：`Verse`、`Chorus`、`End`（先用英文，之後再測中文顯示名）

然後 Export Sequence XML。

### B. Top Button Sequence（兩 Cue、自我 Release）

建立另一條 Sequence：

- Cue 1：觸發本體
- Cue 2：`Follow` Cue 1，延遲 **0.1 秒**，並 **Release**
- Executor Key 設成 **Top**（或你們公司慣用的 Top 觸發方式）

建議名稱：`CuePlayer_Button`

然後 Export Sequence XML。

### C. Timecode Show

建立一個 Timecode，包含：

1. **Main**：對 Main Sequence 使用 **Go+ 並指定目標 Cue**（不要用沒有 CueDestination 的裸 Go+）
2. **Button**：同一條 Button Sequence 上，重複多次 **Top** 觸發事件

然後 Export Timecode XML。

## 建議檔名（放到專案裡）

```text
fixtures/ma2/
  main_sequence.xml
  button_sequence.xml
  timecode.xml
  NOTES.txt          # 可選：你實際用的 Page/Executor/Pool 編號

fixtures/ma3/
  main_sequence.xml
  button_sequence.xml
  timecode.xml
  NOTES.txt
```

## MA3 指令提示

在 grandMA3 command line（版本 2.3.x）：

```text
Export Sequence "CuePlayer_Main"
Export Sequence "CuePlayer_Button"
Export Timecode "CuePlayer_TC"
```

檔案通常會出現在 onPC 的 library / datapools 相關資料夾。  
找到後複製進上面的 `fixtures/ma3/`。

## MA2 指令提示

在 grandMA2 用 Export 把對應 Sequence / Timecode 匯出成 XML，  
同樣改名後放進 `fixtures/ma2/`。

## 請順便記在 NOTES.txt

- Sequence Pool 編號
- Timecode Pool 編號
- Page / Executor 編號
- Timecode Slot
- FPS
- MA3 Data Pool 名稱（通常 Default）

## 完成後

回到 CuePlayer 專案跟我說：

> MA XML 已放到 fixtures

我就會：

1. 讀真實 XML 結構  
2. 寫 parser／比對測試  
3. 開始實作 Main Go+(CueDestination) + Button Top 匯出
