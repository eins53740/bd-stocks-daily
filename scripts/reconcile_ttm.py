#!/usr/bin/env python
"""Layer 0b -- reconcile the vendor's TTM aggregates against series we already hold.

WHY THIS EXISTS (roadmap R15). On 2026-08-17 the ROVI.MC deep report's PROSE named three
vendor-data defects and corrected each one, while `_tmp/2026-08-17_ROVI.MC.json` still
carried the wrong numbers under `data_quality: "ok"`, `corrected_fields: []` and
`consistency_issues: []`. The corrupt `ev_ebitda` had already scored the peer sub-rank
inside the composite. So the system's own correction was unreachable by anything except a
human reading prose -- and every downstream consumer of the JSON (dashboard cards, the
screener, `report_history`) was served known-false numbers under a green stamp.

Measured on that file, with the arithmetic reproducible from two files on disk:

    _fin_history/ROVI.MC.json series (yfinance, EUR, 7 quarters)
      revenue 2025Q3..2026Q2 = 210.473 + 218.420 + 152.494 + 191.666 = 773.053M
      ebitda  2025Q3..2026Q2 =  83.922 +  66.577 +  21.237 + 101.062 = 272.798M
    _tmp/2026-08-17_ROVI.MC.json
      revenue_ttm = 773,052,992   <-- matches the quarterly sum EXACTLY
      ebitda_ttm  = 175,964,992   <-- 35.5% BELOW the quarterly sum
      ev_ebitda   = 16.82         <-- 2,959.789 / 175.965; on 272.798 it is 10.85

The revenue identity is the load-bearing part. It proves the four quarters cover the SAME
window the vendor used for its own TTM, so an EBITDA sum over those quarters is a
like-for-like replacement rather than a different number that happens to look better. When
revenue does NOT reconcile, this script corrects NOTHING and says so: a fix that invents a
number is the defect it is meant to catch.

Deliberately NOT done here: diagnosing *why* the vendor number is wrong. 175.965M matches
neither FY2025 EBITDA (216.201M) nor FY2025 EBIT (185.784M) nor any 4-quarter window in the
series, so any story about it would be a guess. The correction stands on the derivation, not
on the diagnosis.

WHERE IT RUNS. Node 2.2b, immediately after 2.2 financial_history -- which is where the
quarterly series first exists. Node 2 (analyze_ticker) runs BEFORE 2.2, so its own Layer-0
gate (`validate_consistency`) structurally cannot see this series; that is why the check
lives in its own node instead of being bolted onto a gate that runs too early to work.

OPERATING MARGIN IS FLAGGED, NOT REPLACED. `operating_margin_ttm` comes from yfinance's
`operatingMargins` and read 0.0942 for ROVI against annual operating margins of 24.99%
(FY2025) and 23.51% (FY2024). No quarterly operating-income series exists anywhere in the
system, so there is no TTM figure to substitute -- and overwriting a TTM field with an
annual number is a basis break, which is its own class of defect. The false value is
therefore REMOVED and the annual is published beside it under an explicit basis label.
Removing it is not a loss: `red_flags.py` already falls back to statement-derived operating
income when the field is absent, and `star_ratings.band()` already returns None -> n/a. Both
get *better* answers from no data than from wrong data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Relative tolerance before the vendor's EBITDA TTM is treated as wrong. Rounding and
# fiscal-calendar edges live well under this; the ROVI defect was 35.5%.
EBITDA_TOL = 0.15
# The revenue identity that proves the quarters cover the vendor's own TTM window. Tight on
# purpose -- ROVI matched to 8 significant figures, so anything loose here would let a
# different window through and license a wrong "correction".
REVENUE_BASIS_TOL = 0.02
# Relative gap between the vendor's TTM operating margin and the latest ANNUAL one before
# the vendor field is declared unusable.
OP_MARGIN_TOL = 0.50


def _num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    if x != x:  # NaN
        return None
    return float(x)


def ttm_from_series(series: dict, key: str, n: int = 4) -> tuple[float | None, list[str]]:
    """Sum the n most recent quarters of `key`, or return None.

    Requires the n LAST entries to all be present. A gap anywhere in that window means the
    window is not a TTM and no partial sum is returned -- summing 3 quarters and calling it
    TTM is exactly the hollow-denominator shape this file exists to stop.
    """
    vals = series.get(key)
    labels = series.get("labels") or []
    if not isinstance(vals, list) or len(vals) < n:
        return None, []
    window = vals[-n:]
    if any(_num(v) is None for v in window):
        return None, []
    return sum(_num(v) for v in window), list(labels[-n:])


def reconcile(analysis: dict, cache: dict) -> dict:
    """Pure. Returns the verdict; the caller decides whether to write it."""
    # `corrections` = a served value was wrong and is being replaced -> moves data_quality.
    # `additions`   = a derived overlay key with no vendor counterpart -> must NOT move it,
    #                 or every clean run would fly a false "corrected" flag.
    out = {"corrections": [], "additions": [], "issues": [], "checked": [], "skipped": []}
    fund = analysis.get("fundamentals") or {}
    series = (cache or {}).get("series") or {}

    rev_ttm_vendor = _num(fund.get("revenue_ttm"))
    rev_ttm_series, window = ttm_from_series(series, "revenue")
    ebitda_vendor = _num(fund.get("ebitda_ttm"))
    ebitda_series, _ = ttm_from_series(series, "ebitda")

    # ---- EBITDA TTM, gated on the revenue basis identity ------------------------------
    if rev_ttm_series is None or ebitda_series is None or ebitda_series <= 0:
        out["skipped"].append("ebitda_ttm: no complete 4-quarter EBITDA+revenue window in _fin_history")
    elif rev_ttm_vendor is None:
        out["skipped"].append("ebitda_ttm: revenue_ttm absent, cannot prove the quarters share the vendor window")
    else:
        basis_gap = abs(rev_ttm_vendor - rev_ttm_series) / max(rev_ttm_vendor, rev_ttm_series)
        if basis_gap > REVENUE_BASIS_TOL:
            out["issues"].append(
                f"TTM basis mismatch: revenue_ttm {rev_ttm_vendor:,.0f} vs quarters "
                f"{'+'.join(window)} = {rev_ttm_series:,.0f} ({basis_gap*100:.1f}% apart) "
                f"— quarterly window is NOT the vendor's TTM window, so ebitda_ttm was left alone"
            )
        else:
            out["checked"].append(f"revenue basis reconciles ({basis_gap*100:.2f}% on {'+'.join(window)})")
            if ebitda_vendor is None:
                out["corrections"].append({
                    "field": "fundamentals.ebitda_ttm", "old": None,
                    "new": round(ebitda_series),
                    "source": f"sum of _fin_history quarterly EBITDA {'+'.join(window)}",
                })
            else:
                gap = abs(ebitda_vendor - ebitda_series) / ebitda_series
                if gap > EBITDA_TOL:
                    out["corrections"].append({
                        "field": "fundamentals.ebitda_ttm", "old": ebitda_vendor,
                        "new": round(ebitda_series),
                        "source": f"sum of _fin_history quarterly EBITDA {'+'.join(window)} "
                                  f"(vendor was {gap*100:.1f}% off on a window proved identical by revenue)",
                    })
                else:
                    out["checked"].append(f"ebitda_ttm within {gap*100:.1f}% of the quarterly sum")

    # ---- TTM one-offs and net income, for the R16 earnings-quality check --------------
    # Published as additive keys rather than acted on here: red_flags.py owns that verdict
    # and is a pure JSON consumer by contract. Gated on the SAME revenue identity, because a
    # 4-quarter one-off sum measured against a different window is the hollow-denominator
    # defect wearing a new hat.
    if rev_ttm_series is not None and rev_ttm_vendor is not None and \
            abs(rev_ttm_vendor - rev_ttm_series) / max(rev_ttm_vendor, rev_ttm_series) <= REVENUE_BASIS_TOL:
        unusual_ttm, uw = ttm_from_series(series, "unusual_items")
        ni_ttm, _ = ttm_from_series(series, "net_income")
        if unusual_ttm is not None and ni_ttm is not None:
            out["additions"].append({
                "field": "fundamentals.unusual_items_ttm", "new": round(unusual_ttm),
                "source": f"sum of _fin_history quarterly unusual_items {'+'.join(uw)}",
            })
            out["additions"].append({
                "field": "fundamentals.net_income_ttm_statements", "new": round(ni_ttm),
                "source": f"sum of _fin_history quarterly net_income {'+'.join(uw)}",
            })
        else:
            out["skipped"].append(
                "one-off TTM: quarterly unusual_items and/or net_income incomplete "
                "(the Alpha Vantage path has no unusual-items row at all)")

    # ---- Operating margin: flag and remove, never substitute a different basis --------
    om_vendor = _num(fund.get("operating_margin_ttm"))
    inc = ((analysis.get("statements_raw") or {}).get("income") or {})
    oi = (inc.get("operating_income") or [None])
    rev = (inc.get("revenue") or [None])
    dates = (inc.get("fiscal_dates") or [None])
    oi0, rev0 = _num(oi[0] if oi else None), _num(rev[0] if rev else None)
    om_annual = (oi0 / rev0) if (oi0 is not None and rev0 not in (None, 0)) else None

    if om_vendor is None or om_annual is None:
        out["skipped"].append("operating_margin_ttm: no vendor value or no annual operating income to compare")
    else:
        gap = abs(om_vendor - om_annual) / max(abs(om_vendor), abs(om_annual))
        if gap > OP_MARGIN_TOL:
            fy = str(dates[0])[:4] if dates and dates[0] else "latest FY"
            out["corrections"].append({
                "field": "fundamentals.operating_margin_ttm", "old": om_vendor, "new": None,
                "source": f"removed: {gap*100:.0f}% from the {fy} annual operating margin "
                          f"{om_annual*100:.2f}% ({oi0:,.0f}/{rev0:,.0f}); no quarterly "
                          f"operating-income series exists to build a real TTM from",
            })
            out["corrections"].append({
                "field": "fundamentals.operating_margin_annual_latest", "old": None,
                "new": round(om_annual, 6),
                "source": f"{fy} operating_income / {fy} revenue (annual basis, NOT TTM)",
            })
        else:
            out["checked"].append(f"operating_margin_ttm within {gap*100:.0f}% of the annual margin")

    return out


def apply(analysis: dict, verdict: dict) -> list[str]:
    """Write the corrections into `analysis` in place. Returns the touched field names."""
    fund = analysis.setdefault("fundamentals", {})
    touched: list[str] = []
    for c in verdict["corrections"] + verdict.get("additions", []):
        leaf = c["field"].split(".", 1)[1]
        fund[leaf] = c["new"]
        touched.append(c["field"])

    # Derived-from-EBITDA fields have to move with it or the JSON contradicts itself.
    if any(c["field"] == "fundamentals.ebitda_ttm" for c in verdict["corrections"]):
        eb = _num(fund.get("ebitda_ttm"))
        ev = _num(fund.get("enterprise_value"))
        nd = _num(fund.get("net_debt"))
        if eb and eb > 0:
            if ev is not None:
                fund["ev_ebitda"] = round(ev / eb, 4)
                touched.append("fundamentals.ev_ebitda")
            if nd is not None:
                fund["net_debt_ebitda"] = round(nd / eb, 4)
                touched.append("fundamentals.net_debt_ebitda")
            rev = _num(fund.get("revenue_ttm"))
            if rev and rev > 0:
                fund["ebitda_margin_ttm"] = round(eb / rev, 6)
                touched.append("fundamentals.ebitda_margin_ttm")

    # Fold into the existing provenance channels rather than inventing new ones, so the
    # report, dashboard and history all see this the same way they see a Layer-2 self-heal.
    if verdict["corrections"]:
        analysis.setdefault("corrected_fields", []).extend(verdict["corrections"])
    if verdict["issues"]:
        analysis.setdefault("consistency_issues", []).extend(verdict["issues"])
    # `suspect` beats `corrected` beats `ok` -- same precedence analyze_ticker uses.
    if verdict["issues"]:
        analysis["data_quality"] = "suspect"
    elif verdict["corrections"] and analysis.get("data_quality") != "suspect":
        analysis["data_quality"] = "corrected"
    return touched


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--analysis-json", required=True)
    ap.add_argument("--fin-history", default=None,
                    help="defaults to <state>/_fin_history/<ticker>.json beside the analysis JSON")
    ap.add_argument("--update", action="store_true", help="write the corrections back")
    args = ap.parse_args()

    jp = Path(args.analysis_json)
    if not jp.exists():
        print(f"reconcile_ttm: analysis JSON not found: {jp}", file=sys.stderr)
        return 1
    analysis = json.loads(jp.read_text(encoding="utf-8"))
    ticker = analysis.get("ticker") or jp.stem.split("_", 1)[-1]

    cp = Path(args.fin_history) if args.fin_history else jp.parent.parent / "_fin_history" / f"{ticker}.json"
    cache = {}
    if cp.exists():
        cache = json.loads(cp.read_text(encoding="utf-8"))
    else:
        print(f"reconcile_ttm: no _fin_history cache at {cp} — TTM cross-check NOT performed",
              file=sys.stderr)

    verdict = reconcile(analysis, cache)
    for line in verdict["checked"]:
        print(f"  ok      {line}")
    for line in verdict["skipped"]:
        print(f"  SKIP    {line}")
    for line in verdict["issues"]:
        print(f"  ISSUE   {line}")
    for c in verdict["corrections"]:
        print(f"  CORRECT {c['field']}: {c['old']} -> {c['new']}  ({c['source']})")
    for c in verdict["additions"]:
        print(f"  ADD     {c['field']} = {c['new']}  ({c['source']})")

    if args.update and (verdict["corrections"] or verdict["additions"] or verdict["issues"]):
        touched = apply(analysis, verdict)
        jp.write_text(json.dumps(analysis, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"reconcile_ttm: wrote {jp.name}; fields touched: {', '.join(touched) or 'none'}; "
              f"data_quality={analysis.get('data_quality')}")
    elif args.update:
        print("reconcile_ttm: nothing to correct")
    print(json.dumps({"ticker": ticker,
                      "corrections": len(verdict["corrections"]),
                      "additions": len(verdict["additions"]),
                      "issues": len(verdict["issues"]),
                      "skipped": len(verdict["skipped"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
