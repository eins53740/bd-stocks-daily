"""
Unit tests for v4 Phase B — valuation_bands.py + intrinsic_value.py.

Pure-function tests only: no network, no yfinance. Fixtures are hand-computed.
Covers the two Phase-B acceptance gates (spec §13):
  * the AV budget guard is exercised (budget exhausted → yfinance source)
  * the blend skips an invalid DCF and labels its contributors
plus band stats/percentiles, depth degradation, every model validity guard,
MoS boundaries, IRR math, the sensitivity table and the overlay-only property
(merging never touches scores).
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import financial_history as fh
import intrinsic_value as iv
import valuation_bands as vb


# ===================================================================
# percentile_of / band_stats
# ===================================================================
def test_percentile_midpoint_ties():
    assert vb.percentile_of([10, 20, 30, 40], 30) == 62.5


def test_percentile_none_inputs():
    assert vb.percentile_of([], 10) is None
    assert vb.percentile_of([10, 20], None) is None


def test_band_stats_basic():
    b = vb.band_stats([10.0, 20.0, 30.0, None, -5.0], 25.0, "test")
    assert b["min"] == 10.0 and b["max"] == 30.0 and b["mean"] == 20.0
    assert b["median"] == 20.0
    assert b["depth_years"] == 3
    assert b["excluded_years"] == 1  # the negative-EPS year
    assert b["percentile"] == round(100 * 2 / 3, 1)
    assert b["source"] == "test"


def test_band_stats_empty_series_degrades():
    b = vb.band_stats([None, None], 15.0, "shallow")
    assert b["depth_years"] == 0
    assert b["mean"] is None and b["percentile"] is None


def test_band_stats_no_current():
    b = vb.band_stats([10.0, 20.0], None, "s")
    assert b["current"] is None and b["percentile"] is None
    assert b["depth_years"] == 2


# ===================================================================
# mean_price_in_window
# ===================================================================
def _monthly_2020():
    dates = [f"2020-{m:02d}-01" for m in range(1, 13)]
    closes = [float(m) for m in range(1, 13)]
    return dates, closes


def test_mean_price_full_year_window():
    dates, closes = _monthly_2020()
    assert vb.mean_price_in_window(dates, closes, "2020-12-31") == 6.5


def test_mean_price_partial_window():
    dates, closes = _monthly_2020()
    # 60-day window ending 2020-12-31 → only Nov + Dec closes
    assert vb.mean_price_in_window(dates, closes, "2020-12-31", days=60) == 11.5


def test_mean_price_no_data_in_window():
    dates, closes = _monthly_2020()
    assert vb.mean_price_in_window(dates, closes, "2010-12-31") is None


def test_mean_price_bad_date():
    assert vb.mean_price_in_window(["2020-01-01"], [5.0], "not-a-date") is None


# ===================================================================
# price_scale_factor + unit_consistency (EXPN.L pence/USD live findings)
# ===================================================================
def test_scale_detects_pence_history():
    assert vb.price_scale_factor(2700.0, 27.0) == 0.01   # GBp history vs GBP price
    assert vb.price_scale_factor(3400.0, 27.0) == 0.01   # tolerates FX drift in window


def test_scale_detects_inverse():
    assert vb.price_scale_factor(0.27, 27.0) == 100.0


def test_scale_neutral_cases():
    assert vb.price_scale_factor(30.0, 27.0) == 1.0
    assert vb.price_scale_factor(None, 27.0) == 1.0
    assert vb.price_scale_factor(30.0, None) == 1.0


def test_unit_consistency_ok_and_skewed_and_mismatch():
    assert vb.unit_consistency(22.0, 21.77)[0] == "ok"
    assert vb.unit_consistency(35.0, 21.77)[0] == "skewed"     # ~1.6× → currency skew
    status, msg = vb.unit_consistency(2700.0, 21.77)
    assert status == "mismatch" and "mismatch" in msg
    assert vb.unit_consistency(None, 21.77)[0] == "unknown"
    assert vb.unit_consistency(22.0, None)[0] == "unknown"


# ===================================================================
# choose_eps_source — the AV budget guard (acceptance gate)
# ===================================================================
def test_source_av_for_us_with_key_and_budget():
    assert vb.choose_eps_source("", True, True) == "alphavantage"


def test_source_yf_when_budget_exhausted():
    # Acceptance gate: AV budget guard exercised — an exhausted shared budget
    # (financial_history's own predicate) must route EPS to yfinance.
    budget = {"date": "2026-07-22", "calls": fh.AV_DAILY_LIMIT}
    allowed = fh.av_budget_allows(budget, "2026-07-22", fh.AV_DAILY_LIMIT)
    assert allowed is False
    assert vb.choose_eps_source("", True, allowed) == "yfinance"


def test_source_yf_for_non_us():
    assert vb.choose_eps_source(".LS", True, True) == "yfinance"


def test_source_yf_without_key():
    assert vb.choose_eps_source("", False, True) == "yfinance"


def test_budget_resets_next_day():
    budget = {"date": "2026-07-21", "calls": 99}
    assert fh.av_budget_allows(budget, "2026-07-22", fh.AV_DAILY_LIMIT) is True


# ===================================================================
# cagr_ladder_from_annual
# ===================================================================
def _rev_10pct(n):
    labels = [f"FY{2015 + i}" for i in range(n)]
    revs = [100.0 * 1.1 ** i for i in range(n)]
    return labels, revs


def test_ladder_windows_at_7_years():
    labels, revs = _rev_10pct(7)
    l = vb.cagr_ladder_from_annual(labels, revs)
    assert round(l["1y"], 3) == 0.1 and round(l["3y"], 3) == 0.1 and round(l["5y"], 3) == 0.1
    assert l["10y"] is None and l["15y"] is None  # depth-gated until Phase E
    assert l["depth_years"] == 7


def test_ladder_year_aware_gap_nulls_rung():
    labels = ["FY2024", "FY2022", "FY2023", "FY2021"]
    revs = [133.1, 110.0, None, 100.0]
    l = vb.cagr_ladder_from_annual(labels, revs)
    assert l["depth_years"] == 3
    assert l["1y"] is None  # FY2023 revenue missing → the 1y rung nulls, never shrinks
    assert round(l["3y"], 3) == 0.1  # FY2021 100 → FY2024 133.1 over exactly 3 years


def test_ladder_empty():
    l = vb.cagr_ladder_from_annual([], [])
    assert l["1y"] is None and l["depth_years"] == 0


# ===================================================================
# growth_anchor
# ===================================================================
def test_anchor_median_of_inputs():
    ladder = {"1y": 0.20, "3y": 0.10, "5y": 0.06, "10y": None, "15y": None}
    a = vb.growth_anchor(ladder, 0.12)
    assert a["g"] == 0.11  # median of [0.20, 0.10, 0.06, 0.12]
    assert "consensus_eps_growth" in a["basis"]
    assert "revenue_cagr_1y" in a["basis"]


def test_anchor_clamped_high():
    a = vb.growth_anchor({"1y": 0.80}, None)
    assert a["g"] == vb.GROWTH_CLAMP[1]
    assert a["clamped"] is True


def test_anchor_no_inputs():
    a = vb.growth_anchor({"1y": None}, None)
    assert a["g"] is None and a["basis"] == []


# ===================================================================
# forward_target — TIKR presentation: target + total return + IRR
# ===================================================================
TODAY = date(2026, 1, 1)


def test_forward_target_consensus_path():
    f = vb.forward_target(5.0, 4.0, 0.10, 20.0, 80.0, 1.0, 3, TODAY)
    assert f["valid"] is True and f["eps_basis"] == "consensus_next_fy"
    assert f["eps_horizon"] == round(5.0 * 1.1 ** 2, 2)
    assert f["target_price"] == 121.0
    assert f["horizon_label"] == "FY2029" and f["horizon_date"] == "2029-12-31"
    # total: (121 + 3×1.0)/80 − 1 = 55%; IRR = 1.55^(1/3) − 1
    assert f["est_total_return_pct"] == 55.0
    assert f["irr_annualized_pct"] == round(((124.0 / 80.0) ** (1 / 3) - 1) * 100, 1)


def test_forward_target_irr_vs_total_return_divergence():
    # A big total return over a long horizon must not masquerade as a good
    # annual one — IRR is always the smaller number for positive returns >1y.
    f = vb.forward_target(5.0, None, 0.10, 20.0, 80.0, 0.0, 3, TODAY)
    assert f["irr_annualized_pct"] < f["est_total_return_pct"]


def test_forward_target_ttm_fallback():
    f = vb.forward_target(None, 4.0, 0.10, 20.0, 80.0, 0.0, 3, TODAY)
    assert f["valid"] and f["eps_basis"] == "eps_ttm"
    assert f["eps_horizon"] == round(4.0 * 1.1 ** 3, 2)


def test_forward_target_invalid_without_growth():
    f = vb.forward_target(5.0, 4.0, None, 20.0, 80.0, 0.0, 3, TODAY)
    assert f["valid"] is False and "growth" in f["reason"]


def test_forward_target_invalid_without_band():
    f = vb.forward_target(5.0, 4.0, 0.10, None, 80.0, 0.0, 3, TODAY)
    assert f["valid"] is False and "exit P/E" in f["reason"]


def test_forward_target_invalid_without_eps():
    f = vb.forward_target(None, -2.0, 0.10, 20.0, 80.0, 0.0, 3, TODAY)
    assert f["valid"] is False and "EPS" in f["reason"]


# ===================================================================
# justified_exit_pe — median beats outlier-polluted mean (ADSK live case)
# ===================================================================
def test_exit_pe_prefers_median_over_mean():
    # Transition years with near-zero EPS drag the mean to 51× while the
    # median stays ~32× — the median is what a buyer should underwrite.
    band = {"median": 31.9, "mean": 51.5, "max": 134.8}
    assert vb.justified_exit_pe(band) == 31.9


def test_exit_pe_falls_back_to_mean_and_caps_at_max():
    assert vb.justified_exit_pe({"mean": 18.0, "max": 30.0}) == 18.0
    assert vb.justified_exit_pe({"median": 40.0, "mean": 35.0, "max": 25.0}) == 25.0


def test_exit_pe_none_without_band():
    assert vb.justified_exit_pe(None) is None
    assert vb.justified_exit_pe({}) is None


def test_forward_target_sanity_flag_on_implausible_irr():
    # 5 × 1.5² × 60 ≈ 675 target on an 80 price → IRR ≫ 30%/yr → flagged.
    f = vb.forward_target(5.0, None, 0.50, 60.0, 80.0, 0.0, 3, TODAY)
    assert f["valid"] is True
    assert f["sanity_flag"] is not None and "IRR" in f["sanity_flag"]


def test_forward_target_no_sanity_flag_on_normal_irr():
    f = vb.forward_target(5.0, 4.0, 0.10, 20.0, 80.0, 1.0, 3, TODAY)
    assert f["sanity_flag"] is None


# ===================================================================
# sensitivity_table
# ===================================================================
PE_SERIES = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0]


def test_sensitivity_three_rows():
    s = vb.sensitivity_table(PE_SERIES, 6.05, None, None, None, None)
    assert len(s["rows"]) == 3
    labels = [r["label"] for r in s["rows"]]
    assert "conservative" in labels[0] and "mean" in labels[1] and "high" in labels[2]
    assert s["rows"][1]["fair_value"] == round(6.05 * 15.0, 2)
    assert s["rows"][2]["fair_value"] == 121.0
    assert s["margin_bear_row"] is None  # no margin inputs supplied


def test_sensitivity_margin_bear_row():
    s = vb.sensitivity_table(PE_SERIES, 6.05, 1000.0, 100.0, 0.10, 0.08)
    row = s["margin_bear_row"]
    rps_h = 1000.0 * 1.1 ** 3 / 100.0
    assert row["fair_value"] == round(rps_h * 0.08 * 15.0, 2)
    assert row["multiple"] == 15.0


def test_sensitivity_empty_without_eps():
    s = vb.sensitivity_table(PE_SERIES, None, 1000.0, 100.0, 0.10, 0.08)
    assert s["rows"] == [] and s["margin_bear_row"] is None


def test_sensitivity_empty_without_series():
    s = vb.sensitivity_table([None, -3.0], 6.05, None, None, None, None)
    assert s["rows"] == []


# ===================================================================
# intrinsic_value — CAPM + the five models
# ===================================================================
def test_capm_basic():
    assert iv.capm_cost_of_equity(0.04, 1.2) == 0.04 + 1.2 * iv.ERP


def test_capm_beta_fallback():
    assert iv.capm_cost_of_equity(0.04, None) == 0.04 + 1.0 * iv.ERP


def test_two_minute_math():
    m = iv.model_two_minute(4.0, 0.10, 20.0)
    expected = round(4.0 * 1.1 ** 5 * 20.0 / 1.12 ** 5, 2)
    assert m["valid"] and m["value"] == expected


def test_two_minute_invalid_negative_eps():
    m = iv.model_two_minute(-1.0, 0.10, 20.0)
    assert m["valid"] is False and "EPS" in m["reason"]


def test_two_minute_invalid_no_band():
    m = iv.model_two_minute(4.0, 0.10, None)
    assert m["valid"] is False and "exit P/E" in m["reason"]


def test_lynch_peg_math():
    m = iv.model_lynch_peg(4.0, 0.15)
    assert m["valid"] and m["value"] == 60.0
    assert m["assumptions"]["fair_pe"] == 15.0


def test_lynch_peg_rejects_slow_and_hyper_growers():
    assert iv.model_lynch_peg(4.0, 0.03)["valid"] is False
    assert iv.model_lynch_peg(4.0, 0.60)["valid"] is False
    assert iv.model_lynch_peg(4.0, None)["valid"] is False


def test_forward_pe_model_discounts_target():
    m = iv.model_forward_pe({"valid": True, "target_price": 121.0, "horizon_years": 3})
    assert m["valid"] and m["value"] == round(121.0 / 1.12 ** 3, 2)


def test_forward_pe_model_passthrough_reason():
    m = iv.model_forward_pe({"valid": False, "reason": "no growth anchor"})
    assert m["valid"] is False and m["reason"] == "no growth anchor"
    assert iv.model_forward_pe(None)["valid"] is False


def test_dcf_model_gated_by_validity():
    assert iv.model_dcf(150.0, True, None) == {"value": 150.0, "valid": True, "reason": None}
    m = iv.model_dcf(150.0, False, "likely cyclical distortion in base FCF")
    assert m["valid"] is False and "cyclical" in m["reason"]


def test_residual_income_math():
    m = iv.model_residual_income(10.0, 0.20, 0.09)
    assert m["valid"] and m["value"] == round(10.0 + 10.0 * (0.20 - 0.09) / (0.09 - 0.025), 2)


def test_residual_income_guards():
    assert iv.model_residual_income(None, 0.2, 0.09)["valid"] is False
    assert iv.model_residual_income(10.0, None, 0.09)["valid"] is False
    assert iv.model_residual_income(10.0, 0.2, 0.03)["valid"] is False   # Ke too close to g
    assert iv.model_residual_income(10.0, 0.01, 0.09)["valid"] is False  # negative intrinsic


# ===================================================================
# blend + MoS (acceptance gate: skip invalid DCF, label contributors)
# ===================================================================
def _models_with_invalid_dcf():
    return {
        "two_minute_eps_growth": {"value": 100.0, "valid": True, "reason": None},
        "lynch_peg": {"value": 90.0, "valid": True, "reason": None},
        "forward_pe_target": {"value": 110.0, "valid": True, "reason": None},
        "dcf": {"value": None, "valid": False, "reason": "cyclical distortion"},
        "roe_residual_income": {"value": 80.0, "valid": True, "reason": None},
    }


def test_blend_skips_invalid_dcf_and_labels():
    b = iv.blend_models(_models_with_invalid_dcf())
    assert b["value"] == 95.0  # mean of 100, 90, 110, 80
    assert b["n_valid"] == 4 and b["n_models"] == 5
    assert "dcf" not in b["contributors"]
    assert b["label"].startswith("blend of 4/5")
    assert "dcf excluded: cyclical distortion" in b["label"]


def test_blend_not_computable_below_two_models():
    models = {k: {"value": None, "valid": False, "reason": "x"} for k in ("a", "b", "c")}
    models["d"] = {"value": 50.0, "valid": True, "reason": None}
    b = iv.blend_models(models)
    assert b["value"] is None and "not computable" in b["label"]


def test_mos_boundaries():
    assert iv.mos_verdict(100.0, 70.0)["mos_class"] == "deep_value"   # +30%
    assert iv.mos_verdict(100.0, 75.0)["mos_class"] == "deep_value"   # exactly +25%
    assert iv.mos_verdict(100.0, 95.0)["mos_class"] == "fair"         # +5%
    assert iv.mos_verdict(100.0, 110.0)["mos_class"] == "fair"        # exactly −10%
    assert iv.mos_verdict(100.0, 120.0)["mos_class"] == "rich"        # −20%
    assert iv.mos_verdict(None, 100.0)["mos_class"] == "not_computable"
    assert iv.mos_verdict(100.0, None)["mos_class"] == "not_computable"


# ===================================================================
# EV wedge + fair-value range
# ===================================================================
def test_ev_wedge_net_debt_drag():
    e = iv.ev_vs_market_cap(100e9, 120e9, 20e9)
    assert e["wedge_pct"] == 20.0 and "net-debt drag" in e["note"]


def test_ev_wedge_net_cash_cushion():
    e = iv.ev_vs_market_cap(100e9, 90e9, -10e9)
    assert "net-cash cushion" in e["note"]


def test_ev_wedge_not_computable():
    assert "not computable" in iv.ev_vs_market_cap(None, 90e9, None)["note"]


def test_fair_value_range_is_model_spread_and_ordered():
    r = iv.fair_value_range(_models_with_invalid_dcf(), 95.0)
    assert r == {"low": 80.0, "mid": 95.0, "high": 110.0,
                 "basis": "min / blend / max of valid intrinsic models"}
    assert r["low"] <= r["mid"] <= r["high"]


def test_fair_value_range_degrades():
    r = iv.fair_value_range({}, None)
    assert r["low"] is None and r["mid"] is None and r["high"] is None


# ===================================================================
# Integration: run() on a synthetic analysis JSON — overlay-only proof
# ===================================================================
def _analysis_fixture(tmp_path: Path) -> Path:
    data = {
        "ticker": "TEST",
        "price_current": 100.0,
        "currency": "USD",
        "schema_version": "2.2",
        "fundamentals": {
            "pe_ratio": 20.0, "eps_ttm": 5.0, "book_value": 10.0,
            "roe_ttm": 0.20, "beta": 1.0, "market_cap": 100e9,
            "enterprise_value": 120e9, "net_debt": 20e9,
        },
        "dcf_intrinsic": 150.0, "dcf_valid": False,
        "dcf_reason": "likely cyclical distortion in base FCF",
        "scores": {"composite": 7.5, "valuation": 6.0},
        "valuation_bands": {
            "growth_anchor": {"g": 0.10},
            "pe_band": {"mean": 18.0, "max": 30.0},
            "forward_target": {"valid": True, "target_price": 121.0, "horizon_years": 3},
            "sensitivity": {"rows": [{"fair_value": 72.6}, {"fair_value": 90.75},
                                     {"fair_value": 121.0}]},
        },
    }
    p = tmp_path / "analysis.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_run_blends_and_skips_invalid_dcf(tmp_path):
    block = iv.run(str(_analysis_fixture(tmp_path)), rf_override=0.04)
    assert block["blend"]["n_valid"] == 4  # all but the invalid DCF
    assert "dcf excluded" in block["blend"]["label"]
    assert block["capm"]["rf_source"] == "override"
    assert block["mos_class"] in ("deep_value", "fair", "rich")
    assert block["fair_value_range"]["mid"] == block["blend"]["value"]


def test_merge_is_overlay_only(tmp_path):
    p = _analysis_fixture(tmp_path)
    before = json.loads(p.read_text(encoding="utf-8"))
    block = iv.run(str(p), rf_override=0.04)
    iv.merge_into_analysis(str(p), block)
    after = json.loads(p.read_text(encoding="utf-8"))
    # Overlay-only: scores, verdict inputs and schema untouched; one new key.
    assert after["scores"] == before["scores"]
    assert after["schema_version"] == "2.2"
    assert "intrinsic_value" in after
    assert after["intrinsic_value"]["blend"]["value"] == block["blend"]["value"]
