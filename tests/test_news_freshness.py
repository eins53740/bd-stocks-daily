"""
news_freshness day-boundary tolerance (Fix 1) — pure, network-free.

The earnings-date index from yfinance is tz-aware (exchange / US-Eastern). It was
compared against a UTC `today`, so near midnight UTC the day-delta could be off
by 1, shifting `news_freshness`. The fix takes each earnings timestamp's OWN
native-tz calendar date (tz_localize(None) then .date(), which drops tz without
shifting wall-clock) and clamps days_since at 0. These tests pin both behaviours.

news_freshness is a UX overlay only (NOT in the composite), so we test the two
load-bearing pieces directly rather than spinning up a network fetch.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from analyze_ticker import compute_news_freshness  # noqa: E402


def _native_date(ts):
    """Mirror of analyze_ticker's inline helper: native-tz date, tz stripped."""
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_localize(None)
    return ts.date()


# ------------------------- compute_news_freshness contract -------------------------
def test_compute_news_freshness_none_passthrough():
    assert compute_news_freshness(None) is None


def test_compute_news_freshness_decays_monotonically():
    f0 = compute_news_freshness(0)    # fresh -> ~1.0
    f7 = compute_news_freshness(7)    # one half-life -> ~0.5
    f14 = compute_news_freshness(14)  # two half-lives -> ~0.25
    assert f0 == 1.0
    assert abs(f7 - 0.5) < 0.02
    assert f14 < f7 < f0


def test_compute_news_freshness_clamps_negative_like_run_path():
    # The run path does days_since = max(0, ...). A tz off-by-one can make a
    # "today" earnings look 1 day in the future (-1); clamped it must read fresh.
    days_since = max(0, -1)
    assert compute_news_freshness(days_since) == 1.0


# ------------------------- tz-date normalisation is stable across the boundary -------------------------
def test_native_date_unaffected_by_utc_midnight_skew():
    # An earnings print stamped 2026-06-08 20:00 US-Eastern. In UTC that is
    # 2026-06-09 00:00 — a naive UTC .date() would read the NEXT day. The native
    # date must stay 2026-06-08 (the exchange's calendar day).
    ts = pd.Timestamp("2026-06-08 20:00", tz="America/New_York")
    assert _native_date(ts) == date(2026, 6, 8)
    # UTC-naive conversion would have drifted to the 9th:
    assert ts.tz_convert("UTC").date() == date(2026, 6, 9)


def test_native_date_handles_tz_naive_timestamp():
    ts = pd.Timestamp("2026-06-08 20:00")  # tz-naive
    assert _native_date(ts) == date(2026, 6, 8)


def test_day_delta_with_tolerance_no_off_by_one():
    # today (UTC) and an exchange-local earnings date one calendar day apart.
    today = date(2026, 6, 9)
    last = _native_date(pd.Timestamp("2026-06-08 20:00", tz="America/New_York"))
    days_since = max(0, (today - last).days)
    assert days_since == 1                      # exactly one day, not zero or two
    assert compute_news_freshness(days_since) is not None
