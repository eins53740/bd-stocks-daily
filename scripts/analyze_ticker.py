"""
analyze_ticker.py — Ground-truth data extraction for a single ticker.

Collects ALL structured numbers via yfinance, computes gates, Piotroski
F-Score, Altman Z-Score, composite 0-10 score.

Data quality (added after repeated gross yfinance errors on EU small/mid-caps):
  * Layer 0 — validate_consistency(): free internal-consistency gate. Flags a
    stale price (vs SMA50), market_cap != price×shares, and a P/E that can't be
    reconciled with P/S÷net_margin. Sets out["data_quality"] = ok|suspect and
    out["consistency_issues"]. Catches errors no second source is needed for.
  * Layer 1 — fetch_external_validation(): external cross-check, FMP first
    (US fundamentals) → Twelve Data fallback (key in api_keys.txt) → Stooq EOD
    *price* fallback for non-US names (Phase 6, Finding D2; no API key).
    Best-effort & non-fatal. FMP returns 402 and Twelve Data returns 404
    ("needs Grow/Venture plan") for many EU/Asia exchanges on the free tier, so
    the Stooq daily-EOD CSV endpoint (https://stooq.com/q/d/l/?s=<sym>&i=d) is
    wired as the non-US Layer-1 *price* cross-check. As of mid-2026 that CSV
    endpoint is itself gated by a JavaScript proof-of-work challenge for clients
    that don't run JS, so it currently degrades cleanly to Layers 0+2 (the parser
    detects the HTML interstitial and reports it instead of bad data). Disable all
    of Layer 1 with --no-fmp / --no-xval.
  * Layer 2 — reconcile_price_with_history(): self-heals a stale info-price by
    comparing it to history()'s last close (a different, reliable yfinance path)
    and recomputing market_cap. Works on EVERY exchange incl. Iberian small-caps.
    This is what fixes the CMO.MC €8.49→€38 class automatically.

data_quality field: ok | corrected (Layer 2 self-healed price/cap) | suspect
(Layer 0 found an unfixable inconsistency, e.g. distorted margin/PE).

Outputs a single big JSON on stdout. The LLM then wraps narrative around this.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Force UTF-8 on Windows so unicode in output doesn't crash cp1252 console
for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

warnings.filterwarnings("ignore")

import yfinance as yf  # noqa: E402

# Phase 6 — global-market metadata + free Stooq price cross-check.
import listings  # noqa: E402
import markets  # noqa: E402
import share_basis  # noqa: E402

# Reuse BD_Finance's api_keys_reader for the FMP cross-validation key (Layer 1).
BD_FINANCE = Path(r"C:\Github\BD\Finance\BD_Finance")
if str(BD_FINANCE) not in sys.path:
    sys.path.insert(0, str(BD_FINANCE))


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def safe(fn, default=None):
    try:
        val = fn()
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return default
        return val
    except Exception:
        return default


def pct_change(series, periods: int = 1):
    try:
        if len(series) < periods + 1:
            return None
        return (series.iloc[-1] - series.iloc[-(periods + 1)]) / abs(series.iloc[-(periods + 1)])
    except Exception:
        return None


def cagr(start, end, years: int):
    try:
        # Both endpoints must be positive: a fractional power of a negative
        # ratio returns a *complex* number (no exception), which then poisons
        # every downstream comparison. Holding companies (EXO.AS) can report a
        # negative "Total Revenue" when the line is a net investment result.
        if start is None or end is None or start <= 0 or end <= 0 or years <= 0:
            return None
        return (end / start) ** (1.0 / years) - 1.0
    except Exception:
        return None


# ------------------------- Piotroski F-Score -------------------------
def piotroski_fscore(bs, fs, cf, info) -> tuple[int, dict]:
    """9-point Piotroski F-Score. Returns (score, components)."""
    c = {}
    # 1. Positive net income
    try:
        ni_ttm = info.get("netIncomeToCommon") or fs.loc["Net Income"].iloc[0]
        c["pos_net_income"] = 1 if (ni_ttm and ni_ttm > 0) else 0
    except Exception:
        c["pos_net_income"] = 0

    # Shared inputs for components 2-4, guarded independently so a missing
    # "Total Assets" row can't NameError the unrelated earnings-quality point.
    ni = safe(lambda: fs.loc["Net Income"].iloc[0])
    ocf = safe(lambda: cf.loc["Operating Cash Flow"].iloc[0] if "Operating Cash Flow" in cf.index else cf.loc["Total Cash From Operating Activities"].iloc[0])

    # 2. Positive ROA
    try:
        ta = bs.loc["Total Assets"].iloc[0]
        c["pos_roa"] = 1 if (ni and ta and ni / ta > 0) else 0
    except Exception:
        c["pos_roa"] = 0

    # 3. Positive operating cash flow
    c["pos_ocf"] = 1 if (ocf and ocf > 0) else 0

    # 4. OCF > Net Income (earnings quality)
    c["ocf_gt_ni"] = 1 if (ni is not None and ocf is not None and ocf > ni) else 0

    # 5. Decrease in long-term debt ratio (D/A)
    try:
        lt_debt_curr = bs.loc["Long Term Debt"].iloc[0]
        lt_debt_prev = bs.loc["Long Term Debt"].iloc[1]
        ta_curr = bs.loc["Total Assets"].iloc[0]
        ta_prev = bs.loc["Total Assets"].iloc[1]
        c["dec_lt_debt"] = 1 if (lt_debt_curr / ta_curr) < (lt_debt_prev / ta_prev) else 0
    except Exception:
        c["dec_lt_debt"] = 0

    # 6. Increase in current ratio
    try:
        ca = bs.loc["Current Assets"].iloc[0] if "Current Assets" in bs.index else bs.loc["Total Current Assets"].iloc[0]
        cl = bs.loc["Current Liabilities"].iloc[0] if "Current Liabilities" in bs.index else bs.loc["Total Current Liabilities"].iloc[0]
        ca_p = bs.loc["Current Assets"].iloc[1] if "Current Assets" in bs.index else bs.loc["Total Current Assets"].iloc[1]
        cl_p = bs.loc["Current Liabilities"].iloc[1] if "Current Liabilities" in bs.index else bs.loc["Total Current Liabilities"].iloc[1]
        c["inc_current_ratio"] = 1 if (ca / cl) > (ca_p / cl_p) else 0
    except Exception:
        c["inc_current_ratio"] = 0

    # 7. No dilution (shares outstanding not increasing)
    try:
        so = bs.loc["Share Issued"].iloc[0] if "Share Issued" in bs.index else bs.loc["Common Stock"].iloc[0]
        so_p = bs.loc["Share Issued"].iloc[1] if "Share Issued" in bs.index else bs.loc["Common Stock"].iloc[1]
        c["no_dilution"] = 1 if so <= so_p * 1.01 else 0
    except Exception:
        c["no_dilution"] = 0

    # 8. Increase in gross margin
    try:
        gp = fs.loc["Gross Profit"].iloc[0]
        rev = fs.loc["Total Revenue"].iloc[0]
        gp_p = fs.loc["Gross Profit"].iloc[1]
        rev_p = fs.loc["Total Revenue"].iloc[1]
        c["inc_gross_margin"] = 1 if (gp / rev) > (gp_p / rev_p) else 0
    except Exception:
        c["inc_gross_margin"] = 0

    # 9. Increase in asset turnover
    try:
        ta_c = bs.loc["Total Assets"].iloc[0]
        rev_c = fs.loc["Total Revenue"].iloc[0]
        ta_pp = bs.loc["Total Assets"].iloc[1]
        rev_pp = fs.loc["Total Revenue"].iloc[1]
        c["inc_asset_turnover"] = 1 if (rev_c / ta_c) > (rev_pp / ta_pp) else 0
    except Exception:
        c["inc_asset_turnover"] = 0

    score = sum(c.values())
    return score, c


# ------------------------- Altman Z-Score -------------------------
def altman_zscore(bs, fs, info) -> float | None:
    """Classic Altman Z-Score (manufacturing). >2.99 safe, 1.81-2.99 grey, <1.81 distress."""
    try:
        ta = bs.loc["Total Assets"].iloc[0]
        tl = bs.loc["Total Liabilities Net Minority Interest"].iloc[0] if "Total Liabilities Net Minority Interest" in bs.index else bs.loc["Total Liab"].iloc[0]
        wc = (bs.loc["Current Assets"].iloc[0] if "Current Assets" in bs.index else bs.loc["Total Current Assets"].iloc[0]) - (bs.loc["Current Liabilities"].iloc[0] if "Current Liabilities" in bs.index else bs.loc["Total Current Liabilities"].iloc[0])
        re = bs.loc["Retained Earnings"].iloc[0]
        ebit = fs.loc["EBIT"].iloc[0] if "EBIT" in fs.index else fs.loc["Operating Income"].iloc[0]
        mcap = info.get("marketCap")
        rev = fs.loc["Total Revenue"].iloc[0]

        A = wc / ta
        B = re / ta
        C = ebit / ta
        D = (mcap / tl) if tl > 0 else 0
        E = rev / ta
        return 1.2 * A + 1.4 * B + 3.3 * C + 0.6 * D + 1.0 * E
    except Exception as e:
        log(f"  altman fail: {e}")
        return None


# ------------------------- 7 Quality Compounder Gates -------------------------
def evaluate_gates(fund: dict) -> tuple[int, dict]:
    gates = {}

    # Gate 1: revenue growth 5y CAGR >= 8%
    rg = fund.get("revenue_cagr_5y")
    gates["gate_1_revenue_growth"] = {
        "pass": rg is not None and rg >= 0.08,
        "value": rg,
        "threshold": 0.08,
        "label": "Revenue growth 5y CAGR &gt;= 8%",
    }

    # Gate 2: P/E < 35 OR (PEG < 2.5 AND ROE > 20%)
    pe = fund.get("pe_ratio")
    peg = fund.get("peg")
    roe = fund.get("roe_ttm")
    gate2_pass = (pe is not None and pe > 0 and pe < 35) or (
        peg is not None and 0 < peg < 2.5 and roe is not None and roe > 0.20
    )
    gates["gate_2_valuation"] = {
        "pass": gate2_pass,
        "value": {"pe": pe, "peg": peg, "roe": roe},
        "threshold": "P/E<35 OR (PEG<2.5 AND ROE>20%)",
        "label": "Quality valuation",
    }

    # Gate 3: FCF TTM positive (catches capex-trough / negative-FCF compounders)
    fcf = fund.get("fcf_ttm")
    gates["gate_3_fcf_positive"] = {
        "pass": fcf is not None and fcf > 0,
        "value": fcf,
        "threshold": 0,
        "label": "FCF TTM > 0",
    }

    # Gate 4: ROE > 5% (5y avg)
    roe5 = fund.get("roe_5y_avg")
    gates["gate_4_roe"] = {
        "pass": roe5 is not None and roe5 > 0.05,
        "value": roe5,
        "threshold": 0.05,
        "label": "ROE 5y avg > 5%",
    }

    # Gate 5: Net profit margin > 10%
    # v2.2 growth bypass: a hyper-grower deliberately suppressing current margin to
    # reinvest counts as PASS when rev CAGR>=25% AND ROIC>=15% AND FCF/rev improving YoY.
    nm = fund.get("net_margin_ttm")
    margin_pass = nm is not None and nm > 0.10
    g5_bypassed = False
    g5_bypass_reason = None
    if not margin_pass:
        g5_bypassed, g5_bypass_reason = gate5_growth_bypass(
            fund.get("revenue_cagr_5y"), fund.get("roic_ttm"),
            fund.get("fcf_rev_latest"), fund.get("fcf_rev_prior"),
        )
    gates["gate_5_margin"] = {
        "pass": margin_pass or g5_bypassed,
        "value": nm,
        "threshold": 0.10,
        "label": "Net margin > 10%",
        "gate_5_bypassed": g5_bypassed,
        "gate_5_bypass_reason": g5_bypass_reason,
    }

    # Gate 6: D/E < 1.0
    de = fund.get("debt_to_equity")
    gates["gate_6_debt"] = {
        "pass": de is not None and de < 1.0,
        "value": de,
        "threshold": 1.0,
        "label": "D/E < 1.0",
    }

    # Gate 7: Quick ratio > 1.5
    qr = fund.get("quick_ratio")
    gates["gate_7_liquidity"] = {
        "pass": qr is not None and qr > 1.5,
        "value": qr,
        "threshold": 1.5,
        "label": "Quick ratio > 1.5",
    }

    passed = sum(1 for g in gates.values() if g["pass"])
    return passed, gates


# ------------------------- Score 0-10 components -------------------------
def score_fundamentals(fscore: int, gates_passed: int, zscore: float | None) -> float:
    # Piotroski contributes 6, gates contribute 3, Altman contributes 1
    p = (fscore / 9.0) * 6.0
    g = (gates_passed / 7.0) * 3.0
    z = 0.0
    if zscore is not None:
        if zscore >= 2.99:
            z = 1.0
        elif zscore >= 1.81:
            z = 0.5
    return round(p + g + z, 2)


# ------------------------- v2.2 pure helpers (Magic Formula + Buffett + decay + bypass) -------------------------
# These are pure (no network, no yfinance) so they unit-test cleanly. They are
# the single source of truth for the v2.2 fundamentals fields and overlays.

# Minimum invested capital, as a fraction of the gross capital base, for ROIC to
# carry information. Below this the net-cash subtraction has hollowed out the
# denominator (see compute_roic).
IC_MIN_FRACTION = 0.05


def compute_roic(ebit, tax_provision, pretax_income,
                 total_debt, total_equity, cash) -> float | None:
    """ROIC = NOPAT / Invested Capital (Magic Formula proxy).

    NOPAT = EBIT * (1 - effective_tax_rate); eff_rate = tax/pretax clamped to
    [0, 0.35], default 0.21 if unavailable. Invested Capital = total_debt +
    total_equity - cash. None if EBIT/inputs missing, IC <= 0, or IC is a
    degenerate fraction of the gross capital base.

    The degenerate-denominator guard matters for net-cash balance sheets, which
    are the norm in software: subtracting all cash drives IC asymptotically to
    zero and ROIC explodes. VEEV 2026-07-30 held cash 7.31bn against equity
    7.28bn, leaving IC at 0.98% of the gross base and printing ROIC 13,671% —
    which then tripped the >25% Buffett moat opt-in on a company earning ROE
    13.9% / ROCE 12.5%. Below the floor the ratio carries no information, so it
    degrades to None (no opt-in, no gate-5 bypass) rather than a false signal.
    """
    if ebit is None or total_debt is None or total_equity is None or cash is None:
        return None
    tax_rate = 0.21
    if tax_provision is not None and pretax_income not in (None, 0) and pretax_income > 0:
        tax_rate = max(0.0, min(0.35, tax_provision / pretax_income))
    invested_capital = total_debt + total_equity - cash
    if invested_capital <= 0:
        return None
    gross_capital = total_debt + total_equity
    if gross_capital > 0 and invested_capital / gross_capital < IC_MIN_FRACTION:
        return None
    nopat = ebit * (1 - tax_rate)
    return round(nopat / invested_capital, 6)


def compute_ev_ebit(market_cap, total_debt, cash, ebit) -> float | None:
    """EV/EBIT where EV = market_cap + total_debt - cash. None if EBIT<=0/missing."""
    if market_cap is None or ebit is None or ebit <= 0:
        return None
    debt = total_debt or 0.0
    c = cash or 0.0
    ev = market_cap + debt - c
    return round(ev / ebit, 6)


def compute_roce(ebit, total_assets, current_liabilities) -> float | None:
    """ROCE = EBIT / (Total Assets - Current Liabilities). None if unavailable."""
    if ebit is None or total_assets is None or current_liabilities is None:
        return None
    capital_employed = total_assets - current_liabilities
    if capital_employed <= 0:
        return None
    return round(ebit / capital_employed, 6)


def apply_buffett_moat(moat_score: float, roic_ttm) -> tuple[float, bool]:
    """Buffett opt-in: if ROIC > 25%, multiply moat sub-score by 1.25 (cap 10)."""
    if roic_ttm is not None and roic_ttm > 0.25:
        return round(min(10.0, moat_score * 1.25), 2), True
    return round(moat_score, 2), False


# News-event time decay: I(t) = I0 * e^(-lambda * dt), I0=1.0, half-life 7 days.
_NEWS_DECAY_LAMBDA = math.log(2) / 7.0


def compute_news_freshness(days_since_earnings) -> float | None:
    """Freshness overlay 0..1 for the last earnings event. None if no earnings date."""
    if days_since_earnings is None:
        return None
    return round(math.exp(-_NEWS_DECAY_LAMBDA * max(0, days_since_earnings)), 3)


def gate5_growth_bypass(revenue_cagr_5y, roic_ttm,
                        fcf_rev_latest, fcf_rev_prior) -> tuple[bool, str | None]:
    """Gate-5 (net-margin) growth bypass predicate.

    Bypass fires only when ALL hold: revenue_cagr_5y >= 0.25 AND roic_ttm >= 0.15
    AND FCF/revenue improving YoY (latest > prior). Returns (fires, reason).
    """
    if None in (revenue_cagr_5y, roic_ttm, fcf_rev_latest, fcf_rev_prior):
        return False, None
    if revenue_cagr_5y >= 0.25 and roic_ttm >= 0.15 and fcf_rev_latest > fcf_rev_prior:
        reason = (
            f"Gate-5 bypass: hyper-grower reinvesting margin "
            f"(rev CAGR {revenue_cagr_5y*100:.0f}% >=25%, ROIC {roic_ttm*100:.0f}% >=15%, "
            f"FCF/rev improving {fcf_rev_prior*100:.1f}%->{fcf_rev_latest*100:.1f}%)"
        )
        return True, reason
    return False, None


def score_moat(roe_ttm, roe_5y, margin_ttm, margin_5y) -> tuple[float, dict]:
    # ROE consistency + margin stability + absolute levels
    details = {}
    roe_score = 0.0
    if roe_ttm is not None:
        if roe_ttm >= 0.25:
            roe_score = 5.0
        elif roe_ttm >= 0.15:
            roe_score = 4.0
        elif roe_ttm >= 0.10:
            roe_score = 2.5
        elif roe_ttm >= 0.05:
            roe_score = 1.0
    stability = 0.0
    if roe_5y is not None and roe_ttm is not None and roe_5y > 0:
        # penalise big deviation vs 5y
        dev = abs(roe_ttm - roe_5y) / roe_5y
        stability = max(0, 3.0 - dev * 3.0)
    margin_score = 0.0
    if margin_ttm is not None:
        if margin_ttm >= 0.20:
            margin_score = 2.0
        elif margin_ttm >= 0.10:
            margin_score = 1.0
    details.update(roe_score=roe_score, stability=stability, margin_score=margin_score)
    return round(min(10.0, roe_score + stability + margin_score), 2), details


def score_valuation(pe, peg, fcf_yield, dcf_upside, ev_ebit=None) -> tuple[float, dict]:
    # v2.2 — WEIGHT-NEUTRAL: EV/EBIT (Magic Formula) folded INSIDE the 0-10 cap.
    # P/E trimmed 0-3 -> 0-2 (it overlaps EV/EBIT per SCORING_REVIEW_v3 §2.2) and
    # EV/EBIT given a comparable 0-1 band. Sub-points still sum to max 10; the
    # Valuation top weight stays 0.20 (unchanged).
    #   P/E 0-2 + PEG 0-3 + FCF 0-2 + DCF 0-2 + EV/EBIT 0-1 = 10
    s = 0.0
    details = {}
    # P/E component (0-2)
    if pe is not None and pe > 0:
        if pe < 15:
            s += 2
        elif pe < 25:
            s += 1.5
        elif pe < 35:
            s += 0.5
    # PEG (0-3)
    if peg is not None and peg > 0:
        if peg < 1:
            s += 3
        elif peg < 1.5:
            s += 2
        elif peg < 2.5:
            s += 1
    # FCF yield (0-2)
    if fcf_yield is not None:
        if fcf_yield > 0.06:
            s += 2
        elif fcf_yield > 0.03:
            s += 1
    # DCF upside (0-2)
    if dcf_upside is not None:
        if dcf_upside > 0.25:
            s += 2
        elif dcf_upside > 0:
            s += 1
    # EV/EBIT (0-1) — Magic Formula cheapness band: <12 cheap, <18 fair, else rich
    if ev_ebit is not None and ev_ebit > 0:
        if ev_ebit < 12:
            s += 1
        elif ev_ebit < 18:
            s += 0.5
    details.update(pe=pe, peg=peg, fcf_yield=fcf_yield, dcf_upside=dcf_upside, ev_ebit=ev_ebit)
    return round(min(10.0, s), 2), details


def score_growth_durability(rev_cagr_5y, rev_stability, category) -> tuple[float, dict]:
    s = 0.0
    if rev_cagr_5y is not None:
        if rev_cagr_5y >= 0.20:
            s += 4
        elif rev_cagr_5y >= 0.10:
            s += 3
        elif rev_cagr_5y >= 0.05:
            s += 1.5
    if rev_stability is not None:
        s += rev_stability * 4  # 0-4
    # category bonus
    cat_bonus = {"stalwart": 2, "fast_grower": 2, "slow_grower": 0.5, "cyclical": 0, "turnaround": 0}
    s += cat_bonus.get(category, 1)
    return round(min(10.0, s), 2), {"rev_cagr_5y": rev_cagr_5y, "rev_stability": rev_stability, "category": category}


def lynch_category(rev_cagr_5y, roe_5y, net_margin_5y) -> str:
    if rev_cagr_5y is None:
        return "unknown"
    if rev_cagr_5y >= 0.20:
        return "fast_grower"
    if rev_cagr_5y >= 0.05 and (roe_5y or 0) >= 0.10:
        return "stalwart"
    if rev_cagr_5y < 0.05:
        return "slow_grower"
    return "cyclical"


# ------------------------- Market context -------------------------
def fetch_vix() -> float | None:
    try:
        v = yf.Ticker("^VIX").history(period="5d")
        if v.empty:
            return None
        return float(v["Close"].iloc[-1])
    except Exception:
        return None


def fetch_eur_rate(currency: str) -> float | None:
    """Units of `currency` per 1 EUR via the Yahoo FX pair (e.g. EURJPY=X).

    EUR returns 1.0. Best-effort & non-fatal — None on any failure so EUR
    conversion simply degrades to 'not available' rather than crashing a market.
    """
    cur = (currency or "").upper()
    if cur == "EUR":
        return 1.0
    pair = markets.eur_fx_pair(cur)
    if not pair:
        return None
    try:
        h = yf.Ticker(pair).history(period="5d")
        if h is None or h.empty:
            return None
        rate = float(h["Close"].iloc[-1])
        return rate if rate > 0 else None
    except Exception:
        return None


# ------------------------- Composite reweighting (schema v2) -------------------------
# Weights locked in the v2 plan. Management is an LLM-derived score injected after
# Phase 2.5; analyze_ticker emits a provisional composite using mgmt=5.0 for deep,
# and a 6-component renormalised composite for screen mode (no LLM call).
WEIGHTS_V2_DEEP = {
    "fundamentals": 0.35,
    "valuation": 0.20,
    "moat": 0.12,
    "peer": 0.12,
    "growth_durability": 0.08,
    "management": 0.08,
    "market_context": 0.05,
}


def reweighted_composite(scores: dict, mgmt: float | None = None, mode: str = "deep") -> float:
    """
    Compute v2 composite. `scores` must contain the 6 Python-computed components
    (fundamentals, valuation, moat, peer, growth_durability, market_context).

    - deep: mgmt defaults to 5.0 (neutral placeholder); finalize_score.py overwrites
      this with the LLM-derived score once Phase 2.5 completes.
    - screen: ignores mgmt, renormalises the remaining 6 weights so they sum to 1.0
      (each weight / 0.92). Screens never run the management LLM pass.
    """
    fund = scores.get("fundamentals", 0.0)
    val = scores.get("valuation", 0.0)
    moat = scores.get("moat", 0.0)
    peer = scores.get("peer", 0.0)
    growth = scores.get("growth_durability", 0.0)
    mkt = scores.get("market_context", 0.0)

    if mode == "screen":
        denom = 1.0 - WEIGHTS_V2_DEEP["management"]  # 0.92
        c = (
            WEIGHTS_V2_DEEP["fundamentals"] * fund
            + WEIGHTS_V2_DEEP["valuation"] * val
            + WEIGHTS_V2_DEEP["moat"] * moat
            + WEIGHTS_V2_DEEP["peer"] * peer
            + WEIGHTS_V2_DEEP["growth_durability"] * growth
            + WEIGHTS_V2_DEEP["market_context"] * mkt
        ) / denom
        return round(c, 2)

    m = 5.0 if mgmt is None else float(mgmt)
    c = (
        WEIGHTS_V2_DEEP["fundamentals"] * fund
        + WEIGHTS_V2_DEEP["valuation"] * val
        + WEIGHTS_V2_DEEP["moat"] * moat
        + WEIGHTS_V2_DEEP["peer"] * peer
        + WEIGHTS_V2_DEEP["growth_durability"] * growth
        + WEIGHTS_V2_DEEP["management"] * m
        + WEIGHTS_V2_DEEP["market_context"] * mkt
    )
    return round(c, 2)


def verdict_from_composite(composite: float) -> str:
    if composite >= 9.0:
        return "great"
    if composite >= 7.5:
        return "invest"
    if composite >= 6.0:
        return "review"
    if composite >= 4.0:
        return "fair"
    return "reject"


def market_context_score(vix: float | None) -> tuple[float, dict]:
    # Informative, not decisive (5% weight). Bias upward when VIX is elevated (better entry).
    if vix is None:
        return 5.0, {"vix": None, "regime": "unknown"}
    if vix < 13:
        return 3.0, {"vix": vix, "regime": "complacency"}
    if vix < 20:
        return 5.5, {"vix": vix, "regime": "normal"}
    if vix < 30:
        return 7.5, {"vix": vix, "regime": "fear_opportunity"}
    if vix < 40:
        return 8.5, {"vix": vix, "regime": "elevated_fear"}
    return 9.5, {"vix": vix, "regime": "panic_historic_opportunity"}


# ------------------------- Peer ranking (industry-level) -------------------------
_PEERS_PATH = Path(__file__).resolve().parent / "peers.json"


def _load_peer_universe() -> dict:
    try:
        return json.loads(_PEERS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"  peers.json load fail: {e}")
        return {"by_industry": {}, "by_sector": {}}


def _peer_tickers_for(ticker: str, industry: str, sector: str) -> tuple[list[str], str]:
    """Resolve peer list. Returns (peers, source). Source in {by_ticker, by_industry, by_sector, none}."""
    uni = _load_peer_universe()
    by_tkr = uni.get("by_ticker", {})
    by_ind = uni.get("by_industry", {})
    by_sec = uni.get("by_sector", {})
    if ticker.upper() in by_tkr:
        return list(by_tkr[ticker.upper()]), "by_ticker"
    if industry in by_ind:
        return list(by_ind[industry]), "by_industry"
    if sector in by_sec:
        return list(by_sec[sector]), "by_sector"
    return [], "none"


def _compact_fund(ticker: str, info: dict) -> dict:
    """Compact metric dict for a peer. Uses yfinance info fields only (fast path)."""
    mcap = info.get("marketCap")
    fcf = info.get("freeCashflow")
    return {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName"),
        "market_cap": mcap,
        "pe": info.get("trailingPE"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "peg": info.get("pegRatio") or info.get("trailingPegRatio"),
        "roe": info.get("returnOnEquity"),
        "net_margin": info.get("profitMargins"),
        "fcf_yield": (fcf / mcap) if (fcf and mcap and mcap > 0) else None,
        "rev_growth_3y": info.get("revenueGrowth"),  # yoy proxy; not true 3y CAGR but good enough for ranking
    }


# Metric → (label, lower_is_better)
_PEER_METRICS = [
    ("pe", "P/E", True),
    ("ev_ebitda", "EV/EBITDA", True),
    ("peg", "PEG", True),
    ("roe", "ROE", False),
    ("net_margin", "Net margin", False),
    ("fcf_yield", "FCF yield", False),
]


def _rank_metric(values: dict, lower_is_better: bool) -> dict:
    """Return {ticker: rank_1_to_N} with ties sharing the lower rank. Missing values skipped."""
    clean = {k: v for k, v in values.items() if v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))}
    # Drop non-positive P/E / PEG / EV-EBITDA when lower_is_better (negatives mean losses, not "cheap")
    if lower_is_better:
        clean = {k: v for k, v in clean.items() if v > 0}
    if not clean:
        return {}
    sorted_items = sorted(clean.items(), key=lambda kv: kv[1], reverse=not lower_is_better)
    ranks = {}
    prev_val = None
    prev_rank = 0
    for i, (k, v) in enumerate(sorted_items, start=1):
        rank = prev_rank if v == prev_val else i  # ties share the better rank
        ranks[k] = rank
        prev_val, prev_rank = v, rank
    return ranks


def fetch_peer_ranking(ticker: str, info: dict, ticker_fund: dict) -> dict:
    industry = info.get("industry") or "Unknown"
    sector = info.get("sector") or "Unknown"
    peer_tickers, peers_source = _peer_tickers_for(ticker, industry, sector)
    # Exclude the target ticker itself if present in the peer list.
    peer_tickers = [p for p in peer_tickers if p.upper() != ticker.upper()]

    if not peer_tickers:
        return {
            "industry": industry,
            "sector": sector,
            "peers_source": "none",
            "peer_tickers": [],
            "peer_metrics": {},
            "rankings": {},
            "rank_summary": {},
            "score_0_10": 5.0,
            "score_reason": "no peers configured for this industry/sector — neutral placeholder",
        }

    # Build metrics for ticker (from already-computed ticker_fund) and each peer (yfinance info).
    metrics_by_ticker = {
        ticker: {
            "ticker": ticker,
            "name": info.get("longName") or info.get("shortName") or ticker,
            "market_cap": ticker_fund.get("market_cap"),
            "pe": ticker_fund.get("pe_ratio"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "peg": ticker_fund.get("peg"),
            "roe": ticker_fund.get("roe_ttm"),
            "net_margin": ticker_fund.get("net_margin_ttm"),
            "fcf_yield": ticker_fund.get("fcf_yield"),
            "rev_growth_3y": ticker_fund.get("revenue_cagr_5y"),  # closer to structural
        }
    }
    fetched_peers = []
    for pt in peer_tickers:
        try:
            p_info = safe(lambda pt=pt: yf.Ticker(pt).info, default={}) or {}
            if p_info:
                metrics_by_ticker[pt] = _compact_fund(pt, p_info)
                fetched_peers.append(pt)
        except Exception as e:
            log(f"  peer fetch {pt} fail: {e}")

    # Compute ranks per metric
    rankings = {}
    for mkey, _label, lower in _PEER_METRICS:
        values = {k: v.get(mkey) for k, v in metrics_by_ticker.items()}
        rankings[mkey] = _rank_metric(values, lower)

    # Score: for each metric where the ticker has a rank, compute its percentile (rank→0-10)
    # then average across available metrics.
    tscores = []
    for mkey, _label, _lower in _PEER_METRICS:
        rs = rankings.get(mkey, {})
        if ticker not in rs:
            continue
        n = len(rs)
        if n < 3:
            continue  # require at least 3 ranked entries for the metric to count
        rank = rs[ticker]
        # rank 1 of N → 10, rank N of N → 10*(1/N)  (smooth linear mapping: 10*(N-rank+1)/N)
        tscores.append(10.0 * (n - rank + 1) / n)
    peer_score = round(sum(tscores) / len(tscores), 2) if tscores else 5.0

    # Rank summary: sum of ranks (lower = better) across metrics where ticker is ranked.
    rank_summary = {}
    for k in metrics_by_ticker:
        total, count = 0, 0
        for mkey, _label, _lower in _PEER_METRICS:
            rs = rankings.get(mkey, {})
            if k in rs and len(rs) >= 3:
                total += rs[k]
                count += 1
        rank_summary[k] = {"rank_sum": total, "metrics_counted": count, "avg_rank": round(total / count, 2) if count else None}

    return {
        "industry": industry,
        "sector": sector,
        "peers_source": peers_source,
        "peer_tickers": fetched_peers,
        "peer_metrics": metrics_by_ticker,
        "rankings": rankings,
        "rank_summary": rank_summary,
        "score_0_10": peer_score,
        "score_reason": f"avg across {len(tscores)} ranked metrics vs {len(fetched_peers)} peers ({peers_source})",
    }


# ------------------------- Borja v2.1 — extra extractors -------------------------
def compute_shareholder_structure(tk, info: dict) -> dict:
    """§2.4 — Estrutura acionista. Pure yfinance, no LLM."""
    out = {
        "insider_pct": info.get("heldPercentInsiders"),
        "institutional_pct": info.get("heldPercentInstitutions"),
        "float_shares": info.get("floatShares"),
        "shares_out": info.get("sharesOutstanding"),
        "top_institutional": [],
        "recent_insider_transactions": [],
        "data_warnings": [],
    }
    try:
        ih = tk.institutional_holders
        if ih is not None and not ih.empty:
            # Keep top 5; serialise to plain dicts
            for _, row in ih.head(5).iterrows():
                out["top_institutional"].append({
                    "holder": str(row.get("Holder", "")),
                    "shares": int(row["Shares"]) if "Shares" in row and row["Shares"] == row["Shares"] else None,
                    "pct_held": float(row["pctHeld"]) if "pctHeld" in row and row["pctHeld"] == row["pctHeld"] else None,
                    "value": float(row["Value"]) if "Value" in row and row["Value"] == row["Value"] else None,
                })
    except Exception as e:
        out["data_warnings"].append(f"institutional_holders: {e}")
    try:
        it = tk.insider_transactions
        if it is not None and not it.empty:
            for _, row in it.head(5).iterrows():
                out["recent_insider_transactions"].append({
                    "insider": str(row.get("Insider", "")),
                    "position": str(row.get("Position", "")),
                    "transaction": str(row.get("Transaction", "")),
                    "shares": int(row["Shares"]) if "Shares" in row and row["Shares"] == row["Shares"] else None,
                    "value": float(row["Value"]) if "Value" in row and row["Value"] == row["Value"] else None,
                    "date": str(row.get("Start Date", "") or row.get("Date", ""))[:10],
                })
    except Exception as e:
        out["data_warnings"].append(f"insider_transactions: {e}")
    return out


# Row-label fallbacks for the raw 2-year statement snapshot persisted for the
# v4 Phase-C red-flag scanner / Beneish M-score. canonical_key -> yfinance row
# labels to try (first hit wins). Missing rows serialize as null, never
# fabricated; yfinance normally exposes 3-4 annual columns and we keep the two
# most recent (t, t-1) — exactly what Beneish's indices and the trend flags need.
_STMT_ROWS = {
    "income": {
        "revenue": ("Total Revenue", "Operating Revenue", "Revenue"),
        "cost_of_revenue": ("Cost Of Revenue", "Reconciled Cost Of Revenue", "Cost Of Goods Sold"),
        "gross_profit": ("Gross Profit",),
        "operating_income": ("Operating Income", "EBIT", "Total Operating Income As Reported"),
        "sga": ("Selling General And Administration", "Selling General And Administrative Expense", "Selling General Administrative"),
        "depreciation": ("Reconciled Depreciation", "Depreciation Amortization Depletion Income Statement", "Depreciation And Amortization In Income Statement"),
        "interest_expense": ("Interest Expense", "Interest Expense Non Operating"),
        "pretax_income": ("Pretax Income", "Pretax Income Loss"),
        "net_income": ("Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations"),
        "unusual_items": ("Total Unusual Items", "Special Income Charges", "Total Unusual Items Excluding Goodwill"),
    },
    "balance": {
        "total_assets": ("Total Assets",),
        "total_liabilities": ("Total Liabilities Net Minority Interest", "Total Liab"),
        "current_assets": ("Current Assets", "Total Current Assets"),
        "current_liabilities": ("Current Liabilities", "Total Current Liabilities"),
        "receivables": ("Accounts Receivable", "Net Receivables", "Receivables", "Gross Accounts Receivable"),
        "inventory": ("Inventory",),
        "ppe_net": ("Net PPE", "Net Property Plant Equipment", "Property Plant Equipment Net"),
        "ppe_gross": ("Gross PPE", "Gross Property Plant Equipment", "Properties"),
        "long_term_debt": ("Long Term Debt", "Long Term Debt And Capital Lease Obligation"),
        "total_debt": ("Total Debt",),
        "stockholders_equity": ("Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"),
        "retained_earnings": ("Retained Earnings",),
        "shares": ("Share Issued", "Ordinary Shares Number", "Common Stock"),
        # v4.3 wave 3: intangibles. Two consumers need them and neither can
        # derive them from anything already here — `category_lens` prices the
        # asset-play test off TANGIBLE book, and `roic_lens` reports ROIC
        # ex-goodwill beside ROIC. Read from the balance frame that is already
        # in memory, so this costs no fetch and no API call.
        # Kept as three separate keys on purpose: yfinance publishes either the
        # split rows or the combined one depending on the filer, and adding
        # `goodwill` to a combined row that already contains it would double-
        # count the largest line on an acquisitive balance sheet.
        "goodwill": ("Goodwill",),
        "intangibles": ("Other Intangible Assets", "Intangible Assets"),
        "goodwill_and_intangibles": ("Goodwill And Other Intangible Assets",),
        "net_tangible_assets": ("Net Tangible Assets",),
    },
    "cashflow": {
        "operating_cash_flow": ("Operating Cash Flow", "Total Cash From Operating Activities", "Cash Flow From Continuing Operating Activities"),
        "capex": ("Capital Expenditure", "Capital Expenditures", "Purchase Of PPE"),
        "free_cash_flow": ("Free Cash Flow",),
        "dividends_paid": ("Cash Dividends Paid", "Common Stock Dividend Paid", "Cash Dividend Paid"),
        "depreciation": ("Depreciation And Amortization", "Depreciation Amortization Depletion", "Depreciation"),
    },
}


def _stmt_two_years(frame, labels) -> list:
    """[value_t, value_t-1] for the first matching row label, else [None, None].
    Columns the frame doesn't provide degrade to None (never fabricated)."""
    vals = [None, None]
    if frame is None or getattr(frame, "empty", True):
        return vals
    for lab in labels:
        if lab in frame.index:
            row = frame.loc[lab]
            for i in range(2):
                try:
                    v = row.iloc[i]
                    vals[i] = float(v) if (v is not None and v == v) else None  # v==v filters NaN
                except (IndexError, TypeError, ValueError):
                    vals[i] = None
            return vals
    return vals


