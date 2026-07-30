"""
financial_history.py — Quarterly + annual EBITDA / FCF / revenue history with a
4-quarter forward forecast, for the bd-stocks-daily fundamentals chart.

Ground-truth numbers only: Alpha Vantage (US listings, with a daily-budget guard)
→ yfinance fallback (also the only source for non-US names). The LLM never
touches these figures — it only draws narrative around the chart this produces.

Cache: {out_dir}/_fin_history/{SAFE_TICKER}.json, TTL 80 days. A fresh cache is
printed verbatim and no network call is made.

Forecast: the next 4 fiscal quarters. Revenue is either interpolated from the
sell-side consensus FY revenue estimates (>=3 analysts) using a seasonal split,
or — when consensus is thin/absent — a seasonal-naive trend extrapolation.
EBITDA/FCF are the revenue path times the trailing median margin; the forecast is
suppressed if fewer than 4 quarters of margin history are available.

The pure functions (seasonal_split, median_margin, build_forecast,
cache_is_fresh, av_budget_allows, and the label helpers) do no I/O and are
unit-tested in tests/test_financial_history.py. Everything network-facing
degrades cleanly: any fetch failure falls through to the next source, and a total
failure emits an {"error": ...} JSON with exit 0 so the orchestrator can skip the
chart without aborting the run.

Outputs a single JSON object on stdout; progress goes to stderr only.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Force UTF-8 on Windows so unicode in output doesn't crash the cp1252 console.
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

import markets  # noqa: E402  (sibling helper — suffix_of)

OUT_DIR_DEFAULT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
BD_FINANCE = Path(r"C:\Github\BD\Finance\BD_Finance")
API_KEYS_PATH = BD_FINANCE / "config" / "api_keys.txt"

TTL_DAYS = 80
AV_DAILY_LIMIT = 20        # stay well under Alpha Vantage's free 25/day
AV_THROTTLE_RETRIES = 2    # attempts per endpoint when AV answers with a throttle note
AV_THROTTLE_DELAY_S = 20.0  # free tier is 5 req/min — space the retry past the window
MAX_QUARTERS = 40
# Annual-history depth. Lifted from 6 in v4 Phase E so the 10/15-yr revenue-CAGR
# rungs (valuation_bands.cagr_ladder_from_annual) can populate whenever a source
# reaches back that far. Free sources rarely do (yfinance ~4y, Alpha Vantage ~5y),
# so on most names the deep rungs stay null and are labelled by depth_years —
# the price/total-return CAGR ladder (alpha_beta.py) is the real long-horizon
# signal. No forced refetch: deeper annual materialises on the next TTL refetch.
MAX_ANNUAL_YEARS = 20
AV_BASE = "https://www.alphavantage.co/query"
UA = "Mozilla/5.0 (compatible; bd-stocks-daily/1.0)"


def log(msg: str) -> None:
    print(f"[financial_history] {msg}", file=sys.stderr)


# ===================================================================
# Pure functions (no I/O — unit-tested)
# ===================================================================
def safe_ticker_filename(ticker: str) -> str:
    """Cache-safe filename stem for a ticker: strip only path separators, keep dots.

    'BRK.B' -> 'BRK.B'; 'A/B' -> 'A_B'. Dots are kept so exchange suffixes
    (e.g. '2330.TW') survive.
    """
    return ticker.replace("/", "_").replace("\\", "_")


def quarter_label_from_date(iso_date: str) -> str:
    """Calendar-quarter label from a fiscalDateEnding string: '2016-07-31' -> '2016Q3'."""
    year = int(iso_date[:4])
    month = int(iso_date[5:7])
    quarter = (month - 1) // 3 + 1
    return f"{year}Q{quarter}"


def next_quarter_label(label: str) -> str:
    """Next calendar-quarter label: '2026Q2' -> '2026Q3', '2026Q4' -> '2027Q1'."""
    year = int(label[:4])
    quarter = int(label[5:])
    quarter += 1
    if quarter > 4:
        quarter = 1
        year += 1
    return f"{year}Q{quarter}"


def _fy_year(label: str) -> int:
    """Numeric year from an 'FY2023'/'2023' label (trailing digits)."""
    digits = "".join(ch for ch in label if ch.isdigit())
    return int(digits) if digits else 0


def cache_is_fresh(fetched_at_iso: str, now_iso: str, ttl_days: int = TTL_DAYS) -> bool:
    """True if a cache stamped `fetched_at_iso` is within `ttl_days` of `now_iso`.

    Timezone offsets are dropped before comparing — at an 80-day TTL the offset is
    noise. A future-stamped cache (clock skew) is treated as fresh. Unparseable
    input is treated as stale (False)."""
    try:
        fetched = datetime.fromisoformat(fetched_at_iso).replace(tzinfo=None)
        now = datetime.fromisoformat(now_iso).replace(tzinfo=None)
    except (ValueError, TypeError):
        return False
    return (now - fetched) <= timedelta(days=ttl_days)


def cache_has_net_income(cached: dict | None) -> bool:
    """Whether a cached output already carries the annual net_income series
    (added in v4 Phase A). Key presence, not values — a ticker whose statements
    genuinely lack net income caches a list of Nones and stays fresh. Pre-Phase-A
    caches lack the key and must be treated as stale even inside the TTL,
    otherwise the NI-vs-P/E chart silently skips for ~80 days."""
    if not isinstance(cached, dict):
        return False
    annual = cached.get("annual")
    return isinstance(annual, dict) and "net_income" in annual


def cache_has_fcf(cached: dict | None) -> bool:
    """Whether a cached output carries a usable quarterly FCF series.

    Unlike `cache_has_net_income` this checks VALUES, not key presence, because
    the failure being guarded against is a *partial* Alpha Vantage fetch: when
    INCOME_STATEMENT succeeds but CASH_FLOW is throttled, the FCF column comes
    back all-None while revenue and EBITDA are complete, and the cache was
    written as a success and served for the full 80-day TTL. That silently cost
    the flagship EBITDA-vs-FCF chart its FCF line — and suppressed the forecast —
    on 10 of 33 cached names (MSFT, TSM, PYPL, MA, ADSK, TTD among them).

    A name whose FCF is genuinely unavailable re-fetches once per run and lands
    back here; that costs 2 AV calls against a 25/day budget, which is the right
    trade for not silently serving a broken series for three months."""
    if not isinstance(cached, dict):
        return False
    series = cached.get("series")
    if not isinstance(series, dict) or "fcf" not in series:
        return False
    fcf = series.get("fcf") or []
    return any(v is not None for v in fcf)


def av_budget_allows(budget: dict, today_iso: str, limit: int = AV_DAILY_LIMIT) -> bool:
    """Whether another Alpha Vantage call is allowed under the daily budget.

    The counter resets when the stored date isn't today. A non-dict budget is
    treated as empty (allowed)."""
    if not isinstance(budget, dict):
        return True
    if budget.get("date") != today_iso:
        return True
    return int(budget.get("calls", 0)) < limit


def seasonal_split(quarterly_revenue_by_fy: dict) -> list:
    """Average share of full-year revenue falling in each fiscal quarter.

    Uses the last up-to-3 *complete* fiscal years (exactly 4 positive quarters).
    Returns 4 shares summing to 1 in fiscal-quarter order. Falls back to a uniform
    [0.25]*4 when fewer than 2 complete years are available."""
    complete = []
    for label in sorted(quarterly_revenue_by_fy, key=_fy_year):
        vals = quarterly_revenue_by_fy[label]
        if len(vals) == 4 and all(v is not None and v > 0 for v in vals):
            complete.append(vals)
    complete = complete[-3:]
    if len(complete) < 2:
        return [0.25, 0.25, 0.25, 0.25]
    shares_per_fy = [[v / sum(vals) for v in vals] for vals in complete]
    avg = [statistics.mean(s[i] for s in shares_per_fy) for i in range(4)]
    total = sum(avg)
    return [a / total for a in avg]


def median_margin(series_num: list, series_den: list) -> float | None:
    """Median of the pairwise num/den ratios over the aligned quarters.

    None/zero-denominator pairs are skipped. Returns None when fewer than 4 valid
    pairs remain (too little history for a trustworthy margin)."""
    ratios = []
    for num, den in zip(series_num, series_den):
        if num is None or den is None or den == 0:
            continue
        ratios.append(num / den)
    if len(ratios) < 4:
        return None
    return statistics.median(ratios)


def _consensus_revenue_path(cur_year: float, next_year: float, seasonal: list, k: int) -> list:
    """4-quarter revenue path from FY consensus totals + seasonal split.

    `k` = quarters of the current FY already reported. The remaining (4-k)
    quarters of the current FY draw on `cur_year`; the first `k` quarters of the
    next FY draw on `next_year`."""
    path = [cur_year * seasonal[fq] for fq in range(k, 4)]
    path += [(next_year if next_year is not None else cur_year) * seasonal[fq] for fq in range(k)]
    return path


def _trend_revenue_path(revenue: list) -> list | None:
    """Seasonal-naive revenue path: same-quarter-last-year x trailing-4Q YoY growth."""
    n = len(revenue)
    if n < 4:
        return None

    def _s(seq):
        return sum(x for x in seq if x is not None)

    if n >= 8 and _s(revenue[-8:-4]) > 0:
        growth = _s(revenue[-4:]) / _s(revenue[-8:-4])
    elif n >= 5 and revenue[-5]:
        growth = revenue[-1] / revenue[-5]
    else:
        growth = 1.0
    if growth <= 0:
        growth = 1.0

    last_valid = next((x for x in reversed(revenue) if x is not None), None)
    if last_valid is None:
        return None
    path = []
    for i in range(4):
        idx = n - 4 + i
        base = revenue[idx] if 0 <= idx < n and revenue[idx] is not None else last_valid
        path.append(base * growth)
    return path


def build_forecast(consensus: dict | None, hist: dict, seasonal: list) -> dict | None:
    """Next-4-quarter revenue / EBITDA / FCF forecast, or None if suppressed.

    Revenue path: sell-side consensus (>=3 analysts, FY revenue estimates present)
    interpolated across the fiscal quarters, else a seasonal-naive trend
    extrapolation. EBITDA/FCF = revenue path x trailing median margin. Returns
    None (forecast suppressed) when either margin has fewer than 4 quarters of
    history."""
    revenue = hist.get("revenue") or []
    ebitda = hist.get("ebitda") or []
    fcf = hist.get("fcf") or []
    labels = hist.get("labels") or []
    if not revenue or not labels:
        return None

    ebitda_margin = median_margin(ebitda, revenue)
    fcf_margin = median_margin(fcf, revenue)
    if ebitda_margin is None or fcf_margin is None:
        return None

    k = max(0, min(3, int(hist.get("quarters_reported_current_fy") or 0)))
    cur = consensus.get("revenue_estimate_current_year") if consensus else None
    nxt = consensus.get("revenue_estimate_next_year") if consensus else None
    acount = consensus.get("analyst_count") if consensus else None

    use_consensus = (
        consensus is not None
        and isinstance(acount, (int, float))
        and acount >= 3
        and cur is not None
        and (k == 0 or nxt is not None)
    )
    if use_consensus:
        rev_path = _consensus_revenue_path(cur, nxt, seasonal, k)
        basis = "consensus_revenue_x_trailing_margin"
    else:
        rev_path = _trend_revenue_path(revenue)
        basis = "trend_extrapolation_no_consensus"

    if not rev_path or len(rev_path) != 4:
        return None

    fc_labels = []
    cursor = labels[-1]
    for _ in range(4):
        cursor = next_quarter_label(cursor)
        fc_labels.append(cursor)

    return {
        "labels": fc_labels,
        "revenue": [round(r, 2) for r in rev_path],
        "ebitda": [round(r * ebitda_margin, 2) for r in rev_path],
        "fcf": [round(r * fcf_margin, 2) for r in rev_path],
        "basis": basis,
    }


# ===================================================================
# Series assembly (shared by both fetch paths)
# ===================================================================
def group_revenue_by_fy(records: list, fy_end_month: int) -> dict:
    """Group quarterly revenue into fiscal-year buckets (fiscal-quarter order).

    A quarter ending in month m of year y belongs to the FY ending in year y when
    m <= fy_end_month, else year y+1. Each bucket's revenues are ordered by date."""
    buckets: dict[int, list] = {}
    for r in records:
        y = int(r["date"][:4])
        m = int(r["date"][5:7])
        fy_year = y if m <= fy_end_month else y + 1
        buckets.setdefault(fy_year, []).append((r["date"], r["revenue"]))
    out = {}
    for fy_year, items in buckets.items():
        items.sort(key=lambda t: t[0])
        out[f"FY{fy_year}"] = [rev for _, rev in items]
    return out


