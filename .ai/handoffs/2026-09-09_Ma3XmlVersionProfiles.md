# grandMA3 XML Version Profiles

## Task objective
Add selectable 2.3/2.4/2.5+ export profiles.
## What was implemented
Persisted UI selection; legacy `.5.<pool-1>` and new `.6.<actual pool>` serializers;
explicit Main/Button destinations retained.
## Files changed
Domain, persistence, plan, MA3 exporter, Show Patch/Export dialogs, tests and docs.
## Architecture decisions
Exporter profile owns syntax; legacy projects default 2.4, new projects 2.5.
## Tests performed
291 exporter/persistence/UI tests passed; compileall passed.
## Remaining issues
Physical 2.5 import/re-export comparison remains.
## Suggested next task
Run the exact hardware verification in `.ai/NEXT_TASK.md`.