def _fiscal_dates(frame) -> list:
    out = [None, None]
    if frame is None or getattr(frame, "empty", True):
        return out
    for i in range(min(2, len(frame.columns))):
        try:
            out[i] = str(frame.columns[i])[:10]
        except Exception:
            out[i] = None
    return out


def extract_statement_rows(fs, bs, cf) -> dict:
    """Compact 2-year snapshot of raw statement line items so the Phase-C
    red-flag scanner (red_flags.py) runs as a pure JSON consumer — no re-fetch,
    no extra API call. Overlay-only: additive JSON, no scalar/score/gate change.
    Missing rows -> null (expected often on non-US names; Beneish then degrades
    to 'not computable'). Values are [latest, prior] per canonical key."""
    frames = {"income": fs, "balance": bs, "cashflow": cf}
    out = {}
    for stmt, cols in _STMT_ROWS.items():
        frame = frames[stmt]
        block = {"fiscal_dates": _fiscal_dates(frame)}
        for key, labels in cols.items():
            block[key] = _stmt_two_years(frame, labels)
        out[stmt] = block
    return out


def compute_capital_returns(fund: dict, cf) -> dict:
    """§2.5 — Capital returns & shareholder yield. Net Payout Yield is the Borja signature metric."""
    out = {
        "dividend_yield": fund.get("dividend_yield"),
        "dividend_rate": fund.get("dividend_rate"),
        "payout_ratio": fund.get("payout_ratio"),
        "shares_change_5y_pct": fund.get("shares_change_5y_pct"),
        "dividends_paid_ttm": None,
        "buybacks_ttm": None,
        "issuance_ttm": None,
        "net_payout_yield": None,
        "data_warnings": [],
    }
    try:
        if cf is not None and not cf.empty:
            for label in ("Cash Dividends Paid", "Common Stock Dividend Paid"):
                if label in cf.index:
                    out["dividends_paid_ttm"] = abs(float(cf.loc[label].iloc[0]))
                    break
            for label in ("Repurchase Of Capital Stock", "Repurchase Of Common Stock", "Common Stock Payments"):
                if label in cf.index:
                    out["buybacks_ttm"] = abs(float(cf.loc[label].iloc[0]))
                    break
            for label in ("Issuance Of Capital Stock", "Common Stock Issuance"):
                if label in cf.index:
                    out["issuance_ttm"] = abs(float(cf.loc[label].iloc[0]))
                    break
    except Exception as e:
        out["data_warnings"].append(f"cashflow rows: {e}")

    mcap = fund.get("market_cap")
    if mcap and mcap > 0:
        div = out["dividends_paid_ttm"] or 0
        bb = out["buybacks_ttm"] or 0
        iss = out["issuance_ttm"] or 0
        # Net payout yield = (dividends + buybacks - issuance) / market cap
        if (div + bb + iss) > 0:  # at least one component present
            out["net_payout_yield"] = (div + bb - iss) / mcap
    return out


