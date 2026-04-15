# Context — Phase 6: Collaborator Onboarding

## Locked Decisions

1. **Virtual budget, not Alpaca reset:** Alpaca paper accounts start at $100K and can't be set to a custom amount via API. The system tracks the user's chosen budget internally via `starting_capital` in config. Position sizing, risk calcs, and portfolio tracking all use the configured amount. The Alpaca account has more but the system ignores the excess.

2. **user_config.json for per-user settings:** Created by setup.sh, read by config.py, gitignored. Each collaborator gets their own. Falls back to defaults if missing. Currently only holds starting_capital but structured for future extension.

3. **CLAUDE.md stays for Claude:** It's the AI session guide. Human collaborator guidance goes in README under "For Collaborators" section.

4. **Alpaca market scope:** US stocks and ETFs. ~700 international ADRs trading on US exchanges. No European exchanges, no forex, no futures. Crypto available on Alpaca but not wired into this system. Paper trading available from any country.

5. **Europe eligibility:** Paper trading has no geographic restrictions. Live trading from EU requires individual verification with Alpaca support.

6. **Target scales with starting capital:** If starting_capital is $5K instead of $10K, target_capital scales proportionally (2.5x multiplier from the default $10K→$25K ratio).

## Review Decisions

1. [review] Guard against target_capital <= starting_capital in __post_init__ after loading user_config.json. Division by zero in orchestrator.py:291 and risk_manager.py:475 if they're equal.
2. [review] Use Python json.dump in setup.sh to write user_config.json instead of bash echo — prevents malformed JSON from user input edge cases.
3. [review] "For Collaborators" section in README should note Claude Code is required for slash commands and link to installation.

4. [review] Use `Path(__file__).parent / "user_config.json"` for path resolution — `os.getcwd()` breaks when config.py is imported from another directory.
5. [review] Derive target multiplier from `default_target / default_starting` ratio instead of hardcoding 2.5 — stays in sync if defaults change.
6. [review] setup.sh capital input must use `while true; do ... break; done` loop because `set -euo pipefail` would exit the script on validation failure.
7. [review] setup.sh detects existing `user_config.json` on re-run and shows current value with keep-or-change prompt — prevents silent overwrite.
8. [review] README risk section dollar examples replaced with percentages to be correct for any starting_capital.
9. [review] `.gitignore` update is an explicit Task 5, not an implied side-effect.
10. [review] `__post_init__` order: (1) load user_config.json, (2) apply paper_exploration_mode. Capital doesn't interact with exploration but order matters for readability.

## Deferred Ideas

- Allow user_config.json to set target_capital directly — deferred, the 2.5x multiplier is sufficient for now and avoids the division-by-zero risk
- Add a "run setup again to change settings" re-run mode for setup.sh — deferred, users can edit user_config.json directly

## Files Modified

- `config.py` — read user_config.json in __post_init__, override starting_capital and target_capital
- `setup.sh` — new step for starting amount selection, paper trading education
- `README.md` — market scope section, collaborator guide with slash commands
- `CLAUDE.md` — reference user_config.json in session start checklist
- `.gitignore` — add user_config.json
- `user_config.json` — new, created by setup.sh (gitignored)
