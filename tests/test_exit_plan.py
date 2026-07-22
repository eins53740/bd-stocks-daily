"""
Unit tests for v4 Phase A — exit_plan.py (+ the pe_band.series persistence in
valuation_bands.py and the NI-vs-P/E chart in render_charts.py).

Pure-function tests + tmp_path integration; no network, no yfinance calls.
Covers the Phase-A acceptance gate (spec §13):
  * exit_plan block on a held ticker (cost basis from _portfolio_holdings.yaml)
    AND a non-held ticker ("n/a (not held)")
plus the audit fixes: label-only currency rescale (a 100× winner is NOT
rescaled), SHEL.L→SHELL.AS alias, duplicate-ticker first-wins, dividend None/0,
avg_cost None/0, crypto skips the cost rung, --bear-trigger vs _log.csv
fallback, atr always OFF, year-label chart join, and the overlay-only property.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import exit_plan as xp
import valuation_bands as vb


# ===================================================================
# cost_scale_factor — label-only currency guard (audit M1)
# ===================================================================
def test_cost_scale_same_currency():
    assert xp.cost_scale_factor("USD", "USD") == 1.0
    assert xp.cost_scale_factor("eur", "EUR") == 1.0


def test_cost_scale_pence_to_pound():
    assert xp.cost_scale_factor("GBp", "GBP") == 0.01
    assert xp.cost_scale_factor("GBX", "GBP") == 0.01


def test_cost_scale_pound_to_pence():
    assert xp.cost_scale_factor("GBP", "GBp") == 100.0


def test_cost_scale_mismatch_is_none():
    assert xp.cost_scale_factor("TWD", "USD") is None
    assert xp.cost_scale_factor("EUR", "GBP") is None
    assert xp.cost_scale_factor(None, "USD") is None
    assert xp.cost_scale_factor("USD", None) is None


def test_cost_scale_takes_no_prices():
    """The M1 regression: the rescale decision must be label-only. A genuine
    100× long-hold winner (cost 1.50, price 150) keeps factor 1.0 because the
    labels match — no ratio heuristic can touch the cost basis."""
    assert xp.cost_scale_factor("USD", "USD") == 1.0  # signature has no prices


# ===================================================================
# find_holding — held detection
# ===================================================================
_HOLDINGS = [
    {"ticker": "CSCO", "avg_cost": 55.84, "quantity": 31, "currency": "USD",
     "asset_type": "equity"},
    {"ticker": "SHELL.AS", "avg_cost": 26.79, "quantity": 47, "currency": "EUR",
     "asset_type": "equity"},
    {"ticker": "BTC-EUR", "avg_cost": 60000.0, "quantity": 0.1, "currency": "EUR",
     "asset_type": "crypto"},
]


def test_find_holding_exact_match():
    h, w = xp.find_holding("CSCO", _HOLDINGS)
    assert h["avg_cost"] == 55.84
    assert w == []


def test_find_holding_not_held():
    h, w = xp.find_holding("ADSK", _HOLDINGS)
    assert h is None and w == []


def test_find_holding_shel_alias():
    """SHEL.L (the _universe variant) must resolve to the held SHELL.AS line —
    a wrong 'n/a (not held)' on an owned stock is the one failure Phase A
    exists to prevent (audit M2)."""
    h, w = xp.find_holding("SHEL.L", _HOLDINGS)
    assert h["ticker"] == "SHELL.AS"
    assert any("alias" in x for x in w)


def test_find_holding_duplicates_first_wins():
    dup = [{"ticker": "CSCO", "avg_cost": 1.0}, {"ticker": "CSCO", "avg_cost": 2.0}]
    h, w = xp.find_holding("CSCO", dup)
    assert h["avg_cost"] == 1.0
    assert any("duplicate" in x for x in w)


# ===================================================================
# target_exit_pe_block — reuses justified_exit_pe (median capped at max)
# ===================================================================
def test_target_exit_pe_median_capped():
    band = {"median": 18.0, "mean": 25.0, "max": 30.0, "depth_years": 8, "unit_check": "ok"}
    b = xp.target_exit_pe_block(band)
    assert b["value"] == 18.0                       # median, not mean
    assert b["depth_years"] == 8
    # sanity: the shared rule is the actual Phase B function
    assert b["value"] == vb.justified_exit_pe(band)


def test_target_exit_pe_capped_at_max():
    band = {"median": 50.0, "max": 30.0, "unit_check": "ok"}
    assert xp.target_exit_pe_block(band)["value"] == 30.0


def test_target_exit_pe_degraded_band_is_none():
    assert xp.target_exit_pe_block({"median": 18.0, "max": 30.0,
                                    "unit_check": "mismatch"})["value"] is None
    assert xp.target_exit_pe_block(None)["value"] is None


# ===================================================================
# build_ladder — fair-value-anchored + held-only cost rung
# ===================================================================
def test_ladder_fair_value_rungs():
    rungs = xp.build_ladder(110.0, None)
    assert [r["trigger_price"] for r in rungs] == [110.0, 165.0, None]
    assert rungs[0]["basis"] == "fair-value high"
    assert rungs[1]["basis"] == "fair-value high × 1.5"
    assert rungs[2]["rung"] == "hold 1/3"


def test_ladder_with_cost_rung():
    rungs = xp.build_ladder(110.0, 55.84)
    assert rungs[-1]["rung"] == "cost 2×"
    assert rungs[-1]["trigger_price"] == 111.68


def test_ladder_cost_only_when_no_fair_value():
    rungs = xp.build_ladder(None, 55.84)
    assert len(rungs) == 1 and rungs[0]["rung"] == "cost 2×"


def test_ladder_empty_when_nothing_computable():
    assert xp.build_ladder(None, None) == []
    assert xp.build_ladder(0, 0) == []


# ===================================================================
# yield_on_cost_block — every reason path named
# ===================================================================
def test_yoc_happy_path():
    b = xp.yield_on_cost_block(1.60, 55.84, held=True, is_equity=True, ccy_ok=True)
    assert b["pct"] == round(1.60 / 55.84 * 100, 2)
    assert b["basis"] == "dividend_rate / avg_cost"


def test_yoc_not_held_verbatim():
    assert xp.yield_on_cost_block(1.6, None, False, False, False)["reason"] == "n/a (not held)"


def test_yoc_non_equity():
    b = xp.yield_on_cost_block(None, 60000.0, True, False, True)
    assert b["reason"] == "n/a (non-equity holding)"


def test_yoc_currency_mismatch():
    b = xp.yield_on_cost_block(1.6, None, True, True, False)
    assert b["reason"] == "not computable (currency mismatch)"


def test_yoc_no_cost_basis():
    for bad in (None, 0, -1):
        assert xp.yield_on_cost_block(1.6, bad, True, True, True)["reason"] == \
            "not computable (no cost basis)"


def test_yoc_no_dividend_none_and_zero():
    """dividend_rate 0 must read 'no dividend', not a meaningless 0.0% (m4)."""
    for rate in (None, 0, 0.0):
        assert xp.yield_on_cost_block(rate, 55.84, True, True, True)["reason"] == "no dividend"


# ===================================================================
# atr_context_block — always OFF
# ===================================================================
def test_atr_context_available():
    tech = {"indicators": {"atr": 2.1, "atr_pct": 3.2},
            "suggested_stop_loss": [60.0, 58.0], "risk_level": "Medium"}
    b = xp.atr_context_block(tech)
    assert b["enabled"] is False and b["available"] is True
    assert b["atr"] == 2.1 and b["risk_level"] == "Medium"


def test_atr_context_absent():
    assert xp.atr_context_block(None) == {"enabled": False, "available": False}
    assert xp.atr_context_block({"no_indicators": True}) == {"enabled": False, "available": False}


# ===================================================================
# thesis trigger — --bear-trigger first, _log.csv second, never a placeholder
# ===================================================================
def test_trigger_arg_wins():
    t, w = xp.thesis_trigger_block("If margins fall below 20%, the thesis is broken.",
                                   "intact", "old trigger")
    assert t["text"].startswith("If margins")
    assert t["source"] == "phase 2.5 bear case (--bear-trigger)"
    assert t["pillars_status"] == "intact"
    assert w == []


def test_trigger_log_fallback():
    t, w = xp.thesis_trigger_block(None, None, "If X happens, the thesis is broken.")
    assert t["source"] == "_log.csv prior evaluation"
    assert t["pillars_status"] == "first_run"
    assert w == []


def test_trigger_neither_is_null_plus_warning():
    t, w = xp.thesis_trigger_block(None, None, None)
    assert t["text"] is None and t["source"] is None
    assert len(w) == 1


def test_latest_trigger_from_rows_picks_most_recent_nonempty():
    rows = [
        {"ticker": "CSCO", "date": "2026-05-01", "round": "1", "bear_case_trigger": "old"},
        {"ticker": "CSCO", "date": "2026-07-01", "round": "2", "bear_case_trigger": "new"},
        {"ticker": "CSCO", "date": "2026-07-10", "round": "3", "bear_case_trigger": ""},
        {"ticker": "AMD", "date": "2026-07-15", "round": "1", "bear_case_trigger": "other"},
    ]
    assert xp.latest_trigger_from_rows(rows, "CSCO") == "new"
    assert xp.latest_trigger_from_rows(rows, "NVDA") is None


# ===================================================================
# Integration: run() on synthetic fixtures (tmp out_dir, no network)
# ===================================================================
def _write_holdings(out_dir: Path, holdings: list) -> None:
    import yaml
    (out_dir / xp.HOLDINGS_FILENAME).write_text(
        yaml.safe_dump({"version": 1, "holdings": holdings}), encoding="utf-8")


def _analysis_fixture(tmp_path: Path, ticker="CSCO", currency="USD",
                      dividend_rate=1.60) -> Path:
    data = {
        "ticker": ticker,
        "price_current": 68.0,
        "currency": currency,
        "schema_version": "2.2",
        "fundamentals": {"pe_ratio": 17.0, "dividend_rate": dividend_rate},
        "scores": {"composite": 7.5, "valuation": 6.0},
        "valuation_bands": {
            "pe_band": {"median": 18.0, "mean": 20.0, "max": 30.0,
                        "depth_years": 8, "unit_check": "ok"},
        },
        "intrinsic_value": {
            "fair_value_range": {"low": 80.0, "mid": 95.0, "high": 110.0,
                                 "basis": "min / blend / max of valid intrinsic models"},
        },
    }
    p = tmp_path / f"analysis_{ticker}.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_run_held_ticker_full_block(tmp_path):
    _write_holdings(tmp_path, _HOLDINGS)
    block = xp.run("CSCO", str(_analysis_fixture(tmp_path)), tmp_path,
                   bear_trigger="If X happens, the thesis is broken.",
                   thesis_status=None)
    assert block["held"] is True
    assert block["holding"]["quantity"] == 31
    assert block["target_exit_pe"]["value"] == 18.0
    assert block["fair_value_range"]["high"] == 110.0
    assert block["profit_take_ladder"][-1] == {
        "rung": "cost 2×", "trigger_price": 111.68, "basis": "2× cost (held)"}
    assert block["yield_on_cost"]["pct"] == round(1.60 / 55.84 * 100, 2)
    assert block["thesis_broken_trigger"]["text"].startswith("If X")
    assert block["atr_context"]["enabled"] is False


def test_run_not_held_ticker(tmp_path):
    _write_holdings(tmp_path, _HOLDINGS)
    block = xp.run("ADSK", str(_analysis_fixture(tmp_path, ticker="ADSK")), tmp_path,
                   bear_trigger=None, thesis_status=None)
    assert block["held"] is False and block["holding"] is None
    assert block["yield_on_cost"] == {"pct": None, "reason": "n/a (not held)"}
    assert all(r["rung"] != "cost 2×" for r in block["profit_take_ladder"])
    assert len(block["profit_take_ladder"]) == 3  # fair rungs still render


def test_run_currency_mismatch_holding(tmp_path):
    """2330.TW held in TWD, but a (hypothetical) USD analysis — cost rung and
    yield-on-cost must degrade, never divide across currencies."""
    _write_holdings(tmp_path, [{"ticker": "TSM", "avg_cost": 2390.0, "quantity": 20,
                                "currency": "TWD", "asset_type": "equity"}])
    block = xp.run("TSM", str(_analysis_fixture(tmp_path, ticker="TSM")), tmp_path,
                   bear_trigger="t", thesis_status=None)
    assert block["held"] is True
    assert block["yield_on_cost"]["reason"] == "not computable (currency mismatch)"
    assert all(r["rung"] != "cost 2×" for r in block["profit_take_ladder"])
    assert any("currency mismatch" in w for w in block["warnings"])


def test_run_gbp_pence_rescale(tmp_path):
    """Cost basis stored in pence, analysis in GBP → ×0.01, label-decided."""
    _write_holdings(tmp_path, [{"ticker": "EXPN.L", "avg_cost": 3500.0, "quantity": 10,
                                "currency": "GBp", "asset_type": "equity"}])
    block = xp.run("EXPN.L", str(_analysis_fixture(tmp_path, ticker="EXPN.L",
                                                   currency="GBP", dividend_rate=0.60)),
                   tmp_path, bear_trigger="t", thesis_status=None)
    assert block["profit_take_ladder"][-1]["trigger_price"] == 70.0  # 2 × 35.00 GBP
    assert block["yield_on_cost"]["pct"] == round(0.60 / 35.0 * 100, 2)


def test_run_crypto_holding_skips_cost_rung(tmp_path):
    _write_holdings(tmp_path, _HOLDINGS)
    block = xp.run("BTC-EUR", str(_analysis_fixture(tmp_path, ticker="BTC-EUR",
                                                    currency="EUR", dividend_rate=None)),
                   tmp_path, bear_trigger="t", thesis_status=None)
    assert block["held"] is True
    assert all(r["rung"] != "cost 2×" for r in block["profit_take_ladder"])
    assert block["yield_on_cost"]["reason"] == "n/a (non-equity holding)"


def test_run_holdings_yaml_missing(tmp_path):
    block = xp.run("CSCO", str(_analysis_fixture(tmp_path)), tmp_path,
                   bear_trigger="t", thesis_status=None)
    assert block["held"] is False
    assert any("not found" in w for w in block["warnings"])


def test_run_missing_valuation_blocks_degrades(tmp_path):
    _write_holdings(tmp_path, _HOLDINGS)
    p = tmp_path / "thin.json"
    p.write_text(json.dumps({"ticker": "CSCO", "currency": "USD",
                             "schema_version": "2.2", "scores": {"composite": 7.0},
                             "fundamentals": {"dividend_rate": 1.6}}), encoding="utf-8")
    block = xp.run("CSCO", str(p), tmp_path, bear_trigger="t", thesis_status=None)
    assert block["target_exit_pe"]["value"] is None
    assert block["fair_value_range"] is None
    # cost rung survives without fair value (held name)
    assert block["profit_take_ladder"] == [
        {"rung": "cost 2×", "trigger_price": 111.68, "basis": "2× cost (held)"}]


def test_run_reads_log_csv_fallback(tmp_path):
    _write_holdings(tmp_path, _HOLDINGS)
    (tmp_path / "_log.csv").write_text(
        "ticker,date,round,mode,verdict,score,gates_passed,price_at_eval,currency,"
        "size,notes,management_score,management_flag,bear_case_trigger\n"
        'CSCO,2026-06-10,1,deep,invest,7.5,6,60.0,USD,,,,False,'
        '"If X happens, the thesis is broken."\n', encoding="utf-8")
    block = xp.run("CSCO", str(_analysis_fixture(tmp_path)), tmp_path,
                   bear_trigger=None, thesis_status="intact")
    assert block["thesis_broken_trigger"]["source"] == "_log.csv prior evaluation"
    assert block["thesis_broken_trigger"]["pillars_status"] == "intact"


def test_merge_is_overlay_only(tmp_path):
    _write_holdings(tmp_path, _HOLDINGS)
    p = _analysis_fixture(tmp_path)
    before = json.loads(p.read_text(encoding="utf-8"))
    block = xp.run("CSCO", str(p), tmp_path, bear_trigger="t", thesis_status=None)
    xp.merge_into_analysis(str(p), block)
    after = json.loads(p.read_text(encoding="utf-8"))
    # Overlay-only: scores, verdict inputs and schema untouched; one new key.
    assert after["scores"] == before["scores"]
    assert after["schema_version"] == "2.2"
    assert "exit_plan" in after
    assert after["exit_plan"]["held"] is True


# ===================================================================
# pe_band.series persistence (valuation_bands.py)
# ===================================================================
def test_pe_series_records_pairs_years():
    eps = [{"date": "2021-07-31", "eps": 2.0}, {"date": "2022-07-31", "eps": 2.5}]
    assert vb.pe_series_records(eps, [20.0, 22.5]) == [
        {"year": 2021, "pe": 20.0}, {"year": 2022, "pe": 22.5}]


def test_pe_series_records_skips_unusable_and_degraded():
    eps = [{"date": "2021-12-31", "eps": 2.0}, {"date": "2022-12-31", "eps": -1.0}]
    assert vb.pe_series_records(eps, [None, -5.0]) == []
    assert vb.pe_series_records(eps, []) == []  # degraded band ships no series


# ===================================================================
# NI-vs-P/E chart (render_charts.py) — offline, joins on year label
# ===================================================================
def _chart_module():
    import render_charts as rc
    return rc


def test_ni_pe_chart_renders_with_offset_fiscal_years(tmp_path):
    """CSCO-style: FY ends July → fin_history FY labels and EPS fiscal years
    join on the year label; a year missing from one side still renders."""
    rc = _chart_module()
    fin_history = {
        "currency": "USD",
        "annual": {"labels": ["FY2021", "FY2022", "FY2023", "FY2024"],
                   "revenue": [1, 1, 1, 1], "ebitda": [1, 1, 1, 1],
                   "fcf": [1, 1, 1, 1],
                   "net_income": [10.6e9, 11.8e9, None, 10.3e9]},
    }
    bands = {"pe_band": {"series": [{"year": 2022, "pe": 18.1}, {"year": 2023, "pe": 15.2},
                                    {"year": 2024, "pe": 16.0}, {"year": 2025, "pe": 17.3}]}}
    out = tmp_path / "ni_pe.png"
    assert rc.chart_net_income_vs_pe(fin_history, bands, "CSCO", out) is True
    assert out.exists() and out.stat().st_size > 0


def test_ni_pe_chart_fail_soft_on_missing_series(tmp_path):
    rc = _chart_module()
    out = tmp_path / "ni_pe.png"
    no_ni = {"currency": "USD",
             "annual": {"labels": ["FY2024"], "revenue": [1], "ebitda": [1], "fcf": [1]}}
    assert rc.chart_net_income_vs_pe(no_ni, {"pe_band": {"series": [{"year": 2024, "pe": 15}]}},
                                     "T", out) is False
    no_pe = {"currency": "USD",
             "annual": {"labels": ["FY2024"], "revenue": [1], "ebitda": [1], "fcf": [1],
                        "net_income": [5.0]}}
    assert rc.chart_net_income_vs_pe(no_pe, {}, "T", out) is False
    assert rc.chart_net_income_vs_pe(None, {}, "T", out) is False
    assert not out.exists()
