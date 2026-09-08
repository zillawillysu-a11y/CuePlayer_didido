# Next task

**Verify corrected zero-based grandMA3 2.5 Timecode handles on the console.**

Export `S02_XiongZhai` again using the 2.5+ Full profile and run the newly generated
install macro. Before importing, confirm the Timecode XML uses:

- Main Sequence pool 1: `.6.0`
- Mark_3 Sequence pool 2: `.6.1`
- Mark_4 Sequence pool 3: `.6.2`

On grandMA3 2.5.0.3 confirm Main destinations show their cue names and both Button
tracks show/trigger Cue 1. Re-export the imported Timecode only if a destination fails.
