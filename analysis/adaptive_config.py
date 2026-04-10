"""
Adaptive Config Engine

Reads proposals from the learning loop and auto-applies them after N confirmations.
Only applies SAFE changes (disabling failing patterns, tightening filters).
Flags DANGEROUS changes (increasing size, loosening risk) for human review.

Philosophy:
  - Conservative by default: require 3 confirmations of the same proposal before applying
  - Safe changes auto-apply: disabling losing strategies, increasing filters
  - Risky changes never auto-apply: increasing position size, lowering stops, raising risk
  - Every change logged to config_changelog.md with timestamp and reason
  - Every change can be rolled back

State files:
  - adaptations.json: proposal history, confirmation counts
  - config_overrides.json: active runtime overrides that get applied in config.py
  - config_changelog.md: human-readable history of all changes

Usage:
  python3.11 adaptive_config.py                 # Process pending proposals
  python3.11 adaptive_config.py --status        # Show current overrides
  python3.11 adaptive_config.py --rollback N    # Undo last N changes
  python3.11 adaptive_config.py --review        # List proposals awaiting confirmation
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict, field

BASE = Path(__file__).resolve().parent.parent
ADAPTATIONS_FILE = BASE / "adaptations.json"
OVERRIDES_FILE = BASE / "config_overrides.json"
CHANGELOG_FILE = BASE / "config_changelog.md"

# How many times a proposal must appear before auto-applying
CONFIRMATIONS_REQUIRED = 3

# Proposals with these keywords are SAFE to auto-apply
SAFE_KEYWORDS = ["disable", "tighten", "reduce", "skip", "decrease"]
# Proposals with these keywords are DANGEROUS — require human review
DANGEROUS_KEYWORDS = ["increase", "scale up", "loosen", "raise", "larger size"]


@dataclass
class Proposal:
    """A proposed config change, tracked across learning loop runs."""
    text: str                    # Human-readable description
    category: str                # "safe" | "dangerous" | "unknown"
    first_seen: str
    last_seen: str
    confirmations: int = 0
    applied: bool = False
    applied_at: str = ""
    rollback_key: str = ""       # Key in config_overrides.json if applied


def load_adaptations() -> dict[str, Proposal]:
    if not ADAPTATIONS_FILE.exists():
        return {}
    data = json.loads(ADAPTATIONS_FILE.read_text())
    return {k: Proposal(**v) for k, v in data.items()}


def save_adaptations(props: dict[str, Proposal]) -> None:
    ADAPTATIONS_FILE.write_text(json.dumps(
        {k: asdict(v) for k, v in props.items()},
        indent=2,
    ))


def load_overrides() -> dict:
    if not OVERRIDES_FILE.exists():
        return {}
    return json.loads(OVERRIDES_FILE.read_text())


def save_overrides(overrides: dict) -> None:
    OVERRIDES_FILE.write_text(json.dumps(overrides, indent=2))


def classify_proposal(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in DANGEROUS_KEYWORDS):
        return "dangerous"
    if any(k in lower for k in SAFE_KEYWORDS):
        return "safe"
    return "unknown"


def log_change(action: str, proposal: Proposal, details: str = "") -> None:
    """Append to changelog."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    if not CHANGELOG_FILE.exists():
        lines.append("# Config Changelog\n")
        lines.append("Every adaptive config change is logged here with reason and rollback info.\n")
    lines.append(f"\n## {ts} — {action}\n")
    lines.append(f"**Proposal:** {proposal.text}")
    lines.append(f"**Category:** {proposal.category}")
    lines.append(f"**Confirmations:** {proposal.confirmations}")
    if details:
        lines.append(f"**Details:** {details}")

    with open(CHANGELOG_FILE, "a") as f:
        f.write("\n".join(lines) + "\n")


def record_proposals(new_proposals: list[str]) -> dict[str, Proposal]:
    """Called by learning_loop.py: record proposals, increment confirmation counts."""
    props = load_adaptations()
    now = datetime.now().isoformat()

    # Normalize: use the proposal text as the key (dedupe exact matches)
    for text in new_proposals:
        key = text.strip()
        if key in props:
            p = props[key]
            p.confirmations += 1
            p.last_seen = now
        else:
            props[key] = Proposal(
                text=text,
                category=classify_proposal(text),
                first_seen=now,
                last_seen=now,
                confirmations=1,
            )

    save_adaptations(props)
    return props


