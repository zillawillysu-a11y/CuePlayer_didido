# MA3 golden fixtures notes

Collected: 2026-07-26  
Source files:
- `C:\ProgramData\MALightingTechnology\gma3_library\datapools\sequences\cue_player_main.xml`
- `C:\ProgramData\MALightingTechnology\gma3_library\datapools\sequences\cue_player_button.xml`
- `C:\ProgramData\MALightingTechnology\gma3_library\datapools\timecodes\cue_player_tc.xml`

## Version

- XML `DataVersion`: **2.4.2.2**
- Original product target was grandMA3 **2.3.2**
- Decision pending: keep 2.4.2 as primary golden, or re-export from 2.3.2 for compatibility with older onPC.

## Observed structure

### main_sequence.xml
- Root: `GMA3` / `Sequence Name="CuePlayer_Main"`
- Contains `OffCue`, `CueZero`, then Cue 1/2/3
- Cue 1–3 currently have numbers only (no Verse/Chorus/End labels in XML)

### button_sequence.xml
- Sequence `CuePlayer_Button`
- Cue 2 has `TrigType="Follow"` and `TrigTime="0.100"` (matches hidden 0.1s default)
- Cue 2 does not show an explicit `Release="Yes"` attribute in this export
- OffCue has `Release="Yes"`

### timecode.xml
- Timecode `CuePlayer_TC`
- Track `CuePlayer_Main` Target=`ShowData.DataPools.Default.Sequences.CuePlayer_Main`
  - Events named `Go+` with `CueDestination="Cue 1|2|3"`
  - RealtimeCmd `ExecToken="Go+"` and `ValCueDestination` set per cue
  - **Confirmed product default:** Main TC uses Go+ + CueDestination (user habit). Not Goto.
- Track `CuePlayer_Button`
  - Events named `Top` with `CueDestination="Cue 1"`
  - RealtimeCmd `ExecToken="Top"`
  - Three Top events (good pattern for button marks)

## Follow-ups

1. Confirm whether company shows run 2.3.2 or 2.4.x.
2. Confirm Button Cue 2 Release behavior on console / executor settings.
