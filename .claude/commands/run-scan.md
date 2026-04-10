---
description: Run the scanner manually and show what setups are available right now
---

Run `orchestrator.py --scan` from the trading directory. This is read-only — it finds signals but does NOT place any orders.

Steps:
1. Verify we're inside `/Users/bopeterlaanen/trading` (check with `git rev-parse --show-toplevel`)
2. Confirm the market is currently open (`TZ=America/New_York date`, market = 09:30-16:00 ET Mon-Fri). If closed, warn the user that signals will be based on last close, not live, and ask if they still want to proceed.
3. Run `python orchestrator.py --scan` and capture output
4. If signals were found, read `signals.csv` for the structured list
5. Present the signals in a table: ticker | strategy | entry | stop | target | R:R | reasoning

For each signal, also check:
- Is this ticker already in `positions.json`? (mark as "already open — skip")
- Does it violate correlation guard? (would push a sector above 30% of portfolio)
- Does it violate heat cap? (would push total heat above 6%)

End with a plain-English take: "Scanner found N raw signals. M would pass all filters and be eligible for execution. Top 3 by R:R are X, Y, Z."

Do NOT execute any trades. This command is observation-only. If the user wants to actually place one of the signals, they can run the full pipeline separately or ask explicitly.
