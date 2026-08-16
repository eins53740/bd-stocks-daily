"""
red_flags.py — Downside / red-flag scanner for bd-stocks-daily v4 Phase C
(spec §8). A bearish veto list independent of the bullish composite: it
SURFACES a veto with a glyph + colour but NEVER auto-demotes the verdict
(same pattern as management_flag). Overlay-only — nothing here touches
`scores`; the block it emits (`red_flags`) is additive to schema-2.2 JSON.

Pure JSON consumer — NO network, NO yfinance, ZERO extra API calls. It reads
the analysis JSON already produced by analyze_ticker.py: `fundamentals`, the
2-year `statements_raw` snapshot (income / balance / cash-flow line items,
persisted by analyze_ticker for exactly this purpose), `capital_returns`,
`altman_zscore` and `piotroski_components`. This is what the v4 audit finding
m1 requires: "red_flags reuses analyze_ticker JSON, must not re-fetch".

What it produces (all additive keys under `red_flags`):
  * Three statement groups (income / balance / cashflow), each a list of
    checks {id, label, status: pass|warn|bad|na, value, threshold, note} and a
    DETERMINISTIC 0-10 sub-score computed only over the COMPUTABLE checks of
    that statement (pass=1, warn=0.5, bad=0). Same JSON in -> same 0-10 out.
  * Beneish M-score (8 indices; flag if M > -2.22). Any missing variable ->
    "not computable" with the list of missing indices (expected often on
    non-US names, whose receivables / SG&A / depreciation rows are yfinance's
    thinnest). The natural pair to the existing Altman Z.
  * Two POSITIVE pills (never vetoes): net payout yield (>4% rule) and
    ROCE >= 20% — surfaced ✓ when met, ○ neutral when not.
  * A traffic-light summary (pass/warn/bad counts + glyph).

All scoring is a pure function of the input JSON — see tests/test_red_flags.py.
A total failure emits {"error": ...} with exit 0 (orchestrator continues).
With --update the block is merged into the analysis JSON under `red_flags`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

OUT_DIR_DEFAULT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")

BENEISH_FLAG_THRESHOLD = -2.22  # M > -2.22 => elevated manipulation risk


def log(msg: str) -> None:
    print(f"[red_flags] {msg}", file=sys.stderr)


# ===================================================================
# Small numeric helpers (pure)
# ===================================================================
def _num(x):
    """Coerce to float, tolerating None / NaN / non-numeric -> None."""
    try:
        if x is None:
            return None
        f = float(x)
        return f if f == f else None  # f==f filters NaN
    except (TypeError, ValueError):
        return None


def _div(a, b):
    """a / b, or None if either is None or b == 0."""
    a, b = _num(a), _num(b)
    if a is None or b is None or b == 0:
        return None
    return a / b


def _yr(block: dict, key: str, i: int):
    """statements_raw value for canonical `key` at index i (0=latest, 1=prior)."""
    seq = (block or {}).get(key)
    if isinstance(seq, (list, tuple)) and len(seq) > i:
        return _num(seq[i])
    return None


def flag(fid: str, label: str, status: str, value, threshold: str, note: str = "") -> dict:
    return {"id": fid, "label": label, "status": status,
            "value": value, "threshold": threshold, "note": note}


def _round(x, n=2):
    return round(x, n) if isinstance(x, (int, float)) else x


# ===================================================================
# Statement check builders (pure)
# ===================================================================
def income_checks(fund: dict, inc: dict) -> list:
    """Income-statement red flags. `inc` = statements_raw['income']."""
    out = []
    rev_t, rev_p = _yr(inc, "revenue", 0), _yr(inc, "revenue", 1)
    gp_t, gp_p = _yr(inc, "gross_profit", 0), _yr(inc, "gross_profit", 1)

    # gross margin < 10% (bad)
    gm = _num(fund.get("gross_margin_ttm"))
    if gm is None:
        gm = _div(gp_t, rev_t)
    if gm is None:
        out.append(flag("gross_margin", "Gross margin", "na", None, "< 10%", "no data"))
    else:
        out.append(flag("gross_margin", "Gross margin",
                        "bad" if gm < 0.10 else "pass", _round(gm * 100, 1) if gm else gm,
                        "< 10%"))

    # operating margin < 15% (warn — common in healthy low-margin models)
    om = _num(fund.get("operating_margin_ttm"))
    if om is None:
        om = _div(_yr(inc, "operating_income", 0), rev_t)
    if om is None:
        out.append(flag("operating_margin", "Operating margin", "na", None, "< 15%", "no data"))
    else:
        out.append(flag("operating_margin", "Operating margin",
                        "warn" if om < 0.15 else "pass", _round(om * 100, 1), "< 15%"))

    # interest coverage < 2x (bad). No interest expense => not a burden -> pass.
    ie = _yr(inc, "interest_expense", 0)
    oi = _yr(inc, "operating_income", 0)
    if ie is None or oi is None:
        out.append(flag("interest_coverage", "Interest coverage", "na", None, "< 2×", "no data"))
    elif abs(ie) < 1:  # effectively no interest expense
        out.append(flag("interest_coverage", "Interest coverage", "pass", None, "< 2×", "no material interest expense"))
    else:
        cov = oi / abs(ie)
        out.append(flag("interest_coverage", "Interest coverage",
                        "bad" if cov < 2.0 else "pass", _round(cov, 1), "< 2×"))

    # SG&A > 30% of revenue (warn)
    sga = _yr(inc, "sga", 0)
    r = _div(sga, rev_t)
    if r is None:
        out.append(flag("sga_ratio", "SG&A / revenue", "na", None, "> 30%", "no SG&A line"))
    else:
        out.append(flag("sga_ratio", "SG&A / revenue",
                        "warn" if r > 0.30 else "pass", _round(r * 100, 1), "> 30%"))

    # one-time income > 15% of net income (warn — earnings-quality)
    unusual = _yr(inc, "unusual_items", 0)
    ni_t = _yr(inc, "net_income", 0)
    r = _div(abs(unusual) if unusual is not None else None, abs(ni_t) if ni_t else None)
    if r is None:
        out.append(flag("one_time_income", "One-time items / NI", "na", None, "> 15%", "no data"))
    else:
        out.append(flag("one_time_income", "One-time items / NI",
                        "warn" if r > 0.15 else "pass", _round(r * 100, 1), "> 15%"))

    # gross-margin YoY swing > 5 pts (warn)
    gm_t, gm_p = _div(gp_t, rev_t), _div(gp_p, rev_p)
    if gm_t is None or gm_p is None:
        out.append(flag("gm_swing", "Gross-margin YoY swing", "na", None, "> 5 pts", "no data"))
    else:
        swing = abs(gm_t - gm_p) * 100
        out.append(flag("gm_swing", "Gross-margin YoY swing",
                        "warn" if swing > 5.0 else "pass", _round(swing, 1), "> 5 pts"))

    # receivables growth outpacing revenue growth by > 10 pts (warn — rev-rec drift)
    recv_t, recv_p = _yr(inc, "receivables", 0), _yr(inc, "receivables", 1)
    # receivables live on the balance sheet; income_checks receives a merged view
    rev_g = _div(rev_t, rev_p)
    recv_g = _div(recv_t, recv_p)
    if rev_g is None or recv_g is None:
        out.append(flag("receivables_divergence", "Receivables vs revenue", "na", None,
                        "recv growth > rev growth +10 pts", "no data"))
    else:
        gap = (recv_g - rev_g) * 100
        out.append(flag("receivables_divergence", "Receivables vs revenue",
                        "warn" if gap > 10.0 else "pass", _round(gap, 1),
                        "recv growth > rev growth +10 pts"))
    return out


def balance_checks(fund: dict, bal: dict) -> list:
    """Balance-sheet red flags. `bal` = statements_raw['balance']."""
    out = []
    ca_t, cl_t = _yr(bal, "current_assets", 0), _yr(bal, "current_liabilities", 0)

    # current ratio < 1.0 (bad)
    cr = _num(fund.get("current_ratio")) or _div(ca_t, cl_t)
    if cr is None:
        out.append(flag("current_ratio", "Current ratio", "na", None, "< 1.0", "no data"))
    else:
        out.append(flag("current_ratio", "Current ratio",
                        "bad" if cr < 1.0 else "pass", _round(cr, 2), "< 1.0"))

    # quick ratio < 0.6 (bad)
    inv_t = _yr(bal, "inventory", 0)
    qr = _num(fund.get("quick_ratio"))
    if qr is None and ca_t is not None and cl_t not in (None, 0):
        qr = (ca_t - (inv_t or 0)) / cl_t
    if qr is None:
        out.append(flag("quick_ratio", "Quick ratio", "na", None, "< 0.6", "no data"))
    else:
        out.append(flag("quick_ratio", "Quick ratio",
                        "bad" if qr < 0.6 else "pass", _round(qr, 2), "< 0.6"))

    # D/E > 2.0 (bad). fundamentals.debt_to_equity is already a ratio (0.5 = 50%).
    de = _num(fund.get("debt_to_equity"))
    if de is None:
        out.append(flag("debt_equity", "Debt / equity", "na", None, "> 2.0", "no data"))
    else:
        out.append(flag("debt_equity", "Debt / equity",
                        "bad" if de > 2.0 else "pass", _round(de, 2), "> 2.0"))

    # Net Debt / EBITDA > 3.0 (bad) — Borja's leverage metric
    nde = _num(fund.get("net_debt_ebitda"))
    if nde is None:
        out.append(flag("net_debt_ebitda", "Net debt / EBITDA", "na", None, "> 3.0",
                        "no data (or net cash)"))
    else:
        out.append(flag("net_debt_ebitda", "Net debt / EBITDA",
                        "bad" if nde > 3.0 else "pass", _round(nde, 2), "> 3.0"))

    # negative working capital (bad)
    if ca_t is None or cl_t is None:
        out.append(flag("working_capital", "Working capital", "na", None, "< 0", "no data"))
    else:
        wc = ca_t - cl_t
        out.append(flag("working_capital", "Working capital",
                        "bad" if wc < 0 else "pass", _round(wc, 0), "< 0"))

    # inventory turnover < 2x (warn). No inventory => n/a, not a flag.
    cogs_t = _yr(bal, "cost_of_revenue", 0)  # merged view carries income COGS
    turns = _div(cogs_t, inv_t)
    if inv_t in (None, 0):
        out.append(flag("inventory_turnover", "Inventory turnover", "na", None, "< 2×",
                        "no inventory"))
    elif turns is None:
        out.append(flag("inventory_turnover", "Inventory turnover", "na", None, "< 2×", "no data"))
    else:
        out.append(flag("inventory_turnover", "Inventory turnover",
                        "warn" if turns < 2.0 else "pass", _round(turns, 1), "< 2×"))

    # AR days > 60 (warn)
    recv_t = _yr(bal, "receivables", 0)
    rev_t = _yr(bal, "revenue", 0)  # merged view carries income revenue
    ar_days = _div(recv_t, rev_t)
    if ar_days is None:
        out.append(flag("ar_days", "Receivable days", "na", None, "> 60d", "no data"))
    else:
        ar_days *= 365
        out.append(flag("ar_days", "Receivable days",
                        "warn" if ar_days > 60 else "pass", _round(ar_days, 0), "> 60d"))

    # book value / share declining YoY (warn)
    #
    # R6 note, deliberate: `shares` is often NOT shares outstanding — 61 of 147 measured
    # analyses carry an issued count including treasury, an ADR ratio or a stale filing
    # count (see scripts/share_basis.py). This check is unaffected, and that is a property
    # rather than luck: it compares BVPS(t) against BVPS(t-1) on the SAME basis, and a
    # constant basis cancels in the ratio. Swapping in shares_out here would mix a
    # current-day count into a prior-year figure and make the trend worse, not better.
    # The invariant it rests on is that the basis is STABLE year to year.
    eq_t, eq_p = _yr(bal, "stockholders_equity", 0), _yr(bal, "stockholders_equity", 1)
    sh_t, sh_p = _yr(bal, "shares", 0), _yr(bal, "shares", 1)
    bvps_t, bvps_p = _div(eq_t, sh_t), _div(eq_p, sh_p)
    if bvps_t is None or bvps_p is None:
        out.append(flag("book_value_trend", "Book value / share trend", "na", None,
                        "declining YoY", "no data"))
    else:
        out.append(flag("book_value_trend", "Book value / share trend",
                        "warn" if bvps_t < bvps_p else "pass",
                        _round((bvps_t / bvps_p - 1) * 100, 1) if bvps_p else None,
                        "declining YoY"))
    return out


def cashflow_checks(fund: dict, cf: dict, inc: dict, cap: dict) -> list:
    """Cash-flow red flags + earnings quality. `cf` = statements_raw['cashflow']."""
    out = []
    ocf_t = _yr(cf, "operating_cash_flow", 0)
    ni_t = _yr(inc, "net_income", 0)

    # negative operating cash flow (bad)
    if ocf_t is None:
        out.append(flag("ocf_negative", "Operating cash flow", "na", None, "< 0", "no data"))
    else:
        out.append(flag("ocf_negative", "Operating cash flow",
                        "bad" if ocf_t < 0 else "pass", _round(ocf_t, 0), "< 0"))

    # negative FCF (bad)
    fcf = _yr(cf, "free_cash_flow", 0)
    if fcf is None:
        fcf = _num(fund.get("fcf_ttm"))
    if fcf is None:
        out.append(flag("fcf_negative", "Free cash flow", "na", None, "< 0", "no data"))
    else:
        out.append(flag("fcf_negative", "Free cash flow",
                        "bad" if fcf < 0 else "pass", _round(fcf, 0), "< 0"))

    # earnings quality — CFO vs Net Income (folds gap #9). pass CFO>NI, warn CFO<NI, bad CFO<0.
    if ocf_t is None or ni_t is None:
        # fall back to Piotroski ocf_gt_ni component if present
        out.append(flag("earnings_quality", "Earnings quality (CFO vs NI)", "na", None,
                        "CFO < NI", "no data"))
    else:
        ratio = _div(ocf_t, ni_t) if ni_t > 0 else None
        if ocf_t < 0:
            st = "bad"
        elif ni_t > 0 and ocf_t < ni_t:
            st = "warn"
        else:
            st = "pass"
        out.append(flag("earnings_quality", "Earnings quality (CFO vs NI)", st,
                        _round(ratio, 2) if ratio is not None else None, "CFO < NI"))

    # capex < 10% of OCF (warn — possible under-investment / starved capex)
    capex = _yr(cf, "capex", 0)
    r = _div(abs(capex) if capex is not None else None, ocf_t if (ocf_t and ocf_t > 0) else None)
    if r is None:
        out.append(flag("capex_intensity", "Capex / OCF", "na", None, "< 10%", "no data"))
    else:
        out.append(flag("capex_intensity", "Capex / OCF",
                        "warn" if r < 0.10 else "pass", _round(r * 100, 1), "< 10%"))

    # dividends > OCF (bad — distribution beyond cash generation)
    div = _yr(cf, "dividends_paid", 0)
    if div is None:
        div = _num((cap or {}).get("dividends_paid_ttm"))
    if div is None or (div == 0):
        out.append(flag("dividends_gt_ocf", "Dividends / OCF", "na", None, "> 100%",
                        "no dividend"))
    elif ocf_t is None or ocf_t <= 0:
        out.append(flag("dividends_gt_ocf", "Dividends / OCF", "bad", None, "> 100%",
                        "dividend paid on non-positive OCF"))
    else:
        r = abs(div) / ocf_t
        out.append(flag("dividends_gt_ocf", "Dividends / OCF",
                        "bad" if r > 1.0 else "pass", _round(r * 100, 1), "> 100%"))

    # cash-basis interest coverage < 1x (bad)
    ie = _yr(inc, "interest_expense", 0)
    if ie is None or ocf_t is None:
        out.append(flag("cash_interest_coverage", "Cash interest coverage", "na", None,
                        "< 1×", "no data"))
    elif abs(ie) < 1:
        out.append(flag("cash_interest_coverage", "Cash interest coverage", "pass", None,
                        "< 1×", "no material interest expense"))
    else:
        cov = ocf_t / abs(ie)
        out.append(flag("cash_interest_coverage", "Cash interest coverage",
                        "bad" if cov < 1.0 else "pass", _round(cov, 1), "< 1×"))
    return out


# ===================================================================
# Beneish M-score (pure)
# ===================================================================
def beneish_m_score(inc: dict, bal: dict, cf: dict) -> dict:
    """8-index Beneish M-score. Flag if M > -2.22. Any missing index ->
    m_score None, status 'na', with the list of missing indices."""
    idx = {}
    missing = []

    sales_t, sales_p = _yr(inc, "revenue", 0), _yr(inc, "revenue", 1)
    # COGS: prefer reported, else revenue - gross_profit
    cogs_t = _yr(inc, "cost_of_revenue", 0)
    if cogs_t is None:
        gp = _yr(inc, "gross_profit", 0)
        cogs_t = (sales_t - gp) if (sales_t is not None and gp is not None) else None
    cogs_p = _yr(inc, "cost_of_revenue", 1)
    if cogs_p is None:
        gp = _yr(inc, "gross_profit", 1)
        cogs_p = (sales_p - gp) if (sales_p is not None and gp is not None) else None

    recv_t, recv_p = _yr(bal, "receivables", 0), _yr(bal, "receivables", 1)
    ca_t, ca_p = _yr(bal, "current_assets", 0), _yr(bal, "current_assets", 1)
    ppe_t, ppe_p = _yr(bal, "ppe_net", 0), _yr(bal, "ppe_net", 1)
    ta_t, ta_p = _yr(bal, "total_assets", 0), _yr(bal, "total_assets", 1)
    cl_t, cl_p = _yr(bal, "current_liabilities", 0), _yr(bal, "current_liabilities", 1)
    ltd_t, ltd_p = _yr(bal, "long_term_debt", 0), _yr(bal, "long_term_debt", 1)
    tl_t, tl_p = _yr(bal, "total_liabilities", 0), _yr(bal, "total_liabilities", 1)
    sga_t, sga_p = _yr(inc, "sga", 0), _yr(inc, "sga", 1)
    ni_t = _yr(inc, "net_income", 0)
    ocf_t = _yr(cf, "operating_cash_flow", 0)
    # depreciation: income side first, else cash-flow side
    dep_t = _yr(inc, "depreciation", 0) or _yr(cf, "depreciation", 0)
    dep_p = _yr(inc, "depreciation", 1) or _yr(cf, "depreciation", 1)

    # DSRI
    idx["DSRI"] = _div(_div(recv_t, sales_t), _div(recv_p, sales_p))
    # GMI = GM_{t-1} / GM_t
    gm_t = _div((sales_t - cogs_t) if (sales_t is not None and cogs_t is not None) else None, sales_t)
    gm_p = _div((sales_p - cogs_p) if (sales_p is not None and cogs_p is not None) else None, sales_p)
    idx["GMI"] = _div(gm_p, gm_t)
    # AQI = (1-(CA+PPE)/TA)_t / (...)_{t-1}
    aq_t = (1 - (ca_t + ppe_t) / ta_t) if None not in (ca_t, ppe_t, ta_t) and ta_t else None
    aq_p = (1 - (ca_p + ppe_p) / ta_p) if None not in (ca_p, ppe_p, ta_p) and ta_p else None
    idx["AQI"] = _div(aq_t, aq_p)
    # SGI
    idx["SGI"] = _div(sales_t, sales_p)
    # DEPI = dep-rate_{t-1} / dep-rate_t ; dep-rate = dep/(dep+ppe)
    dr_t = _div(dep_t, (dep_t + ppe_t) if (dep_t is not None and ppe_t is not None) else None)
    dr_p = _div(dep_p, (dep_p + ppe_p) if (dep_p is not None and ppe_p is not None) else None)
    idx["DEPI"] = _div(dr_p, dr_t)
    # SGAI
    idx["SGAI"] = _div(_div(sga_t, sales_t), _div(sga_p, sales_p))
    # LVGI = leverage_t / leverage_{t-1}; leverage = (LTD+CL)/TA, fall back to TL/TA
    def _lev(ltd, cl, tl, ta):
        if ta in (None, 0):
            return None
        if ltd is not None and cl is not None:
            return (ltd + cl) / ta
        if tl is not None:
            return tl / ta
        return None
    idx["LVGI"] = _div(_lev(ltd_t, cl_t, tl_t, ta_t), _lev(ltd_p, cl_p, tl_p, ta_p))
    # TATA = (net income - CFO) / total assets  [year t]
    idx["TATA"] = _div((ni_t - ocf_t) if (ni_t is not None and ocf_t is not None) else None, ta_t)

    for k, v in idx.items():
        if v is None:
            missing.append(k)

    if missing:
        return {"m_score": None, "flag": None, "status": "na",
                "components": {k: _round(v, 3) for k, v in idx.items()},
                "missing": missing,
                "threshold": f"M > {BENEISH_FLAG_THRESHOLD}",
                "note": "not computable (missing: " + ", ".join(missing) + ")"}

    m = (-4.84 + 0.92 * idx["DSRI"] + 0.528 * idx["GMI"] + 0.404 * idx["AQI"]
         + 0.892 * idx["SGI"] + 0.115 * idx["DEPI"] - 0.172 * idx["SGAI"]
         + 4.679 * idx["TATA"] - 0.327 * idx["LVGI"])
    flagged = m > BENEISH_FLAG_THRESHOLD
    return {"m_score": round(m, 3), "flag": flagged,
            "status": "bad" if flagged else "pass",
            "components": {k: round(v, 3) for k, v in idx.items()},
            "missing": [],
            "threshold": f"M > {BENEISH_FLAG_THRESHOLD}",
            "note": ("elevated earnings-manipulation risk" if flagged
                     else "below manipulation threshold")}


# ===================================================================
# Sub-scores + pills + summary (pure)
# ===================================================================
_STATUS_WEIGHT = {"pass": 1.0, "warn": 0.5, "bad": 0.0}


def statement_group(checks: list) -> dict:
    """Wrap a list of checks with a deterministic 0-10 sub-score computed over
    the COMPUTABLE checks only (na excluded). pass=1, warn=0.5, bad=0."""
    computable = [c for c in checks if c["status"] in _STATUS_WEIGHT]
    total = len(computable)
    if total == 0:
        subscore = None
    else:
        earned = sum(_STATUS_WEIGHT[c["status"]] for c in computable)
        subscore = round(10 * earned / total, 1)
    return {"checks": checks, "subscore_0_10": subscore,
            "computable": total, "total": len(checks)}


def pills_block(fund: dict, cap: dict) -> dict:
    npy = _num((cap or {}).get("net_payout_yield"))
    roce = _num(fund.get("roce_ttm"))
    return {
        "net_payout_yield": {
            "label": "Net payout yield", "value": _round(npy * 100, 2) if npy is not None else None,
            "met": (npy is not None and npy > 0.04), "rule": "> 4%",
            "status": "na" if npy is None else ("met" if npy > 0.04 else "neutral")},
        "roce": {
            "label": "ROCE", "value": _round(roce * 100, 1) if roce is not None else None,
            "met": (roce is not None and roce >= 0.20), "rule": ">= 20%",
            "status": "na" if roce is None else ("met" if roce >= 0.20 else "neutral")},
    }


def summarize(groups: list, beneish: dict, altman) -> dict:
    counts = {"pass": 0, "warn": 0, "bad": 0, "na": 0}
    for g in groups:
        for c in g["checks"]:
            counts[c["status"]] = counts.get(c["status"], 0) + 1
    # Beneish flag counts as a bad in the headline
    if beneish.get("flag") is True:
        counts["bad"] += 1
    if counts["bad"] > 0:
        glyph, verdict = "\U0001F534", "elevated"   # 🔴
    elif counts["warn"] > 0:
        glyph, verdict = "\U0001F7E1", "watch"       # 🟡
    else:
        glyph, verdict = "\U0001F7E2", "clean"       # 🟢
    return {"pass": counts["pass"], "warn": counts["warn"], "bad": counts["bad"],
            "na": counts["na"], "glyph": glyph, "verdict": verdict,
            "altman_zscore": _num(altman),
            "beneish_m": beneish.get("m_score"),
            "note": "Bearish veto surfaced with a glyph + colour; it never auto-demotes the composite."}


# ===================================================================
# Orchestration
# ===================================================================
def compute(analysis: dict) -> dict:
    """Pure: analysis dict -> red_flags block. Same input -> same output."""
    fund = analysis.get("fundamentals") or {}
    stmts = analysis.get("statements_raw") or {}
    inc = stmts.get("income") or {}
    bal = stmts.get("balance") or {}
    cf = stmts.get("cashflow") or {}
    cap = analysis.get("capital_returns") or {}
    warnings = []
    if not stmts:
        warnings.append("no statements_raw in analysis JSON — re-run analyze_ticker (Phase 2) "
                        "so red flags / Beneish can compute; many checks will read 'n/a'")

    # Balance & income checks share a few cross-statement inputs (receivables,
    # revenue, COGS). Merge those into the view each builder reads so a single
    # canonical source drives every check.
    inc_view = dict(inc)
    inc_view.setdefault("receivables", bal.get("receivables"))
    bal_view = dict(bal)
    bal_view.setdefault("revenue", inc.get("revenue"))
    bal_view.setdefault("cost_of_revenue", inc.get("cost_of_revenue"))

    income = statement_group(income_checks(fund, inc_view))
    balance = statement_group(balance_checks(fund, bal_view))
    cashflow = statement_group(cashflow_checks(fund, cf, inc, cap))
    beneish = beneish_m_score(inc, bal, cf)
    pills = pills_block(fund, cap)
    summary = summarize([income, balance, cashflow], beneish, analysis.get("altman_zscore"))

    return {
        "fetched_at": datetime.now().isoformat(),
        "income": income,
        "balance": balance,
        "cashflow": cashflow,
        "beneish": beneish,
        "pills": pills,
        "summary": summary,
        "warnings": warnings,
    }


def run(ticker: str, analysis_json: str | None, out_dir: Path, force: bool) -> dict:
    analysis = {}
    if analysis_json:
        try:
            analysis = json.loads(Path(analysis_json).read_text(encoding="utf-8"))
        except Exception as e:
            log(f"could not read analysis-json: {e}")
    block = compute(analysis)
    block["ticker"] = ticker
    return block


def merge_into_analysis(analysis_json: str, block: dict) -> None:
    """Write the block into the analysis JSON under `red_flags`
    (additive key; schema stays 2.2; scores untouched)."""
    path = Path(analysis_json)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["red_flags"] = block
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    log(f"merged red_flags into {path.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Downside / red-flag scanner + Beneish M-score (overlay-only)")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--analysis-json", default=None,
                    help="Path to the analyze_ticker output JSON (fundamentals + statements_raw)")
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--force", action="store_true", help="(accepted for CLI parity; no cache here)")
    ap.add_argument("--update", action="store_true",
                    help="Merge the result into the analysis JSON (key: red_flags)")
    args = ap.parse_args()

    try:
        block = run(args.ticker, args.analysis_json, Path(args.out_dir), args.force)
        if args.update and args.analysis_json:
            merge_into_analysis(args.analysis_json, block)
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        print(json.dumps({"ticker": args.ticker, "error": str(e),
                          "error_type": type(e).__name__}))
        return 0  # non-fatal: report degrades, run continues

    print(json.dumps(block, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