def quarters_in_current_fy(revenue_by_fy: dict) -> int:
    """Quarters reported in the newest (incomplete) fiscal year; 0 if it's complete."""
    if not revenue_by_fy:
        return 0
    newest = max(revenue_by_fy, key=_fy_year)
    n = len(revenue_by_fy[newest])
    return 0 if n >= 4 else n


def _quarter_series(records: list) -> dict:
    return {
        "labels": [quarter_label_from_date(r["date"]) for r in records],
        "revenue": [r["revenue"] for r in records],
        "ebitda": [r["ebitda"] for r in records],
        "fcf": [r["fcf"] for r in records],
    }


def _annual_series(records: list) -> dict:
    # net_income via .get(): older/partial records without the key (pre-Phase A
    # caches, thin non-US statements) must map to None, never KeyError.
    return {
        "labels": [f"FY{r['date'][:4]}" for r in records],
        "revenue": [r["revenue"] for r in records],
        "ebitda": [r["ebitda"] for r in records],
        "fcf": [r["fcf"] for r in records],
        "net_income": [r.get("net_income") for r in records],
    }


def assemble_hist(source: str, currency: str, records: list, annual_records: list,
                  fy_end_month: int, warnings: list) -> dict:
    """Normalise raw quarterly/annual records into the hist block used downstream."""
    series = _quarter_series(records)
    revenue_by_fy = group_revenue_by_fy(records, fy_end_month)
    return {
        "source": source,
        "currency": currency,
        "series": series,
        "annual": _annual_series(annual_records),
        "quarters_available": len(records),
        "quarters_reported_current_fy": quarters_in_current_fy(revenue_by_fy),
        "revenue_by_fy": revenue_by_fy,
        "labels": series["labels"],
        "revenue": series["revenue"],
        "ebitda": series["ebitda"],
        "fcf": series["fcf"],
        "warnings": warnings,
    }


