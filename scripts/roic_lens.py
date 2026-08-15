"""roic_lens.py — which return metric applies, and what it is saying (v4.3 wave 3.6).

The system computes ROIC and ROE and uses both. It has never had a WRITTEN RULE for when
each applies, and the two answer different questions: ROE is the return to EQUITY holders
and is inflated by leverage; ROIC is the return on ALL invested capital and is
leverage-neutral. A 25 % ROE on a balance sheet levered 3:1 with a 9 % ROIC is a
financing artefact, and the moat sub-score should not read it as a moat. `docs/ROIC_vs_ROE.md`
publishes the doctrine; this module enforces it so the doc cannot quietly rot.

FOUR RULES, all deterministic and all derived from data already persisted:

 1. LEVERAGE-MANUFACTURED ROE. ROE > 20 % AND D/E > 1.0 AND ROIC < 12 % → flagged, with
    all three numbers shown. It is not a veto and it does not touch the composite; it is
    the sentence a reader needs before treating a high ROE as evidence of quality.

 2. ROIC vs WACC is the economic-value test — a business earning below its cost of
    capital destroys value while growing. `intrinsic_value.capm.cost_of_equity` already
    exists; the cost of debt is derived from interest expense over average debt, and the
    tax rate from the income statement, using the SAME [0, 0.35] clamp
    `analyze_ticker.compute_roic` uses, so the two never disagree about the same company.

 3. ROIC IS DELIBERATELY None FOR NET-CASH BALANCE SHEETS. The v4.2 guard
    (`analyze_ticker.py`, `IC_MIN_FRACTION = 0.05`) returns None once subtracting cash
    has hollowed invested capital below 5 % of the gross base — VEEV printed ROIC
    13,671 % on a company earning ROE 13.9 %. The consequence is undocumented and matters:
    the Buffett moat multiplier is keyed on ROIC > 25 %, so for those names it SILENTLY
    DOES NOT FIRE. Correct, and invisible. This module says so out loud.

 4. FOR BANKS AND INSURERS ROIC IS NOT MEANINGFUL — debt is raw material, not financing.
    ROE, and ROTE where tangible equity is derivable, is the right metric. INGA.AS is in
    the portfolio today, so this is a live case and not a hypothetical.

Plus capital intensity: for asset-light balance sheets ROIC is distorted by near-zero
invested capital and by acquired intangibles, so ROIC-ex-goodwill is reported beside
ROIC and the block states WHICH ONE it is quoting.

Overlay-only, pure stdlib, no network. Nothing here changes `scores`, the gates or the
verdict — it changes what the reader is told the numbers mean.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# --- published thresholds (docs/ROIC_vs_ROE.md) -----------------------------
LEV_ROE_MIN = 0.20            # "high" ROE
LEV_DE_MIN = 1.0              # levered
LEV_ROIC_MAX = 0.12           # but the underlying business does not earn it
BUFFETT_ROIC_GATE = 0.25      # the existing moat multiplier's trigger
WACC_MARGIN = 0.02            # spread inside ±2pp is "marginal", not a verdict
TAX_CLAMP = (0.0, 0.35)       # identical to analyze_ticker.compute_roic
DEFAULT_TAX = 0.21
KD_PLAUSIBLE = (0.0, 0.25)    # a derived cost of debt outside this is a bad row, not a rate
ASSET_LIGHT_PPE_SHARE = 0.15  # net PP&E / total assets below this = asset-light
GOODWILL_HEAVY_SHARE = 0.30   # goodwill+intangibles / equity above this distorts ROIC

# yfinance sector string, plus industry substrings for the cases it buckets oddly.
FINANCIAL_SECTORS = {"financial services", "financials", "financial"}
FINANCIAL_INDUSTRY_HINTS = ("bank", "insurance", "insurer", "capital markets",
                            "asset management", "credit services", "mortgage")


def log(msg: str) -> None:
    print(f"[roic_lens] {msg}", file=sys.stderr)


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    if isinstance(v, str):
        try:
            f = float(v.strip())
        except ValueError:
            return None
        return None if math.isnan(f) else f
    return None


def _first(seq):
    if isinstance(seq, (list, tuple)) and seq:
        return _num(seq[0])
    return _num(seq)


def _pair(seq):
    if isinstance(seq, (list, tuple)):
        return [_num(x) for x in (list(seq) + [None, None])[:2]]
    return [_num(seq), None]


def is_financial(sector: str | None, industry: str | None) -> bool:
    if (sector or "").strip().lower() in FINANCIAL_SECTORS:
        return True
    ind = (industry or "").strip().lower()
    return any(h in ind for h in FINANCIAL_INDUSTRY_HINTS)


def effective_tax_rate(income: dict) -> tuple[float, str]:
    """(rate, provenance). Clamped exactly as compute_roic clamps it, so one company
    never carries two different tax rates in one report."""
    pretax = _first(income.get("pretax_income"))
    ni = _first(income.get("net_income"))
    if pretax and pretax > 0 and ni is not None:
        rate = 1.0 - (ni / pretax)
        return max(TAX_CLAMP[0], min(TAX_CLAMP[1], rate)), "income statement"
    return DEFAULT_TAX, "default 21% (pretax income unavailable)"


def cost_of_debt(income: dict, balance: dict) -> tuple[float | None, str]:
    """Interest expense over AVERAGE gross debt. Average, because a company that
    refinanced mid-year carries a year-end debt figure the interest never applied to."""
    interest = _first(income.get("interest_expense"))
    debt_now, debt_prior = _pair(balance.get("total_debt"))
    if interest is None:
        return None, "interest expense row absent"
    pool = [d for d in (debt_now, debt_prior) if d not in (None, 0)]
    if not pool:
        return None, "total debt row absent"
    avg = sum(pool) / len(pool)
    if avg <= 0:
        return None, "no gross debt"
    kd = abs(interest) / avg
    if not (KD_PLAUSIBLE[0] <= kd <= KD_PLAUSIBLE[1]):
        return None, (f"derived cost of debt {kd:.1%} is outside {KD_PLAUSIBLE[0]:.0%}"
                      f"-{KD_PLAUSIBLE[1]:.0%} — the interest or debt row is not what it "
                      f"claims to be")
    return round(kd, 6), "interest expense / average gross debt"


def compute_wacc(analysis: dict) -> dict:
    """WACC from the CAPM cost of equity already in the JSON plus a derived cost of debt.

    No cost of equity → no WACC. The alternative (assume one) would put an invented
    discount rate behind a value-creation verdict, which is precisely the failure mode
    roadmap N4 records for the DCF.
    """
    out = {"value": None, "cost_of_equity": None, "cost_of_debt": None,
           "tax_rate": None, "weight_equity": None, "notes": []}
    fund = analysis.get("fundamentals") or {}
    stmts = analysis.get("statements_raw") or {}
    income = stmts.get("income") or {}
    balance = stmts.get("balance") or {}

    ke = _num((((analysis.get("intrinsic_value") or {}).get("capm")) or {}
               ).get("cost_of_equity"))
    if ke is None:
        out["notes"].append("no CAPM cost of equity in the JSON — WACC not computed "
                            "rather than assumed")
        return out
    out["cost_of_equity"] = ke

    tax, tax_src = effective_tax_rate(income)
    out["tax_rate"] = round(tax, 4)
    out["notes"].append(f"tax rate from {tax_src}")

    equity_mv = _num(fund.get("market_cap"))
    debt = _num(fund.get("total_debt")) or _first(balance.get("total_debt"))
    if equity_mv is None or equity_mv <= 0:
        out["notes"].append("no market capitalisation — WACC not computed")
        return out
    if not debt:
        out["value"] = round(ke, 6)
        out["weight_equity"] = 1.0
        out["notes"].append("no gross debt — WACC is the cost of equity")
        return out

    kd, kd_src = cost_of_debt(income, balance)
    if kd is None:
        out["notes"].append(f"cost of debt not derivable ({kd_src}) — WACC not computed")
        return out
    out["cost_of_debt"] = kd
    out["notes"].append(f"cost of debt from {kd_src}")
    we = equity_mv / (equity_mv + debt)
    out["weight_equity"] = round(we, 4)
    out["value"] = round(ke * we + kd * (1 - tax) * (1 - we), 6)
    return out


def tangible_equity(balance: dict) -> tuple[float | None, float | None]:
    """(tangible equity, goodwill+intangibles). The combined row wins when present, so an
    acquisitive balance sheet's largest line is never counted twice."""
    equity = _first(balance.get("stockholders_equity"))
    combined = _first(balance.get("goodwill_and_intangibles"))
    if combined is None:
        gw = _first(balance.get("goodwill"))
        it = _first(balance.get("intangibles"))
        combined = None if (gw is None and it is None) else (gw or 0.0) + (it or 0.0)
    if equity is None:
        return None, combined
    if combined is None:
        nta = _first(balance.get("net_tangible_assets"))
        return (nta, None) if nta is not None else (None, None)
    return equity - combined, combined


