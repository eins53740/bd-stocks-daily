"""Tests for buy_list.py — the "Buy today" selection — and its digest rendering."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import buy_list  # noqa: E402
from buy_list import (  # noqa: E402
    BUY_FLOOR,
    candidate_tickers,
    latest_per_ticker,
    max_entry,
    parse_entry_zone_high,
    select_buys,
)


def report(ticker="AAA", score=8.0, price=100.0, mid=150.0, days_left=60,
           mode="deep", date="2026-07-30", **kw) -> dict:
    r = {
        "ticker": ticker, "score": score, "price": price, "fair_value_mid": mid,
        "days_left": days_left, "mode": mode, "date": date, "verdict": "invest",
        "currency": "USD", "company": f"{ticker} Inc",
    }
    r.update(kw)
    return r


# --- max entry price --------------------------------------------------------

@pytest.mark.parametrize("zone,expected", [
    ("349.20–390.54", 390.54),     # en dash, as written by the technical phase
    ("349.20�390.54", 390.54),  # mojibake separator (non-UTF-8 console)
    ("349.20-390.54", 390.54),
    ("1,234.50–1,300.00", 1300.00),  # thousands separators
    ("42.00", 42.00),                # single value
    (55.5, 55.5),                    # already numeric
    ("", None),
    (None, None),
    ("n/a", None),
])
def test_entry_zone_high_is_the_upper_bound_whatever_the_separator(zone, expected):
    assert parse_entry_zone_high(zone) == expected


def test_max_entry_prefers_the_blend_over_the_technical_zone():
    cap, basis = max_entry(report(mid=150.0, entry_zone="90.00–110.00"))
    assert (cap, basis) == (150.0, "fair-value blend")


def test_max_entry_falls_back_to_the_entry_zone_without_a_blend():
    cap, basis = max_entry(report(mid=None, entry_zone="90.00–110.00"))
    assert (cap, basis) == (110.0, "technical entry zone")


def test_max_entry_is_none_when_neither_anchor_exists():
    assert max_entry(report(mid=None, entry_zone=None)) == (None, None)


def test_max_entry_ignores_a_nonpositive_blend():
    cap, basis = max_entry(report(mid=0, entry_zone="90–110"))
    assert (cap, basis) == (110.0, "technical entry zone")


def test_fair_price_is_never_used_as_the_cap():
    """MSFT 2026-07-30 regression: a DCF that survived the ±70% gate by 0.30pp
    published fair_price=118.35 against a 303.28 blend. Anchoring on fair_price
    would have hidden every buy behind a nonsense cap."""
    cap, basis = max_entry(report(fair_price=118.35, mid=303.28))
    assert cap == 303.28
    assert basis == "fair-value blend"


# --- selection --------------------------------------------------------------

def test_a_cheap_quality_name_is_a_buy_with_its_headroom():
    out = select_buys([report(price=100.0, mid=150.0)])
    assert len(out["buys"]) == 1
    b = out["buys"][0]
    assert b["max_entry"] == 150.0
    assert b["headroom_pct"] == pytest.approx(50.0)
    assert b["thin"] is False
    assert b["price_source"] == "eval"


def test_below_the_floor_is_not_a_buy_however_cheap():
    out = select_buys([report(score=BUY_FLOOR - 0.01, price=10.0, mid=1000.0)])
    assert out["buys"] == []
    assert out["above_entry"] == [] and out["no_max_entry"] == []


def test_expired_report_is_not_a_buy():
    assert select_buys([report(days_left=0)])["buys"] == []
    assert select_buys([report(days_left=-5)])["buys"] == []


def test_price_above_the_cap_is_reported_as_excluded_not_dropped():
    out = select_buys([report(ticker="MSFT", price=390.54, mid=303.28)])
    assert out["buys"] == []
    assert out["above_entry"] == ["MSFT"]


def test_a_name_without_a_stateable_max_entry_is_counted_not_shown():
    out = select_buys([report(ticker="ZZZ", mid=None, entry_zone=None)])
    assert out["buys"] == []
    assert out["no_max_entry"] == ["ZZZ"]


def test_a_name_with_no_price_at_all_cannot_be_compared():
    out = select_buys([report(ticker="NOPX", price=None, mid=150.0)])
    assert out["buys"] == []
    assert out["no_max_entry"] == ["NOPX"]


def test_live_price_wins_over_the_eval_price():
    out = select_buys([report(ticker="AAA", price=100.0, mid=150.0)], {"AAA": 120.0})
    b = out["buys"][0]
    assert b["price"] == 120.0
    assert b["price_source"] == "live"
    assert b["headroom_pct"] == pytest.approx(25.0)


def test_a_live_price_can_push_a_name_out_of_the_buy_list():
    out = select_buys([report(ticker="AAA", price=100.0, mid=150.0)], {"AAA": 160.0})
    assert out["buys"] == []
    assert out["above_entry"] == ["AAA"]


def test_thin_margin_is_flagged_below_the_threshold():
    out = select_buys([report(price=100.0, mid=105.0)])
    assert out["buys"][0]["thin"] is True


def test_order_is_by_recommendation_then_headroom():
    rows = [
        report(ticker="LOW", score=7.6, price=100.0, mid=200.0),
        report(ticker="TOP", score=9.1, price=100.0, mid=110.0),
        report(ticker="MID", score=8.0, price=100.0, mid=105.0),
        report(ticker="MIDB", score=8.0, price=100.0, mid=150.0),
    ]
    assert [b["ticker"] for b in select_buys(rows)["buys"]] == ["TOP", "MIDB", "MID", "LOW"]


def test_deep_supersedes_a_same_day_screen_so_the_cap_survives():
    """The Phase-5.5 cascade writes both on one date and the screen carries no
    intrinsic value — ranking the screen first would lose the max entry price."""
    rows = [
        report(ticker="AAA", mode="screen", mid=None, entry_zone=None, date="2026-07-30"),
        report(ticker="AAA", mode="deep", mid=150.0, date="2026-07-30"),
    ]
    assert len(latest_per_ticker(rows)) == 1
    out = select_buys(rows)
    assert [b["ticker"] for b in out["buys"]] == ["AAA"]
    assert out["buys"][0]["max_entry"] == 150.0


def test_a_newer_report_supersedes_an_older_one():
    rows = [report(ticker="AAA", date="2026-01-01", mid=150.0),
            report(ticker="AAA", date="2026-07-30", mid=90.0)]
    out = select_buys(rows)
    assert out["buys"] == []           # newer blend of 90 sits below the 100 price
    assert out["above_entry"] == ["AAA"]


def test_held_names_are_marked_as_adds(tmp_path):
    (tmp_path / "_portfolio_holdings.yaml").write_text(
        "holdings:\n  - ticker: AAA\n    quantity: 10\n    cost_basis: 50\n",
        encoding="utf-8")
    holdings = buy_list.load_holdings_safe(tmp_path)
    out = select_buys([report(ticker="AAA"), report(ticker="BBB")], holdings=holdings)
    marks = {b["ticker"]: b["held"] for b in out["buys"]}
    assert marks == {"AAA": True, "BBB": False}


def test_missing_holdings_file_degrades_to_not_held(tmp_path):
    assert buy_list.load_holdings_safe(tmp_path) == []
    assert select_buys([report()], holdings=[])["buys"][0]["held"] is False


def test_candidate_tickers_are_exactly_the_names_worth_pricing():
    rows = [
        report(ticker="AAA", score=8.0),
        report(ticker="LOWSCORE", score=7.0),
        report(ticker="EXPIRED", score=8.0, days_left=0),
        report(ticker="NOSCORE", score=None),
    ]
    assert candidate_tickers(rows) == ["AAA"]


def test_empty_input_is_an_empty_result_not_a_crash():
    out = select_buys([])
    assert out == {"buys": [], "no_max_entry": [], "above_entry": [], "floor": BUY_FLOOR}


# --- digest rendering -------------------------------------------------------

def _send_email():
    import send_email
    return send_email


def test_empty_buy_list_still_renders_an_explicit_section():
    """'No section' and 'nothing to buy' are different messages — only one is true."""
    html = _send_email().build_buy_today_html(select_buys([]))
    assert "Buy today — nothing" in html
    assert "Patience is a position" in html


def test_rendered_section_states_the_max_entry_price_and_the_basis():
    out = select_buys([report(ticker="AAA", score=8.4, price=100.0, mid=150.0)])
    html = _send_email().build_buy_today_html(out)
    assert "🛒 Buy today (1)" in html
    assert "≤ 150.00 USD" in html
    assert "fair-value blend" in html
    assert "+50.0%" in html
    assert "8.40" in html


def test_rendered_section_names_what_it_excluded():
    out = select_buys([report(ticker="MSFT", price=390.54, mid=303.28),
                       report(ticker="ZZZ", mid=None, entry_zone=None)])
    html = _send_email().build_buy_today_html(out)
    assert "1 above max entry" in html
    assert "1 without a stateable max entry" in html


def test_rendered_section_explains_why_a_7_point_2_name_is_absent():
    """The watch-list floor is 7.0 and this one is 7.5; the email must say so rather
    than leave two sections looking inconsistent."""
    html = _send_email().build_buy_today_html(select_buys([]))
    assert "watch-list block" in html
    assert "7.5" in html


def test_text_part_mirrors_the_html_rows():
    out = select_buys([report(ticker="AAA", score=8.4, price=100.0, mid=150.0)])
    text = _send_email().build_buy_today_text(out)
    assert "BUY TODAY (1)" in text
    assert "max entry 150.00 (fair-value blend)" in text
    assert "NEW" in text


def test_text_part_empty_state_is_explicit():
    assert "nothing" in _send_email().build_buy_today_text(select_buys([])).lower()


def test_timing_no_go_is_surfaced_not_used_to_exclude():
    """A NO-GO is a timing signal, not a veto — dropping the name silently would hide
    a quality compounder trading below fair value."""
    out = select_buys([report(ticker="AAA", price=100.0, mid=150.0, go_no_go="NO-GO")])
    assert len(out["buys"]) == 1
    html = _send_email().build_buy_today_html(out)
    assert "timing NO-GO" in html


def test_stale_eval_price_is_labelled_in_the_render():
    out = select_buys([report(ticker="AAA", price=100.0, mid=150.0)])  # no live price
    html = _send_email().build_buy_today_html(out)
    assert "price at eval, not live" in html