# ===================================================================
# Alpha Vantage (US listings only)
# ===================================================================
def read_alphavantage_key() -> str | None:
    """First api_keys.txt value whose name starts with 'api_key_alphavantage'."""
    try:
        from api_keys_reader import api_keys_reader
    except Exception:
        if str(BD_FINANCE) not in sys.path:
            sys.path.insert(0, str(BD_FINANCE))
        try:
            from api_keys_reader import api_keys_reader
        except Exception as e:
            log(f"could not import api_keys_reader: {e}")
            return None
    keys = api_keys_reader(str(API_KEYS_PATH))
    for name, value in keys.items():
        if name.startswith("api_key_alphavantage") and value:
            return value
    return None


def _av_is_throttled(payload) -> bool:
    """Alpha Vantage signals a rate limit with HTTP 200 and a Note/Information
    key instead of data — so it looks like a successful, empty response."""
    return isinstance(payload, dict) and bool(
        payload.get("Note") or payload.get("Information"))


def _av_get_with_retry(url: str, label: str, attempts: int = AV_THROTTLE_RETRIES,
                       delay_s: float = AV_THROTTLE_DELAY_S, sleep=None) -> tuple:
    """GET an AV endpoint, retrying only when the response is a throttle note.
    Returns (payload, calls_made) so the daily budget counts every request.

    The free tier allows 5 requests/minute. fetch_alphavantage fires
    INCOME_STATEMENT and CASH_FLOW back-to-back and valuation_bands adds an
    EARNINGS call in the same run, so the second or third request in that burst
    is routinely throttled — which used to silently produce an all-None FCF
    column (see cache_has_fcf). Spacing the retry is what actually fixes it;
    everything else only made the failure visible."""
    sleeper = sleep if sleep is not None else _default_sleep
    payload, calls = None, 0
    for attempt in range(1, max(1, attempts) + 1):
        calls += 1
        try:
            payload = _http_get_json(url)
        except Exception as e:
            log(f"AV {label} failed: {type(e).__name__}: {e}")
            payload = None
        if not _av_is_throttled(payload):
            return payload, calls
        if attempt < attempts:
            log(f"AV {label} throttled — retrying in {delay_s:.0f}s "
                f"(attempt {attempt}/{attempts})")
            sleeper(delay_s)
    return payload, calls


