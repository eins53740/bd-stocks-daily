r"""
exit_plan.py — Exit & thesis plan block for bd-stocks-daily v4 Phase A (spec §6).

Every deep report ends with an explicit, numeric sell discipline: target exit
P/E, fair-value range, profit-take ladder, thesis-broken trigger, ATR context
(OFF by default) and yield-on-cost for held tickers.

Overlay-only: the block this script emits (`exit_plan`) is additive to the
schema-2.2 analysis JSON; the composite score is never touched.

Runs as Phase 2.55 — AFTER the Phase 2.5 LLM pass, so the fresh bear-case
trigger can be passed in via --bear-trigger instead of persisting a
placeholder. Fallback: the ticker's most recent `bear_case_trigger` in
_log.csv (re-runs); neither ⇒ null + warning.

Inputs (no network calls at all):
  * `valuation_bands.pe_band`      — target exit P/E via justified_exit_pe()
                                     (band MEDIAN capped at max; Phase B rule).
  * `intrinsic_value.fair_value_range` — low/mid/high anchor for the ladder.
  * `_portfolio_holdings.yaml`     — held detection + per-share cost basis
                                     (native currency). The v4 spec named
                                     BankBD, but its positions table is empty;
                                     the yaml is the maintained source of truth
                                     (decision 2026-07-22).
  * `_technical/{TICKER}.json`     — ATR(14) context, rendered OFF by default:
                                     a compounder is held through normal
                                     30-40% drawdowns; a hard trailing stop
                                     belongs in the growth skill.
  * fundamentals.dividend_rate     — yield-on-cost numerator.

Currency safety: the cost basis is only used when the holding's currency label
matches the analysis currency. The only cross-label rescale allowed is the
pence one (GBp/GBX ↔ GBP), decided from the LABELS — never from a price
ratio, which would corrupt the cost basis of a genuine 100× long-hold winner.

All pure functions do no I/O and are unit-tested in tests/test_exit_plan.py.
Total failure emits {"error": ...} with exit 0 (orchestrator continues).
Outputs a single JSON object on stdout; progress goes to stderr. With
--update, the block is merged into the analysis JSON under `exit_plan`.
"""
from __future__ import annotations

import argparse
import csv
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

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import financial_history as fh  # noqa: E402  (safe_ticker_filename)
from valuation_bands import justified_exit_pe  # noqa: E402  (shared exit-P/E rule)

OUT_DIR_DEFAULT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
HOLDINGS_FILENAME = "_portfolio_holdings.yaml"

# Analysis ticker -> holdings-yaml ticker. SHEL.L (London line, in _universe)
# and SHELL.AS (Amsterdam line, the one actually held) are the same position;
# without this the exit card would print "n/a (not held)" on a held stock.
ALIASES = {"SHEL.L": "SHELL.AS"}

LADDER_CONFIG = {"anchor": "fair_value_high", "steps": [1.0, 1.5], "cost_multiple": 2.0}

# Pence-quoted currency labels (0.01 of their base unit).
_PENCE_LABELS = {"GBP": ("GBP", 0.01), "GBX": ("GBP", 0.01)}


def log(msg: str) -> None:
    print(f"[exit_plan] {msg}", file=sys.stderr)


# ===================================================================
# Pure functions (no I/O — unit-tested)
# ===================================================================
def _ccy_base(label: str) -> tuple[str, float]:
    """(base currency, factor of one unit in base units). 'GBp'/'GBX' → ('GBP', 0.01)."""
    s = (label or "").strip()
    if s.upper() == "GBX" or s == "GBp":
        return "GBP", 0.01
    return s.upper(), 1.0


