"""
intrinsic_value.py — 5-model intrinsic-value blend + margin-of-safety verdict
+ fundamental-EV-vs-market-cap wedge, for bd-stocks-daily v4 Phase B (spec §7,
idea #4 — un-gates old roadmap item 9, triangulated valuation).

Overlay-only: nothing here touches the composite score. The block this script
emits (`intrinsic_value`) is additive to the schema-2.2 analysis JSON.

The five models, each with its own validity flag:
  1. two_minute_eps_growth — EPS_ttm × (1+g)^5 × justified exit P/E
     (own-history band mean, capped at own historical max), discounted back
     5 years at DISCOUNT_RATE (12%, mid of the spec's 10-15%).
  2. lynch_peg — fair P/E = growth rate ×100 (PEG = 1); fair value = EPS × that.
     Valid only for growers (5% ≤ g ≤ 50%); ties into `lynch_category`.
  3. forward_pe_target — the Faes Farma / TIKR forward-target fair value,
     REUSED from valuation_bands.forward_target (no recompute).
  4. dcf — the existing analyze_ticker DCF, gated by `dcf_valid` (an invalid
     DCF is excluded from the blend with `dcf_reason` echoed).
  5. roe_residual_income — single-stage residual income:
     IV = BVPS + BVPS × (ROE − Ke) / (Ke − g), g = 2.5% (matches the DCF
     terminal), Ke = CAPM (rf + β × 5% ERP). rf = yfinance ^TNX last close
     ÷ 100, fallback RF_FALLBACK when unavailable.

Blend = mean of the valid models' values, requires ≥ 2 valid models,
`contributors` labels who's in and why the others are out (spec acceptance
gate: "blend skips an invalid DCF and labels its contributors"). The MoS
verdict is computed off the blend, never off any single model:
  MoS = (blend − price) / blend →
  deep_value ≥ +25% · fair −10%..+25% · rich < −10%.

fair_value_range {low, mid, high} — min / blend / max of the valid models
(the model spread IS the value range; always ordered). Phase A's exit plan
consumes this range.

Inputs come from the analysis JSON only (run valuation_bands.py --update
first); the ONLY network call is the ^TNX risk-free lookup. Pure functions
are unit-tested in tests/test_valuation_depth.py. Failure emits
{"error": ...} with exit 0.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from valuation_bands import justified_exit_pe  # noqa: E402  (shared exit-multiple rule)

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

DISCOUNT_RATE = 0.12      # 2-minute model discount (mid of spec's 10-15%)
GROWTH_YEARS = 5          # 2-minute model projection horizon
RI_TERMINAL_G = 0.025     # residual-income growth (matches DCF terminal g)
ERP = 0.05                # equity risk premium for CAPM Ke
RF_FALLBACK = 0.0425      # used when ^TNX is unavailable (flagged in output)
BETA_FALLBACK = 1.0
LYNCH_G_RANGE = (0.05, 0.50)
MOS_DEEP_VALUE = 0.25     # MoS ≥ +25% → deep_value
MOS_RICH = -0.10          # MoS < −10% → rich
MIN_VALID_MODELS = 2


def log(msg: str) -> None:
    print(f"[intrinsic_value] {msg}", file=sys.stderr)


# ===================================================================
# Pure functions (no I/O — unit-tested)
# ===================================================================
def capm_cost_of_equity(rf, beta, erp: float = ERP) -> float:
    """Ke = rf + β·ERP. Falls back to β=1.0 when beta is missing."""
    b = beta if beta is not None else BETA_FALLBACK
    return rf + b * erp


def model_two_minute(eps_ttm, g, exit_pe, discount: float = DISCOUNT_RATE,
                     years: int = GROWTH_YEARS) -> dict:
    """2-minute EPS-growth model: EPS×(1+g)^years × exit P/E, discounted back."""
    if eps_ttm is None or eps_ttm <= 0:
        return {"value": None, "valid": False, "reason": "EPS (TTM) missing or non-positive"}
    if g is None:
        return {"value": None, "valid": False, "reason": "no growth anchor"}
    if exit_pe is None or exit_pe <= 0:
        return {"value": None, "valid": False, "reason": "no justified exit P/E (band unavailable)"}
    future = eps_ttm * (1 + g) ** years * exit_pe
    return {"value": round(future / (1 + discount) ** years, 2), "valid": True,
            "reason": None, "assumptions": {"g": g, "exit_pe": exit_pe,
                                            "discount": discount, "years": years}}


def model_lynch_peg(eps_ttm, g, g_range: tuple = LYNCH_G_RANGE) -> dict:
    """Lynch PEG=1 fair value: fair P/E = growth×100 → value = EPS × fair P/E.
    Only meaningful for growers: g inside [5%, 50%]."""
    if eps_ttm is None or eps_ttm <= 0:
        return {"value": None, "valid": False, "reason": "EPS (TTM) missing or non-positive"}
    if g is None or not (g_range[0] <= g <= g_range[1]):
        return {"value": None, "valid": False,
                "reason": f"growth {g if g is None else round(g * 100, 1)}% outside Lynch range "
                          f"[{g_range[0]:.0%}–{g_range[1]:.0%}]"}
    fair_pe = g * 100
    return {"value": round(eps_ttm * fair_pe, 2), "valid": True, "reason": None,
            "assumptions": {"g": g, "fair_pe": round(fair_pe, 1)}}


def model_forward_pe(forward_block: dict | None) -> dict:
    """Reuse valuation_bands' forward target discounted to today at DISCOUNT_RATE
    (the band target is an FY+3 price; the blend compares present values)."""
    fb = forward_block or {}
    if not fb.get("valid"):
        return {"value": None, "valid": False,
                "reason": fb.get("reason") or "forward target unavailable (run valuation_bands first)"}
    years = fb.get("horizon_years") or 3
    pv = fb["target_price"] / (1 + DISCOUNT_RATE) ** years
    return {"value": round(pv, 2), "valid": True, "reason": None,
            "assumptions": {"target_fy3": fb["target_price"], "discount": DISCOUNT_RATE,
                            "years": years}}


def model_dcf(dcf_intrinsic, dcf_valid, dcf_reason) -> dict:
    """The existing analyze_ticker DCF, passed through its own validity gate."""
    if not dcf_valid or dcf_intrinsic is None:
        return {"value": None, "valid": False,
                "reason": dcf_reason or "dcf_valid false"}
    return {"value": round(dcf_intrinsic, 2), "valid": True, "reason": None}


def model_residual_income(bvps, roe, ke, g: float = RI_TERMINAL_G) -> dict:
    """Single-stage residual income: IV = BVPS + BVPS·(ROE − Ke)/(Ke − g)."""
    if bvps is None or bvps <= 0:
        return {"value": None, "valid": False, "reason": "book value/share missing or non-positive"}
    if roe is None:
        return {"value": None, "valid": False, "reason": "ROE unavailable"}
    if ke is None or ke <= g + 0.01:
        return {"value": None, "valid": False,
                "reason": f"cost of equity ({ke}) too close to terminal growth ({g})"}
    value = bvps + bvps * (roe - ke) / (ke - g)
    if value <= 0:
        return {"value": None, "valid": False,
                "reason": f"negative intrinsic (ROE {roe:.1%} far below Ke {ke:.1%})"}
    return {"value": round(value, 2), "valid": True, "reason": None,
            "assumptions": {"roe": roe, "ke": round(ke, 4), "g": g}}


def blend_models(models: dict) -> dict:
    """Mean of valid model values; requires ≥ MIN_VALID_MODELS. Labels the
    contributors and each exclusion reason (acceptance-gate requirement)."""
    valid = {k: m["value"] for k, m in models.items() if m.get("valid") and m.get("value")}
    excluded = {k: m.get("reason") for k, m in models.items() if not m.get("valid")}
    n_total = len(models)
    if len(valid) < MIN_VALID_MODELS:
        label = (f"not computable — only {len(valid)}/{n_total} models valid"
                 + (": " + "; ".join(f"{k} excluded: {v}" for k, v in excluded.items())
                    if excluded else ""))
        return {"value": None, "n_valid": len(valid), "n_models": n_total,
                "contributors": sorted(valid), "excluded": excluded, "label": label}
    label = f"blend of {len(valid)}/{n_total} ({', '.join(sorted(valid))})"
    if excluded:
        label += " — " + "; ".join(f"{k} excluded: {v}" for k, v in excluded.items())
    return {"value": round(statistics.mean(valid.values()), 2),
            "n_valid": len(valid), "n_models": n_total,
            "contributors": sorted(valid), "excluded": excluded, "label": label}


def mos_verdict(blend_value, price) -> dict:
    """Margin of safety off the blend: (blend − price)/blend →
    deep_value ≥ +25% · fair −10%..+25% · rich < −10%."""
    if blend_value is None or not price or price <= 0 or blend_value <= 0:
        return {"mos_pct": None, "mos_class": "not_computable"}
    mos = (blend_value - price) / blend_value
    cls = "deep_value" if mos >= MOS_DEEP_VALUE else ("rich" if mos < MOS_RICH else "fair")
    return {"mos_pct": round(mos * 100, 1), "mos_class": cls}


def ev_vs_market_cap(market_cap, enterprise_value, net_debt) -> dict:
    """The EV-vs-market-cap wedge, explained: net-debt drag or net-cash cushion."""
    out = {"market_cap": market_cap, "enterprise_value": enterprise_value,
           "net_debt": net_debt, "wedge_pct": None, "note": None}
    if not market_cap or market_cap <= 0 or enterprise_value is None:
        out["note"] = "not computable (market cap or EV missing)"
        return out
    wedge = (enterprise_value - market_cap) / market_cap
    out["wedge_pct"] = round(wedge * 100, 1)
    if net_debt is not None and net_debt < 0:
        out["note"] = "EV below market cap — net-cash cushion (buyer pays less than the quote)"
    elif wedge > 0.02:
        out["note"] = "EV above market cap — net-debt drag (buyer assumes the debt)"
    else:
        out["note"] = "EV ≈ market cap — balance sheet roughly neutral"
    return out


def fair_value_range(models: dict, blend_value) -> dict:
    """{low, mid, high} = min / blend / max of the VALID models — the model
    spread IS the value range (Jitta/Klarman), and it is always ordered
    (low ≤ mid ≤ high), unlike sensitivity rows built on a different EPS basis
    (live ADSK finding: sensitivity-low 444 vs blend 218). Null when the blend
    is not computable."""
    if blend_value is None:
        return {"low": None, "mid": None, "high": None,
                "basis": "min / blend / max of valid intrinsic models"}
    vals = [m["value"] for m in models.values() if m.get("valid") and m.get("value")]
    return {"low": round(min(vals), 2), "mid": blend_value, "high": round(max(vals), 2),
            "basis": "min / blend / max of valid intrinsic models"}


# ===================================================================
# Risk-free fetch (the only network call)
# ===================================================================
def fetch_risk_free() -> tuple[float, str]:
    """^TNX (CBOE 10y Treasury yield index, points = % × 10⁻²) via yfinance;
    RF_FALLBACK constant when unavailable."""
    try:
        import yfinance as yf
        h = yf.Ticker("^TNX").history(period="5d")
        if h is not None and not h.empty:
            return float(h["Close"].iloc[-1]) / 100.0, "^TNX"
    except Exception as e:
        log(f"^TNX fetch failed: {type(e).__name__}: {e}")
    return RF_FALLBACK, f"fallback constant ({RF_FALLBACK:.2%})"


# ===================================================================
# Main
# ===================================================================
def run(analysis_json: str, rf_override: float | None = None) -> dict:
    data = json.loads(Path(analysis_json).read_text(encoding="utf-8"))
    fund = data.get("fundamentals") or {}
    bands = data.get("valuation_bands") or {}
    price = data.get("price_current")

    eps_ttm = fund.get("eps_ttm")
    if eps_ttm is None and price and fund.get("pe_ratio"):
        eps_ttm = price / fund["pe_ratio"]
    g = (bands.get("growth_anchor") or {}).get("g")
    exit_pe = justified_exit_pe(bands.get("pe_band"))

    if rf_override is not None:
        rf, rf_source = rf_override, "override"
    else:
        rf, rf_source = fetch_risk_free()
    ke = capm_cost_of_equity(rf, fund.get("beta"))

    models = {
        "two_minute_eps_growth": model_two_minute(eps_ttm, g, exit_pe),
        "lynch_peg": model_lynch_peg(eps_ttm, g),
        "forward_pe_target": model_forward_pe(bands.get("forward_target")),
        "dcf": model_dcf(data.get("dcf_intrinsic"), data.get("dcf_valid"),
                         data.get("dcf_reason")),
        "roe_residual_income": model_residual_income(fund.get("book_value"),
                                                     fund.get("roe_ttm"), ke),
    }
    blend = blend_models(models)
    mos = mos_verdict(blend["value"], price)

    return {
        "fetched_at": datetime.now().isoformat(),
        "price_current": price,
        "currency": data.get("currency"),
        "ev_vs_market_cap": ev_vs_market_cap(fund.get("market_cap"),
                                             fund.get("enterprise_value"),
                                             fund.get("net_debt")),
        "capm": {"rf": round(rf, 4), "rf_source": rf_source,
                 "beta": fund.get("beta"), "beta_fallback_used": fund.get("beta") is None,
                 "erp": ERP, "cost_of_equity": round(ke, 4)},
        "models": models,
        "blend": blend,
        **mos,
        "fair_value_range": fair_value_range(models, blend["value"]),
    }


def merge_into_analysis(analysis_json: str, block: dict) -> None:
    """Write the block into the analysis JSON under `intrinsic_value`
    (additive key; schema stays 2.2)."""
    path = Path(analysis_json)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["intrinsic_value"] = block
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    log(f"merged intrinsic_value into {path.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description="5-model intrinsic-value blend + MoS verdict")
    ap.add_argument("--analysis-json", required=True,
                    help="analyze_ticker JSON, ideally after valuation_bands.py --update")
    ap.add_argument("--rf", type=float, default=None,
                    help="Risk-free rate override (skips the ^TNX fetch)")
    ap.add_argument("--update", action="store_true",
                    help="Merge the result into the analysis JSON (key: intrinsic_value)")
    args = ap.parse_args()

    try:
        block = run(args.analysis_json, rf_override=args.rf)
        if args.update:
            merge_into_analysis(args.analysis_json, block)
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        print(json.dumps({"error": str(e), "error_type": type(e).__name__}))
        return 0  # non-fatal: report degrades, run continues

    print(json.dumps(block, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