def apply_pending() -> list[Proposal]:
    """Apply any proposals that have enough confirmations AND are safe."""
    props = load_adaptations()
    overrides = load_overrides()
    applied_now: list[Proposal] = []

    for key, p in props.items():
        if p.applied:
            continue
        if p.confirmations < CONFIRMATIONS_REQUIRED:
            continue
        if p.category != "safe":
            # Dangerous or unknown — never auto-apply
            continue

        # Translate the proposal into a concrete config override
        override_key, override_value = _parse_proposal_to_override(p.text)
        if override_key is None:
            continue

        overrides[override_key] = {
            "value": override_value,
            "reason": p.text,
            "applied_at": datetime.now().isoformat(),
            "confirmations": p.confirmations,
        }
        p.applied = True
        p.applied_at = datetime.now().isoformat()
        p.rollback_key = override_key
        applied_now.append(p)

        log_change(f"APPLIED (auto)", p, f"Set {override_key} = {override_value}")
        print(f"  [APPLIED] {p.text}")
        print(f"    → override: {override_key} = {override_value}")

    save_adaptations(props)
    save_overrides(overrides)
    return applied_now


def _parse_proposal_to_override(text: str) -> tuple[str | None, object]:
    """Convert a proposal's natural-language text into a config override key/value."""
    lower = text.lower()

    # "Consider disabling X in Y regime for Z sector" → disable a pattern
    if "disabling" in lower or "disable" in lower:
        # Extract the pattern key if present
        import re
        m = re.search(r"disabling\s+(\w+)", text, re.IGNORECASE)
        if m:
            strategy = m.group(1).upper()
            # Use disabled_strategies list
            return f"disabled_strategies:append:{strategy}", strategy

    # "Consider increasing position size" → dangerous, never applied
    return None, None


def get_active_overrides() -> dict:
    """Return currently applied config overrides for config.py to consume."""
    overrides = load_overrides()
    # Also apply simple-value overrides directly
    return overrides


def rollback_last(n: int = 1) -> None:
    """Rollback the last N applied proposals."""
    props = load_adaptations()
    overrides = load_overrides()

    applied_sorted = sorted(
        [p for p in props.values() if p.applied],
        key=lambda p: p.applied_at,
        reverse=True,
    )

    for p in applied_sorted[:n]:
        if p.rollback_key in overrides:
            del overrides[p.rollback_key]
        p.applied = False
        p.applied_at = ""
        log_change("ROLLBACK", p, f"Removed override {p.rollback_key}")
        print(f"  [ROLLBACK] {p.text}")

    save_adaptations(props)
    save_overrides(overrides)


def show_status() -> None:
    """Print current overrides + pending proposals."""
    overrides = load_overrides()
    props = load_adaptations()

    print("=" * 70)
    print("  ADAPTIVE CONFIG STATUS")
    print("=" * 70)

    print(f"\n  Active overrides: {len(overrides)}")
    if overrides:
        for k, v in overrides.items():
            val = v.get("value", "?") if isinstance(v, dict) else v
            reason = v.get("reason", "") if isinstance(v, dict) else ""
            print(f"    {k:<40} = {val}")
            if reason:
                print(f"      ↳ {reason}")
    else:
        print("    (none — no auto-applied changes yet)")

    print(f"\n  Pending proposals: {sum(1 for p in props.values() if not p.applied)}")
    pending = sorted(
        [p for p in props.values() if not p.applied],
        key=lambda p: p.confirmations,
        reverse=True,
    )
    for p in pending[:10]:
        status = (
            "READY" if p.confirmations >= CONFIRMATIONS_REQUIRED and p.category == "safe"
            else "REVIEW" if p.category == "dangerous"
            else f"{p.confirmations}/{CONFIRMATIONS_REQUIRED}"
        )
        print(f"    [{status:<8}] [{p.category:<9}] {p.text[:55]}")


def review_dangerous() -> None:
    """List proposals that are dangerous or need review."""
    props = load_adaptations()
    dangerous = [p for p in props.values() if p.category == "dangerous"]

    print("=" * 70)
    print("  DANGEROUS PROPOSALS (require manual review)")
    print("=" * 70)
    if not dangerous:
        print("\n  None. The bot hasn't proposed anything risky yet.")
        return

    for p in dangerous:
        print(f"\n  • {p.text}")
        print(f"    Seen {p.confirmations} times, first: {p.first_seen[:10]}, last: {p.last_seen[:10]}")
    print(f"\n  To apply any of these manually, edit config.py directly.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        flag = sys.argv[1]
        if flag == "--status":
            show_status()
        elif flag == "--rollback":
            n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            rollback_last(n)
        elif flag == "--review":
            review_dangerous()
        else:
            print(f"Unknown flag: {flag}")
            print("Options: --status, --rollback N, --review")
    else:
        apply_pending()
        show_status()
