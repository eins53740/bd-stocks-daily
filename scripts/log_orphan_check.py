"""
log_orphan_check.py - find reports that exist on disk but have no _log.csv row.

WHY THIS EXISTS (roadmap R12, diagnosed 2026-08-18)
---------------------------------------------------
On 2026-08-17 the 13:30 deep run on vmhost1 rendered a complete ROVI.MC report -- node
timings at 13:32, financial history 13:33, charts 13:40, markdown 13:52, HTML 13:53 -- and
the digest attached it and delivered it at 13:56. `_log.csv` never got a row: its mtime
stayed at 2026-08-16 23:29.

The report was delivered anyway because the two paths are independent:
  * send_email.py attaches report FILES by date glob;
  * the dedupe, the dashboard's All-Evaluations view and report_history read _log.csv ROWS.
So the evaluation was invisible to the 6-month dedupe -- the same ticker could be picked
again the next day as if it had never been seen -- while looking perfectly delivered to the
human reading the digest. The email gate did not notice either: it counted 4 rows for that
date, all of them from _growth_log.csv.

That is the class of defect this script closes: "delivered but unlogged". It is deliberately
a CHECK first (exit 1 on orphans, exit 0 when clean) so the failover watchdog can call it,
and only writes with --fix.

Usage:
  python log_orphan_check.py                 # report orphans, exit 1 if any
  python log_orphan_check.py --fix           # append the missing rows from the frontmatter
  python log_orphan_check.py --since 2026-08-01
"""
from __future__ import annotations

import argparse
import csv
import shutil
import socket
import sys
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# RESOLVED, not hardcoded. The laptop keeps the vault on C:; vmhost1 keeps it on D: and
# exposes C:\BD_Obsidian\Personal as a junction to it -- a junction that a NETWORK logon
# cannot traverse ("the path cannot be traversed because it contains an untrusted mount
# point"), so a C:-only path works for a locally-run task and fails over SSH. Probing both
# is what makes this script runnable from either machine and from either context.
# NOTE: 35 scripts in this skill still hardcode C:\BD_Obsidian. Roadmap R11 generalises this.
_CANDIDATES = (
    Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily"),
    Path(r"D:\BD_Obsidian\Personal\Finance\StocksDaily"),
)
HEADERS = ["ticker", "date", "round", "mode", "verdict", "score", "gates_passed",
           "price_at_eval", "currency", "size", "notes", "management_score",
           "management_flag", "bear_case_trigger"]


def describe_root(root: Path) -> str:
    r"""`<host>  <path>` and, when the path is a junction, where it actually lands.

    WHY (roadmap R12, found by Bruno on 2026-08-18). This line used to print just `root`,
    and `root` is picked by probing C: then D:. On vmhost1 `C:\BD_Obsidian\Personal` is a
    JUNCTION to `D:\BD_Obsidian\Personal`, so C: matches there too and the line printed
    `C:\BD_Obsidian\...` on BOTH machines. In a tool whose whole premise is that only ONE
    machine may be written -- the laptop is a read-only mirror that StocksMirrorPull
    overwrites at 09:30 and 15:30 -- the identity of the target is precisely the thing it
    must not be silent about. Establishing which machine had actually been fixed took
    comparing line counts and a backup file's mtime on both boxes; the tool should have just
    said so.
    """
    host = socket.gethostname()
    try:
        real = root.resolve()
    except OSError:
        return f"{host}  {root}  (could not resolve)"
    if str(real).lower() != str(root).lower():
        return f"{host}  {root}  ->  {real}  (junction)"
    return f"{host}  {root}"


def state_dir() -> Path:
    for p in _CANDIDATES:
        if (p / "_log.csv").exists():
            return p
    raise SystemExit(f"no _log.csv under any of: {', '.join(str(p) for p in _CANDIDATES)}")


def frontmatter(path: Path) -> dict[str, str]:
    """Minimal YAML front-matter reader: flat `key: value` pairs only, which is all the
    report writes. Values keep their quotes stripped; nothing else is interpreted."""
    out: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line.startswith((" ", "\t", "-")):
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true",
                    help="append the missing rows, reading each report's own front matter")
    ap.add_argument("--since", default="", help="only consider reports dated >= this ISO date")
    args = ap.parse_args()

    root = state_dir()
    log = root / "_log.csv"
    rows = list(csv.DictReader(log.open(newline="", encoding="utf-8")))
    logged = {(r["ticker"], r["date"]) for r in rows}

    orphans: list[tuple[Path, dict[str, str]]] = []
    for rep in sorted(root.glob("*_review.md")):
        fm = frontmatter(rep)
        tic, date = fm.get("ticker"), fm.get("date")
        if not tic or not date:
            print(f"SKIP  {rep.name}: no ticker/date in front matter")
            continue
        if args.since and date < args.since:
            continue
        if (tic, date) not in logged:
            orphans.append((rep, fm))

    print(f"state    : {describe_root(root)}")
    print(f"reports  : {len(list(root.glob('*_review.md')))} on disk, {len(rows)} rows in _log.csv")
    if not orphans:
        print("ORPHANS  : none - every report on disk has a _log.csv row")
        return 0

    print(f"ORPHANS  : {len(orphans)} report(s) delivered but never logged")
    for rep, fm in orphans:
        print(f"  {fm['date']}  {fm['ticker']:<10} {fm.get('mode','?'):<6} "
              f"{fm.get('verdict','?'):<7} score={fm.get('score','?'):<5} {rep.name}")

    if not args.fix:
        print("\nrun again with --fix to append these rows from each report's front matter")
        return 1

    for _rep, fm in orphans:
        rows.append({
            "ticker": fm["ticker"], "date": fm["date"], "round": fm.get("round", "1"),
            "mode": fm.get("mode", "deep"), "verdict": fm.get("verdict", ""),
            "score": fm.get("score", ""), "gates_passed": fm.get("gates_passed", ""),
            "price_at_eval": fm.get("price_at_eval", ""), "currency": fm.get("currency", ""),
            "size": fm.get("size", ""),
            "notes": f"backfilled by log_orphan_check.py: report existed, row did not (R12)",
            "management_score": fm.get("management_score", ""),
            "management_flag": str(fm.get("management_flag", "")).capitalize(),
            "bear_case_trigger": fm.get("bear_case_trigger", ""),
        })
    rows.sort(key=lambda r: (r["date"], r["ticker"]))

    shutil.copy2(log, str(log) + ".pre-orphan-fix")
    tmp = log.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADERS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(log)

    after = list(csv.DictReader(log.open(newline="", encoding="utf-8")))
    print(f"\nFIXED    : {len(rows) - len(after) + len(after)} rows written "
          f"({len(after)} total, was {len(after) - len(orphans)}); "
          f"backup at {Path(str(log) + '.pre-orphan-fix').name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
