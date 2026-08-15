"""Tests for the two fixes the v4.3 §3.1 audit applied (docs/AUDIT_v43.md).

Both close roadmap items that had been publishing wrong numbers into live reports:

  * **N3** — the own-history P/E band setting price targets off three observations, two
    of which were an earnings collapse (adidas, 2026-07-30).
  * **N4** — `fair_price` taken from a single DCF that survived its ±70 % gate by
    0.30 pp (MSFT, 2026-07-30: \\$118.35 published against a live \\$390.54).

Network-free; synthetic fixtures shaped like the real ones.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import intrinsic_value as iv  # noqa: E402
import valuation_bands as vb  # noqa: E402


# ===================================================================
# N3 — the P/E band may not set a target it cannot support
# ===================================================================
def recs(*eps):
    return [{"date": f"{2010 + i}-12-31", "eps": e} for i, e in enumerate(eps)]


def test_the_collapse_floor_is_relative_to_the_median():
    # Odd count so the median is an observation rather than an average of two.
    floor = vb.collapse_eps_floor(recs(4.0, 4.2, 4.4, 0.10, 4.6))
    assert floor == pytest.approx(4.2 * vb.EPS_ZERO_EPSILON, abs=1e-9)


def test_no_records_no_floor():
    assert vb.collapse_eps_floor([]) is None
    assert vb.collapse_eps_floor(None) is None


def test_a_shallow_band_may_not_set_a_target():
    """adidas: a 3-year band whose median reached 47.73x drove a EUR608 forward target
    and a first trim rung at 2.9x the price."""
    ok, why = vb.band_usability({"depth_years": 3, "median": 47.73})
    assert ok is False and "shallow" in why


def test_a_band_at_the_floor_is_usable():
    ok, why = vb.band_usability({"depth_years": vb.MIN_USABLE_DEPTH})
    assert ok is True and why is None


def test_the_reason_names_the_dropped_collapse_years():
    ok, why = vb.band_usability({"depth_years": 2, "collapse_years": 2})
    assert ok is False and "2 earnings-collapse year(s)" in why


def test_a_missing_band_is_unusable_not_a_crash():
    assert vb.band_usability(None) == (False, "no band")


def test_the_deep_band_of_a_long_history_survives_one_small_year():
    """Writing BOTH conditions into band_usability marked 41 of 48 cached bands
    unusable, ACN (16y) and CSCO (14y) among them. One small-EPS year cannot move a
    median across fifteen observations, so it is EXCLUDED, not disqualifying."""
    ok, _ = vb.band_usability({"depth_years": 15, "collapse_years": 1})
    assert ok is True


def test_justified_exit_pe_refuses_an_unusable_band():
    band = {"median": 47.73, "max": 60.0, "usable": False,
            "usable_reason": "shallow band"}
    assert vb.justified_exit_pe(band) is None


def test_justified_exit_pe_still_works_on_a_usable_band():
    band = {"median": 20.0, "max": 30.0, "usable": True}
    assert vb.justified_exit_pe(band) == 20.0


def test_an_unmarked_band_is_not_treated_as_unusable():
    """Older cached JSONs carry no `usable` key; `is False` and not falsiness is the
    test, or every pre-v4.3 band would silently lose its target."""
    assert vb.justified_exit_pe({"median": 20.0, "max": 30.0}) == 20.0


def test_the_downstream_model_degrades_with_a_reason_rather_than_a_number():
    m = iv.model_two_minute(5.0, 0.10, None)
    assert m["valid"] is False
    assert "band" in m["reason"]


# ===================================================================
# N4 — the fair-price anchor
# ===================================================================
def block(models: dict, blend_value, n_valid):
    return {"models": models,
            "blend": {"value": blend_value, "n_valid": n_valid, "n_models": 5,
                      "label": f"blend of {n_valid}/5"}}


def m(value, valid=True, reason=None):
    return {"value": value, "valid": valid, "reason": reason}


def test_the_blend_is_preferred_over_a_lone_model():
    """MSFT: dcf_valid survived by 0.30pp and published $118.35 against $390.54."""
    b = block({"dcf": m(118.35), "a": m(300.0), "c": m(420.0)}, 279.45, 3)
    got = iv.choose_fair_price({"dcf_valid": True, "dcf_intrinsic": 118.35}, b)
    assert got["fair_price_basis"] == "blend"
    assert got["fair_price"] == 279.45


def test_a_wide_dispersion_switches_to_the_median_not_the_mean():
    b = block({"a": m(10.0), "b": m(100.0), "c": m(1000.0)}, 370.0, 3)
    got = iv.choose_fair_price({}, b)
    assert got["fair_price_basis"] == "blend_median"
    assert got["fair_price"] == 100.0
    assert "disagree" in got["reason"]


def test_the_dispersion_threshold_is_the_one_the_banner_already_uses():
    """One threshold, so the anchor becomes robust at exactly the point the report
    starts warning the reader."""
    import render_report as rr
    assert iv.BLEND_DISPERSION_WIDE == rr.VALUATION_DISPERSION_X


def test_a_narrow_spread_keeps_the_mean():
    b = block({"a": m(90.0), "b": m(100.0), "c": m(110.0)}, 100.0, 3)
    got = iv.choose_fair_price({}, b)
    assert got["fair_price_basis"] == "blend" and got["fair_price"] == 100.0


def test_too_few_models_falls_back_to_a_valid_dcf():
    b = block({"dcf": m(118.35), "a": m(None, False, "no band")}, None, 1)
    got = iv.choose_fair_price({"dcf_valid": True, "dcf_intrinsic": 118.35}, b)
    assert got["fair_price_basis"] == "dcf" and got["fair_price"] == 118.35
    assert "single-model anchor" in got["reason"]


def test_no_models_and_no_dcf_falls_back_to_consensus():
    b = block({"a": m(None, False, "x")}, None, 0)
    got = iv.choose_fair_price(
        {"dcf_valid": False, "consensus": {"target_median": 550.0, "analyst_count": 54}}, b)
    assert got["fair_price_basis"] == "consensus" and got["fair_price"] == 550.0


def test_a_thin_consensus_is_not_an_anchor():
    b = block({}, None, 0)
    got = iv.choose_fair_price(
        {"consensus": {"target_median": 550.0, "analyst_count": 2}}, b)
    assert got["fair_price"] is None
    assert "no anchor" in got["reason"]


def test_nothing_at_all_omits_the_anchor_rather_than_inventing_one():
    got = iv.choose_fair_price({}, block({}, None, 0))
    assert got["fair_price"] is None and got["fair_price_basis"] is None


def test_dispersion_is_reported_even_when_the_anchor_is_the_mean():
    b = block({"a": m(90.0), "b": m(100.0), "c": m(110.0)}, 100.0, 3)
    assert iv.choose_fair_price({}, b)["dispersion"] == pytest.approx(110 / 90, abs=0.01)


def test_the_anchor_is_computed_in_python_not_transcribed_by_the_llm():
    """A structured number printed in a report belongs to a helper (SKILL.md:56). The
    prose rule is what let the MSFT artefact through without anything objecting."""
    skill = (SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
    assert "intrinsic_value.fair_price" in skill
    assert "blend | blend_median | dcf | consensus" in skill


# ===================================================================
# R4 — a cross-venue gap is not a data error
# ===================================================================
import analyze_ticker as at  # noqa: E402


def test_the_stuttgart_case_is_named_rather_than_flagged():
    """ADS.DE: TD answered from XSTU (Stuttgart) with a stale EUR182.25 while Xetra had
    gapped -18% on earnings. The gap was recorded as a yfinance data error."""
    msg = at.venue_mismatch("XSTU", "DE")
    assert msg and "Stuttgart" not in msg.split("(")[0]
    assert "STUTTGART" in msg and "XETRA" in msg
    assert "not a data error" in msg


def test_the_same_venue_is_not_a_mismatch():
    assert at.venue_mismatch("XETRA", "DE") is None
    assert at.venue_mismatch("NYSE", "") is None
    assert at.venue_mismatch("NASDAQ", "") is None


def test_euronext_cities_are_one_venue():
    assert at.venue_mismatch("Euronext Paris", "AS") is None
    assert at.venue_mismatch("Euronext Amsterdam", "PA") is None


@pytest.mark.parametrize("td,suffix", [
    ("Some New Exchange", "DE"),   # unmapped TD spelling
    ("XETRA", "ZZ"),               # unmapped suffix
    (None, "DE"),
    ("XETRA", None),
])
def test_an_unknown_venue_stays_silent_rather_than_manufacturing_a_flag(td, suffix):
    """A false venue flag is another wrong `data_quality: suspect` — the exact defect
    being closed. Silence is the safe default."""
    assert at.venue_mismatch(td, suffix) is None
