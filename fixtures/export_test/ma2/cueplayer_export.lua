-- CuePlayer MA2 install plugin (.xml + .lua pair)
local function Start()
  gma.cmd('Import "cueplayer_test_main.xml" At Sequence 1 /nc')
  gma.cmd('Label Sequence 1 "CuePlayer_Main"')
  gma.cmd('Assign Sequence 1 At Exec 1.101')
  gma.cmd('Assign Go At Exec 1.101')
  gma.cmd('Import "cueplayer_test_button.xml" At Sequence 2 /nc')
  gma.cmd('Label Sequence 2 "CuePlayer_Button"')
  gma.cmd('Assign Sequence 2 At Exec 1.201')
  gma.cmd('Assign Top At Exec 1.201')
  gma.cmd('Import "cueplayer_test_timecode.xml" At Timecode 1 /nc')
  gma.cmd('Label Timecode 1 "CuePlayer_TC"')
  gma.echo("CuePlayer export installed: Seq 1/2, Exec 1.101/1.201, TC 1")
end

local function Cleanup()
end

return Start, Cleanup
