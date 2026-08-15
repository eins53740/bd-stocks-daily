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
import os
import sys
import time
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Reuse pick_candidates' aliasing rather than copying TICKER_ALIASES: the two
# round counters have to agree, and a duplicated table is a drift waiting to happen.
from pick_candidates import company_key  # noqa: E402

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


def write_rows_atomically(path: Path, rows: list[dict]) -> None:
    """Replace `path` with a full v2 CSV of `rows` via tmp + os.replace.

    os.replace can raise PermissionError on Windows if a reader (Excel, Obsidian) holds the file
    without FILE_SHARE_DELETE. That failure mode is the safe one -- the original survives intact
    and the tmp is abandoned -- but it is also transient, so retry briefly before giving up rather
    than losing the run's rows to someone having the log open."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS_V2, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({h: r.get(h, "") for h in HEADERS_V2})
    for attempt in range(3):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 2:
                log(f"  ERROR: {path.name} is locked by another process — rows NOT written")
                raise
            time.sleep(0.5)


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

    # Write v2 atomically. This rewrites the entire backtest record in place, so it was the last
    # non-atomic writer left on _log.csv after the supersede path was made atomic — a kill here
    # would truncate the whole history, not one row.
    write_rows_atomically(path, old_rows)
    log(f"  migrated {len(old_rows)} rows")
    return True


def load_existing() -> list[dict]:
    if not LOG.exists() or LOG.stat().st_size == 0:
        return []
    with LOG.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def round_for(ticker: str, entry_date: str, rows: list[dict]) -> int:
    """Round = distinct PRIOR evaluation dates + 1. A same-day screen+deep pair
    (or same-day re-run) is one visit, not two, so `round` counts real revisits.

    Counted per COMPANY, not per ticker string, so it agrees with
    pick_candidates.ticker_round(): evaluating 2330.TW after two TSM visits is
    round 3 in the pick JSON, and used to be written to _log.csv as round 1.
    Anything backtesting "score by round" off the log inherited that error."""
    key = company_key(ticker)
    prior_dates = {
        r.get("date") for r in rows
        if company_key(r.get("ticker", "")) == key and r.get("date") != entry_date
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

    # A re-run of the same ticker in the same mode on the same day SUPERSEDES the
    # earlier row instead of stacking a second one. Without this a manual re-run
    # put a duplicate card in that evening's digest and inflated TODAYCOUNT (which
    # the bat's email gate counts). `mode` is part of the key on purpose: the
    # same-day screen -> deep cascade is two legitimate rows, not a duplicate.
    def key(r: dict) -> tuple:
        return (r.get("ticker", ""), r.get("date", ""), (r.get("mode") or "").strip())

    # Dedupe WITHIN the batch too — `incoming` only filters pre-existing rows, so a caller passing
    # the same (ticker, date, mode) twice would still write both. Last one wins, matching the
    # supersede rule applied to history.
    deduped, seen = [], {}
    for e in entries:
        k = key(e)
        if k in seen:
            log(f"  dropping earlier duplicate of {k[0]} in this batch")
            deduped[seen[k]] = e
        else:
            seen[k] = len(deduped)
            deduped.append(e)
    entries = deduped

    incoming = set(seen)
    kept = [r for r in existing if key(r) not in incoming]
    superseded = len(existing) - len(kept)

    history = list(kept)
    new_rows = []
    for e in entries:
        e = dict(e)
        e["round"] = round_for(e["ticker"], e.get("date", ""), history)
        history.append(e)
        for h in HEADERS_V2:
            e.setdefault(h, "")
        new_rows.append(e)
        log(
            f"  appended {e['ticker']} round={e['round']} score={e.get('score')} "
            f"verdict={e.get('verdict')} mgmt={e.get('management_score')}"
        )

    if superseded:
        # Full rewrite, but only on the rare supersede path -- the ordinary append
        # below stays untouched. tmp + os.replace so a kill mid-write cannot leave
        # a half-written log.
        log(f"  superseding {superseded} same-day row(s) for the same ticker+mode")
        write_rows_atomically(LOG, kept + new_rows)
    else:
        with LOG.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS_V2, extrasaction="ignore")
            if is_new:
                writer.writeheader()
            for e in new_rows:
                writer.writerow(e)

    print(json.dumps({
        "appended": len(entries),
        "superseded": superseded,
        "log_path": str(LOG),
        "schema_version": LOG_SCHEMA_VERSION,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
