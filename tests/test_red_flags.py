"""
Unit tests for v4 Phase C — red_flags.py (+ analyze_ticker.extract_statement_rows).

Pure-function tests + tmp_path integration; NO network, NO yfinance calls
(extract_statement_rows is exercised with hand-built pandas frames). Covers the
Phase-C acceptance gate (spec §13):
  * Beneish computed on >=3 sample tickers + a "not computable" path on a name
    missing line items (the non-US case)
  * zero extra API calls — red_flags reads only the analysis JSON
  * the 3 statement sub-scores are deterministic — same JSON in, same 0-10 out
plus per-check thresholds, the two positive pills, and the overlay-only property
(scores + schema_version untouched after merge).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import red_flags as rf


# ===================================================================
# Fixtures — synthetic analysis dicts (no real ticker JSON in the repo)
# ===================================================================
def _healthy_income():
    return {
        "fiscal_dates": ["2025-12-31", "2024-12-31"],
        "revenue": [1000.0, 900.0],
        "cost_of_revenue": [500.0, 450.0],
        "gross_profit": [500.0, 450.0],
        "operating_income": [300.0, 270.0],
        "sga": [150.0, 140.0],
        "depreciation": [50.0, 45.0],
        "interest_expense": [10.0, 10.0],
        "pretax_income": [290.0, 260.0],
        "net_income": [200.0, 180.0],
        "unusual_items": [5.0, 4.0],
    }


def _healthy_balance():
    return {
        "fiscal_dates": ["2025-12-31", "2024-12-31"],
        "total_assets": [2000.0, 1900.0],
        "total_liabilities": [800.0, 780.0],
        "current_assets": [800.0, 750.0],
        "current_liabilities": [400.0, 380.0],
        "receivables": [100.0, 95.0],
        "inventory": [150.0, 140.0],
        "ppe_net": [600.0, 580.0],
        "ppe_gross": [900.0, 850.0],
        "long_term_debt": [300.0, 300.0],
        "total_debt": [350.0, 350.0],
        "stockholders_equity": [1200.0, 1120.0],
        "retained_earnings": [900.0, 820.0],
        "shares": [100.0, 100.0],
    }


def _healthy_cashflow():
    return {
        "fiscal_dates": ["2025-12-31", "2024-12-31"],
        "operating_cash_flow": [250.0, 230.0],
        "capex": [80.0, 75.0],
        "free_cash_flow": [170.0, 155.0],
        "dividends_paid": [50.0, 45.0],
        "depreciation": [50.0, 45.0],
    }


def _healthy_analysis():
    return {
        "ticker": "TEST",
        "currency": "USD",
        "schema_version": "2.2",
        "altman_zscore": 5.0,
        "scores": {"composite": 7.5, "valuation": 6.0, "fundamentals": 8.0},
        "fundamentals": {
            "gross_margin_ttm": 0.50, "operating_margin_ttm": 0.30,
            "current_ratio": 2.0, "quick_ratio": 1.5, "debt_to_equity": 0.40,
            "net_debt_ebitda": 1.0, "fcf_ttm": 500.0, "roce_ttm": 0.25,
        },
        "capital_returns": {"net_payout_yield": 0.05, "dividends_paid_ttm": 50.0},
        "statements_raw": {
            "income": _healthy_income(),
            "balance": _healthy_balance(),
            "cashflow": _healthy_cashflow(),
        },
    }


def _analysis_fixture(tmp_path: Path, analysis=None) -> Path:
    data = analysis if analysis is not None else _healthy_analysis()
    p = tmp_path / "analysis.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ===================================================================
# Beneish M-score — >=3 sample tickers + not-computable path
# ===================================================================
def test_beneish_clean_company():
    """Healthy fixture: all indices ~1, TATA slightly negative -> M < -2.22."""
    b = rf.beneish_m_score(_healthy_income(), _healthy_balance(), _healthy_cashflow())
    assert b["status"] == "pass"
    assert b["m_score"] is not None
    assert b["m_score"] < rf.BENEISH_FLAG_THRESHOLD
    assert b["flag"] is False
    assert b["missing"] == []


def test_beneish_flat_all_indices_one():
    """Classic textbook case: every index == 1, TATA == 0 -> M == -2.48."""
    flat_inc = {
        "revenue": [1000.0, 1000.0], "cost_of_revenue": [600.0, 600.0],
        "gross_profit": [400.0, 400.0], "sga": [150.0, 150.0],
        "depreciation": [50.0, 50.0], "net_income": [120.0, 120.0],
    }
    flat_bal = {
        "total_assets": [1000.0, 1000.0], "total_liabilities": [500.0, 500.0],
        "current_assets": [500.0, 500.0], "current_liabilities": [300.0, 300.0],
        "receivables": [100.0, 100.0], "ppe_net": [300.0, 300.0],
        "long_term_debt": [200.0, 200.0],
    }
    flat_cf = {"operating_cash_flow": [120.0, 120.0]}
    b = rf.beneish_m_score(flat_inc, flat_bal, flat_cf)
    assert round(b["m_score"], 2) == -2.48
    assert b["flag"] is False


def test_beneish_manipulator_flags():
    """Receivables double vs sales (DSRI=2) + accruals (TATA>0) -> M > -2.22."""
    inc = {
        "revenue": [1000.0, 1000.0], "cost_of_revenue": [600.0, 600.0],
        "gross_profit": [400.0, 400.0], "sga": [150.0, 150.0],
        "depreciation": [50.0, 50.0], "net_income": [200.0, 120.0],
    }
    bal = {
        "total_assets": [1000.0, 1000.0], "total_liabilities": [500.0, 500.0],
        "current_assets": [500.0, 500.0], "current_liabilities": [300.0, 300.0],
        "receivables": [200.0, 100.0], "ppe_net": [300.0, 300.0],
        "long_term_debt": [200.0, 200.0],
    }
    cf = {"operating_cash_flow": [50.0, 120.0]}
    b = rf.beneish_m_score(inc, bal, cf)
    assert b["status"] == "bad"
    assert b["flag"] is True
    assert b["m_score"] > rf.BENEISH_FLAG_THRESHOLD
    assert round(b["components"]["DSRI"], 2) == 2.0


def test_beneish_not_computable_missing_line_items():
    """Non-US case: receivables + PP&E absent -> DSRI/AQI/DEPI cannot form ->
    M not computable, status na, missing indices listed."""
    inc = {"revenue": [1000.0, 900.0], "gross_profit": [400.0, 360.0],
           "net_income": [100.0, 90.0]}
    bal = {"total_assets": [2000.0, 1900.0], "current_assets": [800.0, 750.0],
           "current_liabilities": [400.0, 380.0]}  # no receivables, no ppe_net
    cf = {"operating_cash_flow": [120.0, 110.0]}
    b = rf.beneish_m_score(inc, bal, cf)
    assert b["status"] == "na"
    assert b["m_score"] is None
    assert b["flag"] is None
    assert "DSRI" in b["missing"]      # needs receivables
    assert "AQI" in b["missing"]       # needs ppe_net
    assert "not computable" in b["note"]


# ===================================================================
# Statement sub-scores — determinism + values
# ===================================================================
def test_healthy_subscores_all_ten():
    block = rf.compute(_healthy_analysis())
    assert block["income"]["subscore_0_10"] == 10.0
    assert block["balance"]["subscore_0_10"] == 10.0
    assert block["cashflow"]["subscore_0_10"] == 10.0
    assert block["summary"]["bad"] == 0
    assert block["summary"]["warn"] == 0
    assert block["summary"]["verdict"] == "clean"


def test_subscores_deterministic():
    """Same JSON in -> same 0-10 out (spec §13 gate C)."""
    a = _healthy_analysis()
    first = rf.compute(a)
    second = rf.compute(a)
    for stmt in ("income", "balance", "cashflow"):
        assert first[stmt]["subscore_0_10"] == second[stmt]["subscore_0_10"]
    assert first["beneish"]["m_score"] == second["beneish"]["m_score"]


def test_subscore_weighting_pass_warn_bad():
    """pass=1, warn=0.5, bad=0 over computable checks only; na excluded."""
    checks = [
        rf.flag("a", "A", "pass", 1, "-"),
        rf.flag("b", "B", "warn", 1, "-"),
        rf.flag("c", "C", "bad", 1, "-"),
        rf.flag("d", "D", "na", None, "-"),
    ]
    g = rf.statement_group(checks)
    # (1 + 0.5 + 0) / 3 computable * 10 = 5.0
    assert g["subscore_0_10"] == 5.0
    assert g["computable"] == 3
    assert g["total"] == 4


def test_subscore_all_na_is_none():
    checks = [rf.flag("a", "A", "na", None, "-"), rf.flag("b", "B", "na", None, "-")]
    g = rf.statement_group(checks)
    assert g["subscore_0_10"] is None
    assert g["computable"] == 0


# ===================================================================
# Per-check thresholds
# ===================================================================
def test_net_debt_ebitda_bad():
    a = _healthy_analysis()
    a["fundamentals"]["net_debt_ebitda"] = 4.6
    block = rf.compute(a)
    chk = next(c for c in block["balance"]["checks"] if c["id"] == "net_debt_ebitda")
    assert chk["status"] == "bad"
    assert chk["value"] == 4.6


def test_gross_margin_bad_below_10pct():
    a = _healthy_analysis()
    a["fundamentals"]["gross_margin_ttm"] = 0.08
    block = rf.compute(a)
    chk = next(c for c in block["income"]["checks"] if c["id"] == "gross_margin")
    assert chk["status"] == "bad"


def test_current_ratio_bad_below_one():
    a = _healthy_analysis()
    a["fundamentals"]["current_ratio"] = 0.9
    block = rf.compute(a)
    chk = next(c for c in block["balance"]["checks"] if c["id"] == "current_ratio")
    assert chk["status"] == "bad"


def test_earnings_quality_warn_when_cfo_below_ni():
    a = _healthy_analysis()
    a["statements_raw"]["cashflow"]["operating_cash_flow"] = [150.0, 140.0]  # < NI 200
    block = rf.compute(a)
    chk = next(c for c in block["cashflow"]["checks"] if c["id"] == "earnings_quality")
    assert chk["status"] == "warn"


def test_negative_fcf_bad():
    a = _healthy_analysis()
    a["statements_raw"]["cashflow"]["free_cash_flow"] = [-50.0, 10.0]
    block = rf.compute(a)
    chk = next(c for c in block["cashflow"]["checks"] if c["id"] == "fcf_negative")
    assert chk["status"] == "bad"
    assert block["summary"]["bad"] >= 1
    assert block["summary"]["verdict"] == "elevated"


def test_interest_coverage_na_without_interest_line():
    a = _healthy_analysis()
    a["statements_raw"]["income"].pop("interest_expense")
    block = rf.compute(a)
    chk = next(c for c in block["income"]["checks"] if c["id"] == "interest_coverage")
    assert chk["status"] == "na"


def test_no_statements_raw_degrades_gracefully():
    """Pre-Phase-C analysis JSON (no statements_raw): checks read n/a, no crash."""
    a = {"ticker": "OLD", "schema_version": "2.2", "scores": {"composite": 6.0},
         "fundamentals": {"gross_margin_ttm": 0.4, "current_ratio": 2.0},
         "capital_returns": {}}
    block = rf.compute(a)
    assert block["beneish"]["status"] == "na"
    assert any("statements_raw" in w for w in block["warnings"])
    # a fundamentals-backed check still computes
    chk = next(c for c in block["balance"]["checks"] if c["id"] == "current_ratio")
    assert chk["status"] == "pass"


# ===================================================================
# Positive pills (never vetoes)
# ===================================================================
def test_pills_met():
    block = rf.compute(_healthy_analysis())
    assert block["pills"]["net_payout_yield"]["met"] is True   # 5% > 4%
    assert block["pills"]["roce"]["met"] is True               # 25% >= 20%


def test_pills_neutral_and_na():
    a = _healthy_analysis()
    a["capital_returns"]["net_payout_yield"] = 0.02
    a["fundamentals"]["roce_ttm"] = None
    block = rf.compute(a)
    assert block["pills"]["net_payout_yield"]["status"] == "neutral"
    assert block["pills"]["roce"]["status"] == "na"


# ===================================================================
# Overlay-only property + merge
# ===================================================================
def test_merge_is_overlay_only(tmp_path):
    p = _analysis_fixture(tmp_path)
    before = json.loads(p.read_text(encoding="utf-8"))
    block = rf.run("TEST", str(p), tmp_path, force=False)
    rf.merge_into_analysis(str(p), block)
    after = json.loads(p.read_text(encoding="utf-8"))
    assert after["scores"] == before["scores"]          # composite untouched
    assert after["schema_version"] == "2.2"
    assert "red_flags" in after                          # one new additive key
    assert after["red_flags"]["ticker"] == "TEST"


def test_run_reads_analysis_json(tmp_path):
    p = _analysis_fixture(tmp_path)
    block = rf.run("TEST", str(p), tmp_path, force=False)
    assert block["summary"]["verdict"] == "clean"
    assert block["beneish"]["m_score"] is not None


# ===================================================================
# analyze_ticker.extract_statement_rows — pure, fed fake frames
# ===================================================================
def test_extract_statement_rows_maps_and_nulls():
    import pandas as pd
    import analyze_ticker as at

    cols = ["2025-12-31", "2024-12-31", "2023-12-31"]
    fs = pd.DataFrame(
        {cols[0]: [1000, 500], cols[1]: [900, 450], cols[2]: [800, 400]},
        index=["Total Revenue", "Gross Profit"],
    )
    bs = pd.DataFrame(
        {cols[0]: [2000], cols[1]: [1900], cols[2]: [1800]},
        index=["Total Assets"],
    )
    cf = pd.DataFrame(
        {cols[0]: [250], cols[1]: [230], cols[2]: [210]},
        index=["Operating Cash Flow"],
    )
    out = at.extract_statement_rows(fs, bs, cf)
    # present rows -> [latest, prior]
    assert out["income"]["revenue"] == [1000.0, 900.0]
    assert out["income"]["gross_profit"] == [500.0, 450.0]
    assert out["balance"]["total_assets"] == [2000.0, 1900.0]
    assert out["cashflow"]["operating_cash_flow"] == [250.0, 230.0]
    # missing rows -> [None, None], never fabricated
    assert out["income"]["sga"] == [None, None]
    assert out["balance"]["receivables"] == [None, None]
    assert out["balance"]["ppe_net"] == [None, None]
    assert out["income"]["fiscal_dates"] == ["2025-12-31", "2024-12-31"]


def test_extract_statement_rows_empty_frames():
    import analyze_ticker as at
    out = at.extract_statement_rows(None, None, None)
    assert out["income"]["revenue"] == [None, None]
    assert out["balance"]["total_assets"] == [None, None]
    assert out["income"]["fiscal_dates"] == [None, None]
