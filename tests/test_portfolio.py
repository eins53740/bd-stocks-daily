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


# ---------------------------------------------------------------- CSV source
# fetch_holdings_csv (Yahoo Finance export) + reconcile FX conversion.
from portfolio_sync import fetch_holdings_csv, reconcile  # noqa: E402

_CSV_HEADER = (
    "Symbol,Current Price,Date,Time,Change,Open,High,Low,Volume,"
    "Trade Date,Purchase Price,Quantity,Commission,High Limit,Low Limit,Comment,Transaction Type\n"
)


def _write_csv(tmp_path, body: str):
    p = tmp_path / "portfolio.csv"
    p.write_text(_CSV_HEADER + body, encoding="utf-8")
    return p


def test_csv_skips_watchlist_rows(tmp_path):
    # rows without Quantity are watchlist entries, not positions
    p = _write_csv(tmp_path, (
        "BABA,116.3,2026/06/10,12:09 EDT,-3.3,116.0,118.1,115.7,5285276,,,,,,,,\n"
        "CSCO,119.63,2026/06/10,12:09 EDT,1.0,118.0,120.0,117.9,100,,55.84,31.0,,,,,1064\n"
    ))
    rows = fetch_holdings_csv(p)
    assert [r["ticker"] for r in rows] == ["CSCO"]
    assert rows[0]["quantity"] == 31.0
    assert rows[0]["avg_buy_price"] == 55.84
    assert rows[0]["stored_price"] == 119.63
    assert rows[0]["value_date"] == "2026-06-10"


def test_csv_aggregates_lots_weighted(tmp_path):
    # two SEM.LS lots -> one row, qty summed, buy price quantity-weighted
    p = _write_csv(tmp_path, (
        "SEM.LS,23.3,2026/06/10,17:14 CEST,0.1,23.0,23.4,22.9,1000,20240101,17.96,55.0,,,,,BUY\n"
        "SEM.LS,23.3,2026/06/10,17:14 CEST,0.1,23.0,23.4,22.9,1000,20240201,17.70,56.0,,,,,BUY\n"
    ))
    rows = fetch_holdings_csv(p)
    assert len(rows) == 1
    r = rows[0]
    assert r["quantity"] == 111.0
    expected_avg = (17.96 * 55 + 17.70 * 56) / 111
    assert abs(r["avg_buy_price"] - expected_avg) < 1e-9
    assert r["currency"] == "EUR"  # .LS -> Euronext Lisbon


def test_csv_crypto_rows_classified_nonequity(tmp_path):
    p = _write_csv(tmp_path, (
        "NEXO-USD,0.797,2026/06/10,12:09 EDT,0.0,0.8,0.81,0.79,1,,1.22,457.0,,,,,BUY\n"
        "AMD,457.7,2026/06/10,12:09 EDT,1.0,450.0,460.0,449.0,1,,97.51,8.0,,,,,0895\n"
    ))
    holdings = reconcile(fetch_holdings_csv(p), live={}, fx={})
    by_ticker = {h["ticker"]: h for h in holdings}
    assert by_ticker["NEXO-USD"]["is_equity"] is False
    assert by_ticker["NEXO-USD"]["non_equity_class"] == "crypto"
    assert by_ticker["AMD"]["is_equity"] is True


def test_reconcile_fx_converts_native_values_to_eur(tmp_path):
    # USD position valued via stored CSV price, converted at EURUSD=1.10;
    # EUR position passes through; weights computed over EUR values.
    p = _write_csv(tmp_path, (
        "AMD,110.0,2026/06/10,12:09 EDT,1.0,450.0,460.0,449.0,1,,97.51,10.0,,,,,BUY\n"
        "SEM.LS,20.0,2026/06/10,17:14 CEST,0.1,23.0,23.4,22.9,1000,,17.96,50.0,,,,,BUY\n"
    ))
    holdings = reconcile(fetch_holdings_csv(p), live={}, fx={"USD": 1.10})
    by_ticker = {h["ticker"]: h for h in holdings}
    assert abs(by_ticker["AMD"]["market_value"] - (110.0 * 10 / 1.10)) < 1e-6
    assert abs(by_ticker["SEM.LS"]["market_value"] - (20.0 * 50)) < 1e-6
    total = by_ticker["AMD"]["market_value"] + by_ticker["SEM.LS"]["market_value"]
    assert abs(by_ticker["AMD"]["weight"] - by_ticker["AMD"]["market_value"] / total) < 1e-9


def test_reconcile_fx_missing_rate_yields_none(tmp_path):
    # unknown FX rate -> market_value None (never a silently-wrong native figure)
    p = _write_csv(tmp_path, (
        "2330.TW,2255.0,2026/06/10,13:30 CST,-50.0,2285.0,2300.0,2255.0,1,20260605,2390.0,20.0,89.56,,,,BUY\n"
    ))
    holdings = reconcile(fetch_holdings_csv(p), live={}, fx={})
    assert holdings[0]["market_value"] is None
    assert holdings[0]["weight"] is None
