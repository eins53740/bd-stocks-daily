"""
alpha_beta.py — v4 Phase E return-profile overlay.

Gives every deep report a market-risk read (Bruno's p13 "α β" note, idea #9):

  * α / β vs the ticker's regional benchmark (3-yr monthly returns): β = cov/var,
    α = annualized Jensen's-alpha regression intercept over excess returns.
  * A CAPM line: realized annualized return vs CAPM-expected (rf + β·(benchmark
    excess)) — does the stock earn its systematic risk?
  * A price/total-return CAGR ladder (1/3/5/10/15-yr) from 15-yr monthly adjusted
    closes — the honest long-horizon compounding signal (revenue CAGR rarely
    reaches back 10/15y on free data; this always can).
  * A Lynch-category return/drawdown prior (report prior, labelled — never scored).
  * A portfolio-fit line: portfolio-level α/β (FX-normalized weighted equity
    holdings, regressed vs the world benchmark URTH, cached once/day) alongside the
    ticker vs the SAME world benchmark — "does adding this raise or dilute my
    portfolio's return profile?".

Overlay-only: merges an additive `alpha_beta` block and adds beta_3y/alpha_ann_pct
to the existing `top_strip` (so the metrics strip renders from one source). NEVER
touches the composite/verdict. Deep-dives only. Any failure prints {"error": ...}
and returns 0 so the run continues.

Ground truth: yfinance monthly closes only; the LLM never fabricates these. rf is
reused from intrinsic_value.capm.rf (node 2.3 runs first) with a constant fallback.
Runs under ambient Python312 (yfinance+pandas); pure functions are stdlib-only so
they unit-test under the skill's lean uv venv.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
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

import markets  # noqa: E402  (eur_fx_pair — pure, no pandas)

OUT_DIR_DEFAULT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
PORTFOLIO_PROFILE = "_portfolio_riskprofile.json"

WORLD_BENCH = "URTH"          # iShares MSCI World (USD) — common apples-to-apples base
HIST_YEARS_TICKER = 15        # for the price-CAGR ladder (also covers β window)
WINDOW_YEARS = 4              # fetch depth for benchmark/portfolio (≥ 37 monthly)
N_MONTHS_BETA = 36            # regression window (3 yr of monthly returns)
MIN_MONTHS = 24               # below this, β/α degrade to "not computable"
DEFAULT_RF = 0.04             # fallback annual risk-free if intrinsic_value.capm.rf absent


def log(msg: str) -> None:
    print(f"[alpha_beta] {msg}", file=sys.stderr)


def _pct(x):
    return round(x * 100.0, 2) if isinstance(x, (int, float)) else None


# ===================================================================
# Pure functions (stdlib only — unit-tested under uv)
# ===================================================================
def benchmark_for(ticker: str, bench_map: dict, default_bench: str) -> str:
    """Regional benchmark for a ticker via dotted-suffix endswith match
    (mirrors technical_score's resolver). bench_map keys are dotted (e.g. '.AS')."""
    for suf, idx in bench_map.items():
        if ticker.endswith(suf):
            return idx
    return default_bench


def returns_by_ym(closes_by_ym: dict) -> dict:
    """{year-month: simple return} from a {year-month: close} map, sorted by key.
    A non-positive or missing close nulls that period's return (dropped)."""
    items = sorted(closes_by_ym.items())
    out = {}
    for i in range(1, len(items)):
        ym, c = items[i]
        _, p = items[i - 1]
        if c is not None and p and p > 0 and c > 0:
            out[ym] = c / p - 1.0
    return out


def align_by_key(a: dict, b: dict) -> tuple[list, list]:
    """Values of a and b over their sorted common keys (paired, same length)."""
    keys = sorted(set(a) & set(b))
    return [a[k] for k in keys], [b[k] for k in keys]


def regress_alpha_beta(r_ticker: list, r_bench: list, rf_monthly: float) -> dict:
    """OLS of excess ticker returns on excess benchmark returns.
    β = cov/var(bench); α = annualized intercept (Jensen). Degrades if n<MIN_MONTHS
    or the benchmark has zero variance."""
    n = min(len(r_ticker), len(r_bench))
    if n < MIN_MONTHS:
        return {"valid": False, "n": n, "reason": f"only {n} months (<{MIN_MONTHS})"}
    et = [r_ticker[i] - rf_monthly for i in range(n)]
    eb = [r_bench[i] - rf_monthly for i in range(n)]
    mean_t = sum(et) / n
    mean_b = sum(eb) / n
    var_b = sum((y - mean_b) ** 2 for y in eb) / n
    if var_b == 0:
        return {"valid": False, "n": n, "reason": "benchmark zero variance"}
    cov = sum((et[i] - mean_t) * (eb[i] - mean_b) for i in range(n)) / n
    beta = cov / var_b
    alpha_m = mean_t - beta * mean_b
    alpha_ann = (1.0 + alpha_m) ** 12 - 1.0
    var_t = sum((x - mean_t) ** 2 for x in et) / n
    r2 = (cov ** 2) / (var_b * var_t) if var_t > 0 else None
    return {
        "valid": True, "n": n,
        "beta": round(beta, 3),
        "alpha_monthly": alpha_m,
        "alpha_ann": round(alpha_ann, 4),
        "r2": round(r2, 3) if r2 is not None else None,
    }


def annualize_from_returns(rets: list) -> float | None:
    """Annualized return from a list of monthly simple returns (geometric)."""
    if not rets:
        return None
    growth = 1.0
    for r in rets:
        growth *= (1.0 + r)
    return round(growth ** (12.0 / len(rets)) - 1.0, 4)


def capm_expected_return(rf_ann: float, beta, bench_ann) -> float | None:
    """CAPM expected annual return = rf + β·(benchmark − rf)."""
    if beta is None or bench_ann is None:
        return None
    return round(rf_ann + beta * (bench_ann - rf_ann), 4)


def price_cagr_ladder(closes_by_ym: dict) -> dict:
    """1/3/5/10/15-yr price CAGR from monthly (adjusted) closes. Index-based
    (assumes ~monthly spacing); a rung stays null when history is too short."""
    items = sorted(closes_by_ym.items())
    closes = [c for _, c in items]
    n = len(closes)
    ladder = {f"{w}y": None for w in (1, 3, 5, 10, 15)}
    ladder["depth_years"] = round((n - 1) / 12.0, 1) if n else 0
    ladder["basis"] = "adjusted monthly close (total-return proxy)"
    last = closes[-1] if n else None
    if not last or last <= 0:
        return ladder
    for w in (1, 3, 5, 10, 15):
        idx = n - 1 - 12 * w
        if idx >= 0 and closes[idx] and closes[idx] > 0:
            ladder[f"{w}y"] = round((last / closes[idx]) ** (1.0 / w) - 1.0, 4)
    return ladder


LYNCH_PRIORS = {
    "fast_grower": {"expected_return_band": "20-25%/yr (while growth durable)",
                    "drawdown_band": "40-50%",
                    "note": "high return, high volatility — thesis lives or dies on growth durability"},
    "stalwart": {"expected_return_band": "10-12%/yr",
                 "drawdown_band": "20-30%",
                 "note": "steady compounder — trim into rich multiples, add on dips; hold through normal drawdowns"},
    "slow_grower": {"expected_return_band": "6-8%/yr (mostly dividend)",
                    "drawdown_band": "15-25%",
                    "note": "own for yield; total return capped by low growth"},
    "cyclical": {"expected_return_band": "highly variable — entry-point dependent",
                 "drawdown_band": "50%+ peak-to-trough",
                 "note": "returns depend on where you buy in the cycle, not the multiple"},
    "unknown": {"expected_return_band": "n/a",
                "drawdown_band": "n/a",
                "note": "insufficient growth history to classify"},
}


def lynch_prior(category) -> dict:
    """Lynch-category → expected-return / drawdown prior (report prior, never scored)."""
    cat = category if category in LYNCH_PRIORS else "unknown"
    out = {"category": cat}
    out.update(LYNCH_PRIORS[cat])
    return out


def fit_verdict(ticker_val, portfolio_val, tol: float) -> str:
    """Directional: is the ticker's metric higher/lower/similar to the portfolio's?"""
    if ticker_val is None or portfolio_val is None:
        return "n/a"
    diff = ticker_val - portfolio_val
    if abs(diff) <= tol:
        return "neutral"
    return "raises" if diff > 0 else "dilutes"


def portfolio_value_series(closes_by_ticker: dict, shares: dict) -> dict:
    """Portfolio market-value series over the common months of all holdings:
    value[ym] = Σ shares_i · close_i[ym]. Restricting to common months keeps the
    weighting drift-aware without a holding blinking in and out."""
    if not closes_by_ticker:
        return {}
    common = None
    for tk, series in closes_by_ticker.items():
        keys = set(series)
        common = keys if common is None else (common & keys)
    common = sorted(common or [])
    out = {}
    for ym in common:
        out[ym] = sum(shares.get(tk, 0.0) * series[ym]
                      for tk, series in closes_by_ticker.items())
    return out


# ===================================================================
# Impure helpers (yfinance / FX — lazy imports, degrade to {})
# ===================================================================
def fetch_monthly_closes(symbol: str, years: int) -> dict:
    """{year-month: adjusted close} for a symbol; {} on any failure."""
    try:
        import yfinance as yf
        tk = yf.Ticker(symbol)
        df = tk.history(period=f"{years}y", interval="1mo", auto_adjust=True)
    except Exception as e:
        log(f"fetch {symbol} failed: {type(e).__name__}: {e}")
        return {}
    if df is None or getattr(df, "empty", True) or "Close" not in df.columns:
        return {}
    out = {}
    for idx, close in df["Close"].items():
        try:
            ym = idx.strftime("%Y-%m")
            c = float(close)
        except Exception:
            continue
        if not math.isnan(c) and c > 0:
            out[ym] = c  # last write per month wins (already monthly)
    return out


def to_eur_series(closes_by_ym: dict, currency: str, fx_cache: dict) -> dict:
    """Convert a {ym: close} series to EUR close-by-close using monthly EUR-FX
    history (spot FX would cancel in returns). EUR passes through; a month with no
    FX quote is dropped."""
    cur = (currency or "").upper()
    if cur in ("", "EUR"):
        return dict(closes_by_ym)
    pair = markets.eur_fx_pair(cur)  # 'EUR{cur}=X' = units of cur per 1 EUR
    if pair is None:
        return dict(closes_by_ym)
    if pair not in fx_cache:
        fx_cache[pair] = fetch_monthly_closes(pair, WINDOW_YEARS)
    fx = fx_cache[pair]
    out = {}
    for ym, c in closes_by_ym.items():
        rate = fx.get(ym)
        if rate and rate > 0 and c is not None:
            out[ym] = c / rate
    return out


def regress_from_closes(closes_a: dict, closes_b: dict, rf_ann: float) -> dict:
    """Align two close series → last N_MONTHS_BETA returns → regression + realized
    benchmark annualized return."""
    ra, rb = align_by_key(returns_by_ym(closes_a), returns_by_ym(closes_b))
    ra, rb = ra[-N_MONTHS_BETA:], rb[-N_MONTHS_BETA:]
    rf_m = (1.0 + rf_ann) ** (1.0 / 12.0) - 1.0
    reg = regress_alpha_beta(ra, rb, rf_m)
    reg["realized_return_ann"] = annualize_from_returns(ra)
    reg["benchmark_return_ann"] = annualize_from_returns(rb)
    return reg


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
    except Exception as e:
        log(f"write {path.name} failed: {e}")


def compute_portfolio_profile(out_dir: Path, rf_ann: float, today_iso: str,
                              fx_cache: dict) -> dict:
    """Portfolio-level α/β vs URTH (EUR), cached once/day in _portfolio_riskprofile.json."""
    cache_path = out_dir / PORTFOLIO_PROFILE
    cached = read_json(cache_path)
    if isinstance(cached, dict) and cached.get("date") == today_iso:
        return cached  # once/day

    try:
        from exit_plan import load_holdings  # reuse the shared loader
        holdings, _ = load_holdings(out_dir)
    except Exception as e:
        prof = {"date": today_iso, "available": False, "benchmark": WORLD_BENCH,
                "reason": f"holdings unavailable: {type(e).__name__}"}
        write_json(cache_path, prof)
        return prof

    eur_closes, shares = {}, {}
    for h in holdings:
        if not isinstance(h, dict):
            continue
        if (h.get("asset_type") or "equity") != "equity":
            continue  # crypto excluded
        tk, qty = h.get("ticker"), h.get("quantity")
        if not tk or not qty:
            continue
        raw = fetch_monthly_closes(tk, WINDOW_YEARS)
        eur = to_eur_series(raw, h.get("currency"), fx_cache)
        if len(eur) >= MIN_MONTHS + 1:
            eur_closes[tk] = eur
            shares[tk] = float(qty)

    if len(eur_closes) < 3:
        prof = {"date": today_iso, "available": False, "benchmark": WORLD_BENCH,
                "reason": f"only {len(eur_closes)} usable equity holdings (<3)"}
        write_json(cache_path, prof)
        return prof

    value_series = portfolio_value_series(eur_closes, shares)
    urth_eur = to_eur_series(fetch_monthly_closes(WORLD_BENCH, WINDOW_YEARS), "USD", fx_cache)
    reg = regress_from_closes(value_series, urth_eur, rf_ann)
    prof = {
        "date": today_iso, "benchmark": WORLD_BENCH, "currency": "EUR",
        "available": bool(reg.get("valid")),
        "beta": reg.get("beta"),
        "alpha_ann_pct": _pct(reg.get("alpha_ann")),
        "n_months": reg.get("n"),
        "holdings_used": len(eur_closes),
    }
    if not reg.get("valid"):
        prof["reason"] = reg.get("reason")
    write_json(cache_path, prof)
    return prof


# ===================================================================
# Main
# ===================================================================
def run(analysis_json: str, out_dir: Path, today_iso: str) -> dict:
    data = json.loads(Path(analysis_json).read_text(encoding="utf-8"))
    ticker = data.get("ticker")
    if not ticker:
        return {"error": "analysis JSON has no ticker"}
    currency = data.get("currency")
    warnings: list = []

    # rf: reuse intrinsic_value.capm.rf (node 2.3 runs first); fallback constant.
    capm = (data.get("intrinsic_value") or {}).get("capm") or {}
    rf_ann = capm.get("rf")
    if not isinstance(rf_ann, (int, float)):
        rf_ann, rf_source = DEFAULT_RF, "fallback constant"
        warnings.append("intrinsic_value.capm.rf absent — used fallback rf")
    else:
        rf_source = capm.get("rf_source") or "intrinsic_value.capm.rf"

    # Regional benchmark (dotted-suffix map from technical_score, injected).
    from technical_score import BENCH_BY_SUFFIX, DEFAULT_BENCH  # noqa: E402 (pandas — ambient only)
    bench = benchmark_for(ticker, BENCH_BY_SUFFIX, DEFAULT_BENCH)

    ticker_closes = fetch_monthly_closes(ticker, HIST_YEARS_TICKER)
    if not ticker_closes:
        return {"error": f"no monthly price history for {ticker}",
                "lynch_prior": lynch_prior(data.get("lynch_category")),
                "warnings": warnings}
    bench_closes = fetch_monthly_closes(bench, WINDOW_YEARS)

    reg = regress_from_closes(ticker_closes, bench_closes, rf_ann)
    beta = reg.get("beta")
    alpha_ann = reg.get("alpha_ann")
    realized_ann = reg.get("realized_return_ann")
    bench_ann = reg.get("benchmark_return_ann")
    if not reg.get("valid"):
        warnings.append(f"α/β not computable: {reg.get('reason')}")

    block = {
        "fetched_at": datetime.now().isoformat(),
        "window": "3y", "n_months": reg.get("n"),
        "benchmark": bench,
        "beta": beta,
        "alpha_ann_pct": _pct(alpha_ann),
        "r2": reg.get("r2"),
        "realized_return_ann_pct": _pct(realized_ann),
        "benchmark_return_ann_pct": _pct(bench_ann),
        "capm_expected_return_ann_pct": _pct(capm_expected_return(rf_ann, beta, bench_ann)),
        "rf_pct": _pct(rf_ann), "rf_source": rf_source,
        "price_cagr_ladder": price_cagr_ladder(ticker_closes),
        "lynch_prior": lynch_prior(data.get("lynch_category")),
        "warnings": warnings,
    }

    # ---- Portfolio fit vs the world benchmark (best-effort) ----
    fx_cache: dict = {}
    try:
        prof = compute_portfolio_profile(out_dir, rf_ann, today_iso, fx_cache)
        tkr_eur = to_eur_series(ticker_closes, currency, fx_cache)
        urth_eur = to_eur_series(fetch_monthly_closes(WORLD_BENCH, WINDOW_YEARS), "USD", fx_cache)
        tvw = regress_from_closes(tkr_eur, urth_eur, rf_ann)
        if prof.get("available") and tvw.get("valid"):
            t_beta, t_alpha = tvw.get("beta"), _pct(tvw.get("alpha_ann"))
            block["portfolio_comparison"] = {
                "benchmark": WORLD_BENCH, "currency": "EUR",
                "portfolio": {"beta": prof.get("beta"), "alpha_ann_pct": prof.get("alpha_ann_pct"),
                              "holdings_used": prof.get("holdings_used"), "n_months": prof.get("n_months")},
                "ticker_vs_world": {"beta": t_beta, "alpha_ann_pct": t_alpha},
                "verdict_beta": fit_verdict(t_beta, prof.get("beta"), 0.10),
                "verdict_alpha": fit_verdict(t_alpha, prof.get("alpha_ann_pct"), 1.0),
            }
        else:
            block["portfolio_comparison"] = {
                "available": False, "benchmark": WORLD_BENCH,
                "reason": prof.get("reason") or tvw.get("reason") or "not computable"}
    except Exception as e:
        log(f"portfolio comparison failed: {type(e).__name__}: {e}")
        block["portfolio_comparison"] = {"available": False, "benchmark": WORLD_BENCH,
                                         "reason": f"{type(e).__name__}"}
    return block


def merge_into_analysis(analysis_json: str, block: dict) -> None:
    """Merge the additive `alpha_beta` block and surface β/α into `top_strip` so
    the metrics strip renders from a single source (schema stays 2.2)."""
    path = Path(analysis_json)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["alpha_beta"] = block
    strip = data.get("top_strip")
    if isinstance(strip, dict):
        strip["beta_3y"] = block.get("beta")
        strip["alpha_ann_pct"] = block.get("alpha_ann_pct")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    log(f"merged alpha_beta into {path.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description="α/β + CAPM + price-CAGR + Lynch prior + portfolio fit")
    ap.add_argument("--analysis-json", required=True,
                    help="analyze_ticker JSON, after intrinsic_value.py --update (for capm.rf)")
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--update", action="store_true",
                    help="Merge the result into the analysis JSON (key: alpha_beta) + top_strip")
    args = ap.parse_args()

    try:
        block = run(args.analysis_json, Path(args.out_dir), date.today().isoformat())
        if args.update and "error" not in block:
            merge_into_analysis(args.analysis_json, block)
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        print(json.dumps({"error": str(e), "error_type": type(e).__name__}))
        return 0  # non-fatal: report degrades, run continues

    print(json.dumps(block, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