def compute(analysis: dict) -> dict:
    fund = analysis.get("fundamentals") or {}
    stmts = analysis.get("statements_raw") or {}
    income = stmts.get("income") or {}
    balance = stmts.get("balance") or {}

    roic = _num(fund.get("roic_ttm"))
    roe = _num(fund.get("roe_ttm"))
    roe_5y = _num(fund.get("roe_5y_avg"))
    roce = _num(fund.get("roce_ttm"))
    de = _num(fund.get("debt_to_equity"))

    out = {
        "schema": "roic_lens/1",
        "roic": roic, "roe": roe, "roe_5y_avg": roe_5y, "roce": roce,
        "debt_to_equity": de,
        "notes": [],
    }

    # --- ROTE and ROIC ex-goodwill -----------------------------------------
    teq, intangibles = tangible_equity(balance)
    ni = _first(income.get("net_income"))
    equity_bv = _first(balance.get("stockholders_equity"))
    out["rote"] = round(ni / teq, 6) if (ni is not None and teq and teq > 0) else None
    out["tangible_equity"] = teq
    out["intangible_share_of_equity"] = (
        round(intangibles / equity_bv, 4)
        if (intangibles is not None and equity_bv and equity_bv > 0) else None)

    ebit = _first(income.get("operating_income"))
    cash = _num(fund.get("total_cash"))
    debt_bs = _first(balance.get("total_debt")) or _num(fund.get("total_debt"))
    tax, _src = effective_tax_rate(income)
    ic = None
    if debt_bs is not None and equity_bv is not None and cash is not None:
        ic = debt_bs + equity_bv - cash
    out["roic_ex_goodwill"] = None
    if ebit is not None and ic and intangibles is not None:
        ic_ex = ic - intangibles
        if ic_ex > 0:
            out["roic_ex_goodwill"] = round(ebit * (1 - tax) / ic_ex, 6)
        else:
            out["notes"].append(
                "ROIC ex-goodwill not computed: removing acquired intangibles leaves "
                "invested capital at or below zero, where the ratio carries no information")

    # --- capital intensity --------------------------------------------------
    ppe = _first(balance.get("ppe_net"))
    assets = _first(balance.get("total_assets"))
    ppe_share = round(ppe / assets, 4) if (ppe is not None and assets and assets > 0) else None
    out["capital_intensity"] = {
        "ppe_share_of_assets": ppe_share,
        "asset_light": None if ppe_share is None else ppe_share < ASSET_LIGHT_PPE_SHARE,
        "goodwill_heavy": (None if out["intangible_share_of_equity"] is None
                           else out["intangible_share_of_equity"] > GOODWILL_HEAVY_SHARE),
    }
    if out["capital_intensity"]["asset_light"]:
        out["notes"].append(
            "asset-light: net PP&E is a small share of assets, so invested capital is "
            "small and ROIC is correspondingly sensitive to how it is measured")
    if out["capital_intensity"]["goodwill_heavy"]:
        out["notes"].append(
            "goodwill-heavy: acquired intangibles dominate equity, so ROIC-with-goodwill "
            "measures the price paid for the businesses and ROIC ex-goodwill measures how "
            "they operate — both are quoted")

    # --- WACC and the economic-value test ----------------------------------
    wacc = compute_wacc(analysis)
    out["wacc"] = wacc
    spread = None
    if roic is not None and wacc.get("value") is not None:
        spread = round(roic - wacc["value"], 6)
    if spread is None:
        verdict = None
    elif spread > WACC_MARGIN:
        verdict = "creates value"
    elif spread < -WACC_MARGIN:
        verdict = "destroys value"
    else:
        verdict = "marginal"
    out["roic_vs_wacc"] = {
        "roic": roic, "wacc": wacc.get("value"), "spread": spread, "verdict": verdict,
        "note": ("a business earning below its cost of capital destroys value as it grows"
                 if verdict == "destroys value" else None),
    }

    # --- rule 1: leverage-manufactured ROE ---------------------------------
    flagged = (roe is not None and de is not None and roic is not None
               and roe > LEV_ROE_MIN and de > LEV_DE_MIN and roic < LEV_ROIC_MAX)
    out["leverage_manufactured_roe"] = {
        "flagged": flagged,
        "roe": roe, "debt_to_equity": de, "roic": roic,
        "thresholds": {"roe_min": LEV_ROE_MIN, "de_min": LEV_DE_MIN,
                       "roic_max": LEV_ROIC_MAX},
        "note": (f"ROE {roe:.1%} rests on {de:.2f}x debt/equity while the business earns "
                 f"ROIC {roic:.1%} — the return to shareholders is financed, not earned"
                 if flagged else None),
    }

    # --- rules 3 & 4: which metric applies ---------------------------------
    financial = is_financial(analysis.get("sector"), analysis.get("industry"))
    out["is_financial"] = financial
    if financial:
        out["preferred_metric"] = "rote" if out["rote"] is not None else "roe"
        out["preferred_reason"] = (
            "banks and insurers fund themselves with debt as raw material, so invested "
            "capital has no operating meaning and ROIC is not the right instrument; "
            + ("ROTE is quoted because tangible equity is derivable"
               if out["rote"] is not None else "ROE is quoted"))
    elif roic is None:
        out["preferred_metric"] = "roe"
        out["preferred_reason"] = (
            "ROIC is None — the net-cash guard (IC_MIN_FRACTION) suppressed it because "
            "subtracting cash leaves invested capital below 5% of the gross base, where "
            "the ratio is a divide-by-almost-zero artefact rather than a signal")
    else:
        out["preferred_metric"] = "roic"
        out["preferred_reason"] = ("ROIC is leverage-neutral and is the default economic "
                                   "test outside financials")

    # --- the silent consequence, said out loud ------------------------------
    fires = roic is not None and roic > BUFFETT_ROIC_GATE
    out["buffett_multiplier"] = {
        "fires": fires,
        "gate": BUFFETT_ROIC_GATE,
        "note": (None if roic is not None else
                 f"the moat multiplier is keyed on ROIC > {BUFFETT_ROIC_GATE:.0%} and "
                 f"ROIC is None here, so it silently does not fire — correct, and "
                 f"otherwise invisible in the report"),
    }
    return out


