"""
Unit tests for financial_history.py — pure functions only, no network.

Exercises the forecast math (seasonal_split, median_margin, build_forecast), the
cache/budget freshness gates (cache_is_fresh, av_budget_allows), and the
calendar-quarter label helpers.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from financial_history import (  # noqa: E402
    MAX_ANNUAL_YEARS,
    _annual_series,
    _av_annual_records,
    av_budget_allows,
    build_forecast,
    cache_has_fcf,
    cache_has_net_income,
    cache_is_fresh,
    suppression_reason,
    median_margin,
    next_quarter_label,
    quarter_label_from_date,
    run,
    seasonal_split,
)


# --------------------------------------------------------------- seasonal_split
def test_seasonal_split_three_complete_fys_sum_to_one_and_seasonal():
    data = {
        "FY2021": [100, 110, 120, 130],
        "FY2022": [120, 130, 140, 150],
        "FY2023": [140, 150, 160, 170],
    }
    shares = seasonal_split(data)
    assert len(shares) == 4
    assert abs(sum(shares) - 1.0) < 1e-9
    # Revenue climbs across the year, so Q4 must carry a larger share than Q1.
    assert shares[3] > shares[0]


def test_seasonal_split_exact_shares():
    # Every FY has the same 10/20/30/40 shape -> shares are exactly .1/.2/.3/.4.
    data = {"FY2021": [10, 20, 30, 40], "FY2022": [10, 20, 30, 40]}
    shares = seasonal_split(data)
    assert abs(shares[0] - 0.1) < 1e-9
    assert abs(shares[1] - 0.2) < 1e-9
    assert abs(shares[2] - 0.3) < 1e-9
    assert abs(shares[3] - 0.4) < 1e-9


def test_seasonal_split_one_fy_is_uniform():
    assert seasonal_split({"FY2023": [10, 20, 30, 40]}) == [0.25, 0.25, 0.25, 0.25]


def test_seasonal_split_incomplete_fys_are_uniform():
    # Neither FY has 4 quarters -> fewer than 2 complete -> uniform.
    data = {"FY2022": [10, 20, 30], "FY2023": [10, 20]}
    assert seasonal_split(data) == [0.25, 0.25, 0.25, 0.25]


# --------------------------------------------------------------- median_margin
def test_median_margin_normal():
    # ratios .1/.2/.3/.4 -> median = (.2 + .3) / 2 = .25
    assert median_margin([10, 20, 30, 40], [100, 100, 100, 100]) == 0.25


def test_median_margin_fewer_than_four_pairs_is_none():
    assert median_margin([10, 20, 30], [100, 100, 100]) is None


def test_median_margin_ignores_none_and_zero_denominator():
    # Valid pairs: .1, .4, .5, .6 (index 1 None, index 2 zero-den both dropped).
    num = [10, None, 30, 40, 50, 60]
    den = [100, 100, 0, 100, 100, 100]
    assert median_margin(num, den) == 0.45


# --------------------------------------------------------------- build_forecast
def _hist_eight_quarters():
    """8 quarters, EBITDA=30% of revenue, FCF=20% of revenue, 2 complete FYs."""
    rev = [100, 110, 120, 130, 140, 150, 160, 170]
    return {
        "revenue": rev,
        "ebitda": [r * 0.30 for r in rev],
        "fcf": [r * 0.20 for r in rev],
        "labels": ["2024Q1", "2024Q2", "2024Q3", "2024Q4",
                   "2025Q1", "2025Q2", "2025Q3", "2025Q4"],
        "quarters_reported_current_fy": 0,
        "revenue_by_fy": {"FY2024": rev[:4], "FY2025": rev[4:]},
    }


def test_build_forecast_consensus_path():
    hist = _hist_eight_quarters()
    seasonal = seasonal_split(hist["revenue_by_fy"])
    consensus = {
        "analyst_count": 12,
        "revenue_estimate_current_year": 800.0,
        "revenue_estimate_next_year": 900.0,
    }
    fc = build_forecast(consensus, hist, seasonal)
    assert fc is not None
    assert fc["basis"] == "consensus_revenue_x_trailing_margin"
    assert len(fc["labels"]) == 4
    assert len(fc["revenue"]) == 4
    assert fc["labels"][0] == "2026Q1"
    assert fc["labels"][-1] == "2026Q4"
    # k=0 -> all four quarters come from the current-year 800 total.
    assert abs(sum(fc["revenue"]) - 800.0) < 0.05
    # EBITDA/FCF follow the 30% / 20% median margins.
    for r, e, f in zip(fc["revenue"], fc["ebitda"], fc["fcf"]):
        assert abs(e - r * 0.30) < 0.02
        assert abs(f - r * 0.20) < 0.02


def test_build_forecast_trend_basis_when_few_analysts():
    hist = _hist_eight_quarters()
    seasonal = seasonal_split(hist["revenue_by_fy"])
    consensus = {
        "analyst_count": 2,
        "revenue_estimate_current_year": 800.0,
        "revenue_estimate_next_year": 900.0,
    }
    fc = build_forecast(consensus, hist, seasonal)
    assert fc is not None
    assert fc["basis"] == "trend_extrapolation_no_consensus"
    assert len(fc["revenue"]) == 4


def test_build_forecast_trend_basis_when_no_consensus():
    hist = _hist_eight_quarters()
    seasonal = seasonal_split(hist["revenue_by_fy"])
    fc = build_forecast(None, hist, seasonal)
    assert fc is not None
    assert fc["basis"] == "trend_extrapolation_no_consensus"


def test_build_forecast_suppressed_when_margin_none():
    # Only 3 quarters -> fewer than 4 margin pairs -> suppressed.
    hist = {
        "revenue": [100, 110, 120],
        "ebitda": [30, 33, 36],
        "fcf": [20, 22, 24],
        "labels": ["2025Q1", "2025Q2", "2025Q3"],
        "quarters_reported_current_fy": 3,
        "revenue_by_fy": {"FY2025": [100, 110, 120]},
    }
    assert build_forecast(None, hist, [0.25, 0.25, 0.25, 0.25]) is None


# ------------------------------------------------------------------ cache TTL
def test_cache_is_fresh_true_within_ttl():
    assert cache_is_fresh("2026-06-01T12:00:00+00:00", "2026-07-15T12:00:00+00:00", 80) is True


def test_cache_is_fresh_false_beyond_ttl():
    assert cache_is_fresh("2026-01-01T12:00:00+00:00", "2026-07-15T12:00:00+00:00", 80) is False


def test_cache_is_fresh_naive_and_aware_mix():
    # One stamp tz-aware, one naive — must not raise, must compare cleanly.
    assert cache_is_fresh("2026-07-14T12:00:00+00:00", "2026-07-15T12:00:00", 80) is True


def test_cache_is_fresh_bad_input_is_stale():
    assert cache_is_fresh("not-a-date", "2026-07-15T00:00:00", 80) is False


# ------------------------------------------------------------------ AV budget
def test_av_budget_resets_on_new_day():
    budget = {"date": "2026-07-14", "calls": 50}
    assert av_budget_allows(budget, "2026-07-15", limit=20) is True


def test_av_budget_exhausted_same_day():
    budget = {"date": "2026-07-15", "calls": 20}
    assert av_budget_allows(budget, "2026-07-15", limit=20) is False


def test_av_budget_allows_under_limit_same_day():
    budget = {"date": "2026-07-15", "calls": 19}
    assert av_budget_allows(budget, "2026-07-15", limit=20) is True


def test_av_budget_empty_is_allowed():
    assert av_budget_allows({}, "2026-07-15", limit=20) is True


# --------------------------------------------- cache-hit forecast recompute
def test_cache_hit_recomputes_forecast_from_supplied_consensus(tmp_path):
    """A fresh cache carrying a trend forecast must be re-forecast against a fresh
    consensus supplied via --analysis-json — no network, cache rewritten in place,
    fetched_at preserved."""
    rev = [100, 110, 120, 130, 140, 150, 160, 170]
    labels = ["2024Q1", "2024Q2", "2024Q3", "2024Q4",
              "2025Q1", "2025Q2", "2025Q3", "2025Q4"]
    fetched_at = datetime.now().isoformat()
    cached = {
        "ticker": "TEST",
        "fetched_at": fetched_at,
        "source": "alphavantage",
        "currency": "USD",
        "quarters_available": 8,
        "series": {
            "labels": labels,
            "revenue": rev,
            "ebitda": [r * 0.30 for r in rev],
            "fcf": [r * 0.20 for r in rev],
        },
        "annual": {"labels": [], "revenue": [], "ebitda": [], "fcf": [], "net_income": []},
        "forecast": {
            "labels": ["2026Q1", "2026Q2", "2026Q3", "2026Q4"],
            "revenue": [180, 190, 200, 210],
            "ebitda": [54, 57, 60, 63],
            "fcf": [36, 38, 40, 42],
            "basis": "trend_extrapolation_no_consensus",
        },
        "forecast_suppressed_reason": None,
        "warnings": [],
        "_forecast_inputs": {
            "revenue_by_fy": {"FY2024": rev[:4], "FY2025": rev[4:]},
            "quarters_reported_current_fy": 0,
        },
    }
    fh_dir = tmp_path / "_fin_history"
    fh_dir.mkdir(parents=True)
    (fh_dir / "TEST.json").write_text(json.dumps(cached), encoding="utf-8")

    aj = tmp_path / "analysis.json"
    aj.write_text(json.dumps({"consensus": {
        "analyst_count": 30,
        "revenue_estimate_current_year": 800.0,
        "revenue_estimate_next_year": 900.0,
    }}), encoding="utf-8")

    result = run("TEST", str(aj), tmp_path, force=False)

    # Returned + on-disk forecast switched to the consensus basis; data unchanged.
    assert result["forecast"]["basis"] == "consensus_revenue_x_trailing_margin"
    assert result["fetched_at"] == fetched_at
    on_disk = json.loads((fh_dir / "TEST.json").read_text(encoding="utf-8"))
    assert on_disk["forecast"]["basis"] == "consensus_revenue_x_trailing_margin"
    assert on_disk["fetched_at"] == fetched_at
    assert on_disk["series"]["revenue"] == rev


def test_cache_hit_without_analysis_json_keeps_forecast(tmp_path):
    """No consensus supplied -> cached forecast returned verbatim (no network)."""
    rev = [100, 110, 120, 130, 140, 150, 160, 170]
    fetched_at = datetime.now().isoformat()
    cached = {
        "ticker": "TEST2",
        "fetched_at": fetched_at,
        "source": "yfinance",
        "currency": "USD",
        "quarters_available": 8,
        "series": {
            "labels": ["2024Q1", "2024Q2", "2024Q3", "2024Q4",
                       "2025Q1", "2025Q2", "2025Q3", "2025Q4"],
            "revenue": rev,
            "ebitda": [r * 0.30 for r in rev],
            "fcf": [r * 0.20 for r in rev],
        },
        "annual": {"labels": [], "revenue": [], "ebitda": [], "fcf": [], "net_income": []},
        "forecast": {"labels": ["2026Q1"], "revenue": [180], "ebitda": [54],
                     "fcf": [36], "basis": "trend_extrapolation_no_consensus"},
        "forecast_suppressed_reason": None,
        "warnings": [],
        "_forecast_inputs": {
            "revenue_by_fy": {"FY2024": rev[:4], "FY2025": rev[4:]},
            "quarters_reported_current_fy": 0,
        },
    }
    fh_dir = tmp_path / "_fin_history"
    fh_dir.mkdir(parents=True)
    (fh_dir / "TEST2.json").write_text(json.dumps(cached), encoding="utf-8")

    result = run("TEST2", None, tmp_path, force=False)
    assert result["forecast"]["basis"] == "trend_extrapolation_no_consensus"
    assert result["fetched_at"] == fetched_at


# ------------------------------------------------------------------ label helpers
def test_next_quarter_label_wraps_year():
    assert next_quarter_label("2026Q4") == "2027Q1"
    assert next_quarter_label("2026Q2") == "2026Q3"


def test_quarter_label_from_date():
    assert quarter_label_from_date("2016-07-31") == "2016Q3"
    assert quarter_label_from_date("2016-01-31") == "2016Q1"
    assert quarter_label_from_date("2016-12-31") == "2016Q4"


# ------------------------------------------------- net_income (v4 Phase A)
def test_annual_series_carries_net_income_and_tolerates_missing_key():
    records = [
        {"date": "2023-12-31", "revenue": 100, "ebitda": 30, "fcf": 20, "net_income": 15},
        {"date": "2024-12-31", "revenue": 110, "ebitda": 33, "fcf": 22},  # pre-Phase-A record
    ]
    s = _annual_series(records)
    assert s["net_income"] == [15, None]
    assert s["labels"] == ["FY2023", "FY2024"]


def test_av_annual_records_extract_net_income():
    annual_income = [{
        "fiscalDateEnding": "2025-07-31", "totalRevenue": "53800000000",
        "ebitda": "18000000000", "netIncome": "9900000000",
    }]
    records = _av_annual_records(annual_income, {})
    assert records[0]["net_income"] == 9.9e9


def test_av_annual_records_net_income_none_string():
    records = _av_annual_records(
        [{"fiscalDateEnding": "2025-12-31", "totalRevenue": "100", "netIncome": "None"}], {})
    assert records[0]["net_income"] is None


def test_cache_has_net_income_key_presence_not_values():
    assert cache_has_net_income({"annual": {"net_income": [None, None]}}) is True
    assert cache_has_net_income({"annual": {"labels": [], "revenue": []}}) is False
    assert cache_has_net_income({}) is False
    assert cache_has_net_income(None) is False


def test_av_annual_records_cap_lifted_beyond_six_years():
    """v4 Phase E: the annual cap was lifted from 6 to MAX_ANNUAL_YEARS so the
    10/15-yr revenue-CAGR rungs can populate whenever a source is deep enough.
    Free sources rarely are (fixture proves the code path, not live data)."""
    assert MAX_ANNUAL_YEARS >= 15
    annual_income = [
        {"fiscalDateEnding": f"{year}-12-31", "totalRevenue": str(100 + year),
         "netIncome": "10"}
        for year in range(2009, 2025)  # 16 fiscal years
    ]
    records = _av_annual_records(annual_income, {})
    assert len(records) == 16  # all 16 kept — no longer clipped to 6
    assert records[0]["date"] == "2009-12-31"
    assert records[-1]["date"] == "2024-12-31"


def test_av_annual_records_still_capped_at_max_annual_years():
    annual_income = [
        {"fiscalDateEnding": f"{year}-12-31", "totalRevenue": "100", "netIncome": "10"}
        for year in range(2000, 2030)  # 30 fiscal years — beyond the cap
    ]
    records = _av_annual_records(annual_income, {})
    assert len(records) == MAX_ANNUAL_YEARS
    assert records[-1]["date"] == "2029-12-31"  # newest retained


def test_pre_phase_a_cache_is_treated_as_stale():
    """A fresh-TTL cache without annual.net_income must not be served verbatim —
    otherwise the NI-vs-P/E chart silently skips for the whole 80-day TTL."""
    cached = {"fetched_at": datetime.now().isoformat(),
              "annual": {"labels": ["FY2024"], "revenue": [1], "ebitda": [1], "fcf": [1]}}
    assert cache_is_fresh(cached["fetched_at"], datetime.now().isoformat()) is True
    assert cache_has_net_income(cached) is False  # → run() refetches


# ---------- partial-AV-fetch guard: FCF-less cache (2026-07-30) ----------
# A throttled CASH_FLOW call returns complete income data and an all-None FCF
# column. The fetch logged "AV ok", the cache was written as a success, and the
# EBITDA-vs-FCF chart lost its FCF line for the full 80-day TTL — silently, on
# 10 of 33 cached names (MSFT, TSM, PYPL, MA, ADSK, TTD among them).
def test_cache_has_fcf_checks_values_not_key_presence():
    assert cache_has_fcf({"series": {"fcf": [1.0, 2.0]}}) is True
    assert cache_has_fcf({"series": {"fcf": [None, 2.0]}}) is True  # partial is usable
    assert cache_has_fcf({"series": {"fcf": [None, None]}}) is False
    assert cache_has_fcf({"series": {"fcf": []}}) is False
    assert cache_has_fcf({"series": {"revenue": [1]}}) is False  # key absent
    assert cache_has_fcf({}) is False
    assert cache_has_fcf(None) is False


def test_fcf_less_cache_is_treated_as_stale_despite_fresh_ttl():
    """The MSFT case: 40 quarters of revenue/EBITDA, zero FCF, inside the TTL."""
    cached = {
        "fetched_at": datetime.now().isoformat(),
        "series": {"labels": ["2026Q1"] * 40, "revenue": [1.0] * 40,
                   "ebitda": [1.0] * 40, "fcf": [None] * 40},
        "annual": {"net_income": [1.0]},
    }
    assert cache_is_fresh(cached["fetched_at"], datetime.now().isoformat()) is True
    assert cache_has_net_income(cached) is True   # this gate passed...
    assert cache_has_fcf(cached) is False         # ...this one now catches it


def test_suppression_reason_names_the_real_cause():
    """`insufficient_quarters` was reported for every suppression, including a
    40-quarter series missing only FCF — a label that sends you to the wrong bug."""
    forty_no_fcf = {"series": {"revenue": [1.0] * 40, "fcf": [None] * 40}}
    assert suppression_reason(forty_no_fcf, None) == "no_fcf_data"
    thin = {"series": {"revenue": [1.0, 2.0], "fcf": [1.0, 2.0]}}
    assert suppression_reason(thin, None) == "insufficient_quarters"
    assert suppression_reason(forty_no_fcf, {"labels": ["2026Q2"]}) is None


def test_suppression_reason_accepts_a_bare_series_block():
    """Called with a cached output (nested `series`) and with a hist block."""
    assert suppression_reason({"fcf": [None, None], "revenue": [1, 2]}, None) == "no_fcf_data"


def test_av_currency_ignores_the_literal_none_string():
    """AV sends absent strings as "None", which is truthy — it overwrote the USD
    default and would have printed "None" as the currency on MSFT's chart axis."""
    from financial_history import _av_currency
    assert _av_currency([{"reportedCurrency": "None"}]) == "USD"
    assert _av_currency([{"reportedCurrency": "none"}]) == "USD"
    assert _av_currency([{"reportedCurrency": "  "}]) == "USD"
    assert _av_currency([{"reportedCurrency": None}]) == "USD"
    assert _av_currency([]) == "USD"
    assert _av_currency([{"reportedCurrency": "EUR"}]) == "EUR"
    # falls through to the first report that actually names a currency
    assert _av_currency([{"reportedCurrency": "None"},
                         {"reportedCurrency": "USD"}]) == "USD"


