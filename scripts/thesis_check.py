"""
thesis_check.py — Phase 0.5 (round > 1 only).

Compares today's analyze_ticker.py output against the most recent prior
evaluation in _log.csv for the same ticker. Surfaces whether the prior
thesis pillars are intact / weakened / broken.

No LLM call. Cheap, deterministic comparison.

Inputs:
  --ticker           ticker symbol (case-sensitive, match _log.csv)
  --current-json     path to today's analyze_ticker.py JSON output

Optional:
  --log-csv          override default _log.csv path
  --out-dir          override OUT_DIR for prior report lookup

Output (stdout): JSON dict with prior_date, prior_score, pillars, overall_status, summary.
Exit 0 on success, 1 if no prior row found (caller should skip Phase 0.5).
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

DEFAULT_LOG = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily\_log.csv")
DEFAULT_OUT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def find_prior_row(log_path: Path, ticker: str, today_date: str) -> dict | None:
    """Return the most recent _log.csv row for ticker, excluding today's date."""
    if not log_path.exists():
        return None
    rows = []
    with log_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("ticker", "").strip() == ticker and row.get("date", "") != today_date:
                rows.append(row)
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("date", ""), reverse=True)
    return rows[0]


def _to_float(v):
    try:
        return float(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def classify_drift(prior, now, weakened_pct=0.10, broken_pct=0.30) -> str:
    """Compare prior vs now. Sign change → broken; magnitude drift → weakened/intact."""
    if prior is None or now is None:
        return "unknown"
    if prior == 0:
        return "broken" if abs(now) > 0.01 else "intact"
    if (prior > 0) != (now > 0):
        return "broken"
    drift = abs(now - prior) / abs(prior)
    if drift > broken_pct:
        return "broken"
    if drift > weakened_pct:
        return "weakened"
    return "intact"


def evaluate_pillars(prior_row: dict, current: dict) -> list[dict]:
    """Build the 4-pillar comparison: score, fundamentals (ROE, rev growth, net margin), ROIC."""
    pillars = []
    fund = current.get("fundamentals", {})

    # Pillar 1: composite score (most aggregated single signal)
    prior_score = _to_float(prior_row.get("score"))
    now_score = _to_float(current.get("scores", {}).get("composite"))
    if prior_score is not None and now_score is not None:
        delta = now_score - prior_score
        if delta < -1.0:
            status = "broken"
        elif delta < -0.5:
            status = "weakened"
        else:
            status = "intact"
        pillars.append({
            "name": "Composite score",
            "prior": prior_score,
            "now": now_score,
            "delta": round(delta, 2),
            "status": status,
        })

    # Pillar 2: gates passed (7-gate Quality Compounder)
    prior_gates = _to_float(prior_row.get("gates_passed"))
    now_gates = current.get("gates_passed")
    if prior_gates is not None and now_gates is not None:
        delta = now_gates - prior_gates
        status = "broken" if delta <= -2 else "weakened" if delta == -1 else "intact"
        pillars.append({
            "name": "Quality gates passed",
            "prior": int(prior_gates),
            "now": int(now_gates),
            "delta": int(delta),
            "status": status,
        })

    # Pillar 3: ROE TTM (prior value pulled from prior frontmatter if we had it;
    # otherwise we can only compare against the score). For now we only track
    # the *current* values relative to the score-implied prior assumption.
    # When prior frontmatter parsing is wired in, fill prior here.
    now_roe = fund.get("roe_ttm")
    if now_roe is not None:
        pillars.append({
            "name": "ROE TTM",
            "prior": None,
            "now": now_roe,
            "delta": None,
            "status": "intact" if now_roe > 0.15 else "weakened" if now_roe > 0.05 else "broken",
            "note": "absolute-level check (prior value not stored in _log.csv)",
        })

    # Pillar 4: management score (if both available)
    prior_mgmt = _to_float(prior_row.get("management_score"))
    now_mgmt = _to_float(current.get("management_score"))
    if prior_mgmt is not None and now_mgmt is not None:
        delta = now_mgmt - prior_mgmt
        status = "broken" if delta < -1.5 else "weakened" if delta < -0.5 else "intact"
        pillars.append({
            "name": "Management quality",
            "prior": prior_mgmt,
            "now": now_mgmt,
            "delta": round(delta, 2),
            "status": status,
        })

    return pillars


def overall_from_pillars(pillars: list[dict]) -> str:
    statuses = [p["status"] for p in pillars if p["status"] != "unknown"]
    if not statuses:
        return "unknown"
    if "broken" in statuses:
        return "broken"
    if "weakened" in statuses:
        return "weakened"
    return "intact"


def summarise(prior_row: dict, current: dict, pillars: list[dict], overall: str) -> str:
    n_total = len(pillars)
    n_intact = sum(1 for p in pillars if p["status"] == "intact")
    n_broken = sum(1 for p in pillars if p["status"] == "broken")
    parts = [f"{n_intact}/{n_total} pillars intact"]
    if n_broken:
        broken_names = [p["name"] for p in pillars if p["status"] == "broken"]
        parts.append(f"broken: {', '.join(broken_names)}")
    bear = prior_row.get("bear_case_trigger", "").strip()
    if bear and overall == "broken":
        parts.append(f"prior bear trigger may have hit: {bear}")
    return "; ".join(parts) + "."


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--current-json", required=True, help="path to today's analyze_ticker.py JSON")
    ap.add_argument("--log-csv", default=str(DEFAULT_LOG))
    args = ap.parse_args()

    current_path = Path(args.current_json)
    if not current_path.exists():
        log(f"FATAL: current-json not found: {current_path}")
        return 1
    current = json.loads(current_path.read_text(encoding="utf-8"))
    today_date = current.get("fetched_at", "")[:10]

    prior_row = find_prior_row(Path(args.log_csv), args.ticker, today_date)
    if prior_row is None:
        log(f"No prior _log.csv row for {args.ticker} (excluding today). Skipping Phase 0.5.")
        print(json.dumps({"ticker": args.ticker, "skip_reason": "no_prior_row"}))
        return 1

    pillars = evaluate_pillars(prior_row, current)
    overall = overall_from_pillars(pillars)
    summary = summarise(prior_row, current, pillars, overall)

    out = {
        "ticker": args.ticker,
        "prior_date": prior_row.get("date"),
        "prior_score": _to_float(prior_row.get("score")),
        "prior_verdict": prior_row.get("verdict"),
        "prior_bear_trigger": prior_row.get("bear_case_trigger", ""),
        "pillars": pillars,
        "overall_status": overall,
        "summary": summary,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    log(f"thesis_check {args.ticker}: overall={overall} ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
