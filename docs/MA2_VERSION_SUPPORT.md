# grandMA2 Version Support

## Supported range

- Minimum supported grandMA2 version: 3.3.4.3.
- Current upper target: 3.9.63.6.
- The supported range applies to XML export, Plugins, Views, Sequences, Effects, Timecode, Macros, Export Registry scanning, and Telnet integration.

## Compatibility policy

- CuePlayer must not generate only the newest MA2 schema and assume older versions accept it.
- Output-path version detection selects a verified compatibility profile.
- Unknown versions inside the supported range require an explicitly tested compatible profile or a blocking validation message.
- Versions below 3.3.4.3 are unsupported and must be rejected clearly.
- Telnet uses command port 30000 and optional read-only System Monitor port 30001.
- Scanner records include the detected MA2 version so CuePlayer can select the correct parser/profile.

## Verification required

- Golden XML fixtures for 3.3.4.3, 3.9.60, 3.9.61, and 3.9.63.6 families.
- Plugin import and execution tests on 3.3.4.3 and latest supported 3.9.
- Sequence, Effects, Timecode, Macro, and View round-trip checks.
- Telnet login, scanner framing, disconnect, timeout, and noisy System Monitor tests.
- Unicode paths remain supported by CuePlayer even though MA XML labels remain English-only.

## Completion rule

The application must not claim full 3.3.4.3 support until the golden fixtures and onPC verification above pass.
