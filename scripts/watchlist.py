"""
watchlist.py — v4 Phase E price-triggered watch-list maintenance.

A quality name that clears the compounder bar (composite >= 7) but is held back
*only* by price (Phase B margin-of-safety class == "rich") is not a "no" — it is a
"not yet". This script maintains `_watchlist.csv` so the daily email can shout when
such a name finally falls to its fair-low target.

Membership rule (the whole policy, in one line):
    keep on the list  iff  composite >= 7  AND  mos_class == "rich"  AND  not held
                            AND fair_value_range.low is available (the target)
Anything else ⇒ ensure absent. That single rule subsumes every removal the spec
lists: a *buy* (now held), a *thesis break / quality loss* (score drops < 7), and a
*graduation to cheap* (mos_class leaves "rich"). No separate remove paths needed.

Overlay-only: this reads the analysis JSON but never writes into it and never
touches the composite/verdict. It maintains an external CSV only. Live-price
triggering happens later, in send_email.py (this script does no network I/O).

Reuses exit_plan.load_holdings / find_holding so held-detection (incl. the
SHEL.L -> SHELL.AS alias and asset_type handling) matches the exit-plan node
exactly. Failure prints {"error": ...} and returns 0 so the orchestrator skips
the step without aborting the run.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

# Force UTF-8 on Windows so unicode in output doesn't crash the cp1252 console.
for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from exit_plan import find_holding, load_holdings  # noqa: E402  (shared held-detection)

OUT_DIR_DEFAULT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
WATCHLIST_FILENAME = "_watchlist.csv"
QUALITY_FLOOR = 7.0  # composite >= this = the compounder bar cleared

# Column order is the CSV contract read by send_email.read_watchlist_rows().
COLUMNS = ["ticker", "target", "currency", "added_date", "fair_low",
           "mos_class", "score", "fail_reason", "thesis"]


def log(msg: str) -> None:
    print(f"[watchlist] {msg}", file=sys.stderr)


# ===================================================================
# Pure functions (no I/O — unit-tested)
# ===================================================================
def is_watchlist_eligible(score, mos_class, fair_low) -> bool:
    """A name is watch-list material when quality is proven (composite >= 7) but
    price is the only thing holding it back (MoS 'rich') AND we have a numeric
    fair-low to use as the alert target."""
    return (
        score is not None and float(score) >= QUALITY_FLOOR
        and mos_class == "rich"
        and fair_low is not None and float(fair_low) > 0
    )


def should_be_on_list(score, mos_class, fair_low, held: bool) -> bool:
    """Keep iff eligible AND not held (a buy graduates it off the list)."""
    return is_watchlist_eligible(score, mos_class, fair_low) and not held


def distance_to_target_pct(live, target):
    """How far `live` sits above `target`, in %. <= 0 means triggered (live at or
    below target). None when either input is missing/non-positive."""
    if live is None or target is None:
        return None
    try:
        live_f, target_f = float(live), float(target)
    except (TypeError, ValueError):
        return None
    if target_f <= 0:
        return None
    return round((live_f / target_f - 1.0) * 100.0, 2)


def remove_ticker(rows: list, ticker: str) -> list:
    """All rows except the one for `ticker` (case-insensitive on the symbol)."""
    t = (ticker or "").upper()
    return [r for r in rows if (r.get("ticker") or "").upper() != t]


def upsert_row(rows: list, new_row: dict) -> list:
    """Replace the existing row for this ticker (preserving its original
    added_date) or append. Ticker match is case-insensitive."""
    t = (new_row.get("ticker") or "").upper()
    out, replaced = [], False
    for r in rows:
        if (r.get("ticker") or "").upper() == t:
            merged = dict(new_row)
            if r.get("added_date"):
                merged["added_date"] = r["added_date"]  # keep first-seen date
            out.append(merged)
            replaced = True
        else:
            out.append(r)
    if not replaced:
        out.append(new_row)
    return out


def build_row(ticker: str, target, currency, fair_low, mos_class, score,
              mos_pct, today_iso: str) -> dict:
    """One CSV row for an eligible name. thesis is a short synthesized note."""
    mos_txt = f"; MoS {mos_pct:+.0f}%" if isinstance(mos_pct, (int, float)) else ""
    return {
        "ticker": ticker,
        "target": round(float(target), 4),
        "currency": currency or "",
        "added_date": today_iso,
        "fair_low": round(float(fair_low), 4),
        "mos_class": mos_class,
        "score": round(float(score), 2),
        "fail_reason": "price rich (MoS)",
        "thesis": f"Quality {float(score):.1f}/10, price rich{mos_txt} — "
                  f"buy near fair-low {round(float(target), 2)}",
    }


def apply_maintenance(rows: list, ticker: str, score, mos_class, fair_low,
                      held: bool, currency, mos_pct, today_iso: str) -> tuple:
    """Apply the one-line membership rule. Returns (new_rows, action)."""
    if should_be_on_list(score, mos_class, fair_low, held):
        row = build_row(ticker, fair_low, currency, fair_low, mos_class,
                        score, mos_pct, today_iso)
        return upsert_row(rows, row), "kept"
    was_present = any((r.get("ticker") or "").upper() == (ticker or "").upper()
                      for r in rows)
    return (remove_ticker(rows, ticker), "removed") if was_present else (rows, "absent")


# ===================================================================
# CSV I/O
# ===================================================================
def load_watchlist(out_dir: Path) -> list:
    """Rows from _watchlist.csv. Missing/empty/unreadable ⇒ [] (non-fatal).

    Also imported by send_email.py — keep the guarded-reader contract stable."""
    path = out_dir / WATCHLIST_FILENAME
    try:
        if not path.exists() or path.stat().st_size == 0:
            return []
        with path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def write_watchlist(out_dir: Path, rows: list) -> None:
    path = out_dir / WATCHLIST_FILENAME
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in COLUMNS})


# ===================================================================
# Main
# ===================================================================
def run(analysis_json: str, out_dir: Path, today_iso: str, do_update: bool) -> dict:
    data = json.loads(Path(analysis_json).read_text(encoding="utf-8"))
    ticker = data.get("ticker")
    if not ticker:
        return {"error": "analysis JSON has no ticker"}

    score = (data.get("scores") or {}).get("composite")
    iv = data.get("intrinsic_value") or {}
    mos_class = iv.get("mos_class")
    mos_pct = iv.get("mos_pct")
    fair_low = ((iv.get("fair_value_range") or {}).get("low"))
    currency = data.get("currency")

    holdings, warnings = load_holdings(out_dir)
    holding, w = find_holding(ticker, holdings)
    warnings += w
    held = holding is not None

    rows = load_watchlist(out_dir)
    new_rows, action = apply_maintenance(
        rows, ticker, score, mos_class, fair_low, held, currency, mos_pct, today_iso)

    if do_update:
        write_watchlist(out_dir, new_rows)
        log(f"{ticker}: {action} (score={score}, mos={mos_class}, held={held}); "
            f"list now {len(new_rows)} name(s)")

    return {
        "ticker": ticker,
        "action": action,
        "eligible": is_watchlist_eligible(score, mos_class, fair_low),
        "held": held,
        "score": score,
        "mos_class": mos_class,
        "fair_low": fair_low,
        "watchlist_size": len(new_rows),
        "warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Maintain the price-triggered watch-list (_watchlist.csv)")
    ap.add_argument("--analysis-json", required=True,
                    help="analyze_ticker JSON, after valuation_bands/intrinsic_value --update")
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--update", action="store_true",
                    help="Write the maintained list to _watchlist.csv")
    args = ap.parse_args()

    try:
        result = run(args.analysis_json, Path(args.out_dir), date.today().isoformat(),
                     do_update=args.update)
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        print(json.dumps({"error": str(e), "error_type": type(e).__name__}))
        return 0  # non-fatal: watch-list unchanged, run continues

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
