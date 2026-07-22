"""
Unit tests for v4 Phase E — the watch-list block in send_email.py.

Pure-function only: build_watchlist_html renders a red triggered callout when
live <= target and a quiet status table otherwise. No network, no SMTP.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import send_email as se  # noqa: E402


def test_empty_watchlist_renders_nothing():
    assert se.build_watchlist_html([], {}) == ("", 0)


def test_triggered_when_live_at_or_below_target():
    rows = [
        {"ticker": "ADSK", "target": "250.0", "currency": "USD", "thesis": "Quality 8.4"},
        {"ticker": "CSCO", "target": "45.0", "currency": "USD", "thesis": "Quality 7.1"},
    ]
    live = {"ADSK": 240.0, "CSCO": 60.0}  # ADSK triggered (below), CSCO not
    html_out, n = se.build_watchlist_html(rows, live)
    assert n == 1
    assert "Watch-list triggered (1)" in html_out
    assert "#d62728" in html_out          # red callout
    assert "ADSK" in html_out
    assert "Watch-list status (1" in html_out  # CSCO in the status details


def test_exactly_at_target_triggers():
    rows = [{"ticker": "ADSK", "target": "250.0", "currency": "USD", "thesis": "x"}]
    html_out, n = se.build_watchlist_html(rows, {"ADSK": 250.0})
    assert n == 1


def test_no_live_price_goes_to_status_not_triggered():
    rows = [{"ticker": "ADSK", "target": "250.0", "currency": "USD", "thesis": "x"}]
    html_out, n = se.build_watchlist_html(rows, {})  # no live price
    assert n == 0
    assert "not yet triggered" in html_out
    assert "n/a" in html_out  # live shown as n/a


def test_bad_target_row_is_skipped():
    rows = [{"ticker": "BAD", "target": "", "currency": "USD"}]
    html_out, n = se.build_watchlist_html(rows, {"BAD": 10.0})
    assert n == 0 and html_out == ""  # unparseable target dropped → nothing to show