def _default_sleep(seconds: float) -> None:
    import time
    time.sleep(seconds)


def _http_get_json(url: str) -> dict | None:
    """GET the URL and parse JSON. requests if available, else urllib. None on error."""
    text = None
    try:
        import requests
        resp = requests.get(url, timeout=20, headers={"User-Agent": UA})
        if resp.status_code != 200:
            return None
        text = resp.text
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            text = resp.read().decode("utf-8", "replace")
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _av_num(value) -> float | None:
    """Alpha Vantage numeric string -> float. 'None'/''/missing -> None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "none":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _av_currency(reports: list, default: str = "USD") -> str:
    """reportedCurrency from the newest report, ignoring AV's literal "None"."""
    for r in reports or []:
        cur = r.get("reportedCurrency")
        if isinstance(cur, str) and cur.strip() and cur.strip().lower() != "none":
            return cur.strip()
    return default


def _av_records(quarterly_income: list, cf_by_date: dict) -> list:
    """Build oldest->newest quarterly records from AV income + cashflow reports."""
    records = []
    for r in quarterly_income:
        d = r.get("fiscalDateEnding")
        if not d:
            continue
        rev = _av_num(r.get("totalRevenue"))
        ebitda = _av_num(r.get("ebitda"))
        if ebitda is None:
            oi = _av_num(r.get("operatingIncome"))
            da = _av_num(r.get("depreciationAndAmortization"))
            if oi is not None and da is not None:
                ebitda = oi + da
        fcf = None
        cf = cf_by_date.get(d)
        if cf:
            ocf = _av_num(cf.get("operatingCashflow"))
            capex = _av_num(cf.get("capitalExpenditures"))
            if ocf is not None and capex is not None:
                # AV reports capitalExpenditures as a positive magnitude.
                fcf = ocf - capex
        records.append({"date": d, "revenue": rev, "ebitda": ebitda, "fcf": fcf})
    records.sort(key=lambda r: r["date"])
    return records[-MAX_QUARTERS:]


