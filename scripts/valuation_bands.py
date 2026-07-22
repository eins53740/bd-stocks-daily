"""
valuation_bands.py — Own-history P/E & P/S multiple bands, forward-target
valuation (TIKR-style: target @ horizon + est. total return + IRR) and a
sensitivity table, for bd-stocks-daily v4 Phase B (spec §7).

Overlay-only: nothing here touches the composite score. The block this script
emits (`valuation_bands`) is additive to the schema-2.2 analysis JSON.

Data sources (exact endpoint + limit per source — spec §7 requirement):
  * Prices        — yfinance `Ticker.history(period="15y", interval="1mo")`
                    monthly closes; free, no key, works for non-US names.
  * EPS (US)      — Alpha Vantage `function=EARNINGS` `annualEarnings[]`
                    (`fiscalDateEnding`, `reportedEPS`), typically 15-25 years.
                    1 HTTP call per ticker, counted against the SHARED daily
                    budget in `_fin_history/_av_budget.json` (AV free tier =
                    25 req/day; financial_history.py already consumes up to
                    ~10; guard limit AV_DAILY_LIMIT=20).
  * EPS (non-US / AV exhausted / AV empty)
                  — yfinance `Ticker.income_stmt` "Diluted EPS"/"Basic EPS"
                    row, falling back to Net Income ÷ per-year "Share Issued"
                    (balance sheet). Depth ≈ 4-5 years — the band is EXPECTED
                    to run shallow on non-US names; `depth_years` is always
                    labelled (v4 audit M2).
  * Revenue/share — the financial_history.py cache
                    `_fin_history/{TICKER}.json` `annual` block (no re-fetch),
                    divided by CURRENT shares outstanding (per-year share
                    counts are not reliably available; caveat carried in
                    `ps_band.source`).

Cache: `_valuation/{SAFE_TICKER}.json`, TTL 80 days (annual data — same
rationale as financial_history). A fresh cache serves the ratio series
verbatim; band stats are recomputed against the current price each run.

All pure functions (band_stats, percentile_of, mean_price_in_window,
cagr_ladder_from_annual, growth_anchor, forward_target, sensitivity_table,
choose_eps_source) do no I/O and are unit-tested in
tests/test_valuation_depth.py. Any fetch failure degrades to the next source;
a total failure emits {"error": ...} with exit 0 (orchestrator continues).

Outputs a single JSON object on stdout; progress goes to stderr. With
--update, the block is also merged into the analysis JSON under the key
`valuation_bands` so downstream phases (intrinsic_value.py, the report) read
one file.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date, datetime, timedelta
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

import markets  # noqa: E402
import financial_history as fh  # noqa: E402  (shared AV budget + cache helpers)

OUT_DIR_DEFAULT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")

TTL_DAYS = 80
HORIZON_YEARS = 3            # forward target = FY+3 (TIKR presentation)
GROWTH_CLAMP = (-0.10, 0.30)  # sanity clamp on the growth anchor
SANE_IRR_RANGE = (-15.0, 30.0)  # outside ⇒ sanity_flag on the forward target
CONSERVATIVE_PCTL = 15       # "conservative" multiple = 15th percentile (spec §7)
AV_EARNINGS_URL = f"{fh.AV_BASE}?function=EARNINGS"


def log(msg: str) -> None:
    print(f"[valuation_bands] {msg}", file=sys.stderr)


# ===================================================================
# Pure functions (no I/O — unit-tested)
# ===================================================================
def percentile_of(values: list, x) -> float | None:
    """Percentile rank (0-100) of x within values (inclusive, midpoint ties)."""
    vals = [v for v in values if v is not None]
    if x is None or not vals:
        return None
    below = sum(1 for v in vals if v < x)
    equal = sum(1 for v in vals if v == x)
    return round(100.0 * (below + 0.5 * equal) / len(vals), 1)


def band_stats(series: list, current, source: str) -> dict:
    """Band summary for a historical ratio series (positive ratios only).

    `depth_years` counts the usable (positive-ratio) years; negative-EPS years
    are excluded from a P/E band and reported in `excluded_years`."""
    usable = [v for v in series if v is not None and v > 0]
    excluded = len([v for v in series if v is not None]) - len(usable)
    if not usable:
        return {"current": current, "min": None, "mean": None, "max": None,
                "percentile": None, "depth_years": 0, "excluded_years": excluded,
                "source": source}
    return {
        "current": round(current, 2) if current is not None else None,
        "min": round(min(usable), 2),
        "mean": round(statistics.mean(usable), 2),
        "median": round(statistics.median(usable), 2),
        "max": round(max(usable), 2),
        "percentile": percentile_of(usable, current),
        "depth_years": len(usable),
        "excluded_years": excluded,
        "source": source,
    }


def pe_series_records(eps_records: list, pe_series: list) -> list:
    """[{year, pe}] pairs for the persisted band series (Phase A NI-vs-P/E
    chart), keeping only usable positive ratios. `pe_series` is aligned 1:1
    with `eps_records`; an emptied (degraded) series yields []."""
    return [
        {"year": int(r["date"][:4]), "pe": round(v, 2)}
        for r, v in zip(eps_records, pe_series)
        if v is not None and v > 0
    ]


def justified_exit_pe(pe_band: dict | None) -> float | None:
    """The justified exit multiple for forward targets: the band MEDIAN capped
    at the band max. The median, not the mean — transition years with near-zero
    EPS produce outlier P/Es (e.g. ADSK 2016-18 >100×) that drag the mean far
    above anything a buyer should underwrite (live finding, 2026-07-22)."""
    if not pe_band:
        return None
    exit_pe = pe_band.get("median") or pe_band.get("mean")
    if exit_pe is not None and pe_band.get("max") is not None:
        exit_pe = min(exit_pe, pe_band["max"])
    return exit_pe


def mean_price_in_window(price_dates: list, price_closes: list,
                         end_iso: str, days: int = 365) -> float | None:
    """Mean close over the `days` window ending at `end_iso` (fiscal year).

    `price_dates` are ISO strings sorted ascending, `price_closes` aligned."""
    try:
        end = date.fromisoformat(end_iso[:10])
    except (ValueError, TypeError):
        return None
    start = end - timedelta(days=days)
    window = [c for d, c in zip(price_dates, price_closes)
              if c is not None and start <= date.fromisoformat(d[:10]) <= end]
    return statistics.mean(window) if window else None


def price_scale_factor(last_close, price_current) -> float:
    """Detect a pence-quoted (GBp/GBX) price history by self-consistency: the
    last monthly close vs the analysis JSON's ALREADY-NORMALISED price_current.
    A ratio around 100 (50-200, tolerating FX/EPS drift) means the history is
    in pence → scale by 0.01 (live EXPN.L finding: raw band was ~125× off).
    The inverse window guards against a pre-scaled history. Otherwise 1.0."""
    if not last_close or not price_current or price_current <= 0:
        return 1.0
    ratio = last_close / price_current
    if 50 <= ratio <= 200:
        return 0.01
    if 0.005 <= ratio <= 0.02:
        return 100.0
    return 1.0


def unit_consistency(series_latest, current) -> tuple[str, str | None]:
    """Cross-check the band's latest-year ratio against the known-consistent
    current ratio from analyze_ticker. Returns (status, message):
      ok       — within ±33%
      skewed   — off by 1.33-3× (typically statement-vs-trading currency, e.g.
                 USD statements under a GBP quote); band renders with a warning
      mismatch — off by >3×; the band is garbage and must degrade, not render
      unknown  — nothing to compare against"""
    if series_latest is None or current is None or current <= 0 or series_latest <= 0:
        return "unknown", None
    r = series_latest / current
    if r > 3 or r < 1 / 3:
        return "mismatch", (f"latest band ratio {series_latest:.1f} vs current {current:.1f} "
                            f"({r:.1f}×) — unit/currency mismatch, band degraded")
    if r > 1.33 or r < 0.75:
        return "skewed", (f"latest band ratio {series_latest:.1f} vs current {current:.1f} "
                          f"({r:.2f}×) — possible statement-vs-trading currency skew")
    return "ok", None


def choose_eps_source(suffix: str, has_av_key: bool, budget_allows: bool) -> str:
    """Which EPS source to use: 'alphavantage' only for US listings with a key
    and remaining shared daily budget; 'yfinance' otherwise (the M2 degradation
    path — non-US names are expected to run shallow)."""
    if suffix == "" and has_av_key and budget_allows:
        return "alphavantage"
    return "yfinance"


def cagr_ladder_from_annual(fy_labels: list, revenues: list) -> dict:
    """1/3/5/10/15-yr revenue CAGR ladder from annual FY series. Year-aware:
    each rung requires the FY exactly `window` years before the latest one, so
    a gap year nulls the rung instead of silently shrinking the window.

    10/15-yr rungs stay null until Phase E extends financial_history's 6-year
    annual cap. Input order is irrelevant; non-positive revenues are dropped."""
    by_year = {}
    for label, rev in zip(fy_labels, revenues):
        if rev is None or rev <= 0:
            continue
        digits = "".join(ch for ch in str(label) if ch.isdigit())
        if digits:
            by_year[int(digits)] = rev
    ladder = {f"{w}y": None for w in (1, 3, 5, 10, 15)}
    ladder["depth_years"] = len(by_year)
    if not by_year:
        return ladder
    latest = max(by_year)
    for window in (1, 3, 5, 10, 15):
        start_year = latest - window
        if start_year in by_year:
            ladder[f"{window}y"] = round(
                (by_year[latest] / by_year[start_year]) ** (1.0 / window) - 1.0, 4)
    return ladder


def growth_anchor(ladder: dict, consensus_eps_growth,
                  clamp: tuple = GROWTH_CLAMP) -> dict:
    """Growth rate anchored on the CAGR ladder + consensus — never a single
    guessed rate (spec §7). Median of the available inputs, clamped."""
    inputs = {}
    for key in ("1y", "3y", "5y", "10y", "15y"):
        if ladder.get(key) is not None:
            inputs[f"revenue_cagr_{key}"] = ladder[key]
    if consensus_eps_growth is not None:
        inputs["consensus_eps_growth"] = round(consensus_eps_growth, 4)
    if not inputs:
        return {"g": None, "basis": [], "clamped": False}
    med = statistics.median(inputs.values())
    lo, hi = clamp
    g = min(max(med, lo), hi)
    return {"g": round(g, 4), "basis": sorted(inputs), "inputs": inputs,
            "clamped": g != round(med, 10) and (med < lo or med > hi)}


def forward_target(eps_next_fy, eps_ttm, g, exit_pe, price,
                   dividend_rate, horizon_years: int = HORIZON_YEARS,
                   today: date | None = None) -> dict:
    """TIKR-style forward target: EPS path × justified exit P/E → target price
    @ explicit horizon + est. total return % + IRR (annualized) side by side.

    EPS path starts from the consensus next-FY estimate when available (grown
    `horizon_years - 1` further years), else from TTM EPS grown the full
    horizon. Dividends are held flat at the current rate (conservative,
    deterministic). Invalid (valid=false + reason) when EPS or growth anchor
    or exit multiple is missing/non-positive."""
    out = {"valid": False, "reason": None, "sanity_flag": None, "eps_horizon": None,
           "exit_pe": exit_pe, "target_price": None,
           "horizon_years": horizon_years, "horizon_label": None,
           "horizon_date": None, "est_total_return_pct": None,
           "irr_annualized_pct": None, "eps_basis": None}
    today = today or date.today()
    out["horizon_label"] = f"FY{today.year + horizon_years}"
    out["horizon_date"] = date(today.year + horizon_years, 12, 31).isoformat()
    if g is None:
        out["reason"] = "no growth anchor (no CAGR ladder rungs, no consensus)"
        return out
    if exit_pe is None or exit_pe <= 0:
        out["reason"] = "no justified exit P/E (own-history band unavailable)"
        return out
    if eps_next_fy is not None and eps_next_fy > 0:
        eps_h = eps_next_fy * (1 + g) ** (horizon_years - 1)
        out["eps_basis"] = "consensus_next_fy"
    elif eps_ttm is not None and eps_ttm > 0:
        eps_h = eps_ttm * (1 + g) ** horizon_years
        out["eps_basis"] = "eps_ttm"
    else:
        out["reason"] = "no positive EPS base (consensus and TTM both unusable)"
        return out
    target = eps_h * exit_pe
    out["eps_horizon"] = round(eps_h, 2)
    out["target_price"] = round(target, 2)
    if price and price > 0:
        divs = (dividend_rate or 0.0) * horizon_years
        total = (target + divs) / price - 1.0
        out["est_total_return_pct"] = round(total * 100, 1)
        out["irr_annualized_pct"] = round(
            (((target + divs) / price) ** (1.0 / horizon_years) - 1.0) * 100, 1)
    out["valid"] = True
    if out["irr_annualized_pct"] is not None and not (
            SANE_IRR_RANGE[0] <= out["irr_annualized_pct"] <= SANE_IRR_RANGE[1]):
        out["sanity_flag"] = (
            f"IRR {out['irr_annualized_pct']:+.1f}%/yr outside plausible range "
            f"[{SANE_IRR_RANGE[0]:.0f}%, {SANE_IRR_RANGE[1]:.0f}%] — exit multiple or "
            f"growth anchor likely distorted; treat as a scenario, not a target")
    return out


def sensitivity_table(pe_series: list, eps_horizon, revenue_ttm, shares_out,
                      g, net_margin_min, horizon_years: int = HORIZON_YEARS) -> dict:
    """Fair value at conservative (15th pct) / mean / historical-high multiples,
    plus one margin-bear row: FY+3 revenue/share × 5-yr-MIN net margin × mean
    multiple — margin trend modelled, not assumed flat (TIKR "Mistake #2")."""
    usable = sorted(v for v in pe_series if v is not None and v > 0)
    rows = []
    out = {"rows": rows, "margin_bear_row": None}
    if not usable or eps_horizon is None or eps_horizon <= 0:
        return out
    n = len(usable)
    p15 = usable[max(0, min(n - 1, round(CONSERVATIVE_PCTL / 100 * (n - 1))))]
    mean_m = statistics.mean(usable)
    for label, mult in (
        (f"conservative (p{CONSERVATIVE_PCTL} multiple)", p15),
        ("mean multiple", mean_m),
        ("historical-high multiple", max(usable)),
    ):
        rows.append({"label": label, "multiple": round(mult, 2),
                     "fair_value": round(eps_horizon * mult, 2)})
    if (revenue_ttm and shares_out and g is not None
            and net_margin_min is not None and net_margin_min > 0):
        rps_h = revenue_ttm * (1 + g) ** horizon_years / shares_out
        eps_bear = rps_h * net_margin_min
        out["margin_bear_row"] = {
            "label": "margin bear (5y-min net margin, mean multiple)",
            "net_margin_min": round(net_margin_min, 4),
            "multiple": round(mean_m, 2),
            "fair_value": round(eps_bear * mean_m, 2),
        }
    return out


# ===================================================================
# Fetchers (network — degrade cleanly)
# ===================================================================
def fetch_av_eps(ticker: str, key: str) -> tuple[list, int]:
    """Alpha Vantage EARNINGS → [{'date': fiscalDateEnding, 'eps': float}], calls.

    1 HTTP call, counted even when the response is empty/throttled."""
    data = fh._http_get_json(f"{AV_EARNINGS_URL}&symbol={ticker}&apikey={key}")
    if not isinstance(data, dict) or "annualEarnings" not in data:
        if isinstance(data, dict) and (data.get("Note") or data.get("Information")):
            log("AV rate-limited (Note/Information response)")
        else:
            log("AV EARNINGS empty or malformed")
        return [], 1
    records = []
    for r in data.get("annualEarnings", []) or []:
        d = r.get("fiscalDateEnding")
        eps = fh._av_num(r.get("reportedEPS"))
        if d and eps is not None:
            records.append({"date": d, "eps": eps})
    records.sort(key=lambda r: r["date"])
    return records, 1


def fetch_yf_eps(tk) -> list:
    """yfinance annual EPS: income_stmt 'Diluted EPS'/'Basic EPS' row, falling
    back to Net Income ÷ per-year 'Share Issued'. Depth ≈ 4-5 years."""
    records = []
    try:
        is_stmt = tk.income_stmt
        if is_stmt is None or is_stmt.empty:
            return records
        eps_label = next((l for l in ("Diluted EPS", "Basic EPS") if l in is_stmt.index), None)
        if eps_label is not None:
            row = is_stmt.loc[eps_label].dropna()
            for col, val in row.items():
                records.append({"date": str(col)[:10], "eps": float(val)})
        else:
            ni = is_stmt.loc["Net Income"].dropna() if "Net Income" in is_stmt.index else None
            bs = tk.balance_sheet
            so_label = None
            if bs is not None and not bs.empty:
                so_label = next((l for l in ("Share Issued", "Ordinary Shares Number") if l in bs.index), None)
            if ni is not None and so_label:
                so = bs.loc[so_label].dropna()
                for col, val in ni.items():
                    if col in so.index and float(so[col]) > 0:
                        records.append({"date": str(col)[:10], "eps": float(val) / float(so[col])})
    except Exception as e:
        log(f"yfinance EPS fetch failed: {type(e).__name__}: {e}")
    records.sort(key=lambda r: r["date"])
    return records


def fetch_monthly_prices(tk) -> tuple[list, list]:
    """15y of monthly closes → (iso_dates asc, closes)."""
    try:
        h = tk.history(period="15y", interval="1mo")
        if h is None or h.empty:
            return [], []
        dates = [str(idx)[:10] for idx in h.index]
        closes = [float(c) if c == c else None for c in h["Close"].tolist()]
        return dates, closes
    except Exception as e:
        log(f"price history fetch failed: {type(e).__name__}: {e}")
        return [], []


def load_fin_history_annual(out_dir: Path, ticker: str) -> tuple[list, list]:
    """(fy_labels, revenues) from the financial_history cache — no re-fetch."""
    path = out_dir / "_fin_history" / f"{fh.safe_ticker_filename(ticker)}.json"
    cached = fh.read_cache(path)
    if not isinstance(cached, dict):
        return [], []
    annual = cached.get("annual") or {}
    return annual.get("labels") or [], annual.get("revenue") or []


# ===================================================================
# Main
# ===================================================================
def build_eps_series(ticker: str, tk, out_dir: Path, force: bool) -> tuple[list, str]:
    """EPS records via cache → AV (US, shared budget) → yfinance. Returns
    (records, source)."""
    val_dir = out_dir / "_valuation"
    val_dir.mkdir(parents=True, exist_ok=True)
    cache_path = val_dir / f"{fh.safe_ticker_filename(ticker)}.json"
    now_iso = datetime.now().isoformat()
    today_iso = date.today().isoformat()

    if not force:
        cached = fh.read_cache(cache_path)
        if (isinstance(cached, dict) and cached.get("eps_records")
                and fh.cache_is_fresh(cached.get("fetched_at", ""), now_iso, TTL_DAYS)):
            log(f"EPS cache hit for {ticker} (fresh, no network)")
            return cached["eps_records"], cached.get("eps_source", "cache")

    suffix = markets.suffix_of(ticker)
    key = fh.read_alphavantage_key() if suffix == "" else None
    budget_path = out_dir / "_fin_history" / "_av_budget.json"
    budget = fh.load_budget(budget_path, today_iso)
    allowed = fh.av_budget_allows(budget, today_iso, fh.AV_DAILY_LIMIT)
    source = choose_eps_source(suffix, bool(key), allowed)
    if suffix == "" and key and not allowed:
        log(f"AV daily budget exhausted ({budget['calls']}/{fh.AV_DAILY_LIMIT}); using yfinance")

    records = []
    if source == "alphavantage":
        records, calls = fetch_av_eps(ticker, key)
        budget["calls"] += calls
        fh.save_budget(budget_path, budget)
        if not records:
            log("AV EPS empty; falling back to yfinance")
            source = "yfinance"
    if not records:
        records = fetch_yf_eps(tk)
        source = "yfinance"

    if records:
        fh.write_cache(cache_path, {"ticker": ticker, "fetched_at": now_iso,
                                    "eps_source": source, "eps_records": records})
    return records, source


def run(ticker: str, analysis_json: str | None, out_dir: Path, force: bool) -> dict:
    analysis = {}
    if analysis_json:
        try:
            analysis = json.loads(Path(analysis_json).read_text(encoding="utf-8"))
        except Exception as e:
            log(f"could not read analysis-json: {e}")
    fund = analysis.get("fundamentals") or {}
    consensus = analysis.get("consensus") or {}
    price = analysis.get("price_current")
    warnings: list = []

    import yfinance as yf
    tk = yf.Ticker(ticker)

    eps_records, eps_source = build_eps_series(ticker, tk, out_dir, force)
    price_dates, price_closes = fetch_monthly_prices(tk)

    # Pence-quoted histories (GBp/GBX) would inflate every ratio ~100×.
    last_close = next((c for c in reversed(price_closes) if c), None)
    scale = price_scale_factor(last_close, price)
    if scale != 1.0:
        price_closes = [c * scale if c is not None else None for c in price_closes]
        warnings.append(f"price history rescaled ×{scale} (pence-quote detected)")

    # --- Own-history P/E band ---
    pe_series = []
    for r in eps_records:
        mp = mean_price_in_window(price_dates, price_closes, r["date"])
        pe_series.append(mp / r["eps"] if (mp and r["eps"] and r["eps"] > 0) else None)
    pe_band = band_stats(pe_series, fund.get("pe_ratio"),
                         f"{eps_source} EPS × yfinance 15y monthly prices")
    pe_latest = next((v for v in reversed(pe_series) if v and v > 0), None)
    pe_band["unit_check"], msg = unit_consistency(pe_latest, fund.get("pe_ratio"))
    if pe_band["unit_check"] == "mismatch":
        pe_band = band_stats([], fund.get("pe_ratio"),
                             f"{eps_source} EPS × yfinance prices — DEGRADED: unit mismatch")
        pe_band["unit_check"] = "mismatch"
        pe_series = []
        warnings.append(f"P/E band degraded: {msg}")
    elif msg:
        warnings.append(f"P/E band: {msg}")
    # Persist the per-year series for the Phase A NI-vs-P/E chart. Placed after
    # the mismatch degradation (pe_series is emptied there) so a degraded band
    # never ships a garbage series. Additive key; parsers tolerate absence.
    pe_band["series"] = pe_series_records(eps_records, pe_series)
    if pe_band["depth_years"] < 5:
        warnings.append(f"P/E band shallow: {pe_band['depth_years']}y "
                        f"(source {eps_source}; expected on non-US names)")

    # --- Own-history P/S band (fin-history annual revenue, current shares) ---
    fy_labels, revenues = load_fin_history_annual(out_dir, ticker)
    shares = fund.get("shares_out")
    ps_series = []
    if shares and shares > 0:
        for label, rev in zip(fy_labels, revenues):
            if not rev or rev <= 0:
                ps_series.append(None)
                continue
            mp = mean_price_in_window(price_dates, price_closes, f"{label[2:]}-12-31")
            ps_series.append(mp / (rev / shares) if mp else None)
    ps_band = band_stats(ps_series, fund.get("ps_ratio"),
                         "fin_history annual revenue ÷ current shares × yfinance prices")
    ps_latest = next((v for v in reversed(ps_series) if v and v > 0), None)
    ps_band["unit_check"], msg = unit_consistency(ps_latest, fund.get("ps_ratio"))
    if ps_band["unit_check"] == "mismatch":
        ps_band = band_stats([], fund.get("ps_ratio"),
                             "fin_history revenue × yfinance prices — DEGRADED: unit mismatch")
        ps_band["unit_check"] = "mismatch"
        warnings.append(f"P/S band degraded: {msg}")
    elif msg:
        warnings.append(f"P/S band: {msg}")
    if not fy_labels:
        warnings.append("P/S band: no financial_history cache — run Phase 2.2 first")

    # --- CAGR ladder + growth anchor ---
    ladder = cagr_ladder_from_annual(fy_labels, revenues)
    if ladder.get("5y") is None and fund.get("revenue_cagr_5y") is not None:
        ladder["5y"] = round(fund["revenue_cagr_5y"], 4)
        ladder["5y_basis"] = fund.get("revenue_cagr_basis", "analyze_ticker")
    eps_cur = consensus.get("eps_estimate_current_year")
    eps_next = consensus.get("eps_estimate_next_year")
    cons_growth = (eps_next / eps_cur - 1.0) if (eps_cur and eps_next and eps_cur > 0) else None
    anchor = growth_anchor(ladder, cons_growth)

    # --- Forward target (justified exit P/E = own-history MEDIAN, cap = own max) ---
    exit_pe = justified_exit_pe(pe_band)
    eps_ttm = fund.get("eps_ttm")
    if eps_ttm is None and price and fund.get("pe_ratio"):
        eps_ttm = price / fund["pe_ratio"]
    fwd = forward_target(eps_next, eps_ttm, anchor["g"], exit_pe, price,
                         fund.get("dividend_rate"))

    # --- Sensitivity table ---
    sens = sensitivity_table(pe_series, fwd.get("eps_horizon"),
                             fund.get("revenue_ttm"), shares, anchor["g"],
                             fund.get("net_margin_5y_min"))

    block = {
        "fetched_at": datetime.now().isoformat(),
        "pe_band": pe_band,
        "ps_band": ps_band,
        "cagr_ladder": ladder,
        "growth_anchor": anchor,
        "forward_target": fwd,
        "sensitivity": sens,
        "warnings": warnings,
    }
    return block


def merge_into_analysis(analysis_json: str, block: dict) -> None:
    """Write the block into the analysis JSON under `valuation_bands`
    (additive key; schema stays 2.2)."""
    path = Path(analysis_json)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["valuation_bands"] = block
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    log(f"merged valuation_bands into {path.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Own-history P/E & P/S bands + forward target + sensitivity")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--analysis-json", default=None,
                    help="Path to the analyze_ticker output JSON (fundamentals + consensus)")
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--force", action="store_true", help="Ignore the EPS cache and refetch")
    ap.add_argument("--update", action="store_true",
                    help="Merge the result into the analysis JSON (key: valuation_bands)")
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
