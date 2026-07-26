# Audio routing spike 結果（白話說明）

更新日期：2026-07-26

## 這次在家用電腦測了什麼？

用一小段程式確認：**可以把「左聲道當 LTC、右聲道當音樂」分別送到不同輸出聲道**。

- 右聲道（音樂）→ 裝置 **CH1 + CH2**
- 左聲道（LTC 代替音）→ 裝置 **CH3**
- 順便確認：中文資料夾／檔名、播放、Seek（跳時間）、Stop

## 結果：成功

| 項目 | 結果 |
|------|------|
| 測試 | 6 項通過 |
| 實際使用的裝置 | `CABLE In 16ch (VB-Audio Virtual Cable)`，16 聲道（MME） |
| 路由 | R→CH1+CH2、L→CH3 |
| 中文路徑 | 成功（`fixtures/media/中文測試/LTC左_音樂右_測試.wav`） |
| Focusrite | 家用機沒有，**不算失敗** |

機器上 JSON 明細：`docs/spikes/audio_routing_result.json`

## 為什麼沒用 Focusrite？

Focusrite 在**公司**才有。家裡用 **VB-Audio 虛擬 16 聲道**先把「路由數學」驗證完。  
同一支程式之後在公司接上 Focusrite 再跑一次即可（有 Focusrite 會優先選它）。

公司複測前請在 **Focusrite Control** 確認：

`Playback 1–4` → 直通硬體 `Output 1–4`  
（不要留在預設 stereo pair，否則軟體以為有 4 路，實際聽起來會不對。）

## 之後怎麼再跑

```powershell
cd C:\Users\willy\Projects\CuePlayer
.\.venv\Scripts\Activate.ps1
python -m cueplayer.spikes.audio_routing --seconds 2.0
```

只列裝置：

```powershell
python -m cueplayer.spikes.audio_routing --list-only
```