def _av_annual_records(annual_income: list, acf_by_date: dict) -> list:
    records = []
    for r in annual_income:
        d = r.get("fiscalDateEnding")
        if not d:
            continue
        rev = _av_num(r.get("totalRevenue"))
        ebitda = _av_num(r.get("ebitda"))
        if ebitda is None:
            oi = _av_num(r.get("operatingIncome"))
            da = _av_num(r.get("depreciationAndAmortization"))
            if oi is not None and da is not None:
                ebitda = oi + da
        fcf = None
        cf = acf_by_date.get(d)
        if cf:
            ocf = _av_num(cf.get("operatingCashflow"))
            capex = _av_num(cf.get("capitalExpenditures"))
            if ocf is not None and capex is not None:
                fcf = ocf - capex
        records.append({"date": d, "revenue": rev, "ebitda": ebitda, "fcf": fcf,
                        "net_income": _av_num(r.get("netIncome"))})
    records.sort(key=lambda r: r["date"])
    return records[-MAX_ANNUAL_YEARS:]


def fetch_alphavantage(ticker: str, key: str) -> tuple[dict | None, int]:
    """Fetch quarterly+annual series from Alpha Vantage. Returns (hist|None, calls_made).

    calls_made counts the HTTP requests issued (for the daily-budget counter) even
    when the response is empty or throttled."""
    calls = 0
    income, n = _av_get_with_retry(
        f"{AV_BASE}?function=INCOME_STATEMENT&symbol={ticker}&apikey={key}",
        "INCOME_STATEMENT")
    calls += n
    cashflow, n = _av_get_with_retry(
        f"{AV_BASE}?function=CASH_FLOW&symbol={ticker}&apikey={key}", "CASH_FLOW")
    calls += n

    if not isinstance(income, dict) or "quarterlyReports" not in income:
        # Throttle/limit responses carry a 'Note'/'Information' key instead of data.
        if isinstance(income, dict) and (income.get("Note") or income.get("Information")):
            log("AV rate-limited (Note/Information response)")
        else:
            log("AV income statement empty or malformed")
        return None, calls

    quarterly_income = income.get("quarterlyReports", []) or []
    annual_income = income.get("annualReports", []) or []
    cf_quarterly = (cashflow.get("quarterlyReports", []) if isinstance(cashflow, dict) else []) or []
    cf_annual = (cashflow.get("annualReports", []) if isinstance(cashflow, dict) else []) or []
    cf_by_date = {r.get("fiscalDateEnding"): r for r in cf_quarterly}
    acf_by_date = {r.get("fiscalDateEnding"): r for r in cf_annual}

    # A throttled CASH_FLOW call used to pass silently: income data is complete,
    # so the fetch logged "AV ok" and cached an all-None FCF column for 80 days.
    # Say so instead — the caller decides, and cache_has_fcf() forces a refetch.
    av_warnings = []
    if not cf_quarterly:
        note = ""
        if isinstance(cashflow, dict) and (cashflow.get("Note") or cashflow.get("Information")):
            note = " (rate-limited)"
        elif not isinstance(cashflow, dict):
            note = " (request failed)"
        msg = f"AV CASH_FLOW returned no quarterly reports{note} — FCF series unavailable"
        log(msg)
        av_warnings.append(msg)

    records = _av_records(quarterly_income, cf_by_date)
    if not records:
        log("AV returned no usable quarterly rows")
        return None, calls
    annual_records = _av_annual_records(annual_income, acf_by_date)

    # AV sends absent strings as the literal "None", which is truthy — so this
    # used to overwrite the USD default with the word "None" and print it on the
    # chart axis (MSFT, 2026-07-30).
    currency = _av_currency(quarterly_income, "USD")

    # Fiscal year-end month from the most recent annual report; default December.
    fy_end_month = 12
    if annual_income and annual_income[0].get("fiscalDateEnding"):
        fy_end_month = int(annual_income[0]["fiscalDateEnding"][5:7])

    n_fcf = sum(1 for r in records if r.get("fcf") is not None)
    log(f"AV ok: {len(records)} quarters ({n_fcf} with FCF), "
        f"{len(annual_records)} years, currency={currency}")
    return assemble_hist("alphavantage", currency, records, annual_records,
                         fy_end_month, av_warnings), calls