def compute_consensus(tk) -> dict:
    """§2.14 — Consensus & sell-side. yfinance only — no paywalled feed."""
    out = {
        "recommendation_mean": None,
        "recommendation_key": None,
        "analyst_count": None,
        "target_mean": None,
        "target_median": None,
        "target_high": None,
        "target_low": None,
        "eps_estimate_current_year": None,
        "eps_estimate_next_year": None,
        "revenue_estimate_current_year": None,
        "revenue_estimate_next_year": None,
        "data_warnings": [],
    }
    try:
        apt = tk.analyst_price_targets
        if isinstance(apt, dict):
            out["target_mean"] = apt.get("mean")
            out["target_median"] = apt.get("median")
            out["target_high"] = apt.get("high")
            out["target_low"] = apt.get("low")
    except Exception as e:
        out["data_warnings"].append(f"price_targets: {e}")
    try:
        info = tk.info or {}
        out["recommendation_mean"] = info.get("recommendationMean")
        out["recommendation_key"] = info.get("recommendationKey")
        out["analyst_count"] = info.get("numberOfAnalystOpinions")
    except Exception:
        pass
    try:
        ee = tk.earnings_estimate
        if ee is not None and not ee.empty:
            if "0y" in ee.index:
                out["eps_estimate_current_year"] = float(ee.loc["0y", "avg"]) if "avg" in ee.columns else None
            if "+1y" in ee.index:
                out["eps_estimate_next_year"] = float(ee.loc["+1y", "avg"]) if "avg" in ee.columns else None
    except Exception as e:
        out["data_warnings"].append(f"earnings_estimate: {e}")
    try:
        re = tk.revenue_estimate
        if re is not None and not re.empty:
            if "0y" in re.index:
                out["revenue_estimate_current_year"] = float(re.loc["0y", "avg"]) if "avg" in re.columns else None
            if "+1y" in re.index:
                out["revenue_estimate_next_year"] = float(re.loc["+1y", "avg"]) if "avg" in re.columns else None
    except Exception as e:
        out["data_warnings"].append(f"revenue_estimate: {e}")
    return out


