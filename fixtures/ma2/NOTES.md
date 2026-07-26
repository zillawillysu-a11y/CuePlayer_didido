# MA2 golden fixtures notes

Collected: 2026-07-26  
Source folder: `C:\ProgramData\MA Lighting Technologies\grandma\gma2_V_3.9.61\importexport`

Source files:
- `sequ_1_cueplayer_main.xml`
- `sequ_2_cueplayer_button.xml`
- `timecode_1_cueplayer_tc.xml`

## Version

- XML attributes: `major_vers="3" minor_vers="9" stream_vers="61"`
- Matches target grandMA2 **3.9.61.5**

## Observed structure

### main_sequence.xml
- Root namespace: `http://schemas.malighting.de/grandma2/xml/MA`
- Element: `Sequ name="CuePlayer_Main"`
- Cues 1 / 2 / 3 present

### button_sequence.xml
- `Sequ name="CuePlayer_Button"`
- Cue 2: `cue_mode="Release"`
- Cue 2 Trigger: `type="Follow" data_f="0.1"`
- Matches the intended 2-cue self-release pattern

### timecode.xml
- `Timecode name="CuePlayer_TC"`
- Main track Object `CuePlayer_Main 1.1`
  - Events `command="Go"` with nested Cue destinations (MA2 XML token for Go+)
  - Steps 1 / 2 / 3
- Button track Object `CuePlayer_Button 1.2`
  - Events `command="Top"` (three times)
  - No extra cues added to the button sequence for each mark

## Product defaults confirmed

- Main TC: Go(+)-style command with specific cue destination
- Button TC: Top against one self-release sequence
