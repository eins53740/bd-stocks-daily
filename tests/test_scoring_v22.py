"""
Phase-2 (schema v2.2) pure-function unit tests for the scoring engine.

Covers the five v2.2 features:
  1. ROIC (Magic Formula proxy) math
  2. EV/EBIT math
  3. Buffett-moat multiplier (>25% fires, <=25% no-op, caps at 10)
  4. News-event time decay (half-life 7d)
  5. Gate-5 (net-margin) growth-bypass predicate

All functions under test are PURE — no network, no yfinance. They live in
analyze_ticker.py and are imported directly.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from analyze_ticker import (  # noqa: E402
    apply_buffett_moat,
    compute_ev_ebit,
    compute_news_freshness,
    compute_roce,
    compute_roic,
    gate5_growth_bypass,
)


# ------------------------- 1. ROIC -------------------------
def test_roic_known_inputs():
    # EBIT 1000, tax 200 / pretax 800 -> eff rate 0.25
    # NOPAT = 1000 * (1 - 0.25) = 750
    # Invested capital = debt 2000 + equity 3000 - cash 500 = 4500
    # ROIC = 750 / 4500 = 0.16667
    roic = compute_roic(ebit=1000, tax_provision=200, pretax_income=800,
                        total_debt=2000, total_equity=3000, cash=500)
    assert roic == round(750 / 4500, 6)


def test_roic_default_tax_when_inputs_missing():
    # No tax/pretax -> default 0.21. NOPAT = 1000*0.79 = 790. IC = 1000+1000-0 = 2000
    roic = compute_roic(ebit=1000, tax_provision=None, pretax_income=None,
                        total_debt=1000, total_equity=1000, cash=0)
    assert roic == round(790 / 2000, 6)


def test_roic_tax_rate_clamped_high():
    # tax 900 / pretax 1000 = 0.9 -> clamp to 0.35. NOPAT = 1000*0.65 = 650
    roic = compute_roic(ebit=1000, tax_provision=900, pretax_income=1000,
                        total_debt=1000, total_equity=1000, cash=0)
    assert roic == round(650 / 2000, 6)


def test_roic_none_when_denominator_nonpositive():
    # IC = 500 + 200 - 1000 = -300 <= 0 -> None
    assert compute_roic(ebit=1000, tax_provision=None, pretax_income=None,
                        total_debt=500, total_equity=200, cash=1000) is None


def test_roic_none_when_ebit_missing():
    assert compute_roic(ebit=None, tax_provision=10, pretax_income=100,
                        total_debt=1000, total_equity=1000, cash=0) is None


# ------------------------- 2. EV/EBIT -------------------------
def test_ev_ebit_known_inputs():
    # EV = mc 8000 + debt 2000 - cash 1000 = 9000 ; EBIT 1500 -> 6.0
    assert compute_ev_ebit(market_cap=8000, total_debt=2000, cash=1000, ebit=1500) == 6.0


def test_ev_ebit_none_when_ebit_nonpositive():
    assert compute_ev_ebit(market_cap=8000, total_debt=2000, cash=1000, ebit=0) is None
    assert compute_ev_ebit(market_cap=8000, total_debt=2000, cash=1000, ebit=-50) is None


def test_ev_ebit_none_when_market_cap_missing():
    assert compute_ev_ebit(market_cap=None, total_debt=2000, cash=1000, ebit=1500) is None


# ------------------------- 3. Buffett moat multiplier -------------------------
def test_buffett_fires_above_25pct():
    score, applied = apply_buffett_moat(6.0, roic_ttm=0.30)
    assert applied is True
    assert score == round(6.0 * 1.25, 2)  # 7.5


def test_buffett_no_op_at_exactly_25pct():
    score, applied = apply_buffett_moat(6.0, roic_ttm=0.25)
    assert applied is False
    assert score == 6.0


def test_buffett_no_op_when_roic_none():
    score, applied = apply_buffett_moat(6.0, roic_ttm=None)
    assert applied is False
    assert score == 6.0


def test_buffett_caps_at_10():
    score, applied = apply_buffett_moat(9.0, roic_ttm=0.40)
    assert applied is True
    assert score == 10.0  # 9*1.25=11.25 capped


# ------------------------- 4. News-event time decay -------------------------
def test_decay_at_zero_is_one():
    assert compute_news_freshness(0) == 1.0


def test_decay_at_half_life_is_half():
    assert compute_news_freshness(7) == 0.5


def test_decay_at_two_half_lives():
    assert compute_news_freshness(14) == 0.25


def test_decay_none_when_no_earnings():
    assert compute_news_freshness(None) is None


def test_decay_matches_formula():
    lam = math.log(2) / 7
    assert compute_news_freshness(3) == round(math.exp(-lam * 3), 3)


# ------------------------- 5. Gate-5 growth-bypass predicate -------------------------
def test_bypass_fires_when_all_conditions_hold():
    ok, reason = gate5_growth_bypass(
        revenue_cagr_5y=0.30, roic_ttm=0.18,
        fcf_rev_latest=0.12, fcf_rev_prior=0.08,
    )
    assert ok is True
    assert reason and "bypass" in reason.lower()


def test_bypass_blocked_low_cagr():
    ok, reason = gate5_growth_bypass(0.20, 0.18, 0.12, 0.08)
    assert ok is False
    assert reason is None


def test_bypass_blocked_low_roic():
    ok, _ = gate5_growth_bypass(0.30, 0.14, 0.12, 0.08)
    assert ok is False


def test_bypass_blocked_fcf_not_improving():
    ok, _ = gate5_growth_bypass(0.30, 0.18, 0.08, 0.10)
    assert ok is False


def test_bypass_blocked_when_inputs_none():
    assert gate5_growth_bypass(None, 0.18, 0.12, 0.08)[0] is False
    assert gate5_growth_bypass(0.30, None, 0.12, 0.08)[0] is False
    assert gate5_growth_bypass(0.30, 0.18, None, 0.08)[0] is False
    assert gate5_growth_bypass(0.30, 0.18, 0.12, None)[0] is False
