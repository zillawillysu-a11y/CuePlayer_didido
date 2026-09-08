# MA2 Telnet Live Pool Scan

CuePlayer's live scan is read-only. It uses MA2 Command Telnet to trigger a
scanner Plugin and System Monitor to receive the scanner's framed result.
It never stores, deletes, imports, or changes an object in the current show.

CuePlayer performs the required Telnet option negotiation before it sends MA2
commands, then uses MA2's command-line `Login "user" "password"` syntax.
Telnet control bytes are filtered from CuePlayer's status text, so the status
area shows only actual MA2 feedback.
MA2 also sends an ANSI login screen immediately after connecting; CuePlayer
waits for its `Please login !` prompt before it writes the Login command.

## First-time MA2 setup

1. In MA2, enable Command Telnet on port `30000` and System Monitor on port
   `30001`. Use the console's IP address in CuePlayer; `127.0.0.1` works only
   when CuePlayer and MA2 onPC are on the same computer.
2. In CuePlayer, open **Export Registry** and fill in MA2 Host, ports, the
   exact **MA2 Show User**, and Password. MA2 user names and passwords are
   case-sensitive. CuePlayer sends MA2's `Login "user" "password"` command;
   the password is never saved in the CuePlayer project.
3. Select the target MA2 Output Folder, then click **Write Scan Plugin**.
   CuePlayer writes `CuePlayer_Live_Scan.xml` and `.lua` to the MA2 `plugins`
   folder using the schema matching the selected MA2 version. After changing
   MA2 versions, write the Plugin again before importing it.
4. Set an unused **Plugin Pool** number (CuePlayer defaults to `9999`) and an
   optional **MA2 Plugin Import Path**. For local MA2 onPC, leave the path
   blank: CuePlayer sends the same `Import "CuePlayer_Live_Scan" At Plugin N`
   command that works in MA2's local command line. A remote console needs the
   Plugin files copied to a console-visible drive; enter its MA2-visible path
   only in that case.
5. Click **Import Plugin & Scan**, acknowledge the overwrite warning, and
   CuePlayer sends `Import "CuePlayer_Live_Scan" At Plugin <number>` through
   Command Telnet before running that exact Plugin Pool.
6. Click **Test Connection** in CuePlayer to check only Command Telnet. Then
   click **Scan Current Show** to run the already-installed scanner at the
   configured **Plugin Pool** number. MA2 executes Plugins by Pool number, not
   by their display name.
   A completed scan uses
   its System Monitor result to calculate safe starts for Sequence, Effect,
   Timecode, Song Macro, and View pools.

## Safety and behavior

- Fixed Macro Start, Template Page, executors, and View Layout settings are
  not changed by a scan.
- A timeout, missing scanner Plugin, invalid frame, or unsupported remote MA2
  version leaves the current CuePlayer configuration unchanged.
- Scanner settings Host, Command Port, Monitor Port, and User are stored in
  the project. The scanner Plugin Pool and MA2 import path are also stored.
  Password is session-only.
- The three status lights show Command Telnet, System Monitor, and Plugin/Scan.
  Green all three means the end-to-end scan completed. Red means that the
  latest connection or scan attempt failed.
- **Test Connection** shows a short MA2 response when the console returns one;
  the full end-to-end proof remains a scan with all three status lights green.
- MA2 Import can overwrite an occupied Plugin Pool. CuePlayer requires a
  confirmation but cannot query a Plugin Pool atomically, so select an empty
  ID before using **Import Plugin & Scan**.
- The first scan may take a few seconds because MA2 checks Pool objects up to
  number 9999 for each supported Pool type.
