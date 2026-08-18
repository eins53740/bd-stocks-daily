"""Tests for reconcile_ttm.py -- the R15 Layer-0b TTM cross-check.

The first test is the regression that produced the script: the real ROVI.MC numbers, which
are the only ones here that are not synthetic. Everything else is a synthetic fixture,
keeping the suite network-free.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import reconcile_ttm as rt  # noqa: E402


def _analysis(**fund):
    base = {
        "ticker": "TEST",
        "fundamentals": {"revenue_ttm": 1000.0, "ebitda_ttm": 200.0,
                         "enterprise_value": 3000.0, "net_debt": 400.0},
        "statements_raw": {"income": {"fiscal_dates": ["2025-12-31"],
                                      "revenue": [1000.0], "operating_income": [200.0]}},
        "data_quality": "ok",
    }
    base["fundamentals"].update(fund)
    return base


def _cache(revenue, ebitda, labels=("Q1", "Q2", "Q3", "Q4")):
    return {"series": {"labels": list(labels), "revenue": list(revenue), "ebitda": list(ebitda)}}


# --- the regression -----------------------------------------------------------------

ROVI_REVENUE = [None, None, 159698000.0, 210473000.0, 218420000.0, 152494000.0, 191666000.0]
ROVI_EBITDA = [None, None, 34943000.0, 83922000.0, 66577000.0, 21237000.0, 101062000.0]
ROVI_LABELS = ["2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"]


def test_rovi_regression_reproduces_the_audit():
    """The 2026-08-17 ROVI.MC defect: 175.965M served, 272.798M derivable, EV/EBITDA 16.82 -> 10.85."""
    analysis = {
        "ticker": "ROVI.MC",
        "fundamentals": {"revenue_ttm": 773052992, "ebitda_ttm": 175964992.0,
                         "operating_margin_ttm": 0.094160005, "enterprise_value": 2959788800,
                         "net_debt": -20382000, "ev_ebitda": 16.82},
        "statements_raw": {"income": {"fiscal_dates": ["2025-12-31", "2024-12-31"],
                                      "revenue": [743483000.0, 763749000.0],
                                      "operating_income": [185784000.0, 179545000.0]}},
        "data_quality": "ok", "corrected_fields": [], "consistency_issues": [],
    }
    cache = _cache(ROVI_REVENUE, ROVI_EBITDA, ROVI_LABELS)

    v = rt.reconcile(analysis, cache)
    fields = {c["field"] for c in v["corrections"]}
    assert "fundamentals.ebitda_ttm" in fields
    assert "fundamentals.operating_margin_ttm" in fields
    assert not v["issues"], "the revenue identity holds, so this is a correction not an issue"

    rt.apply(analysis, v)
    f = analysis["fundamentals"]
    assert f["ebitda_ttm"] == 272798000
    assert f["ev_ebitda"] == pytest.approx(10.85, abs=0.01)
    assert f["operating_margin_ttm"] is None, "a false TTM margin is removed, not replaced"
    assert f["operating_margin_annual_latest"] == pytest.approx(0.2499, abs=0.0001)
    assert analysis["data_quality"] == "corrected", "the green 'ok' stamp is the actual bug"


# --- the basis guard ----------------------------------------------------------------

def test_revenue_basis_mismatch_corrects_nothing():
    """Different window => the quarterly EBITDA is not a like-for-like replacement."""
    analysis = _analysis(revenue_ttm=1000.0, ebitda_ttm=200.0)
    cache = _cache([100, 100, 100, 100], [90, 90, 90, 90])  # revenue sums to 400, not 1000
    v = rt.reconcile(analysis, cache)
    assert not v["corrections"]
    assert any("basis mismatch" in i for i in v["issues"])
    rt.apply(analysis, v)
    assert analysis["fundamentals"]["ebitda_ttm"] == 200.0, "left alone"
    assert analysis["data_quality"] == "suspect", "unfixable => suspect, not corrected"


def test_partial_quarter_window_is_not_a_ttm():
    """A hole in the last four quarters means no sum at all -- never a 3-quarter 'TTM'."""
    analysis = _analysis()
    cache = _cache([250, None, 250, 250], [50, 50, 50, 50])
    v = rt.reconcile(analysis, cache)
    assert not v["corrections"]
    assert any("no complete 4-quarter" in s for s in v["skipped"])


def test_missing_cache_skips_without_pretending():
    v = rt.reconcile(_analysis(), {})
    assert not v["corrections"]
    assert any("ebitda_ttm" in s for s in v["skipped"])


# --- tolerance behaviour ------------------------------------------------------------

def test_small_deviation_is_left_alone():
    analysis = _analysis(ebitda_ttm=205.0)          # 2.5% off, inside EBITDA_TOL
    cache = _cache([250, 250, 250, 250], [50, 50, 50, 50])
    v = rt.reconcile(analysis, cache)
    assert not any(c["field"] == "fundamentals.ebitda_ttm" for c in v["corrections"])
    assert any("within" in c for c in v["checked"])


def test_absent_ebitda_is_filled_from_the_series():
    analysis = _analysis(ebitda_ttm=None)
    cache = _cache([250, 250, 250, 250], [50, 50, 50, 50])
    v = rt.reconcile(analysis, cache)
    rt.apply(analysis, v)
    assert analysis["fundamentals"]["ebitda_ttm"] == 200


def test_derived_fields_move_with_ebitda():
    """ev_ebitda / net_debt_ebitda must not keep pointing at the old denominator."""
    analysis = _analysis(ebitda_ttm=100.0, enterprise_value=3000.0, net_debt=400.0)
    cache = _cache([250, 250, 250, 250], [50, 50, 50, 50])   # TTM EBITDA = 200
    v = rt.reconcile(analysis, cache)
    rt.apply(analysis, v)
    f = analysis["fundamentals"]
    assert f["ev_ebitda"] == pytest.approx(15.0)
    assert f["net_debt_ebitda"] == pytest.approx(2.0)
    assert f["ebitda_margin_ttm"] == pytest.approx(0.2)


def test_ev_ebit_is_not_touched():
    """EV/EBIT has a different denominator; correcting EBITDA must not move it."""
    analysis = _analysis(ebitda_ttm=100.0, ev_ebit=12.5)
    cache = _cache([250, 250, 250, 250], [50, 50, 50, 50])
    rt.apply(analysis, rt.reconcile(analysis, cache))
    assert analysis["fundamentals"]["ev_ebit"] == 12.5


# --- operating margin ---------------------------------------------------------------

def test_operating_margin_in_range_is_kept():
    analysis = _analysis(operating_margin_ttm=0.19)   # vs 0.20 annual
    v = rt.reconcile(analysis, {})
    assert not any("operating_margin" in c["field"] for c in v["corrections"])


def test_operating_margin_without_annual_data_is_skipped():
    analysis = _analysis(operating_margin_ttm=0.05)
    analysis["statements_raw"]["income"] = {"fiscal_dates": [], "revenue": [], "operating_income": []}
    v = rt.reconcile(analysis, {})
    assert not any("operating_margin" in c["field"] for c in v["corrections"])
    assert any("operating_margin_ttm" in s for s in v["skipped"])


# --- idempotency --------------------------------------------------------------------

def test_second_pass_changes_nothing():
    analysis = _analysis(ebitda_ttm=100.0, operating_margin_ttm=0.02)
    cache = _cache([250, 250, 250, 250], [50, 50, 50, 50])
    rt.apply(analysis, rt.reconcile(analysis, cache))
    snapshot = json.dumps(analysis, sort_keys=True, default=str)
    second = rt.reconcile(analysis, cache)
    assert not second["corrections"]
    rt.apply(analysis, second)
    assert json.dumps(analysis, sort_keys=True, default=str) == snapshot


def test_ttm_from_series_requires_the_trailing_window():
    assert rt.ttm_from_series({"labels": ["a", "b", "c", "d"],
                               "revenue": [1, 2, 3, 4]}, "revenue")[0] == 10
    assert rt.ttm_from_series({"labels": ["a", "b", "c"], "revenue": [1, 2, 3]}, "revenue")[0] is None
    assert rt.ttm_from_series({"revenue": [1, 2, 3, None]}, "revenue")[0] is None
