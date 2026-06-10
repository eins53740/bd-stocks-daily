"""
portfolio_dashboard.py — Phase 4 step 2.

Take the holdings bundle produced by portfolio_sync.py, enrich each EQUITY holding
with its most-recent Fundamental Score + verdict (from _log.csv) and Technical
Score / GO-NO-GO (from the report frontmatter, via build_dashboard's slim parse),
compute an Overall Investment Score, run a deterministic Decision Engine
(Hold / Buy-More / Sell / Review — each with a cited trigger), and write
``_portfolio.json`` for the stdlib dashboard renderer.

Freshness: scores older than FRESHNESS_DAYS (90d, matching the shortlist expiry in
build_dashboard.py) are flagged ``score_stale: true`` and never silently used —
a stale holding is routed to ``Review`` with a "needs screen" trigger.

The decision engine functions (decide / overall_score / is_fresh) are PURE — no
network, no DB, no filesystem — so tests can exercise them directly.

Usage:
  python portfolio_dashboard.py                  # syncs (via portfolio_sync) + writes _portfolio.json
  python portfolio_dashboard.py --bundle FILE    # use a pre-made sync bundle instead of syncing
  python portfolio_dashboard.py --no-prices      # pass-through to portfolio_sync
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
LOG = ROOT / "_log.csv"
OUT_JSON = ROOT / "_portfolio.json"

FRESHNESS_DAYS = 90  # consistent with build_dashboard.py shortlist expiry

# Verdicts that signal fundamental deterioration (cite as Sell/Review trigger).
WEAK_VERDICTS = {"reject", "fair"}
STRONG_VERDICTS = {"great", "invest"}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ----------------------------------------------------------------------------
# PURE decision-engine helpers (unit-tested — no I/O)
# ----------------------------------------------------------------------------

def is_fresh(score_date: str | None, today: date, window: int = FRESHNESS_DAYS) -> bool:
    """True if score_date is within `window` days of today (inclusive)."""
    if not score_date:
        return False
    try:
        d = date.fromisoformat(score_date[:10])
    except (ValueError, TypeError):
        return False
    age = (today - d).days
    return 0 <= age <= window


def overall_score(fund: float | None, tech: float | None) -> float | None:
    """Overall Investment Score: 70% fundamental + 30% technical when both present;
    otherwise the available one. Returns None if neither is present."""
    if fund is None and tech is None:
        return None
    if fund is None:
        return round(tech, 2)
    if tech is None:
        return round(fund, 2)
    return round(0.70 * fund + 0.30 * tech, 2)


def decide(h: dict) -> dict:
    """Decision engine. Pure function over an enriched holding dict.

    Returns {decision, trigger} where decision is one of:
      Hold | Buy-More | Sell | Review

    Expected keys on `h` (all optional unless noted):
      fund_score (float|None), tech_score (float|None), verdict (str|None),
      go_no_go (str|None), thesis_status (str|None: intact/weakened/broken),
      score_stale (bool), weight (float|None 0..1), live_price (float|None),
      avg_buy_price (float|None), overall (float|None)
    """
    verdict = (h.get("verdict") or "").lower()
    go = (h.get("go_no_go") or "").upper()
    thesis = (h.get("thesis_status") or "").lower()
    fund = h.get("fund_score")
    overall = h.get("overall")
    weight = h.get("weight")
    live = h.get("live_price")
    avg = h.get("avg_buy_price")

    # 1) No fresh data at all -> Review (needs screen). Never silently hold on stale numbers.
    if h.get("score_stale") or fund is None:
        return {
            "decision": "Review",
            "trigger": "No fresh evaluation within "
                       f"{FRESHNESS_DAYS}d (score_stale) — needs a screen before any action.",
        }

    # 2) Thesis invalidation (thesis_check logic) -> Sell.
    if thesis == "broken":
        return {
            "decision": "Sell",
            "trigger": "Thesis invalidated — pillar-integrity check returned BROKEN.",
        }

    # 3) Fundamental deterioration -> Sell.
    if verdict in WEAK_VERDICTS or (fund is not None and fund < 5.0):
        return {
            "decision": "Sell",
            "trigger": f"Fundamental deterioration — verdict '{verdict or 'n/a'}', "
                       f"fund score {fund:.2f} (< 5.0 / reject-fair band).",
        }

    # 4) Technical breakdown on an otherwise-OK name -> Sell (de-risk).
    if go == "NO-GO" and (fund is not None and fund < 7.0):
        return {
            "decision": "Sell",
            "trigger": f"Technical breakdown (Phase-3 NO-GO) with only moderate "
                       f"fundamentals (fund {fund:.2f}) — exit / de-risk.",
        }

    # 5) Concentration / capital-reallocation guard -> Review trim.
    if weight is not None and weight > 0.20:
        return {
            "decision": "Review",
            "trigger": f"Position is {weight*100:.0f}% of equity portfolio (> 20%) — "
                       f"review for capital reallocation / trim.",
        }

    # 6) Buy-More: strong score AND trading below cost basis (entry discount) AND tech not a NO-GO.
    below_cost = (live is not None and avg not in (None, 0) and live < avg)
    strong = (overall is not None and overall >= 7.5) or verdict in STRONG_VERDICTS
    if strong and below_cost and go != "NO-GO":
        return {
            "decision": "Buy-More",
            "trigger": f"Strong score (overall {overall}) and price {live:.2f} below "
                       f"entry/cost {avg:.2f} — add on weakness.",
        }

    # 7) Default -> Hold, citing why.
    reasons = []
    if overall is not None:
        reasons.append(f"overall {overall}")
    if verdict:
        reasons.append(f"verdict '{verdict}'")
    if go in ("GO", "NO-GO"):
        reasons.append(f"tech {go}")
    return {
        "decision": "Hold",
        "trigger": "Thesis intact; " + (", ".join(reasons) if reasons else "no exit trigger") + ".",
    }


# ----------------------------------------------------------------------------
# I/O: enrich holdings from _log.csv + reports, then write _portfolio.json
# ----------------------------------------------------------------------------

def load_log_scores(log_path: Path) -> dict[str, dict]:
    """Most-recent _log.csv row per (canonical) ticker: fund score, verdict, date, bear trigger."""
    from importlib import util as _il_util

    # reuse canon() from portfolio_sync (which reused the gap script)
    spec = _il_util.spec_from_file_location("portfolio_sync", SCRIPT_DIR / "portfolio_sync.py")
    psync = _il_util.module_from_spec(spec)
    spec.loader.exec_module(psync)
    canon = psync.canon

    out: dict[str, dict] = {}
    if not log_path.exists():
        return out
    with log_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            t = (row.get("ticker") or "").strip()
            if not t:
                continue
            c = canon(t)
            d = row.get("date", "")
            prev = out.get(c)
            if prev is None or d > prev["date"]:
                try:
                    score = float(row["score"]) if row.get("score") else None
                except ValueError:
                    score = None
                out[c] = {
                    "date": d,
                    "fund_score": score,
                    "verdict": (row.get("verdict") or "").strip().lower() or None,
                    "bear_case_trigger": (row.get("bear_case_trigger") or "").strip(),
                    "mode": row.get("mode"),
                }
    return out, canon


def load_report_technical(root: Path, canon) -> dict[str, dict]:
    """Most-recent technical read per canonical ticker, parsed from report frontmatter
    via build_dashboard.slim_report (stdlib, no extra deps)."""
    from importlib import util as _il_util

    spec = _il_util.spec_from_file_location("build_dashboard", SCRIPT_DIR / "build_dashboard.py")
    bd = _il_util.module_from_spec(spec)
    spec.loader.exec_module(bd)

    today = date.today()
    out: dict[str, dict] = {}
    for p in sorted(root.glob("*.md")):
        if not bd.REPORT_NAME_RE.match(p.name):
            continue
        slim = bd.slim_report(p, today)
        if not slim:
            continue
        c = canon(slim["ticker"])
        prev = out.get(c)
        if prev is None or (slim.get("date") or "") > prev["date"]:
            out[c] = {
                "date": slim.get("date") or "",
                "tech_score": slim.get("tech_score"),
                "go_no_go": slim.get("go_no_go"),
                "combined_score": slim.get("combined_score"),
                "thesis": slim.get("thesis"),
                "filename": slim.get("filename"),
                "company": slim.get("company"),
            }
    return out


def enrich(holdings: list[dict], log_scores: dict, tech_reads: dict, today: date) -> list[dict]:
    enriched = []
    for h in holdings:
        if not h.get("is_equity"):
            continue
        c = h["canon_ticker"]
        lg = log_scores.get(c, {})
        tr = tech_reads.get(c, {})

        fund_score = lg.get("fund_score")
        fund_date = lg.get("date")
        tech_score = tr.get("tech_score")
        score_stale = not is_fresh(fund_date, today)

        ov = overall_score(fund_score if not score_stale else None, tech_score)

        row = {
            "ticker": h["ticker"],
            "canon_ticker": c,
            "account": h.get("account"),
            "quantity": h.get("quantity"),
            "avg_buy_price": h.get("avg_buy_price"),
            "live_price": h.get("live_price"),
            "currency": h.get("currency"),
            "market_value": h.get("market_value"),
            "weight": h.get("weight"),
            "unrealized_pnl": h.get("unrealized_pnl"),
            "fund_score": fund_score,
            "fund_date": fund_date,
            "verdict": lg.get("verdict"),
            "tech_score": tech_score,
            "go_no_go": tr.get("go_no_go"),
            "combined_score": tr.get("combined_score"),
            "thesis_status": None,  # populated when thesis_check is run inline; not in batch dashboard
            "thesis": tr.get("thesis"),
            "bear_case_trigger": lg.get("bear_case_trigger") or None,
            "score_stale": score_stale,
            "overall": ov,
            "filename": tr.get("filename"),
            "company": tr.get("company"),
        }
        decision = decide(row)
        row.update(decision)
        enriched.append(row)
    return enriched


def run_sync(args) -> dict:
    """Invoke portfolio_sync.py as a subprocess and capture its JSON bundle."""
    cmd = [sys.executable, str(SCRIPT_DIR / "portfolio_sync.py")]
    if args.db:
        cmd += ["--db", args.db]
    if args.csv:
        cmd += ["--csv", args.csv]
    if args.no_prices:
        cmd += ["--no-prices"]
    log(f"Running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        log(proc.stderr)
        raise RuntimeError(f"portfolio_sync.py failed (exit {proc.returncode})")
    log(proc.stderr)  # surface the sync summary
    return json.loads(proc.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default=None, help="use a pre-made sync bundle JSON instead of syncing")
    ap.add_argument("--db", default=None, help="BankBD DB path (passed to portfolio_sync)")
    ap.add_argument("--csv", default=None, help="Yahoo Finance portfolio export (passed to portfolio_sync)")
    ap.add_argument("--no-prices", action="store_true")
    ap.add_argument("--out", default=str(OUT_JSON))
    ap.add_argument("--log-csv", default=str(LOG))
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args()

    if args.bundle:
        bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    else:
        bundle = run_sync(args)

    today = date.today()
    log_scores, canon = load_log_scores(Path(args.log_csv))
    tech_reads = load_report_technical(Path(args.root), canon)

    enriched = enrich(bundle.get("holdings", []), log_scores, tech_reads, today)

    out = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "today": today.isoformat(),
        "source_db": bundle.get("source_db"),
        "freshness_days": FRESHNESS_DAYS,
        "n_equities": len(enriched),
        "equity_market_value": bundle.get("equity_market_value", 0.0),
        "holdings": enriched,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # Summary
    from collections import Counter
    decisions = Counter(h["decision"] for h in enriched)
    log("=" * 64)
    log(f"Portfolio dashboard — {len(enriched)} equity holdings")
    log(f"Decisions: {dict(decisions)}")
    for h in sorted(enriched, key=lambda x: -(x["market_value"] or 0)):
        w = f"{h['weight']*100:4.1f}%" if h["weight"] else "  — "
        log(f"  {h['ticker']:<12} ov={str(h['overall']):<5} "
            f"fund={str(h['fund_score']):<5}{' STALE' if h['score_stale'] else '     '} "
            f"{h['decision']:<9} | {h['trigger']}")
    if not enriched:
        log("  (no equity holdings to evaluate — BankBD positions table is empty)")
    log(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