# ===================================================================
# yfinance fallback (all markets)
# ===================================================================
def _safe_df(fn):
    try:
        df = fn()
        return df if df is not None and not df.empty else None
    except Exception:
        return None


def _row(df, names: list):
    if df is None:
        return None
    for nm in names:
        if nm in df.index:
            return df.loc[nm]
    return None


def _col_date(col) -> str:
    try:
        return col.strftime("%Y-%m-%d")
    except Exception:
        return str(col)[:10]


def _cell(row, col) -> float | None:
    if row is None:
        return None
    try:
        v = row[col]
    except Exception:
        return None
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _yf_records(fin_df, cf_df) -> list:
    """Quarterly/annual records from yfinance financials + cashflow DataFrames."""
    if fin_df is None or fin_df.empty:
        return []
    rev_row = _row(fin_df, ["Total Revenue"])
    ebitda_row = _row(fin_df, ["EBITDA", "Normalized EBITDA"])
    ni_row = _row(fin_df, ["Net Income", "Net Income Common Stockholders"])
    fcf_row = _row(cf_df, ["Free Cash Flow"])
    ocf_row = _row(cf_df, ["Operating Cash Flow"])
    capex_row = _row(cf_df, ["Capital Expenditure"])
    records = []
    for col in fin_df.columns:
        d = _col_date(col)
        rev = _cell(rev_row, col)
        ebitda = _cell(ebitda_row, col)
        fcf = _cell(fcf_row, col)
        if fcf is None:
            ocf = _cell(ocf_row, col)
            capex = _cell(capex_row, col)
            if ocf is not None and capex is not None:
                # yfinance reports Capital Expenditure as a negative cash outflow,
                # so free cash flow = operating cash flow + capex.
                fcf = ocf + capex
        records.append({"date": d, "revenue": rev, "ebitda": ebitda, "fcf": fcf,
                        "net_income": _cell(ni_row, col)})
    records.sort(key=lambda r: r["date"])
    return records