def cost_scale_factor(holding_ccy, analysis_ccy) -> float | None:
    """Factor converting a cost basis in `holding_ccy` into `analysis_ccy` units,
    decided from the currency LABELS only. Same label → 1.0; pence↔pound →
    0.01/100; anything else → None (mismatch: never divide across currencies).

    Deliberately NOT valuation_bands.price_scale_factor(): that ratio heuristic
    would rescale the cost basis of a genuine 100× winner (audit M1)."""
    if not holding_ccy or not analysis_ccy:
        return None
    h_base, h_f = _ccy_base(holding_ccy)
    a_base, a_f = _ccy_base(analysis_ccy)
    if h_base != a_base or not h_base:
        return None
    return h_f / a_f


def find_holding(ticker: str, holdings: list, aliases: dict = ALIASES) -> tuple[dict | None, list]:
    """The holdings-yaml entry for `ticker` (exact match, then alias map, then
    any other listing of the same company).

    The cross-listing fallback exists because the analysis now runs on the home
    line (listings.py): a user holding the TSM ADR would otherwise get
    "n/a (not held)" on a 2330.TW report — the position is the same, only the
    symbol we chose to analyse changed. Duplicate tickers: first wins + warning.
    Returns (entry|None, warnings)."""
    warnings: list = []
    targets = [ticker]
    if aliases.get(ticker):
        targets.append(aliases[ticker])
    try:
        import listings
        targets += [t for t in listings.all_tickers(ticker) if t not in targets]
    except Exception:  # identity is a nicety here; never break the exit card over it
        pass
    for target in targets:
        matches = [h for h in holdings
                   if isinstance(h, dict) and h.get("ticker") == target]
        if len(matches) > 1:
            warnings.append(f"duplicate ticker {target} in holdings yaml — first entry wins")
        if matches:
            if target != ticker:
                warnings.append(f"held via alias {ticker} → {target}")
            return matches[0], warnings
    return None, warnings


def target_exit_pe_block(pe_band: dict | None) -> dict:
    """Target exit P/E = justified_exit_pe (band median capped at max). A band
    that is absent or degraded (unit_check mismatch ⇒ empty stats) yields None."""
    value = None
    if pe_band and pe_band.get("unit_check") != "mismatch":
        value = justified_exit_pe(pe_band)
    return {
        "value": round(value, 2) if value is not None else None,
        "basis": "own-history P/E band median, capped at band max",
        "depth_years": (pe_band or {}).get("depth_years"),
    }


def build_ladder(fair_high, cost_basis, config: dict = LADDER_CONFIG) -> list:
    """Profit-take ladder: fair-value-anchored rungs (spec §6 / audit M3 — never
    cost-anchored for non-held names) plus one cost rung when a usable cost
    basis (already in analysis currency) is supplied."""
    rungs = []
    if fair_high is not None and fair_high > 0:
        for step in config["steps"]:
            basis = "fair-value high" if step == 1.0 else f"fair-value high × {step:g}"
            rungs.append({"rung": "trim 1/3", "trigger_price": round(fair_high * step, 2),
                          "basis": basis})
        rungs.append({"rung": "hold 1/3", "trigger_price": None,
                      "basis": "run winners; re-evaluate on thesis break"})
    if cost_basis is not None and cost_basis > 0:
        mult = config["cost_multiple"]
        rungs.append({"rung": f"cost {mult:g}×", "trigger_price": round(mult * cost_basis, 2),
                      "basis": f"{mult:g}× cost (held)"})
    return rungs


def yield_on_cost_block(dividend_rate, cost_basis, held: bool,
                        is_equity: bool, ccy_ok: bool) -> dict:
    """Yield on cost = current dividend/share ÷ cost basis/share, both in the
    analysis currency. Every non-computable path names its reason (spec §6:
    "n/a (not held)" verbatim). dividend_rate 0 is "no dividend", not 0.0%."""
    if not held:
        return {"pct": None, "reason": "n/a (not held)"}
    if not is_equity:
        return {"pct": None, "reason": "n/a (non-equity holding)"}
    if not ccy_ok:
        return {"pct": None, "reason": "not computable (currency mismatch)"}
    if cost_basis is None or cost_basis <= 0:
        return {"pct": None, "reason": "not computable (no cost basis)"}
    if dividend_rate is None or dividend_rate <= 0:
        return {"pct": None, "reason": "no dividend"}
    return {"pct": round(dividend_rate / cost_basis * 100, 2),
            "basis": "dividend_rate / avg_cost"}


