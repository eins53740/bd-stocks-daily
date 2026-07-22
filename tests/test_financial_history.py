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
    av_budget_allows,
    build_forecast,
    cache_is_fresh,
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
        "annual": {"labels": [], "revenue": [], "ebitda": [], "fcf": []},
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
        "annual": {"labels": [], "revenue": [], "ebitda": [], "fcf": []},
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