def compute_price_returns(hist) -> dict:
    """Dividend-inclusive price returns from the 5y history frame (auto_adjust
    default → Close already reflects dividends). 1y = last close vs the close
    ~252 trading days back; 5y = last vs first close of the frame. The span label
    tells the report whether the "5y" number really covers 5 years or a shorter
    listing, so short histories are labelled honestly ("since YYYY-MM-DD")."""
    out = {
        "price_return_1y_pct": None,
        "price_return_5y_pct": None,
        "price_return_5y_span": None,
    }
    try:
        if hist is None or hist.empty or "Close" not in hist:
            return out
        close = hist["Close"].dropna()
        if close.empty:
            return out
        last = float(close.iloc[-1])
        if len(close) >= 253 and float(close.iloc[-253]) > 0:
            out["price_return_1y_pct"] = round((last / float(close.iloc[-253]) - 1) * 100, 2)
        first = float(close.iloc[0])
        if first > 0:
            out["price_return_5y_pct"] = round((last / first - 1) * 100, 2)
        span_days = (close.index[-1] - close.index[0]).days
        if span_days >= 4.75 * 365.25:
            out["price_return_5y_span"] = "5y"
        else:
            out["price_return_5y_span"] = f"since {close.index[0].date().isoformat()}"
    except Exception:
        pass
    return out


# ------------------------- Main -------------------------
class ThrottleSuspected(RuntimeError):
    """Every core yfinance fetch came back empty — almost certainly a 429.

    A distinct class rather than a bare RuntimeError because it crosses two process
    boundaries as `error_type` (main()'s JSON for subprocess callers, and
    run_prefilter's own except clause for the in-process path), which lets the caller
    tell "this ticker has no data" from "we were throttled". They deserve opposite
    treatment: the first is a fact about the ticker, the second is a fact about us.
    """


CORE_MISSING_LIMIT = 3


def core_fetches_missing(info, fs, bs, hist) -> int:
    """How many of the four core yfinance fetches came back empty (0-4).

    One definition, used by both the retry loop and the gate that raises. When the two
    computed it separately they could disagree, and the disagreement would be invisible:
    the loop would stop retrying while the gate still rejected the ticker.
    """
    return sum([
        not info,
        fs is None or getattr(fs, "empty", True),
        bs is None or getattr(bs, "empty", True),
        hist is None or getattr(hist, "empty", True),
    ])


# One retry, then give up. Measured on 2026-08-17: the prefilter on vmhost1 rejected 76
# `.AX` names with 4/4 empty fetches, and all 16 retested from another IP returned
# complete data (price, AUD, market cap, history) on the FIRST call — so the failure is
# transient and IP-scoped, not a property of the ticker or the exchange.
# The cost is bounded on purpose: every retry is paid only for a ticker that would
# otherwise have been discarded, but at ~76 throttled names a longer ladder would add
# more than the prefilter's 2h cap can absorb. If the cap starts binding, the answer is
# to stop the jobs competing for one IP's budget, not to shorten this.
THROTTLE_ATTEMPTS = 2
THROTTLE_BACKOFF_S = 15


