"""
Phase-5 unit tests for the Investment Thesis dashboard derivation engine.

All pure-function, network-free and DB-free. Exercises:
  * overall_score()   — 70/30 fund/tech blend with None handling
  * quality/valuation/risk reads — band logic over stored scalars
  * derive_pillars()  — 3–5 pillars with status (intact/weakened/broken)
                        + conviction (High/Med/Low), incl. bear-trigger guard
  * pillar_summary()  — roll-up
  * derive_stance()   — Buy / Hold / Sell on synthetic report data
  * build_thesis_entry() — end-to-end shape
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from thesis_dashboard import (  # noqa: E402
    build_thesis_entry,
    derive_pillars,
    derive_stance,
    overall_score,
    pillar_summary,
    quality_read,
    risk_read,
    valuation_read,
)


def _rep(**kw) -> dict:
    """Synthetic slim-report dict. Strong-quality investable base; override per test."""
    base = {
        "ticker": "TEST",
        "date": "2026-06-01",
        "sector": "Technology",
        "region": "US",
        "size": "big",
        "mode": "deep",
        "verdict": "invest",
        "score": 8.0,
        "gates_passed": 6,
        "piotroski": 7,
        "altman": 5.0,
        "mgmt": 8.0,
        "mgmt_flag": False,
        "tech_score": 7.0,
        "go_no_go": "GO",
        "tech_risk": "Low",
        "bear_case_trigger": "If net subscriber growth turns negative two quarters running.",
        "thesis": "Quality compounder at a discount.",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------- overall_score
def test_overall_blend():
    assert overall_score(8.0, 7.0) == 7.7  # 0.7*8 + 0.3*7


def test_overall_fund_only():
    assert overall_score(7.0, None) == 7.0


def test_overall_tech_only():
    assert overall_score(None, 6.5) == 6.5


def test_overall_none():
    assert overall_score(None, None) is None


# ---------------------------------------------------------------- reads
def test_quality_strong():
    assert quality_read(_rep(gates_passed=6, piotroski=7))["label"] == "Strong"


def test_quality_adequate():
    assert quality_read(_rep(gates_passed=5, piotroski=4))["label"] == "Adequate"


def test_quality_weak():
    assert quality_read(_rep(gates_passed=3, piotroski=3))["label"] == "Weak"


def test_quality_unknown():
    assert quality_read(_rep(gates_passed=None, piotroski=None))["label"] == "Unknown"


def test_valuation_attractive():
    assert valuation_read(_rep(score=8.0, verdict="invest"))["label"] == "Attractive"


def test_valuation_fair():
    assert valuation_read(_rep(score=6.0, verdict="fair"))["label"] == "Fair"


def test_valuation_stretched():
    assert valuation_read(_rep(score=4.0, verdict="reject"))["label"] == "Stretched"


def test_risk_high_when_distress_and_flag():
    r = risk_read(_rep(altman=1.5, mgmt_flag=True, tech_risk="High"))
    assert r["label"] == "High"


def test_risk_low_when_solvent_clean():
    assert risk_read(_rep(altman=5.0, mgmt_flag=False, tech_risk="Low"))["label"] == "Low"


# ---------------------------------------------------------------- pillars
def test_pillars_count_three_to_five():
    pillars = derive_pillars(_rep())
    assert 3 <= len(pillars) <= 5


def test_pillars_have_status_and_conviction():
    for p in derive_pillars(_rep()):
        assert p["status"] in ("intact", "weakened", "broken")
        assert p["conviction"] in ("High", "Med", "Low")
        assert p["claim"] and p["evidence"]


def test_pillar_quality_intact_for_strong():
    pillars = {p["name"]: p for p in derive_pillars(_rep(gates_passed=6))}
    assert pillars["Business quality"]["status"] == "intact"


def test_pillar_quality_broken_for_weak():
    pillars = {p["name"]: p for p in derive_pillars(_rep(gates_passed=3))}
    assert pillars["Business quality"]["status"] == "broken"


def test_pillar_balance_sheet_broken_on_low_altman():
    pillars = {p["name"]: p for p in derive_pillars(_rep(altman=1.0))}
    assert pillars["Balance-sheet resilience"]["status"] == "broken"


def test_pillar_management_broken_on_flag():
    pillars = {p["name"]: p for p in derive_pillars(_rep(mgmt_flag=True))}
    assert pillars["Management & capital allocation"]["status"] == "broken"
    assert pillars["Management & capital allocation"]["conviction"] == "Low"


def test_pillar_bear_guard_reflects_thesis_status_broken():
    pillars = {p["name"]: p for p in derive_pillars(_rep(thesis_status="broken"))}
    assert pillars["Thesis-failure guard"]["status"] == "broken"


def test_pillar_bear_guard_intact_when_no_drift():
    pillars = {p["name"]: p for p in derive_pillars(_rep())}
    assert pillars["Thesis-failure guard"]["status"] == "intact"


def test_pillar_summary_rollup():
    pillars = derive_pillars(_rep(gates_passed=3))  # broken quality pillar
    summ = pillar_summary(pillars)
    assert summ["overall"] == "broken"
    assert summ["total"] == len(pillars)


# ---------------------------------------------------------------- stance
def test_stance_buy():
    out = derive_stance(_rep(), derive_pillars(_rep()))
    assert out["stance"] == "Buy"
    assert any("conviction line" in r or "intact" in r for r in out["rationale"])


def test_stance_sell_weak_verdict():
    rep = _rep(verdict="reject", score=4.0, gates_passed=2)
    out = derive_stance(rep, derive_pillars(rep))
    assert out["stance"] == "Sell"


def test_stance_sell_thesis_broken():
    rep = _rep(thesis_status="broken")
    out = derive_stance(rep, derive_pillars(rep))
    assert out["stance"] == "Sell"
    assert any("Thesis-failure" in r or "broken" in r.lower() for r in out["rationale"])


def test_stance_hold_constructive_but_below_line():
    # decent score, fair valuation, GO — not strong enough for Buy
    rep = _rep(verdict="review", score=6.8, tech_score=6.0, gates_passed=5, piotroski=5)
    out = derive_stance(rep, derive_pillars(rep))
    assert out["stance"] == "Hold"


def test_stance_hold_when_strong_but_nogo():
    rep = _rep(go_no_go="NO-GO")
    out = derive_stance(rep, derive_pillars(rep))
    assert out["stance"] == "Hold"
    assert any("NO-GO" in r for r in out["rationale"])


def test_stance_rationale_nonempty():
    for v in ("invest", "review", "reject", "fair", "great"):
        rep = _rep(verdict=v)
        out = derive_stance(rep, derive_pillars(rep))
        assert out["rationale"], f"empty rationale for verdict {v}"
        assert out["headline"]


# ---------------------------------------------------------------- end-to-end
def test_build_thesis_entry_shape():
    e = build_thesis_entry(_rep())
    for key in ("ticker", "stance", "stance_headline", "rationale", "pillars",
                "pillar_summary", "quality", "valuation", "risk", "overall_score"):
        assert key in e
    assert e["stance"] in ("Buy", "Hold", "Sell")
    assert 3 <= len(e["pillars"]) <= 5


def test_build_thesis_entry_screen_only_missing_scalars():
    # screen-only name: only score + verdict, no gates/altman/mgmt/tech
    rep = {
        "ticker": "SCRN", "date": "2026-05-01", "verdict": "review", "score": 6.5,
        "mode": "screen",
    }
    e = build_thesis_entry(rep)
    assert e["stance"] in ("Buy", "Hold", "Sell")
    # quality/risk read should degrade to Unknown, not crash
    assert e["quality"]["label"] == "Unknown"
    assert e["risk"]["label"] == "Unknown"
