# Next task

**Verify the grandMA3 2.5 destination-resolution hotfix on real hardware.**

Using CuePlayer's 2.5+ profile, export `S02_XiongZhai` Full again and run the newly
generated install macro. Confirm:

1. Main Go+ Destination names display `TEST_1` and `TEST_2` and trigger the correct cues.
2. Both `Mark_3` and `Mark_4` Top events display and trigger Cue 1.
3. Re-export the imported Timecode and verify every event retains `Object`,
   `ValCueDestination`, and `CueDestination`.

If all three pass, close the MA3 2.5 profile verification task.