def analyze(ticker: str, mode: str = "deep", use_fmp: bool = True) -> dict:
    log(f"Analyzing {ticker} (mode={mode})...")

    # A throttled yfinance answers with an EMPTY FRAME, not an error, so `safe()` cannot
    # see it and each fetch below merely looks "missing". Retrying is what separates a
    # throttle from a dead symbol. A fresh yf.Ticker per attempt is required: the old one
    # caches the empty frames it already received and would replay them for ever.
    for attempt in range(1, THROTTLE_ATTEMPTS + 1):
        tk = yf.Ticker(ticker)
        # Use short calls with generous fallbacks
        info = safe(lambda: tk.info, default={}) or {}
        bs = safe(lambda: tk.balance_sheet)
        fs = safe(lambda: tk.financials)
        cf = safe(lambda: tk.cashflow)
        hist = safe(lambda: tk.history(period="5y"), default=None)

        core_missing = core_fetches_missing(info, fs, bs, hist)
        if core_missing < CORE_MISSING_LIMIT or attempt == THROTTLE_ATTEMPTS:
            break
        log(f"  {ticker}: {core_missing}/4 core fetches empty — throttle? retrying in "
            f"{THROTTLE_BACKOFF_S}s (attempt {attempt}/{THROTTLE_ATTEMPTS})")
        time.sleep(THROTTLE_BACKOFF_S)

    warnings_ = []
    if not info:
        warnings_.append("yfinance info empty")
    if bs is None or bs.empty:
        warnings_.append("balance_sheet missing")
    if fs is None or fs.empty:
        warnings_.append("financials missing")
    if cf is None or cf.empty:
        warnings_.append("cashflow missing")

    # --- Throttle gate: refuse to score a ticker we have no data for ---
    # A rate-limited (HTTP 429) yfinance answers every call with an empty frame
    # rather than an error. Without this gate the run continues on nothing:
    # Piotroski scores 0, all 7 gates fail on None, peers/market default to a
    # neutral 5.0, and the composite lands ~1.0 -> a confident "reject" verdict
    # for a company that was never actually looked at (the 2026-07-31 PKO BP
    # incident). Layer 0 cannot catch it either — every HARD check is guarded on
    # non-None inputs, so a total blackout validates as "ok".
    # Raising here is the correct outcome and is already handled downstream:
    # main() turns it into {"error": ...} + exit 1, and run_prefilter.classify()
    # routes "error" to the RETRY bucket instead of evicting the ticker.
    # `core_missing` comes from the retry loop above — by the time we are here the
    # fetches have already been retried, so reaching this line means the blackout
    # survived a backoff and is worth reporting rather than retrying again.
    if core_missing >= CORE_MISSING_LIMIT:
        raise ThrottleSuspected(
            f"insufficient yfinance data for {ticker} "
            f"({core_missing}/4 core fetches empty after {THROTTLE_ATTEMPTS} attempts "
            f"— rate-limited?)"
        )

    # --- Basics ---
    price_curr = safe(lambda: info.get("currentPrice") or info.get("regularMarketPrice") or (hist["Close"].iloc[-1] if hist is not None and not hist.empty else None))

    # --- Phase 6: global-market metadata (suffix-driven currency/region/accounting) ---
    mkt_meta = markets.market_meta(ticker)
    # Prefer yfinance's reported currency; fall back to the suffix-derived one.
    # Warn (don't crash) when they disagree — a sign of an ADR / odd listing.
    currency = info.get("currency") or mkt_meta["currency"]
    if info.get("currency") and info["currency"].upper() != mkt_meta["currency"] and mkt_meta["known"]:
        warnings_.append(
            f"currency mismatch: yfinance reports {info['currency']} but "
            f"{mkt_meta['exchange']} ({ticker}) is normally {mkt_meta['currency']}"
        )

    # An ADR whose statements are filed in the home currency gets a USD market cap
    # divided by a home-currency revenue line, so every market-cap-over-statement
    # ratio comes out wrong by the FX rate. Measured on TSM 2026-07-27: P/S 0.46 vs
    # the Taiwan line's 13.72 — off by exactly 29.74x, the TWD/USD rate — and
    # EV/EBITDA 4.49 vs 18.41. Those "cheap" multiples then flattered the peer and
    # valuation sub-scores enough to score the ADR 8.14 against the same company's
    # 7.80 two days earlier. Preferring the home listing (listings.py) avoids this
    # for every mapped pair; this warning catches the ones not yet in the registry.
    _adr_hint = listings.adr_suspicion(ticker, info)
    if _adr_hint:
        warnings_.append(_adr_hint)
    if (info.get("financialCurrency") and info.get("currency")
            and info["financialCurrency"].upper() != info["currency"].upper()):
        warnings_.append(
            f"reporting currency {info['financialCurrency']} != trading currency "
            f"{info['currency']}: market-cap-derived ratios (P/S, EV/EBITDA, "
            f"EV/Revenue) mix the two and are NOT comparable to peers — "
            f"P/E, PEG, margins and ROE are computed within one currency and stay valid"
        )
    # GBp/GBX (LSE pence) -> GBP. London shares are quoted in pence (1/100 GBP).
    # yfinance is inconsistent: info["currency"] is sometimes the explicit "GBp"/
    # "GBX", but for many .L names it reports plain "GBP" while currentPrice /
    # marketCap are STILL in pence (e.g. SHEL.L ~3227.5 = £32.27). So treat any
    # .L line whose currency is in the GBP family as pence-quoted and collapse to
    # GBP, so the local->EUR path (EURGBP=X) isn't 100x too high. USD/EUR-
    # denominated .L lines report their own currency and are left untouched.
    lse_pence = (
        markets.suffix_of(ticker) == "L"
        and (currency or "").upper() in ("GBP", "GBX")
    ) or currency in ("GBp", "GBX")
    if lse_pence:
        price_curr, currency = markets.normalize_gbx(price_curr, "GBp")
    region = mkt_meta["region"]
    accounting_standard = mkt_meta["accounting_standard"]
    exchange_name = mkt_meta["exchange"]
    # Per-market accounting / coverage / liquidity caveats into data_warnings.
    for cav in markets.market_caveats(ticker):
        warnings_.append(cav)

    # --- Fundamentals from info + statements ---
    fund = {
        "market_cap": info.get("marketCap"),
        "enterprise_value": info.get("enterpriseValue"),
        "revenue_ttm": info.get("totalRevenue"),
        "ebitda_ttm": info.get("ebitda"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "peg": info.get("pegRatio") or info.get("trailingPegRatio"),
        "ps_ratio": info.get("priceToSalesTrailing12Months"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "ev_revenue": info.get("enterpriseToRevenue"),
        "roe_ttm": info.get("returnOnEquity"),
        "roa_ttm": info.get("returnOnAssets"),
        "net_margin_ttm": info.get("profitMargins"),
        "gross_margin_ttm": info.get("grossMargins"),
        "operating_margin_ttm": info.get("operatingMargins"),
        "debt_to_equity": (info["debtToEquity"] / 100.0) if info.get("debtToEquity") is not None else None,
        "total_debt": info.get("totalDebt"),
        "total_cash": info.get("totalCash"),
        "quick_ratio": info.get("quickRatio"),
        "current_ratio": info.get("currentRatio"),
        "fcf_ttm": info.get("freeCashflow"),
        "dividend_yield": info.get("dividendYield"),
        "dividend_rate": info.get("dividendRate"),
        "payout_ratio": info.get("payoutRatio"),
        "beta": info.get("beta"),
        "eps_ttm": info.get("trailingEps"),
        "book_value": info.get("bookValue"),
        "shares_out": info.get("sharesOutstanding"),
        "float_shares": info.get("floatShares"),
        "insider_pct_held": info.get("heldPercentInsiders"),
        "institutional_pct_held": info.get("heldPercentInstitutions"),
    }

    # --- Borja v2.1: net debt, net debt / EBITDA ---
    if fund["total_debt"] is not None and fund["total_cash"] is not None:
        fund["net_debt"] = fund["total_debt"] - fund["total_cash"]
    else:
        fund["net_debt"] = None
    if fund["net_debt"] is not None and fund["ebitda_ttm"] and fund["ebitda_ttm"] > 0:
        fund["net_debt_ebitda"] = fund["net_debt"] / fund["ebitda_ttm"]
    else:
        fund["net_debt_ebitda"] = None

    # FCF yield
    fund["fcf_yield"] = None
    if fund["fcf_ttm"] and fund["market_cap"] and fund["market_cap"] > 0:
        fund["fcf_yield"] = fund["fcf_ttm"] / fund["market_cap"]

    # Revenue CAGR — try annual financials first; tolerate NaN years and short series.
    # Falls back to income_stmt (newer yfinance API) then to info.revenueGrowth (YoY proxy).
    # Records actual basis so downstream scoring / report narrative can annotate it.
    fund["revenue_cagr_5y"] = None
    fund["revenue_cagr_basis"] = "unavailable"
    fund["eps_cagr_5y"] = None
    try:
        sources = []
        if fs is not None and not fs.empty:
            sources.append(("financials", fs))
        try:
            is_stmt = tk.income_stmt
            if is_stmt is not None and not is_stmt.empty:
                sources.append(("income_stmt", is_stmt))
        except Exception:
            pass
        for src_name, src in sources:
            label = next((l for l in ("Total Revenue", "Operating Revenue", "Revenue") if l in src.index), None)
            if not label:
                continue
            series = src.loc[label].dropna()
            if len(series) < 2:
                continue
            # Take the longest meaningful span (most recent → oldest available)
            rev_end = float(series.iloc[0])
            rev_start = float(series.iloc[-1])
            n_years = len(series) - 1
            v = cagr(rev_start, rev_end, n_years)
            if v is not None:
                fund["revenue_cagr_5y"] = v
                # Label by span: 5y / 4y / 3y / 2y_annual
                fund["revenue_cagr_basis"] = f"{n_years + 1}y_{src_name}" if n_years + 1 >= 3 else f"{n_years + 1}y_{src_name}_short"
                break
        # Last-resort fallback: yfinance YoY revenue growth (single year, low confidence)
        if fund["revenue_cagr_5y"] is None and info.get("revenueGrowth") is not None:
            fund["revenue_cagr_5y"] = float(info["revenueGrowth"])
            fund["revenue_cagr_basis"] = "1y_yoy_fallback"
    except Exception as e:
        warnings_.append(f"revenue_cagr calc: {e}")

    # 5y averages (+ v4 Phase B additive: net_margin_5y_min, eps_cagr_5y)
    fund["roe_5y_avg"] = None
    fund["net_margin_5y_avg"] = None
    fund["net_margin_5y_min"] = None
    try:
        if fs is not None and bs is not None and "Net Income" in fs.index:
            ni = fs.loc["Net Income"].dropna()
            rev = fs.loc["Total Revenue"].dropna() if "Total Revenue" in fs.index else None
            eq_label = "Stockholders Equity" if "Stockholders Equity" in bs.index else "Total Stockholder Equity"
            eq = bs.loc[eq_label].dropna() if eq_label in bs.index else None
            if eq is not None and len(eq) >= 2:
                roes = [float(ni.iloc[i]) / float(eq.iloc[i]) for i in range(min(len(ni), len(eq))) if eq.iloc[i] != 0]
                if roes:
                    fund["roe_5y_avg"] = statistics.mean(roes)
            if rev is not None:
                margins = [float(ni.iloc[i]) / float(rev.iloc[i]) for i in range(min(len(ni), len(rev))) if rev.iloc[i] != 0]
                if margins:
                    fund["net_margin_5y_avg"] = statistics.mean(margins)
                    fund["net_margin_5y_min"] = min(margins)
            # v4 Phase B: populate the long-standing eps_cagr_5y stub. EPS per
            # year = NI ÷ per-year Share Issued (falls back to current shares).
            # Same fetched statements — zero extra API calls. Columns are
            # most-recent-first, so CAGR runs oldest (iloc[-1]) → newest (iloc[0]).
            so_label = "Share Issued" if "Share Issued" in bs.index else ("Ordinary Shares Number" if "Ordinary Shares Number" in bs.index else None)
            so = bs.loc[so_label].dropna() if so_label else None
            if len(ni) >= 2:
                def _eps_at(i):
                    sh = float(so.iloc[i]) if (so is not None and i < len(so) and float(so.iloc[i]) > 0) else fund.get("shares_out")
                    return float(ni.iloc[i]) / sh if sh else None
                eps_new, eps_old = _eps_at(0), _eps_at(len(ni) - 1)
                v = cagr(eps_old, eps_new, len(ni) - 1)
                if v is not None and eps_new is not None and eps_new > 0:
                    fund["eps_cagr_5y"] = v
    except Exception as e:
        warnings_.append(f"5y avgs: {e}")

    # --- v2.2: Magic-Formula proxy — ROIC, EV/EBIT, ROCE from financials + balance sheet ---
    # ROIC  = NOPAT / Invested Capital; IC = Total Debt + Total Equity - Cash (compute_roic)
    # EV/EBIT = (market_cap + total_debt - cash) / EBIT (compute_ev_ebit)
    # ROCE  = EBIT / (Total Assets - Current Liabilities) (compute_roce)
    fund["roce_ttm"] = None
    fund["roic_ttm"] = None
    fund["ev_ebit"] = None
    try:
        ebit = None
        ta = None
        cl = None
        equity = None
        tax = None
        pretax = None
        if fs is not None and bs is not None and not fs.empty and not bs.empty:
            if "EBIT" in fs.index:
                ebit = float(fs.loc["EBIT"].iloc[0])
            elif "Operating Income" in fs.index:
                ebit = float(fs.loc["Operating Income"].iloc[0])
            ta = float(bs.loc["Total Assets"].iloc[0]) if "Total Assets" in bs.index else None
            cl_label = "Current Liabilities" if "Current Liabilities" in bs.index else ("Total Current Liabilities" if "Total Current Liabilities" in bs.index else None)
            cl = float(bs.loc[cl_label].iloc[0]) if cl_label else None
            eq_label = "Stockholders Equity" if "Stockholders Equity" in bs.index else ("Total Stockholder Equity" if "Total Stockholder Equity" in bs.index else None)
            equity = float(bs.loc[eq_label].iloc[0]) if eq_label else None
            if "Tax Provision" in fs.index:
                tax = float(fs.loc["Tax Provision"].iloc[0])
            if "Pretax Income" in fs.index:
                pretax = float(fs.loc["Pretax Income"].iloc[0])
        # ROIC uses balance-sheet Total Debt/Cash (more precise) falling back to info.
        bs_debt = fund.get("total_debt")
        bs_cash = fund.get("total_cash")
        fund["roce_ttm"] = compute_roce(ebit, ta, cl)
        fund["roic_ttm"] = compute_roic(ebit, tax, pretax, bs_debt, equity, bs_cash)
        fund["ev_ebit"] = compute_ev_ebit(fund.get("market_cap"), bs_debt, bs_cash, ebit)
    except Exception as e:
        warnings_.append(f"roce/roic/ev_ebit: {e}")

    # --- v2.2: FCF/revenue YoY (latest vs prior) — input to the Gate-5 growth bypass ---
    fund["fcf_rev_latest"] = None
    fund["fcf_rev_prior"] = None
    try:
        if cf is not None and fs is not None and "Free Cash Flow" in cf.index and "Total Revenue" in fs.index:
            fcfs = [float(x) for x in cf.loc["Free Cash Flow"].dropna().tolist()]
            revs = [float(x) for x in fs.loc["Total Revenue"].dropna().tolist()]
            if len(fcfs) >= 2 and len(revs) >= 2 and revs[0] > 0 and revs[1] > 0:
                fund["fcf_rev_latest"] = fcfs[0] / revs[0]
                fund["fcf_rev_prior"] = fcfs[1] / revs[1]
    except Exception:
        pass

    # --- Borja v2.1: 5y share-count delta (catches dilution / buyback) ---
    fund["shares_change_5y_pct"] = None
    try:
        if bs is not None and not bs.empty:
            so_label = "Share Issued" if "Share Issued" in bs.index else ("Ordinary Shares Number" if "Ordinary Shares Number" in bs.index else None)
            if so_label:
                series = bs.loc[so_label].dropna()
                if len(series) >= 2:
                    so_now = float(series.iloc[0])
                    so_then = float(series.iloc[-1])
                    if so_then > 0:
                        fund["shares_change_5y_pct"] = (so_now - so_then) / so_then
    except Exception:
        pass

    # Revenue stability (lower CoV = more stable; map to 0-1 score)
    fund["revenue_stability_0_1"] = None
    try:
        if fs is not None and "Total Revenue" in fs.index:
            revs = [float(x) for x in fs.loc["Total Revenue"].dropna().tolist() if x > 0]
            if len(revs) >= 3:
                mean = statistics.mean(revs)
                cov = statistics.pstdev(revs) / mean if mean > 0 else 1.0
                fund["revenue_stability_0_1"] = max(0, min(1, 1 - cov))
    except Exception:
        pass

    # --- Piotroski + Altman ---
    statements_incomplete = False
    if bs is not None and fs is not None and cf is not None and not any(x.empty for x in (bs, fs, cf)):
        fscore, fscore_components = piotroski_fscore(bs, fs, cf, info)
        zscore = altman_zscore(bs, fs, info)
    else:
        fscore, fscore_components = 0, {}
        zscore = None
        warnings_.append("piotroski/altman skipped (missing statements)")
        # This skip is itself a data-quality verdict, and a more honest one than any fetch count:
        # `cashflow` is NOT in the core_fetches_missing tally, yet losing it alone zeroes Piotroski
        # and voids Altman -- up to 6 of the 10 fundamentals points -- while every other signal
        # still looks healthy. A throttle hits sequential calls, so "info+bs+fs cached, cf+hist
        # empty" is the realistic partial signature and it scores core_missing = 1: no raise, no
        # suspect, `ok`. If this branch fired, the composite is already badly distorted, so the
        # flag cannot over-fire on a name the score is treating fairly.
        statements_incomplete = True

    # --- Gates ---
    gates_passed, gates_detail = evaluate_gates(fund)

    # --- Technical (1Y) ---
    tech = {}
    try:
        h1 = tk.history(period="1y")
        if not h1.empty:
            close = h1["Close"]
            tech["sma50"] = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
            tech["sma200"] = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
            tech["change_1y_pct"] = float((close.iloc[-1] / close.iloc[0] - 1) * 100)
            # RSI 14
            delta = close.diff()
            up = delta.clip(lower=0).rolling(14).mean()
            down = -delta.clip(upper=0).rolling(14).mean()
            rs = up / down
            tech["rsi_14"] = float(100 - (100 / (1 + rs.iloc[-1]))) if down.iloc[-1] and down.iloc[-1] > 0 else None
            # Max drawdown
            roll_max = close.cummax()
            dd = (close - roll_max) / roll_max
            tech["max_drawdown_1y_pct"] = float(dd.min() * 100)
    except Exception as e:
        warnings_.append(f"technical: {e}")

    # --- DCF (simple 5y FCF + terminal) ---
    # Skip entirely if base FCF is non-positive — projecting a negative number
    # as a flat annuity produces a meaningless negative intrinsic that misleads
    # readers even when flagged. Better to emit dcf_valid=false and let the
    # narrative handle the company with a qualitative note.
    dcf_intrinsic = None
    dcf_upside = None
    dcf_valid = False
    dcf_reason = None
    try:
        if cf is None or "Free Cash Flow" not in cf.index:
            dcf_reason = "FCF series unavailable"
        else:
            fcfs = [float(x) for x in cf.loc["Free Cash Flow"].dropna().tolist()[:5]]
            if not fcfs:
                dcf_reason = "no FCF data points"
            elif not fund["shares_out"]:
                dcf_reason = "shares outstanding unknown"
            elif fcfs[0] <= 0:
                dcf_reason = f"base FCF is non-positive ({fcfs[0]:.0f}) — capex / transition phase, DCF not meaningful"
            elif fund.get("fcf_ttm") is not None and fund["fcf_ttm"] <= 0:
                dcf_reason = (
                    f"annual FCF positive ({fcfs[0]:.0f}) but TTM FCF is negative ({fund['fcf_ttm']:.0f}) — "
                    f"company in transition; annual-based DCF unreliable"
                )
            else:
                base = fcfs[0]
                r = 0.10
                g = 0.025
                pv_5y = sum(base / ((1 + r) ** i) for i in range(1, 6))
                terminal = base * (1 + g) / (r - g) / ((1 + r) ** 5)
                ev = pv_5y + terminal
                dcf_intrinsic = ev / fund["shares_out"]
                if price_curr and price_curr > 0:
                    dcf_upside = (dcf_intrinsic - price_curr) / price_curr
                # Final sanity gate: |upside| > 70% usually means the model is
                # fighting a cyclical trough / peak, not a real mispricing.
                if dcf_upside is not None and abs(dcf_upside) > 0.70:
                    dcf_reason = (
                        f"DCF implies {dcf_upside*100:+.0f}% vs price — magnitude exceeds 70% sanity threshold, "
                        f"likely cyclical distortion in base FCF"
                    )
                else:
                    dcf_valid = True
    except Exception as e:
        warnings_.append(f"dcf: {e}")
        dcf_reason = f"exception: {type(e).__name__}"

    # --- Score components ---
    fund_score = score_fundamentals(fscore, gates_passed, zscore)
    moat_score, moat_details = score_moat(
        fund["roe_ttm"], fund["roe_5y_avg"], fund["net_margin_ttm"], fund["net_margin_5y_avg"]
    )
    # v2.2 Buffett opt-in: superior capital efficiency (ROIC>25%) lifts the moat
    # sub-score 1.25x (cap 10). Does NOT touch the top-level WEIGHTS_V2_DEEP.
    moat_score, buffett_applied = apply_buffett_moat(moat_score, fund.get("roic_ttm"))
    moat_details["buffett_moat_applied"] = buffett_applied
    moat_details["roic_ttm"] = fund.get("roic_ttm")
    # An invalid DCF must not feed the valuation sub-score — its upside is a
    # flagged distortion, not a signal (dcf_upside_pct stays in the JSON for context).
    val_score, val_details = score_valuation(
        fund["pe_ratio"], fund["peg"], fund["fcf_yield"],
        dcf_upside if dcf_valid else None, fund.get("ev_ebit")
    )
    category = lynch_category(fund["revenue_cagr_5y"], fund["roe_5y_avg"], fund["net_margin_5y_avg"])
    growth_score, growth_details = score_growth_durability(
        fund["revenue_cagr_5y"], fund["revenue_stability_0_1"], category
    )
    vix = fetch_vix()
    mkt_score, mkt_details = market_context_score(vix)
    peer_info = fetch_peer_ranking(ticker, info, fund)
    peer_score = peer_info["score_0_10"]
    if peer_info.get("peers_source") == "none":
        warnings_.append(
            "peer ranking: no peers configured for this industry/sector — "
            "score is a neutral 5.0 placeholder, not a real ranking"
        )

    component_scores = {
        "fundamentals": fund_score,
        "valuation": val_score,
        "moat": moat_score,
        "peer": peer_score,
        "growth_durability": growth_score,
        "market_context": mkt_score,
    }

    # Provisional composite — deep uses mgmt=5.0 placeholder; finalize_score.py
    # overwrites after Phase 2.5 supplies the real management score. Screen uses
    # the 6-component renormalised formula and never gets a management pass.
    composite = reweighted_composite(component_scores, mgmt=None, mode=mode)
    verdict = verdict_from_composite(composite)

    # Earnings
    earnings_next = None
    try:
        cal = tk.calendar
        if cal is not None and "Earnings Date" in (cal.index if hasattr(cal, "index") else cal):
            ed = cal.loc["Earnings Date"] if hasattr(cal, "loc") else cal.get("Earnings Date")
            if ed is not None:
                earnings_next = str(ed[0] if hasattr(ed, "__iter__") and not isinstance(ed, str) else ed)[:10]
    except Exception:
        pass

    # earnings_today flag — evaluating a ticker on earnings day means every
    # number is obsolete within hours. Caller (Phase 1 / SKILL.md) can re-pick.
    today = datetime.now(timezone.utc).date()
    today_iso = today.isoformat()
    earnings_today = bool(earnings_next and earnings_next[:10] == today_iso)

    # --- v2.2: news-event time decay overlay (UX/freshness, NO composite change) ---
    # I(t) = e^(-ln2/7 * dt); dt = days since the most recent PAST earnings date.
    # A stale earnings event visibly decays; surfaced in data_warnings when low.
    last_earnings_date = None
    try:
        ed_df = tk.earnings_dates  # includes recent past + upcoming
        if ed_df is not None and not ed_df.empty:
            # The index is tz-aware (exchange / US-Eastern). Take each timestamp's
            # OWN calendar date in its native tz (tz_localize(None) drops the tz
            # without shifting wall-clock) so we compare exchange-local dates, not
            # a UTC-shifted one — otherwise near midnight UTC the day-delta is off
            # by 1. We allow +1 day of slack vs the UTC `today` so a not-yet-past
            # (by exchange clock) event isn't excluded by tz skew.
            tomorrow = today + timedelta(days=1)

            def _native_date(ts):
                # Drop tz (if any) WITHOUT shifting wall-clock, then take the date.
                if getattr(ts, "tzinfo", None) is not None:
                    ts = ts.tz_localize(None)
                return ts.date()

            past = [d for d in (_native_date(ts) for ts in ed_df.index) if d <= tomorrow]
            if past:
                last_earnings_date = max(past)
    except Exception:
        pass
    news_freshness = None
    if last_earnings_date is not None:
        # Clamp at 0: tz skew can make a "today" earnings look 1 day in the future.
        days_since = max(0, (today - last_earnings_date).days)
        news_freshness = compute_news_freshness(days_since)
        if news_freshness is not None and news_freshness < 0.5:
            warnings_.append(
                f"news_freshness {news_freshness} — last earnings {last_earnings_date.isoformat()} "
                f"({days_since}d ago) is stale (>1 half-life); numbers may lag the next print"
            )

    # --- Borja v2.1 extractors (informational; do not feed composite score) ---
    shareholder_structure = compute_shareholder_structure(tk, info)
    capital_returns = compute_capital_returns(fund, cf)
    consensus = compute_consensus(tk)
    # v4 Phase C: persist a 2-year raw statement snapshot for red_flags.py
    # (pure JSON consumer, no re-fetch). Additive, overlay-only.
    statements_raw = extract_statement_rows(fs, bs, cf)
    # v4.3 R6: classify what basis the balance-sheet share count is on. Additive and
    # overlay-only -- the extracted number is NOT rewritten, so no published composite,
    # gate or verdict moves. Measured on 147 analyses: 86 agree with shares outstanding,
    # 61 do not, and they fail in three different ways that used to look like one.
    # See scripts/share_basis.py.
    try:
        statements_raw["balance"]["shares_basis"] = share_basis.classify(
            (statements_raw.get("balance", {}).get("shares") or [None])[0],
            fund.get("shares_out"),
        )
    except Exception as exc:                       # never fail an analysis over metadata
        log(f"share-basis classification skipped (non-fatal): {type(exc).__name__}: {exc}")

    # --- Phase 6: local -> EUR conversion (local currency + EUR everywhere) ---
    eur_rate = fetch_eur_rate(currency)
    price_eur = markets.to_eur(price_curr, currency, eur_rate)
    market_cap_eur = markets.to_eur(fund.get("market_cap"), currency, eur_rate)
    if eur_rate is None and (currency or "").upper() != "EUR":
        warnings_.append(f"EUR FX rate for {currency} unavailable — EUR figures omitted")

    # --- Price returns + report top-strip (reference already-computed fund /
    # capital_returns values; fcf_margin is the only new derivation here). ---
    price_returns = compute_price_returns(hist)

    def _pct(x, nd=2):
        return round(x * 100, nd) if isinstance(x, (int, float)) else None

    def _rnd(x, nd=2):
        return round(x, nd) if isinstance(x, (int, float)) else None

    fcf_margin_pct = None
    if fund.get("fcf_ttm") is not None and fund.get("revenue_ttm"):
        fcf_margin_pct = round(fund["fcf_ttm"] / fund["revenue_ttm"] * 100, 2)

    top_strip = {
        "pe_ttm": _rnd(fund.get("pe_ratio")),
        "forward_pe": _rnd(fund.get("forward_pe")),
        "revenue_cagr_5y_pct": _pct(fund.get("revenue_cagr_5y")),
        "fcf_margin_pct": fcf_margin_pct,
        "fcf_yield_pct": _pct(fund.get("fcf_yield")),
        "roe_ttm_pct": _pct(fund.get("roe_ttm")),
        "roic_pct": _pct(fund.get("roic_ttm")),
        "gross_margin_pct": _pct(fund.get("gross_margin_ttm")),
        "net_debt_ebitda": _rnd(fund.get("net_debt_ebitda")),
        "net_payout_yield_pct": _pct(capital_returns.get("net_payout_yield")),
        "price_return_1y_pct": price_returns["price_return_1y_pct"],
        "price_return_5y_pct": price_returns["price_return_5y_pct"],
        "price_return_5y_span": price_returns["price_return_5y_span"],
    }

    out = {
        "ticker": ticker,
        "mode": mode,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "company_name": info.get("longName") or info.get("shortName") or ticker,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": currency,
        "region": region,
        "exchange": exchange_name,
        "accounting_standard": accounting_standard,
        "eur_rate_local_per_eur": eur_rate,
        "price_current": price_curr,
        "price_current_eur": price_eur,
        "market_cap_eur": market_cap_eur,
        "price_return_1y_pct": price_returns["price_return_1y_pct"],
        "price_return_5y_pct": price_returns["price_return_5y_pct"],
        "price_return_5y_span": price_returns["price_return_5y_span"],
        "top_strip": top_strip,
        "fundamentals": fund,
        "technical": tech,
        "piotroski_fscore": fscore,
        "piotroski_components": fscore_components,
        "altman_zscore": zscore,
        "gates_passed": gates_passed,
        "gates_detail": gates_detail,
        "lynch_category": category,
        "dcf_intrinsic": dcf_intrinsic,
        "dcf_upside_pct": dcf_upside,
        "dcf_valid": dcf_valid,
        "dcf_reason": dcf_reason,
        "vix": vix,
        "earnings_date_next": earnings_next,
        "earnings_today": earnings_today,
        "last_earnings_date": last_earnings_date.isoformat() if last_earnings_date else None,
        "news_freshness": news_freshness,
        "management_score": None,   # filled by Phase 2.5 LLM pass; deep only
        "management_flag": False,   # set true by finalize_score.py if mgmt<7 and mode==deep
        "shareholder_structure": shareholder_structure,
        "capital_returns": capital_returns,
        "statements_raw": statements_raw,
        "consensus": consensus,
        "schema_version": "2.2",
        "weights": WEIGHTS_V2_DEEP,
        "scores": {
            "fundamentals": fund_score,
            "valuation": val_score,
            "moat": moat_score,
            "peer": peer_score,
            "growth_durability": growth_score,
            "market_context": mkt_score,
            "management": None,     # placeholder; provisional composite uses 5.0
            "composite": composite,
            "composite_is_provisional": mode == "deep",
        },
        "score_details": {
            "moat": moat_details,
            "valuation": val_details,
            "growth": growth_details,
            "market_context": mkt_details,
            "peer_info": peer_info,
        },
        "verdict": verdict,
        "data_source": "yfinance",
        "data_warnings": warnings_,
    }

    # --- Layer 2: reconcile price/market_cap vs history() and self-heal (free) ---
    # For LSE pence names price_current is already in GBP but history() Close is
    # still in GBp; scale the history side by 0.01 so the two are comparable.
    corrected_fields = reconcile_price_with_history(out, hist, price_scale=0.01 if lse_pence else 1.0)
    out["corrected_fields"] = corrected_fields
    for c in corrected_fields:
        warnings_.append(
            f"corrected: {c['field']} {c['old']} -> {c['new']} ({c['source']})"
        )
    # Recompute EUR figures off the (possibly self-healed) price/market_cap.
    if corrected_fields and eur_rate is not None:
        out["price_current_eur"] = markets.to_eur(out.get("price_current"), currency, eur_rate)
        out["market_cap_eur"] = markets.to_eur(
            out.get("fundamentals", {}).get("market_cap"), currency, eur_rate
        )

    # --- Layer 0: internal-consistency gate on the (possibly corrected) data ---
    consistency_issues, data_quality = validate_consistency(out)
    out["consistency_issues"] = consistency_issues
    for msg in consistency_issues:
        warnings_.append(f"consistency: {msg}")
    # data_quality precedence: suspect (unfixable) > corrected (self-healed) > ok
    if data_quality == "suspect":
        out["data_quality"] = "suspect"
    elif corrected_fields:
        out["data_quality"] = "corrected"
    else:
        out["data_quality"] = "ok"

    # A PARTIAL blackout survives the throttle gate above but still means we
    # scored on holes: Layer 0's HARD checks all no-op on None inputs, so
    # nothing else downstream would ever mark it. Publish the count so the
    # prefilter and the SKILL.md downshift rule can see it.
    out["core_fetches_missing"] = core_missing
    if core_missing >= 2 and out["data_quality"] != "suspect":
        out["data_quality"] = "suspect"
        warnings_.append(
            f"consistency: {core_missing}/4 core yfinance fetches empty "
            f"— scored on partial data"
        )
    if statements_incomplete and out["data_quality"] != "suspect":
        out["data_quality"] = "suspect"
        warnings_.append(
            "consistency: Piotroski/Altman skipped for missing statements "
            "— up to 6 of 10 fundamentals points are absent, not earned"
        )

    # --- Layer 1: external cross-validation — FMP (US) → Twelve Data (EU) ---
    if use_fmp:
        xval = fetch_external_validation(ticker, fund, price_curr)
        out["cross_validation"] = xval
        prov = xval.get("provider", "?")
        for d in xval.get("divergences", []):
            warnings_.append(f"{prov}-divergence: {d}")
        # An external source disagreeing on price/market_cap means the data is
        # suspect even if internal checks passed (e.g. both yfinance fields
        # stale-but-consistent). This is the independent confirmation.
        if any(d.startswith(("price", "market_cap")) for d in xval.get("divergences", [])):
            out["data_quality"] = "suspect"
    else:
        out["cross_validation"] = {"provider": "skipped"}

    return out


def validate_consistency(out: dict) -> tuple[list[str], str]:
    """Layer 0 — internal-consistency gate (free, no second API).

    Catches the gross yfinance errors that are detectable from the data itself:
    stale price (vs SMA), market-cap not matching price×shares, and a P/E that
    can't be reconciled with P/S and net margin. Returns (issues, quality) where
    quality is 'ok' or 'suspect'. 'suspect' means at least one HARD check failed.
    """
    issues: list[str] = []
    f = out.get("fundamentals", {}) or {}
    tech = out.get("technical", {}) or {}
    price = out.get("price_current")

    def num(x):
        return x if isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x)) else None

    price = num(price)
    sma50 = num(tech.get("sma50"))
    mktcap = num(f.get("market_cap"))
    shares = num(f.get("shares_out"))
    pe = num(f.get("pe_ratio"))
    fwd_pe = num(f.get("forward_pe"))
    ps = num(f.get("ps_ratio"))
    net_margin = num(f.get("net_margin_ttm"))

    # HARD 1 — price vs 50-day SMA. A live price should track its own SMA50
    # within tolerance; a >40% gap means the price field is stale/wrong.
    if price and sma50 and sma50 > 0:
        dev = abs(price / sma50 - 1)
        if dev > 0.40:
            issues.append(
                f"price {price:g} deviates {dev*100:.0f}% from SMA50 {sma50:g} "
                f"— price field likely stale/wrong"
            )

    # HARD 2 — market cap must equal price × shares outstanding.
    if mktcap and price and shares and shares > 0:
        implied = price * shares
        if implied > 0 and abs(mktcap - implied) / max(mktcap, implied) > 0.10:
            issues.append(
                f"market_cap {mktcap:,.0f} != price×shares {implied:,.0f} "
                f"— market_cap or shares_out is stale"
            )

    # HARD 3 — P/E must reconcile with P/S ÷ net margin (mktcap/NI identity).
    if pe and pe > 0 and ps and ps > 0 and net_margin and net_margin > 0:
        implied_pe = ps / net_margin
        if implied_pe > 0 and abs(pe - implied_pe) / pe > 0.50:
            issues.append(
                f"P/E {pe:.1f} inconsistent with P/S÷net_margin (implies {implied_pe:.1f}) "
                f"— net_margin_ttm or pe_ratio is distorted"
            )

    quality = "suspect" if issues else "ok"

    # SOFT — trailing vs forward P/E divergence: not an error, but flags a
    # cyclical-trough / one-off distortion in trailing earnings (context only).
    if pe and pe > 0 and fwd_pe and fwd_pe > 0 and pe / fwd_pe > 3.0:
        issues.append(
            f"(soft) trailing P/E {pe:.0f} >> forward P/E {fwd_pe:.0f} "
            f"— trailing earnings likely depressed (cyclical trough / one-off)"
        )

    return issues, quality


