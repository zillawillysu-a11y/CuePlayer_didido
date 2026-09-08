# grandMA3 XML Profiles

- Users select `2.3`, `2.4`, or `2.5+`; the choice persists per project.
- 2.3/2.4 retain DataVersion 2.4.2.2 and `0.5.<pool-1>` handles.
- 2.5+ uses DataVersion 2.5.0.3 and console-proven `0.6.<pool-1>` handles.
  A same-object 2.3/2.5 console comparison proves Sequence 201 serializes as
  `.5.200` on 2.3 and `.6.200` on 2.5; only the handle kind changes.
- Main Go+ and Button Top both retain explicit CueDestination values.
- Evidence: the user's grandMA3 2.5.0.3 canonical `TC301.xml` export.
