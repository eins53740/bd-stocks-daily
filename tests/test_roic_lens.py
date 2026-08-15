"""Tests for scripts/roic_lens.py (v4.3 wave 3.6).

The doctrine lives in `docs/ROIC_vs_ROE.md`; these pin the four rules that enforce it, so
the doc and the code cannot drift apart the way SKILL.md and the schedule did.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import roic_lens as rl  # noqa: E402

DOC = SCRIPTS.parent / "docs" / "ROIC_vs_ROE.md"


def a(**kw):
    base = {
        "ticker": "TEST", "sector": "Technology", "industry": "Software",
        "fundamentals": {"roic_ttm": 0.20, "roe_ttm": 0.22, "roe_5y_avg": 0.21,
                         "roce_ttm": 0.18, "debt_to_equity": 0.4,
                         "market_cap": 1000.0, "total_debt": 200.0, "total_cash": 100.0},
        "statements_raw": {
            "income": {"operating_income": [150.0, 140.0], "pretax_income": [130.0, 120.0],
                       "net_income": [100.0, 95.0], "interest_expense": [10.0, 9.0]},
            "balance": {"stockholders_equity": [500.0, 460.0], "total_debt": [200.0, 190.0],
                        "total_assets": [900.0, 850.0], "ppe_net": [300.0, 280.0],
                        "goodwill": [50.0, 50.0]},
        },
        "intrinsic_value": {"capm": {"cost_of_equity": 0.09}},
    }
    for k, v in kw.items():
        if k in ("fundamentals",) and isinstance(v, dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


# --- rule 1: leverage-manufactured ROE --------------------------------------
def test_a_levered_high_roe_on_a_low_roic_business_is_flagged():
    b = rl.compute(a(fundamentals={"roe_ttm": 0.28, "debt_to_equity": 2.1,
                                   "roic_ttm": 0.09}))
    lev = b["leverage_manufactured_roe"]
    assert lev["flagged"] is True
    assert "financed, not earned" in lev["note"]
    assert lev["thresholds"] == {"roe_min": 0.20, "de_min": 1.0, "roic_max": 0.12}


@pytest.mark.parametrize("over", [
    {"roe_ttm": 0.28, "debt_to_equity": 2.1, "roic_ttm": 0.19},   # ROIC is fine
    {"roe_ttm": 0.28, "debt_to_equity": 0.3, "roic_ttm": 0.09},   # not levered
    {"roe_ttm": 0.12, "debt_to_equity": 2.1, "roic_ttm": 0.09},   # ROE not high
])
def test_all_three_conditions_are_required(over):
    assert rl.compute(a(fundamentals=over))["leverage_manufactured_roe"]["flagged"] is False


def test_the_flag_never_touches_the_score():
    b = rl.compute(a(fundamentals={"roe_ttm": 0.28, "debt_to_equity": 2.1,
                                   "roic_ttm": 0.09}))
    assert "scores" not in b and "verdict" not in b and "composite" not in b


# --- rule 2: ROIC vs WACC ---------------------------------------------------
def test_wacc_blends_the_capm_equity_cost_with_a_derived_debt_cost():
    b = rl.compute(a())
    w = b["wacc"]
    # kd = 10 / mean(200, 190) = 5.128 %; tax = 1 - 100/130 = 23.08 %;
    # we = 1000 / 1200 = 0.8333
    assert w["cost_of_debt"] == pytest.approx(0.05128, abs=1e-4)
    assert w["tax_rate"] == pytest.approx(0.2308, abs=1e-3)
    expected = 0.09 * (1000 / 1200) + 0.05128 * (1 - 0.2308) * (200 / 1200)
    assert w["value"] == pytest.approx(expected, abs=1e-4)


def test_no_cost_of_equity_means_no_wacc_rather_than_an_assumed_one():
    """Inventing a discount rate behind a value-creation verdict is the exact failure
    roadmap N4 records for the DCF."""
    d = a()
    d.pop("intrinsic_value")
    b = rl.compute(d)
    assert b["wacc"]["value"] is None
    assert any("not computed rather than assumed" in n for n in b["wacc"]["notes"])
    assert b["roic_vs_wacc"]["verdict"] is None


def test_a_debt_free_company_has_wacc_equal_to_its_cost_of_equity():
    d = a(fundamentals={"total_debt": 0.0})
    d["statements_raw"]["balance"]["total_debt"] = [0.0, 0.0]
    b = rl.compute(d)
    assert b["wacc"]["value"] == pytest.approx(0.09)
    assert b["wacc"]["weight_equity"] == 1.0


def test_an_implausible_derived_cost_of_debt_is_refused():
    d = a()
    d["statements_raw"]["income"]["interest_expense"] = [900.0, 900.0]
    b = rl.compute(d)
    assert b["wacc"]["value"] is None
    assert any("not what it claims to be" in n for n in b["wacc"]["notes"])


@pytest.mark.parametrize("roic,expect", [
    (0.20, "creates value"), (0.05, "destroys value"), (0.086, "marginal")])
def test_the_value_verdict_has_a_neutral_band(roic, expect):
    b = rl.compute(a(fundamentals={"roic_ttm": roic}))
    assert b["roic_vs_wacc"]["verdict"] == expect


def test_the_tax_rate_uses_the_same_clamp_as_compute_roic():
    """One company must not carry two different effective tax rates in one report."""
    assert rl.TAX_CLAMP == (0.0, 0.35)
    hi = rl.effective_tax_rate({"pretax_income": [100.0], "net_income": [10.0]})
    assert hi[0] == 0.35
    lo = rl.effective_tax_rate({"pretax_income": [100.0], "net_income": [140.0]})
    assert lo[0] == 0.0
    missing = rl.effective_tax_rate({})
    assert missing[0] == rl.DEFAULT_TAX and "default" in missing[1]


def test_cost_of_debt_uses_average_debt():
    kd, src = rl.cost_of_debt({"interest_expense": [10.0]},
                              {"total_debt": [300.0, 100.0]})
    assert kd == pytest.approx(0.05)
    assert "average" in src


# --- rule 3: ROIC is deliberately None --------------------------------------
def test_a_suppressed_roic_falls_back_to_roe_and_explains_why():
    """VEEV: cash 7.31bn against equity 7.28bn printed ROIC 13,671 % before the guard."""
    b = rl.compute(a(fundamentals={"roic_ttm": None}))
    assert b["preferred_metric"] == "roe"
    assert "IC_MIN_FRACTION" in b["preferred_reason"]


def test_the_silently_unfired_buffett_multiplier_is_stated():
    b = rl.compute(a(fundamentals={"roic_ttm": None}))
    bm = b["buffett_multiplier"]
    assert bm["fires"] is False
    assert "silently does not fire" in bm["note"]
    assert bm["gate"] == 0.25


def test_a_high_roic_fires_the_multiplier():
    b = rl.compute(a(fundamentals={"roic_ttm": 0.31}))
    assert b["buffett_multiplier"]["fires"] is True
    assert b["buffett_multiplier"]["note"] is None


# --- rule 4: financials -----------------------------------------------------
@pytest.mark.parametrize("sector,industry", [
    ("Financial Services", "Banks - Regional"),
    ("Industrials", "Insurance - Diversified"),
    ("Technology", "Capital Markets"),
])
def test_banks_and_insurers_are_routed_away_from_roic(sector, industry):
    b = rl.compute(a(sector=sector, industry=industry))
    assert b["is_financial"] is True
    assert b["preferred_metric"] in ("roe", "rote")
    assert "raw material" in b["preferred_reason"]


def test_rote_is_preferred_when_tangible_equity_is_derivable():
    b = rl.compute(a(sector="Financial Services", industry="Banks"))
    assert b["preferred_metric"] == "rote"
    assert b["rote"] == pytest.approx(100.0 / (500.0 - 50.0), abs=1e-4)


def test_a_non_financial_with_healthy_roic_prefers_roic():
    b = rl.compute(a())
    assert b["is_financial"] is False and b["preferred_metric"] == "roic"


# --- capital intensity and goodwill ----------------------------------------
def test_roic_ex_goodwill_is_reported_beside_roic():
    b = rl.compute(a())
    # IC = 200 + 500 - 100 = 600; ex-goodwill 550; NOPAT = 150 * (1 - 0.2308)
    assert b["roic_ex_goodwill"] == pytest.approx(150 * (1 - 0.2308) / 550, abs=1e-4)
    assert b["roic_ex_goodwill"] > b["roic"] or b["roic"] is None


def test_the_combined_intangibles_row_is_not_double_counted():
    d = a()
    d["statements_raw"]["balance"]["goodwill_and_intangibles"] = [120.0, 120.0]
    b = rl.compute(d)
    assert b["tangible_equity"] == pytest.approx(380.0)  # 500 - 120, never 500 - 50 - 120


def test_asset_light_and_goodwill_heavy_are_both_surfaced():
    d = a()
    d["statements_raw"]["balance"]["ppe_net"] = [50.0, 45.0]
    d["statements_raw"]["balance"]["goodwill"] = [300.0, 300.0]
    b = rl.compute(d)
    assert b["capital_intensity"]["asset_light"] is True
    assert b["capital_intensity"]["goodwill_heavy"] is True
    assert any("asset-light" in n for n in b["notes"])
    assert any("goodwill-heavy" in n for n in b["notes"])


def test_negative_ex_goodwill_capital_is_refused_not_printed():
    d = a()
    d["statements_raw"]["balance"]["goodwill"] = [900.0, 900.0]
    b = rl.compute(d)
    assert b["roic_ex_goodwill"] is None
    assert any("at or below zero" in n for n in b["notes"])


# --- plumbing ---------------------------------------------------------------
def test_the_block_is_additive_and_versioned():
    b = rl.compute(a())
    assert b["schema"] == "roic_lens/1"


def test_compute_is_pure():
    d = a()
    before = json.dumps(d, sort_keys=True)
    one, two = rl.compute(d), rl.compute(d)
    assert json.dumps(d, sort_keys=True) == before
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)


def test_an_empty_json_degrades_without_raising():
    b = rl.compute({})
    assert b["roic"] is None and b["wacc"]["value"] is None
    assert b["preferred_metric"] == "roe"


def test_render_lines_shows_the_flag_when_it_fires():
    b = rl.compute(a(fundamentals={"roe_ttm": 0.28, "debt_to_equity": 2.1,
                                   "roic_ttm": 0.09}))
    text = "\n".join(rl.render_lines(b))
    assert "⚠" in text and "ROIC vs WACC" in text


def test_cli_update_merges_the_block(tmp_path, monkeypatch):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(a()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["roic_lens.py", str(p), "--update"])
    assert rl.main() == 0
    merged = json.loads(p.read_text(encoding="utf-8"))
    assert merged["roic_lens"]["preferred_metric"] == "roic"
    assert merged["ticker"] == "TEST"


# --- the doctrine document has to exist and agree with the code -------------
def test_the_doctrine_document_publishes_every_threshold():
    text = DOC.read_text(encoding="utf-8")
    for token in ("20", "1.0", "12", "25"):
        assert token in text
    for phrase in ("ROTE", "IC_MIN_FRACTION", "WACC", "ex-goodwill"):
        assert phrase in text