def reconcile_price_with_history(out: dict, hist, price_scale: float = 1.0) -> list[dict]:
    """Layer 2 — reconcile the info-derived price against history() and self-heal.

    yfinance's `Ticker.info` price (currentPrice/regularMarketPrice) and
    `fast_info.last_price` can be grossly stale on thin EU listings (e.g. CMO.MC
    returned €8.49 while history()'s last close was the correct €38). The
    history() endpoint is a *different, more reliable* yfinance data path — and
    it works for every exchange, including the Iberian small/mid-caps that NO
    free quote API covers (FMP/Polygon/Finnhub = US-only; Stooq = blocked).

    When info-price and the last history close diverge >10%, the history close
    wins: this corrects price_current and recomputes market_cap (= close×shares)
    when the cap is also inconsistent. Returns a list of corrected-field records.

    `price_scale` rescales the raw history close before comparison (and before it
    overwrites price_current). For LSE pence-quoted names history()'s Close is in
    GBp like the quote, while out["price_current"] has already been collapsed to
    GBP — passing price_scale=0.01 keeps the comparison like-for-like so this
    layer doesn't "self-heal" the GBP price back into pence.
    """
    corrected: list[dict] = []
    try:
        if hist is None or getattr(hist, "empty", True):
            return corrected
        hist_close = float(hist["Close"].iloc[-1]) * price_scale
    except Exception:
        return corrected
    if not (isinstance(hist_close, (int, float)) and hist_close > 0):
        return corrected

    price = out.get("price_current")
    if isinstance(price, (int, float)) and price > 0:
        if abs(price / hist_close - 1) > 0.10:
            out["price_current"] = round(hist_close, 4)
            corrected.append({
                "field": "price_current", "old": price, "new": round(hist_close, 4),
                "source": "yfinance.history (info price stale)",
            })
            # If the cap was built off the stale price, recompute it from shares.
            f = out.get("fundamentals", {}) or {}
            shares = f.get("shares_out")
            cap = f.get("market_cap")
            if isinstance(shares, (int, float)) and shares > 0:
                new_cap = hist_close * shares
                if not isinstance(cap, (int, float)) or cap <= 0 or abs(cap - new_cap) / new_cap > 0.10:
                    f["market_cap"] = round(new_cap)
                    corrected.append({
                        "field": "fundamentals.market_cap", "old": cap, "new": round(new_cap),
                        "source": "recomputed = history_close × shares_out",
                    })
    return corrected