def fetch_yfinance(ticker: str) -> tuple[dict | None, list]:
    """Fetch quarterly (5-6q) + annual (4-5y) series from yfinance. (hist|None, warnings)."""
    try:
        import yfinance as yf
    except Exception as e:
        log(f"yfinance import failed: {e}")
        return None, [f"yfinance unavailable: {e}"]

    warnings: list = []
    tk = yf.Ticker(ticker)
    currency = "USD"
    try:
        info = tk.info or {}
        currency = info.get("financialCurrency") or info.get("currency") or "USD"
    except Exception:
        warnings.append("yfinance info unavailable; assuming USD")

    qf = _safe_df(lambda: tk.quarterly_financials)
    qcf = _safe_df(lambda: tk.quarterly_cashflow)
    records = _yf_records(qf, qcf)
    if not records:
        log("yfinance returned no quarterly rows")
        return None, warnings

    af = _safe_df(lambda: tk.financials)
    acf = _safe_df(lambda: tk.cashflow)
    annual_records = _yf_records(af, acf)[-MAX_ANNUAL_YEARS:]

    fy_end_month = 12
    if af is not None and len(af.columns):
        try:
            fy_end_month = af.columns[0].month
        except Exception:
            fy_end_month = int(records[-1]["date"][5:7])

    records = records[-MAX_QUARTERS:]
    log(f"yfinance ok: {len(records)} quarters, {len(annual_records)} years, currency={currency}")
    return assemble_hist("yfinance", currency, records, annual_records, fy_end_month, warnings), warnings