def atr_context_block(tech: dict | None) -> dict:
    """ATR(14) context from the Phase 3.5 output — always enabled:false (a
    compounder is held through normal drawdowns; spec §6)."""
    if not isinstance(tech, dict) or not isinstance(tech.get("indicators"), dict):
        return {"enabled": False, "available": False}
    ind = tech["indicators"]
    return {
        "enabled": False,
        "available": True,
        "atr": ind.get("atr"),
        "atr_pct": ind.get("atr_pct"),
        "suggested_stop_loss": tech.get("suggested_stop_loss"),
        "risk_level": tech.get("risk_level"),
        "note": "context only — exit discipline is fundamental (P/E + thesis), not a trailing stop",
    }


def latest_trigger_from_rows(rows: list, ticker: str) -> str | None:
    """Most recent non-empty bear_case_trigger for `ticker` in _log.csv rows."""
    hits = [r for r in rows
            if r.get("ticker") == ticker and (r.get("bear_case_trigger") or "").strip()]
    if not hits:
        return None
    hits.sort(key=lambda r: (r.get("date") or "", r.get("round") or ""))
    return hits[-1]["bear_case_trigger"].strip()


def thesis_trigger_block(bear_trigger, thesis_status, log_trigger) -> tuple[dict, list]:
    """thesis_broken_trigger: fresh --bear-trigger first, _log.csv prior second,
    neither ⇒ null + warning (a persisted placeholder would outlive the run)."""
    warnings = []
    if bear_trigger and bear_trigger.strip():
        text, source = bear_trigger.strip(), "phase 2.5 bear case (--bear-trigger)"
    elif log_trigger:
        text, source = log_trigger, "_log.csv prior evaluation"
    else:
        text, source = None, None
        warnings.append("no bear-case trigger available (--bear-trigger not passed, no _log.csv prior)")
    return {"text": text, "source": source,
            "pillars_status": thesis_status or "first_run"}, warnings


# ===================================================================
# I/O helpers
# ===================================================================
def load_holdings(out_dir: Path) -> tuple[list, list]:
    """holdings[] from _portfolio_holdings.yaml. Missing/unreadable ⇒ ([], warning)."""
    path = out_dir / HOLDINGS_FILENAME
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        holdings = data.get("holdings") or []
        if not isinstance(holdings, list):
            return [], [f"{HOLDINGS_FILENAME}: 'holdings' is not a list — treating all as not held"]
        return holdings, []
    except FileNotFoundError:
        return [], [f"{HOLDINGS_FILENAME} not found — treating all tickers as not held"]
    except Exception as e:
        return [], [f"{HOLDINGS_FILENAME} unreadable ({type(e).__name__}: {e}) — treating all as not held"]


def load_technical(out_dir: Path, ticker: str) -> dict | None:
    path = out_dir / "_technical" / f"{fh.safe_ticker_filename(ticker)}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_log_trigger(out_dir: Path, ticker: str) -> str | None:
    path = out_dir / "_log.csv"
    try:
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return None
    return latest_trigger_from_rows(rows, ticker)


