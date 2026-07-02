"""
update_log.py - Append evaluation results to _log.csv.

Input (stdin or --entries-json): list of entry dicts with keys:
  ticker, date, mode, verdict, score, gates_passed, price_at_eval, currency,
  size, notes, management_score, management_flag, bear_case_trigger

Calculates `round` (1-based count of prior evaluations for each ticker).

Schema v2 (2026-04-20): adds management_score, management_flag, bear_case_trigger,
and ensures `size` is present between `currency` and `notes`. Legacy files with
v1 headers are migrated once on open (non-destructive: unknown old fields drop,
missing new fields become blank).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

LOG = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily\_log.csv")
LOG_SCHEMA_VERSION = 2

HEADERS_V2 = [
    "ticker", "date", "round", "mode", "verdict", "score",
    "gates_passed", "price_at_eval", "currency", "size", "notes",
    "management_score", "management_flag", "bear_case_trigger",
]


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def read_header(path: Path) -> list[str] | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            return next(reader)
        except StopIteration:
            return None


def migrate_if_needed(path: Path) -> bool:
    """
    If file headers do not match HEADERS_V2, rewrite the file with v2 headers
    carrying over any matching field names and blanking the rest. Returns True
    when a rewrite happened.
    """
    current = read_header(path)
    if current is None or current == HEADERS_V2:
        return False

    log(f"  migrating _log.csv from headers={current} to v{LOG_SCHEMA_VERSION}")
    # Read all rows under the old schema
    with path.open("r", encoding="utf-8", newline="") as f:
        old_rows = list(csv.DictReader(f))

    # Write v2
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS_V2, extrasaction="ignore")
        writer.writeheader()
        for r in old_rows:
            row_v2 = {h: r.get(h, "") for h in HEADERS_V2}
            writer.writerow(row_v2)
    log(f"  migrated {len(old_rows)} rows")
    return True


def load_existing() -> list[dict]:
    if not LOG.exists() or LOG.stat().st_size == 0:
        return []
    with LOG.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def round_for(ticker: str, entry_date: str, rows: list[dict]) -> int:
    """Round = distinct PRIOR evaluation dates + 1. A same-day screen+deep pair
    (or same-day re-run) is one visit, not two, so `round` counts real revisits."""
    prior_dates = {
        r.get("date") for r in rows
        if r.get("ticker") == ticker and r.get("date") != entry_date
    }
    return len(prior_dates) + 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entries-json", help="Inline JSON list; if omitted reads from stdin")
    args = ap.parse_args()

    raw = args.entries_json or sys.stdin.read()
    entries = json.loads(raw)
    if not isinstance(entries, list):
        entries = [entries]

    LOG.parent.mkdir(parents=True, exist_ok=True)
    migrate_if_needed(LOG)

    existing = load_existing()
    is_new = not LOG.exists() or LOG.stat().st_size == 0

    with LOG.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS_V2, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        for e in entries:
            e = dict(e)
            e["round"] = round_for(e["ticker"], e.get("date", ""), existing)
            existing.append(e)
            for h in HEADERS_V2:
                e.setdefault(h, "")
            writer.writerow(e)
            log(
                f"  appended {e['ticker']} round={e['round']} score={e.get('score')} "
                f"verdict={e.get('verdict')} mgmt={e.get('management_score')}"
            )

    print(json.dumps({
        "appended": len(entries),
        "log_path": str(LOG),
        "schema_version": LOG_SCHEMA_VERSION,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
