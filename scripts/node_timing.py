"""node_timing.py -- per-node elapsed timings for the daily pipeline.

WHY
  The 13:30 job runs under a 30-minute wall-clock budget and has ~6 minutes of headroom
  on a good day (measured 22m21s and 23m41s on 2026-08-14 / 08-13). v4.3 wants to add work
  to that path -- financial history for the screens, EDGAR, two charts, a SWOT image,
  mermaid rendering. Deciding what may be default-on needs DATA, not guesses, and until now
  the only timing available was the bat's start/end pair for the whole run.

  So: every node appends one line here, and `--report` turns the day's lines into a table.

DESIGN
  * Append-only JSONL, one file per date: {OUT_DIR}/_timings/{YYYY-MM-DD}.jsonl
  * Append-only means concurrent nodes cannot clobber each other, and a killed run keeps
    everything written so far -- which is exactly the case we most need to diagnose
    (the 2026-08-15 timeout lost Phase 6 entirely).
  * NEVER raises. Instrumentation that can break the pipeline is worse than no
    instrumentation; every entry point swallows its own errors.

USE -- as a context manager, one line per node:

    from node_timing import timed
    with timed("2.2", ticker="ASML.AS"):
        ...work...

USE -- from the shell, wrapping any command without touching the script:

    python node_timing.py --node 2.2 --ticker ASML.AS -- python financial_history.py --ticker ASML.AS

REPORT:

    python node_timing.py --report              # today
    python node_timing.py --report 2026-08-14   # a given date
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

OUT_DIR = Path(os.environ.get("BD_STOCKS_OUT_DIR", r"C:\BD_Obsidian\Personal\Finance\StocksDaily"))
TIMINGS_DIR = OUT_DIR / "_timings"

# Set BD_TIMINGS=0 to disable recording entirely (the report path still works).
ENABLED = os.environ.get("BD_TIMINGS", "1") != "0"


def _path_for(day: str | None = None) -> Path:
    return TIMINGS_DIR / f"{day or date.today().isoformat()}.jsonl"


def record(node: str, elapsed_s: float, *, ticker: str | None = None,
           ok: bool = True, note: str | None = None) -> None:
    """Append one timing line. Silent on any failure -- never breaks a run."""
    if not ENABLED:
        return
    try:
        TIMINGS_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "node": node,
            "elapsed_s": round(float(elapsed_s), 2),
            "ok": bool(ok),
            "at": time.strftime("%H:%M:%S"),
        }
        if ticker:
            entry["ticker"] = ticker
        if note:
            entry["note"] = note
        with _path_for().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # deliberate: instrumentation must never take the pipeline down


@contextmanager
def timed(node: str, *, ticker: str | None = None, note: str | None = None):
    """Time a block and record it, whether or not the block raised."""
    t0 = time.monotonic()
    ok = True
    try:
        yield
    except BaseException:
        ok = False
        raise
    finally:
        record(node, time.monotonic() - t0, ticker=ticker, ok=ok, note=note)


def load(day: str | None = None) -> list[dict]:
    """Read a day's entries. Returns [] if absent; skips unparseable lines."""
    p = _path_for(day)
    if not p.exists():
        return []
    rows: list[dict] = []
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return []
    return rows


def summarise(rows: list[dict]) -> list[dict]:
    """Aggregate per node: calls, total, mean, max. Sorted by total time descending --
    the ordering that answers 'what is eating the budget?'."""
    agg: dict[str, dict] = {}
    for r in rows:
        node = str(r.get("node", "?"))
        e = float(r.get("elapsed_s") or 0.0)
        a = agg.setdefault(node, {"node": node, "calls": 0, "total_s": 0.0,
                                  "max_s": 0.0, "failures": 0})
        a["calls"] += 1
        a["total_s"] += e
        a["max_s"] = max(a["max_s"], e)
        if not r.get("ok", True):
            a["failures"] += 1
    out = []
    for a in agg.values():
        a["total_s"] = round(a["total_s"], 1)
        a["max_s"] = round(a["max_s"], 1)
        a["mean_s"] = round(a["total_s"] / a["calls"], 1) if a["calls"] else 0.0
        out.append(a)
    return sorted(out, key=lambda a: a["total_s"], reverse=True)


def _print_report(day: str | None) -> int:
    rows = load(day)
    label = day or date.today().isoformat()
    if not rows:
        print(f"no timings recorded for {label} ({_path_for(day)})")
        return 0
    summary = summarise(rows)
    grand = sum(a["total_s"] for a in summary)
    print(f"Node timings for {label} -- {len(rows)} calls, {grand:.0f}s total "
          f"({grand / 60:.1f} min) against a 1800s budget\n")
    print(f"{'node':<10} {'calls':>5} {'total_s':>9} {'mean_s':>8} {'max_s':>8} {'fail':>5}")
    print("-" * 50)
    for a in summary:
        print(f"{a['node']:<10} {a['calls']:>5} {a['total_s']:>9.1f} "
              f"{a['mean_s']:>8.1f} {a['max_s']:>8.1f} {a['failures']:>5}")
    print("-" * 50)
    print(f"{'TOTAL':<10} {len(rows):>5} {grand:>9.1f}")
    if grand > 1800:
        print("\n!! over the 1800s ceiling -- something must move off the scheduled path")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--node", help="node id to record, e.g. 2.2")
    ap.add_argument("--ticker")
    ap.add_argument("--note")
    ap.add_argument("--report", nargs="?", const="__today__", metavar="DATE",
                    help="print a summary table for DATE (default today)")
    ap.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="-- followed by the command to time")
    args = ap.parse_args(argv)

    if args.report:
        return _print_report(None if args.report == "__today__" else args.report)

    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        ap.error("nothing to do: pass --report, or --node NODE -- <command>")
    if not args.node:
        ap.error("--node is required when timing a command")

    t0 = time.monotonic()
    rc = 1
    try:
        rc = subprocess.call(cmd)
    finally:
        record(args.node, time.monotonic() - t0, ticker=args.ticker,
               ok=(rc == 0), note=args.note)
    return rc


if __name__ == "__main__":
    sys.exit(main())