def render_lines(block: dict) -> list:
    def pct(v):
        return "n/a" if v is None else f"{v:.1%}"
    out = [f"preferred: {block.get('preferred_metric')} — {block.get('preferred_reason')}",
           f"  ROIC {pct(block.get('roic'))} · ex-goodwill {pct(block.get('roic_ex_goodwill'))}"
           f" · ROE {pct(block.get('roe'))} · ROTE {pct(block.get('rote'))}"
           f" · ROCE {pct(block.get('roce'))}"]
    rv = block.get("roic_vs_wacc") or {}
    out.append(f"  ROIC vs WACC: {pct(rv.get('roic'))} vs {pct(rv.get('wacc'))} → "
               f"{rv.get('verdict') or 'not computable'}")
    lev = block.get("leverage_manufactured_roe") or {}
    if lev.get("flagged"):
        out.append(f"  ⚠ {lev['note']}")
    if (block.get("buffett_multiplier") or {}).get("note"):
        out.append(f"  {block['buffett_multiplier']['note']}")
    for n in block.get("notes") or []:
        out.append(f"  · {n}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="ROIC-vs-ROE doctrine applied to an analysis JSON (docs/ROIC_vs_ROE.md).")
    ap.add_argument("json_path")
    ap.add_argument("--update", action="store_true",
                    help="merge the block into the analysis JSON under `roic_lens`")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    path = Path(args.json_path)
    try:
        analysis = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 0

    block = compute(analysis)
    if args.update:
        analysis["roic_lens"] = block
        path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"merged roic_lens into {path.name}")
    if args.pretty:
        for line in render_lines(block):
            print(line, file=sys.stderr)
    print(json.dumps(block, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
