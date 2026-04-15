# Phase 6 Summary: Collaborator Onboarding

## Status: Complete

## What was built

### Task 1: user_config.json support in config.py
- `AgentConfig.__post_init__` reads `user_config.json` via `Path(__file__).parent`
- Overrides `starting_capital` and derives `target_capital` using the default ratio (2.5x)
- Guard ensures `target_capital > starting_capital`
- Catches only `FileNotFoundError` and `json.JSONDecodeError` — permission errors surface

### Task 2: Starting capital selection in setup.sh
- New Step 4 of 6 with paper trading budget explanation
- Re-run detection: shows current value if `user_config.json` exists
- Input validation via `while true; do ... break; done` (compatible with `set -euo pipefail`)
- Writes JSON via `python -c "import json; ..."` for guaranteed valid output
- All step headers updated to "X of 6"

### Task 3: README market scope and collaborator guide
- "What markets does this cover?" section: US stocks/ETFs, ADRs, exclusions, paper trading geography
- "For Collaborators" section: session behavior, slash commands table, when to clear, what persists
- Risk examples use percentages, not dollar amounts tied to $10K

### Task 4: CLAUDE.md user_config.json awareness
- Added to session start checklist as item 6
- Added to Environment section with explanation of what it does and that it's gitignored

### Task 5: .gitignore
- `user_config.json` added to runtime/live state group

## Files modified
- `config.py` — user_config.json loading in __post_init__
- `setup.sh` — Step 4 capital selection with validation
- `README.md` — market scope + collaborator guide sections
- `CLAUDE.md` — user_config.json references
- `.gitignore` — user_config.json entry

## Test metrics
- Existing tests (`test_simulation.py`, `test_executor.py`) unaffected — no business logic changes
- config.py changes are backwards-compatible (falls back to defaults without user_config.json)
