# MA2 Telnet Live Pool Scan

CuePlayer's live scan is read-only. It uses MA2 Command Telnet to trigger a
scanner Plugin and System Monitor to receive the scanner's framed result.
It never stores, deletes, imports, or changes an object in the current show.

## First-time MA2 setup

1. In MA2, enable Command Telnet on port `30000` and System Monitor on port
   `30001`. Use the console's IP address in CuePlayer; `127.0.0.1` works only
   when CuePlayer and MA2 onPC are on the same computer.
2. In CuePlayer, open **Export Registry** and fill in MA2 Host, ports, User,
   and Password. The password is never saved in the CuePlayer project.
3. Select the target MA2 Output Folder, then click **Write Scan Plugin**.
   CuePlayer writes `CuePlayer_Live_Scan.xml` and `.lua` to the MA2 `plugins`
   folder.
4. In MA2, import that Plugin once and keep its name as **CuePlayer Live Scan**.
5. Click **Test Connection** in CuePlayer. This only sends an `Echo` command.
6. Click **Scan Current Show**. CuePlayer runs the installed Plugin and uses
   its System Monitor result to calculate safe starts for Sequence, Effect,
   Timecode, Song Macro, and View pools.

## Safety and behavior

- Fixed Macro Start, Template Page, executors, and View Layout settings are
  not changed by a scan.
- A timeout, missing scanner Plugin, invalid frame, or unsupported remote MA2
  version leaves the current CuePlayer configuration unchanged.
- Scanner settings Host, Command Port, Monitor Port, and User are stored in
  the project. Password is session-only.
- The first scan may take a few seconds because MA2 checks Pool objects up to
  number 9999 for each supported Pool type.