def fetch_fmp_validation(ticker: str, fund: dict, price_curr) -> dict:
    """Layer 1 — cross-validate core fields against Financial Modeling Prep.

    Uses the FMP key already in BD_Finance/config/api_keys.txt. Best-effort and
    fully non-fatal: any failure (no key, no coverage, network) returns a result
    with an 'error' field and empty divergences. FMP has better EU small/mid-cap
    coverage than Polygon/Finnhub free tiers, which is exactly where yfinance
    breaks (.MC/.LS/.PA/.DE).
    """
    result = {"source": "fmp", "checked": [], "divergences": [], "agree": None, "error": None}
    try:
        import requests
        try:
            from api_keys_reader import api_keys_reader
            keys = api_keys_reader(str(BD_FINANCE / "config" / "api_keys.txt"))
            key = keys.get("api_key_financialmodelingprep")
        except Exception as e:
            result["error"] = f"key read failed: {type(e).__name__}: {e}"
            return result
        if not key or not str(key).strip():
            result["error"] = "no FMP key configured"
            return result

        # FMP retired the legacy /api/v3/ endpoints (403) — use the /stable/ API.
        url = f"https://financialmodelingprep.com/stable/quote?symbol={ticker}&apikey={str(key).strip()}"
        r = requests.get(url, timeout=12)
        if r.status_code in (402, 403):
            # 402/403 on the stable endpoint = ticker outside the free-tier
            # coverage (FMP free is US-centric; EU exchanges like .MC/.LS need a
            # paid plan). Not an error in the data — just no cross-check available.
            result["error"] = f"FMP free tier: no coverage for {ticker} (HTTP {r.status_code})"
            return result
        if r.status_code != 200:
            result["error"] = f"FMP HTTP {r.status_code}"
            return result
        data = r.json()
        if not isinstance(data, list) or not data:
            result["error"] = "FMP empty (likely no coverage for this ticker)"
            return result
        q = data[0]
        fmp_price = q.get("price")
        fmp_mktcap = q.get("marketCap")
        fmp_pe = q.get("pe")
        result["fmp_price"] = fmp_price
        result["fmp_market_cap"] = fmp_mktcap
        result["fmp_pe"] = fmp_pe

        def diverge(name, a, b, tol):
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a and b:
                d = abs(a - b) / max(abs(a), abs(b))
                result["checked"].append(name)
                if d > tol:
                    result["divergences"].append(
                        f"{name}: yfinance {a:g} vs FMP {b:g} ({d*100:.0f}% apart)"
                    )

        diverge("price", price_curr, fmp_price, 0.15)
        diverge("market_cap", fund.get("market_cap"), fmp_mktcap, 0.20)
        diverge("pe_ratio", fund.get("pe_ratio"), fmp_pe, 0.25)
        result["agree"] = len(result["divergences"]) == 0 and len(result["checked"]) > 0
        return result
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        return result


