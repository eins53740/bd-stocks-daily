"""Tests for the R16 fix: the one-off detector reads TTM, not the annual snapshot only.

The ROVI.MC quarterly numbers here are REAL -- fetched live from yfinance on 2026-08-18 to
confirm the row exists at all before the fix was built on the assumption that it does. The
2026Q2 unusual item of EUR 62,352,000 is the gain the 2026-08-17 report's prose caught and
the deterministic scanner missed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import red_flags as rf  # noqa: E402
import reconcile_ttm as rt  # noqa: E402

# Live yfinance values, ROVI.MC, 2026-08-18. Oldest -> newest.
LABELS = ["2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"]
REVENUE = [None, None, 159698000.0, 210473000.0, 218420000.0, 152494000.0, 191666000.0]
NET_INCOME = [None, None, 21635000.0, 58029000.0, 42677000.0, 9479000.0, 74997000.0]
UNUSUAL = [None, None, -372000.0, 28000.0, -103000.0, 116000.0, 62352000.0]

ROVI_CACHE = {"series": {"labels": LABELS, "revenue": REVENUE,
                         "ebitda": [None, None, 34943000.0, 83922000.0, 66577000.0,
                                    21237000.0, 101062000.0],
                         "net_income": NET_INCOME, "unusual_items": UNUSUAL}}

# The annual snapshot the old check used: FY2025 cannot contain a Q2-2026 gain.
ROVI_ANNUAL_INCOME = {"fiscal_dates": ["2025-12-31", "2024-12-31"],
                      "revenue": [743483000.0, 763749000.0],
                      "gross_profit": [481000000.0, 490000000.0],
                      "operating_income": [185784000.0, 179545000.0],
                      "net_income": [140442000.0, 136881000.0],
                      "unusual_items": [-608000.0, 81000.0]}


def _one_off(flags):
    return next(f for f in flags if f["id"] == "one_time_income")


def test_annual_only_misses_the_gain_which_is_the_defect():
    """Pins the old behaviour so the regression is visible, not just asserted in prose."""
    flag = _one_off(rf.income_checks({}, ROVI_ANNUAL_INCOME))
    assert flag["status"] == "pass"
    assert flag["value"] < 1.0, "FY2025's -608k against 140.4M NI reads as 0.4%"
    assert "annual only" in flag["note"], "a weaker basis must say so"


def test_ttm_catches_the_rovi_gain():
    """62.393M over 185.182M = 33.7%, 2.2x the 15% threshold."""
    fund = {"unusual_items_ttm": 62393000, "net_income_ttm_statements": 185182000}
    flag = _one_off(rf.income_checks(fund, ROVI_ANNUAL_INCOME))
    assert flag["status"] == "warn"
    assert flag["value"] == 33.7, "reproduces the audit's figure to one decimal"
    assert flag["note"] == "TTM (4 quarters)"


def test_reconcile_publishes_the_ttm_one_off_inputs():
    analysis = {"ticker": "ROVI.MC",
                "fundamentals": {"revenue_ttm": 773052992, "ebitda_ttm": 272798000},
                "statements_raw": {"income": ROVI_ANNUAL_INCOME}}
    v = rt.reconcile(analysis, ROVI_CACHE)
    adds = {a["field"]: a["new"] for a in v["additions"]}
    assert adds["fundamentals.unusual_items_ttm"] == 62393000
    assert adds["fundamentals.net_income_ttm_statements"] == 185182000


def test_additions_do_not_raise_a_false_corrected_flag():
    """A clean run that only gains derived keys must stay `ok`."""
    analysis = {"ticker": "ROVI.MC", "data_quality": "ok",
                "fundamentals": {"revenue_ttm": 773052992, "ebitda_ttm": 272798000,
                                 "operating_margin_ttm": 0.24},
                "statements_raw": {"income": ROVI_ANNUAL_INCOME}}
    v = rt.reconcile(analysis, ROVI_CACHE)
    assert not v["corrections"], "nothing is wrong in this fixture"
    assert v["additions"]
    rt.apply(analysis, v)
    assert analysis["data_quality"] == "ok", "additions are not corrections"
    assert analysis["fundamentals"]["unusual_items_ttm"] == 62393000


def test_one_off_ttm_needs_a_proved_window():
    """A basis mismatch must not license a TTM one-off ratio either."""
    analysis = {"ticker": "X", "fundamentals": {"revenue_ttm": 1000.0},
                "statements_raw": {"income": {}}}
    v = rt.reconcile(analysis, ROVI_CACHE)   # 773M quarters vs a 1000 revenue_ttm
    assert not any("unusual_items_ttm" in a["field"] for a in v["additions"])
    assert any("basis mismatch" in i for i in v["issues"])


def test_incomplete_quarterly_one_offs_fall_back_not_forward():
    cache = {"series": {"labels": LABELS, "revenue": REVENUE,
                        "ebitda": [None, None, 1, 2, 3, 4, 5],
                        "net_income": NET_INCOME,
                        "unusual_items": [None] * 7}}
    analysis = {"ticker": "ROVI.MC",
                "fundamentals": {"revenue_ttm": 773052992, "ebitda_ttm": 14},
                "statements_raw": {"income": ROVI_ANNUAL_INCOME}}
    v = rt.reconcile(analysis, cache)
    assert not any("unusual_items_ttm" in a["field"] for a in v["additions"])
    assert any("Alpha Vantage" in s for s in v["skipped"]), "names why the row can be absent"

    # and red_flags then uses the annual basis, saying so
    flag = _one_off(rf.income_checks({}, ROVI_ANNUAL_INCOME))
    assert "annual only" in flag["note"]


def test_zero_ttm_net_income_does_not_divide_by_zero():
    fund = {"unusual_items_ttm": 5000, "net_income_ttm_statements": 0}
    flag = _one_off(rf.income_checks(fund, {"unusual_items": [None], "net_income": [None],
                                            "revenue": [None], "gross_profit": [None]}))
    assert flag["status"] == "na"
