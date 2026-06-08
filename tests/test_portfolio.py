"""
Phase-4 unit tests for the Portfolio Management dashboard decision engine.

All pure-function, network-free and DB-free. Exercises:
  * is_fresh()        — the freshness/stale gating window
  * overall_score()   — 70/30 fund/tech blend with None handling
  * decide()          — one synthetic holding per decision branch:
                        Hold / Buy-More / Sell / Review (+ stale gating)
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from portfolio_dashboard import (  # noqa: E402
    FRESHNESS_DAYS,
    decide,
    is_fresh,
    overall_score,
)

TODAY = date(2026, 6, 8)


# ---------------------------------------------------------------- is_fresh
def test_is_fresh_recent():
    assert is_fresh((TODAY - timedelta(days=10)).isoformat(), TODAY) is True


def test_is_fresh_on_boundary():
    assert is_fresh((TODAY - timedelta(days=FRESHNESS_DAYS)).isoformat(), TODAY) is True


def test_is_fresh_stale():
    assert is_fresh((TODAY - timedelta(days=FRESHNESS_DAYS + 1)).isoformat(), TODAY) is False


def test_is_fresh_none_or_garbage():
    assert is_fresh(None, TODAY) is False
    assert is_fresh("not-a-date", TODAY) is False


# ---------------------------------------------------------------- overall_score
def test_overall_blend():
    # 0.7*8 + 0.3*6 = 5.6 + 1.8 = 7.4
    assert overall_score(8.0, 6.0) == 7.4


def test_overall_fund_only():
    assert overall_score(7.0, None) == 7.0


def test_overall_tech_only():
    assert overall_score(None, 6.5) == 6.5


def test_overall_none():
    assert overall_score(None, None) is None


# ---------------------------------------------------------------- decide()
def test_decide_hold():
    h = {
        "fund_score": 7.8, "tech_score": 7.0, "verdict": "invest", "go_no_go": "GO",
        "thesis_status": "intact", "score_stale": False, "weight": 0.10,
        "live_price": 110.0, "avg_buy_price": 90.0, "overall": overall_score(7.8, 7.0),
    }
    out = decide(h)
    assert out["decision"] == "Hold"
    assert "intact" in out["trigger"].lower()


def test_decide_buy_more():
    # strong score + price below cost + tech not NO-GO -> Buy-More
    h = {
        "fund_score": 8.2, "tech_score": 7.5, "verdict": "great", "go_no_go": "GO",
        "thesis_status": "intact", "score_stale": False, "weight": 0.08,
        "live_price": 80.0, "avg_buy_price": 100.0, "overall": overall_score(8.2, 7.5),
    }
    out = decide(h)
    assert out["decision"] == "Buy-More"
    assert "below" in out["trigger"].lower()


def test_decide_sell_fundamental():
    h = {
        "fund_score": 4.2, "tech_score": 6.0, "verdict": "reject", "go_no_go": "GO",
        "thesis_status": "intact", "score_stale": False, "weight": 0.05,
        "live_price": 50.0, "avg_buy_price": 40.0, "overall": overall_score(4.2, 6.0),
    }
    out = decide(h)
    assert out["decision"] == "Sell"
    assert "deterioration" in out["trigger"].lower()


def test_decide_sell_thesis_broken():
    h = {
        "fund_score": 7.5, "tech_score": 7.0, "verdict": "invest", "go_no_go": "GO",
        "thesis_status": "broken", "score_stale": False, "weight": 0.05,
        "live_price": 50.0, "avg_buy_price": 40.0, "overall": overall_score(7.5, 7.0),
    }
    out = decide(h)
    assert out["decision"] == "Sell"
    assert "thesis" in out["trigger"].lower()


def test_decide_sell_technical_breakdown():
    # moderate fundamentals (<7) + NO-GO -> Sell to de-risk
    h = {
        "fund_score": 6.2, "tech_score": 3.0, "verdict": "review", "go_no_go": "NO-GO",
        "thesis_status": "intact", "score_stale": False, "weight": 0.05,
        "live_price": 50.0, "avg_buy_price": 60.0, "overall": overall_score(6.2, 3.0),
    }
    out = decide(h)
    assert out["decision"] == "Sell"
    assert "no-go" in out["trigger"].lower()


def test_decide_review_stale():
    h = {
        "fund_score": 8.0, "tech_score": 7.0, "verdict": "invest", "go_no_go": "GO",
        "thesis_status": "intact", "score_stale": True, "weight": 0.05,
        "live_price": 100.0, "avg_buy_price": 90.0, "overall": None,
    }
    out = decide(h)
    assert out["decision"] == "Review"
    assert "stale" in out["trigger"].lower()


def test_decide_review_missing_fund():
    h = {
        "fund_score": None, "tech_score": 7.0, "verdict": None, "go_no_go": "GO",
        "score_stale": False, "weight": 0.05, "live_price": 100.0, "avg_buy_price": 90.0,
        "overall": overall_score(None, 7.0),
    }
    out = decide(h)
    assert out["decision"] == "Review"


def test_decide_review_concentration():
    # healthy name but > 20% weight -> Review for reallocation
    h = {
        "fund_score": 7.6, "tech_score": 7.0, "verdict": "invest", "go_no_go": "GO",
        "thesis_status": "intact", "score_stale": False, "weight": 0.28,
        "live_price": 110.0, "avg_buy_price": 90.0, "overall": overall_score(7.6, 7.0),
    }
    out = decide(h)
    assert out["decision"] == "Review"
    assert "%" in out["trigger"]


def test_decide_buy_more_not_triggered_when_above_cost():
    # strong but trading ABOVE cost -> Hold, not Buy-More
    h = {
        "fund_score": 8.2, "tech_score": 7.5, "verdict": "great", "go_no_go": "GO",
        "thesis_status": "intact", "score_stale": False, "weight": 0.08,
        "live_price": 120.0, "avg_buy_price": 100.0, "overall": overall_score(8.2, 7.5),
    }
    assert decide(h)["decision"] == "Hold"