# ===================================================================
# Main
# ===================================================================
def run(ticker: str, analysis_json: str | None, out_dir: Path,
        bear_trigger: str | None, thesis_status: str | None) -> dict:
    analysis = {}
    if analysis_json:
        try:
            analysis = json.loads(Path(analysis_json).read_text(encoding="utf-8"))
        except Exception as e:
            log(f"could not read analysis-json: {e}")
    fund = analysis.get("fundamentals") or {}
    analysis_ccy = analysis.get("currency")
    warnings: list = []

    # --- held detection + cost basis (yaml is the source of truth) ---
    holdings, w = load_holdings(out_dir)
    warnings += w
    holding_raw, w = find_holding(ticker, holdings)
    warnings += w
    held = holding_raw is not None
    holding = None
    cost_basis = None          # per share, in the ANALYSIS currency
    ccy_ok = False
    is_equity = False
    if held:
        asset_type = holding_raw.get("asset_type") or "equity"
        is_equity = asset_type == "equity"
        holding = {
            "quantity": holding_raw.get("quantity"),
            "avg_cost": holding_raw.get("avg_cost"),
            "currency": holding_raw.get("currency"),
            "asset_type": asset_type,
            "source": HOLDINGS_FILENAME,
        }
        scale = cost_scale_factor(holding_raw.get("currency"), analysis_ccy)
        ccy_ok = scale is not None
        if not ccy_ok:
            warnings.append(
                f"cost basis in {holding_raw.get('currency')} vs analysis in {analysis_ccy} "
                f"— cost rung and yield-on-cost not computable (currency mismatch)")
        avg_cost = holding_raw.get("avg_cost")
        if ccy_ok and isinstance(avg_cost, (int, float)) and avg_cost > 0:
            cost_basis = avg_cost * scale
        elif ccy_ok:
            warnings.append("holding has no usable avg_cost — cost rung skipped")
        if not is_equity:
            warnings.append(f"non-equity holding ({asset_type}) — cost rung and yield-on-cost skipped")

    # --- valuation inputs from the Phase 2.3 blocks ---
    pe_band = (analysis.get("valuation_bands") or {}).get("pe_band")
    exit_pe = target_exit_pe_block(pe_band)
    if exit_pe["value"] is None:
        warnings.append("target exit P/E not computable (P/E band absent or degraded)")

    fvr = (analysis.get("intrinsic_value") or {}).get("fair_value_range")
    fair_high = fvr.get("high") if isinstance(fvr, dict) else None
    if fair_high is None:
        warnings.append("fair_value_range unavailable — fair-value ladder rungs not computable")

    ladder = build_ladder(fair_high, cost_basis if (held and is_equity) else None)
    if not ladder:
        warnings.append("profit-take ladder empty (no fair value, no cost basis)")

    trigger, w = thesis_trigger_block(
        bear_trigger, thesis_status,
        load_log_trigger(out_dir, ticker) if not (bear_trigger and bear_trigger.strip()) else None)
    warnings += w

    block = {
        "fetched_at": datetime.now().isoformat(),
        "held": held,
        "holding": holding,
        "target_exit_pe": exit_pe,
        "fair_value_range": fvr if isinstance(fvr, dict) else None,
        "profit_take_ladder": ladder,
        "ladder_config": dict(LADDER_CONFIG),
        "thesis_broken_trigger": trigger,
        "atr_context": atr_context_block(load_technical(out_dir, ticker)),
        "yield_on_cost": yield_on_cost_block(fund.get("dividend_rate"), cost_basis,
                                             held, is_equity, ccy_ok),
        "warnings": warnings,
    }
    return block


def merge_into_analysis(analysis_json: str, block: dict) -> None:
    """Write the block into the analysis JSON under `exit_plan` (additive key;
    schema stays 2.2)."""
    path = Path(analysis_json)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["exit_plan"] = block
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    log(f"merged exit_plan into {path.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Exit & thesis plan block (v4 Phase A)")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--analysis-json", default=None,
                    help="Path to the analysis JSON (valuation_bands + intrinsic_value already merged)")
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--bear-trigger", default=None,
                    help="Fresh bear-case trigger sentence from Phase 2.5 step 7")
    ap.add_argument("--thesis-status", default=None,
                    choices=["intact", "weakened", "broken", "first_run"],
                    help="thesis_check overall_status (re-runs); omit on first runs")
    ap.add_argument("--update", action="store_true",
                    help="Merge the result into the analysis JSON (key: exit_plan)")
    args = ap.parse_args()

    try:
        block = run(args.ticker, args.analysis_json, Path(args.out_dir),
                    args.bear_trigger, args.thesis_status)
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