def test_av_is_throttled_detects_the_200_with_a_note():
    from financial_history import _av_is_throttled
    assert _av_is_throttled({"Note": "call frequency"}) is True
    assert _av_is_throttled({"Information": "rate limit"}) is True
    assert _av_is_throttled({"quarterlyReports": []}) is False
    assert _av_is_throttled(None) is False


def test_av_retry_spaces_the_second_attempt_and_counts_both_calls(monkeypatch):
    """The root cause: AV free tier is 5 req/min and the two statement calls fire
    back-to-back, so the second is throttled. The retry must wait, not hammer."""
    import financial_history as fh
    responses = [{"Note": "call frequency"}, {"quarterlyReports": [{"x": 1}]}]
    monkeypatch.setattr(fh, "_http_get_json", lambda url: responses.pop(0))
    slept = []
    payload, calls = fh._av_get_with_retry("http://x", "CASH_FLOW",
                                           sleep=slept.append)
    assert payload == {"quarterlyReports": [{"x": 1}]}
    assert calls == 2, "both requests must count against the daily budget"
    assert slept == [fh.AV_THROTTLE_DELAY_S], "must wait past the per-minute window"


def test_av_retry_gives_up_after_the_configured_attempts(monkeypatch):
    import financial_history as fh
    monkeypatch.setattr(fh, "_http_get_json", lambda url: {"Note": "call frequency"})
    slept = []
    payload, calls = fh._av_get_with_retry("http://x", "CASH_FLOW", attempts=2,
                                           sleep=slept.append)
    assert fh._av_is_throttled(payload) is True  # still throttled → caller warns
    assert calls == 2 and len(slept) == 1, "no sleep after the final attempt"


def test_av_retry_does_not_retry_a_good_first_response(monkeypatch):
    import financial_history as fh
    monkeypatch.setattr(fh, "_http_get_json", lambda url: {"quarterlyReports": []})
    slept = []
    _, calls = fh._av_get_with_retry("http://x", "INCOME_STATEMENT",
                                     sleep=slept.append)
    assert calls == 1 and slept == []


def test_av_records_report_missing_cashflow_as_none_not_zero():
    """Guards the join: no cashflow row for a date must yield fcf None, never 0.0
    — a zero would be plotted as a real datapoint."""
    from financial_history import _av_records
    income = [{"fiscalDateEnding": "2026-03-31", "totalRevenue": "100",
               "ebitda": "20"}]
    recs = _av_records(income, {})  # empty cf_by_date = throttled CASH_FLOW
    assert len(recs) == 1
    assert recs[0]["fcf"] is None
    assert recs[0]["revenue"] == 100.0