# ===================================================================
# Cache + budget I/O
# ===================================================================
def read_cache(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_cache(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log(f"cache write failed: {e}")


def load_budget(path: Path, today_iso: str) -> dict:
    """Load the AV budget counter, resetting it when the stored date isn't today."""
    data = read_cache(path)
    if not isinstance(data, dict) or data.get("date") != today_iso:
        return {"date": today_iso, "calls": 0}
    return {"date": today_iso, "calls": int(data.get("calls", 0))}


def save_budget(path: Path, budget: dict) -> None:
    try:
        path.write_text(json.dumps(budget), encoding="utf-8")
    except Exception as e:
        log(f"budget write failed: {e}")


def load_consensus(analysis_json: str | None) -> dict | None:
    """Read the consensus block from an analyze_ticker output JSON, if provided."""
    if not analysis_json:
        return None
    try:
        data = json.loads(Path(analysis_json).read_text(encoding="utf-8"))
    except Exception as e:
        log(f"could not read analysis-json ({analysis_json}): {e}")
        return None
    consensus = data.get("consensus")
    return consensus if isinstance(consensus, dict) else None


# ===================================================================
# Main
# ===================================================================
def compute_forecast(hist: dict, consensus: dict | None) -> dict | None:
    """Seasonal split + forecast for a hist block (pure; no I/O)."""
    seasonal = seasonal_split(hist["revenue_by_fy"])
    return build_forecast(consensus, hist, seasonal)


def hist_from_cache(cached: dict) -> dict:
    """Reconstruct the forecast-input hist block from a cached output JSON.

    Only the fields build_forecast needs: the quarterly series plus the persisted
    `_forecast_inputs` (revenue_by_fy + quarters_reported_current_fy)."""
    series = cached.get("series", {}) or {}
    fi = cached.get("_forecast_inputs", {}) or {}
    return {
        "revenue": series.get("revenue", []),
        "ebitda": series.get("ebitda", []),
        "fcf": series.get("fcf", []),
        "labels": series.get("labels", []),
        "revenue_by_fy": fi.get("revenue_by_fy", {}),
        "quarters_reported_current_fy": fi.get("quarters_reported_current_fy", 0),
    }


def suppression_reason(hist_or_cached: dict, forecast: dict | None) -> str | None:
    """Why no forecast was produced — the honest reason, not a catch-all.

    `insufficient_quarters` used to be reported for every suppression, including
    MSFT's, which had 40 quarters of revenue and EBITDA and was missing only the
    FCF leg. A label that names the wrong cause sends you looking for the wrong
    bug, so distinguish the two."""
    if forecast:
        return None
    series = hist_or_cached.get("series") or hist_or_cached
    fcf = (series.get("fcf") if isinstance(series, dict) else None) or []
    if fcf and not any(v is not None for v in fcf):
        return "no_fcf_data"
    return "insufficient_quarters"


def build_output(ticker: str, hist: dict, forecast: dict | None, now_iso: str) -> dict:
    return {
        "ticker": ticker,
        "fetched_at": now_iso,
        "source": hist["source"],
        "currency": hist["currency"],
        "quarters_available": hist["quarters_available"],
        "series": hist["series"],
        "annual": hist["annual"],
        "forecast": forecast,
        "forecast_suppressed_reason": suppression_reason(hist, forecast),
        "warnings": hist.get("warnings", []),
        # Inputs needed to recompute the forecast from cache without a refetch
        # (fresh consensus can change the forecast well inside the 80-day TTL).
        "_forecast_inputs": {
            "revenue_by_fy": hist["revenue_by_fy"],
            "quarters_reported_current_fy": hist["quarters_reported_current_fy"],
        },
    }


def run(ticker: str, analysis_json: str | None, out_dir: Path, force: bool) -> dict:
    now_iso = datetime.now().isoformat()
    today_iso = date.today().isoformat()
    fh_dir = out_dir / "_fin_history"
    fh_dir.mkdir(parents=True, exist_ok=True)
    cache_path = fh_dir / f"{safe_ticker_filename(ticker)}.json"

    if not force:
        cached = read_cache(cache_path)
        if (cached and cache_is_fresh(cached.get("fetched_at", ""), now_iso, TTL_DAYS)
                and cache_has_net_income(cached)
                and cache_has_fcf(cached)):
            # A fresh cache serves the historical series verbatim (no network), but
            # the forecast can go stale well inside the 80-day TTL. If a fresh
            # consensus was supplied, recompute the forecast from the cached series
            # (pure computation) and rewrite the cache — keeping fetched_at, which
            # tracks the data fetch, not the forecast.
            consensus = load_consensus(analysis_json)
            if consensus is not None and cached.get("_forecast_inputs"):
                forecast = compute_forecast(hist_from_cache(cached), consensus)
                cached["forecast"] = forecast
                cached["forecast_suppressed_reason"] = suppression_reason(cached, forecast)
                write_cache(cache_path, cached)
                log(f"cache hit for {ticker} (fresh); forecast recomputed from supplied consensus")
            else:
                log(f"cache hit for {ticker} (fresh, no network)")
            return cached

    hist = None
    if markets.suffix_of(ticker) == "":
        key = read_alphavantage_key()
        if not key:
            log("no Alpha Vantage key; skipping AV")
        else:
            budget = load_budget(fh_dir / "_av_budget.json", today_iso)
            if not av_budget_allows(budget, today_iso, AV_DAILY_LIMIT):
                log(f"AV daily budget exhausted ({budget['calls']}/{AV_DAILY_LIMIT}); skipping AV")
            else:
                av_hist, calls = fetch_alphavantage(ticker, key)
                budget["calls"] += calls
                save_budget(fh_dir / "_av_budget.json", budget)
                if av_hist:
                    hist = av_hist
                else:
                    log("AV empty; falling back to yfinance")
    else:
        log(f"{ticker} is a non-US listing; using yfinance")

    if hist is None:
        yf_hist, _ = fetch_yfinance(ticker)
        if yf_hist:
            hist = yf_hist

    if hist is None:
        log(f"no data from AV or yfinance for {ticker}")
        return {"ticker": ticker, "fetched_at": now_iso, "error": "no financial history available"}

    consensus = load_consensus(analysis_json)
    forecast = compute_forecast(hist, consensus)
    if forecast is None:
        log("forecast suppressed (insufficient margin history)")

    out = build_output(ticker, hist, forecast, now_iso)
    write_cache(cache_path, out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Quarterly/annual EBITDA-FCF-revenue history + forecast")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--analysis-json", default=None,
                    help="Path to an analyze_ticker output JSON (supplies sell-side consensus)")
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--force", action="store_true", help="Ignore cache and refetch")
    args = ap.parse_args()

    try:
        result = run(args.ticker, args.analysis_json, Path(args.out_dir), args.force)
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        print(json.dumps({"ticker": args.ticker, "error": str(e), "error_type": type(e).__name__}))
        return 0  # non-fatal: orchestrator skips the chart

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