# Yahoo suffix -> Twelve Data `country` param. TD addresses non-US listings by
# base symbol + country (not by Yahoo's exchange suffix). US tickers (no suffix)
# need no country param. Covers the suffixes seen in the user's portfolio.
_TD_COUNTRY_BY_SUFFIX = {
    "MC": "Spain", "LS": "Portugal", "AS": "Netherlands", "PA": "France",
    "DE": "Germany", "F": "Germany", "MI": "Italy", "L": "United Kingdom",
    "IR": "Ireland", "ST": "Sweden", "CO": "Denmark", "HE": "Finland",
    "OL": "Norway", "VI": "Austria", "BR": "Belgium", "Lport": "Portugal",
    "HK": "Hong Kong", "TW": "Taiwan", "T": "Japan", "KS": "South Korea",
    "SS": "China", "SZ": "China", "NS": "India", "TO": "Canada", "SW": "Switzerland",
}


# Roadmap R4, closed by the v4.3 §3.1 audit. Twelve Data resolves `ADS.DE` on the free
# tier but answers from **XSTU (Stuttgart)**, a thin secondary venue — not Xetra. On
# 2026-07-30 it returned a stale EUR182.25 while Xetra had gapped −18% on earnings, and
# the system recorded that as a yfinance `data_quality: suspect` flag. THE REFERENCE PRICE
# WAS WRONG, NOT THE DATA BEING CHECKED. `td_exchange` was already captured and simply
# never read.
#
# The map is deliberately partial and the default is SILENCE. Naming a venue this table
# does not know as a "mismatch" would manufacture exactly the false flag being fixed, so
# an unrecognised venue yields `None` and the comparison proceeds unchanged.
_TD_VENUE_ALIASES = {
    # Twelve Data spelling -> canonical venue token
    "NYSE": "US", "NASDAQ": "US", "NYSE American": "US", "OTC": "US",
    "XETRA": "XETRA", "FSX": "FRANKFURT", "Frankfurt": "FRANKFURT",
    "XSTU": "STUTTGART", "Stuttgart": "STUTTGART", "Berlin": "BERLIN",
    "Munich": "MUNICH", "Dusseldorf": "DUSSELDORF", "Hamburg": "HAMBURG",
    "Euronext": "EURONEXT", "Euronext Amsterdam": "EURONEXT",
    "Euronext Paris": "EURONEXT", "Euronext Lisbon": "EURONEXT",
    "LSE": "LONDON", "London Stock Exchange": "LONDON",
    "BME": "MADRID", "MTA": "MILAN", "SIX": "SWISS",
}
# The venue the Yahoo suffix denotes. Derived from the suffix rather than from the
# analysis JSON's prose `exchange` string, so the check has no dependency on a field this
# function is not given.
_SUFFIX_VENUE = {
    "": "US", "DE": "XETRA", "AS": "EURONEXT", "PA": "EURONEXT", "LS": "EURONEXT",
    "BR": "EURONEXT", "L": "LONDON", "MC": "MADRID", "MI": "MILAN", "SW": "SWISS",
}


def venue_mismatch(td_exchange, suffix) -> str | None:
    """Named venue conflict, or None when either side is unknown (R4).

    Returns a sentence when BOTH venues resolve to canonical tokens and those tokens
    differ. Anything else — an unmapped spelling, a suffix not in the table — returns
    None, because the cost of a FALSE venue flag is another wrong `data_quality: suspect`,
    which is the defect this closes.
    """
    if suffix is None:
        return None  # "" means a US listing; None means we were told nothing
    a = _TD_VENUE_ALIASES.get((td_exchange or "").strip())
    b = _SUFFIX_VENUE.get(suffix.strip())
    if not a or not b or a == b:
        return None
    return (f"venue mismatch: Twelve Data quoted {td_exchange} ({a}) while the listing "
            f"trades on {b} — a cross-venue gap, not a data error")


def fetch_twelvedata_validation(ticker: str, fund: dict, price_curr) -> dict:
    """Layer 1b — external price cross-check via Twelve Data (EU-capable).

    Unlike FMP/Polygon/Finnhub free tiers (US-only), Twelve Data's free plan
    (800 req/day, 8/min) covers Euronext, BME large-caps, Frankfurt, LSE, etc.
    Independent of yfinance, so it can confirm/contradict the price even when
    BOTH yfinance endpoints agree. Key: api_key_twelvedata in api_keys.txt.
    Coverage isn't total (e.g. Cementos Molins / some Iberian small-caps are
    absent) — those degrade to 'no coverage' and Layers 0+2 carry them.
    """
    result = {"source": "twelvedata", "checked": [], "divergences": [], "agree": None, "error": None}
    try:
        import requests
        try:
            from api_keys_reader import api_keys_reader
            keys = api_keys_reader(str(BD_FINANCE / "config" / "api_keys.txt"))
            key = keys.get("api_key_twelvedata")
        except Exception as e:
            result["error"] = f"key read failed: {type(e).__name__}: {e}"
            return result
        if not key or not str(key).strip():
            result["error"] = "no Twelve Data key configured"
            return result

        # Map Yahoo ticker -> TD (base symbol, optional country).
        base, _, suffix = ticker.rpartition(".")
        if base:
            symbol = base
            country = _TD_COUNTRY_BY_SUFFIX.get(suffix)
        else:
            symbol, country = ticker, None  # US listing
        params = {"symbol": symbol, "apikey": str(key).strip()}
        if country:
            params["country"] = country

        r = requests.get("https://api.twelvedata.com/quote", params=params, timeout=12)
        # TD FREE plan only serves US quotes; EU/intl symbols 404 with a
        # "available starting with the Grow or Venture plan" message. Treat that
        # as "no coverage on this plan" so the log is clear (and EU validation
        # auto-activates if the plan is ever upgraded — no code change needed).
        try:
            q = r.json()
        except Exception:
            result["error"] = f"TD HTTP {r.status_code} (non-JSON)"
            return result
        if isinstance(q, dict) and q.get("status") == "error":
            msg = str(q.get("message", ""))
            if "plan" in msg.lower():
                result["error"] = f"TD free plan: no coverage for {ticker} (EU/intl needs paid plan)"
            else:
                result["error"] = f"TD no coverage for {ticker} ({msg[:80]})"
            return result
        if r.status_code != 200 or not isinstance(q, dict) or "close" not in q:
            result["error"] = f"TD HTTP {r.status_code} / no close field"
            return result
        try:
            td_price = float(q.get("close"))
        except (TypeError, ValueError):
            result["error"] = "TD close not numeric"
            return result
        result["td_price"] = td_price
        result["td_name"] = q.get("name")
        result["td_exchange"] = q.get("exchange")

        if isinstance(price_curr, (int, float)) and price_curr and td_price:
            d = abs(price_curr - td_price) / max(abs(price_curr), abs(td_price))
            result["checked"].append("price")
            if d > 0.15:
                # R4: a gap between two DIFFERENT VENUES is not evidence that either
                # quote is wrong. Named as such it stops being a data-quality flag.
                vm = venue_mismatch(result.get("td_exchange"), suffix if base else "")
                result["venue_mismatch"] = vm
                msg = (f"price: yfinance {price_curr:g} vs TwelveData {td_price:g} "
                       f"({d*100:.0f}% apart)")
                if vm:
                    result["venue_notes"] = [f"{msg} — {vm}"]
                else:
                    result["divergences"].append(msg)
        result["agree"] = len(result["divergences"]) == 0 and len(result["checked"]) > 0
        return result
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        return result


def fetch_external_validation(ticker: str, fund: dict, price_curr) -> dict:
    """Orchestrate the external cross-checks: FMP first (best for US fundamentals),
    fall back to Twelve Data (EU-capable), then Stooq EOD price (Finding D2 —
    free global price cross-check for non-US names, no API key). Returns a single
    unified dict with a `provider` field naming who actually validated.

    Stooq closes the EU/Asia price-validation gap that FMP (US-only free) and
    Twelve Data (gated EU coverage) leave open — it serves Taiwan/HK/Korea/Japan/
    India/China EOD via the CSV endpoint, which is NOT JS-blocked (only the
    interactive stooq.com site is). Price/market-cap only — Stooq has no
    fundamentals. For US names FMP already covers price+P/E, so Stooq is reserved
    as the non-US fallback to avoid a redundant request on the daily path."""
    fmp = fetch_fmp_validation(ticker, fund, price_curr)
    if fmp.get("checked"):
        fmp["provider"] = "fmp"
        return fmp
    td = fetch_twelvedata_validation(ticker, fund, price_curr)
    if td.get("checked"):
        td["provider"] = "twelvedata"
        td["fmp_note"] = fmp.get("error")
        return td
    # Stooq EOD price fallback (non-US: anything with a Yahoo suffix).
    stooq_note = None
    if markets.suffix_of(ticker):
        stq = markets.stooq_price_check(ticker, price_curr)
        if stq.get("checked"):
            stq["provider"] = "stooq"
            stq["fmp_note"] = fmp.get("error")
            stq["twelvedata_note"] = td.get("error")
            return stq
        stooq_note = stq.get("error")
    return {
        "provider": "none", "checked": [], "divergences": [], "agree": None,
        "error": f"FMP: {fmp.get('error')} | TwelveData: {td.get('error')}"
                 + (f" | Stooq: {stooq_note}" if stooq_note else ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--mode", default="deep", choices=["deep", "screen"])
    ap.add_argument("--no-fmp", "--no-xval", dest="no_fmp", action="store_true",
                    help="Skip external cross-validation (FMP + Twelve Data, Layer 1)")
    args = ap.parse_args()

    try:
        result = analyze(args.ticker, args.mode, use_fmp=not args.no_fmp)
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        print(json.dumps({"ticker": args.ticker, "error": str(e), "error_type": type(e).__name__}))
        return 1

    # JSON can contain nan/inf; convert to None
    def clean(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, list):
            return [clean(x) for x in v]
        return v

    print(json.dumps(clean(result), indent=2, ensure_ascii=False, default=str))
    log(f"OK {args.ticker}: score={result['scores']['composite']}, verdict={result['verdict']}, gates={result['gates_passed']}/7")
    return 0


if __name__ == "__main__":
    sys.exit(main())
