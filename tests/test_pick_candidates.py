"""
Unit tests for pick_candidates.py — company identity and fallback fairness.

Regression cover for the TSMC-carousel bug: with the prefiltered pool exhausted,
every day ran the fallback, the fallback ranked purely by staleness, and TSMC held
two slots (TSM + 2330.TW). The same few high scorers therefore repeated every
fortnight. Pure functions only: no yaml, no network.
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pick_candidates as pc  # noqa: E402


def row(ticker, d, score=8.0, size="big", mode="deep", region="US", sector="Tech"):
    return {"ticker": ticker, "date": d, "score": str(score), "size": size,
            "mode": mode, "region": region, "sector": sector, "notes": ""}


# --- company identity -------------------------------------------------------

def test_adr_and_local_line_share_one_company_key():
    # Canonical identity is the HOME line, not the ADR (policy change 2026-08-05).
    assert pc.company_key("2330.TW") == pc.company_key("TSM") == "2330.TW"


def test_dual_share_classes_share_one_company_key():
    assert pc.company_key("GOOG") == pc.company_key("GOOGL") == "GOOGL"


def test_unaliased_ticker_is_its_own_company():
    assert pc.company_key("NVDA") == "NVDA"


def test_company_key_tolerates_whitespace_and_none():
    assert pc.company_key("  TSM  ") == "2330.TW"
    assert pc.company_key(None) == ""  # type: ignore[arg-type]


# --- company-level staleness & rounds ---------------------------------------

def test_last_date_spans_every_listing_of_the_company():
    rows = [row("2330.TW", "2026-07-25"), row("TSM", "2026-06-01")]
    # The Taiwan line is the more recent look, so both tickers report it.
    assert pc.ticker_last_date("TSM", rows) == date(2026, 7, 25)
    assert pc.ticker_last_date("2330.TW", rows) == date(2026, 7, 25)


def test_round_counts_visits_across_listings():
    rows = [row("TSM", "2026-06-01"), row("2330.TW", "2026-07-08"),
            row("TSM", "2026-07-09")]
    # Three distinct days on one company -> the next look is round 4.
    assert pc.ticker_round("TSM", rows) == 4
    assert pc.ticker_round("2330.TW", rows) == 4


def test_same_day_screen_and_deep_is_one_visit():
    rows = [row("TTD", "2026-07-22", mode="screen"), row("TTD", "2026-07-22", mode="deep")]
    assert pc.ticker_round("TTD", rows) == 2


def test_unseen_ticker_starts_at_round_one():
    assert pc.ticker_round("NEWCO", []) == 1
    assert pc.ticker_last_date("NEWCO", []) is None


# --- dedupe -----------------------------------------------------------------

def test_evaluating_the_local_line_benches_the_adr():
    pool = [{"ticker": "TSM", "size": "big", "region": "US"}]
    rows = [row("2330.TW", "2026-07-25")]
    assert pc.eligible(pool, rows, date(2026, 7, 27)) == []


def test_company_becomes_eligible_again_past_the_dedupe_window():
    pool = [{"ticker": "TSM", "size": "big", "region": "US"}]
    rows = [row("2330.TW", "2025-01-01")]
    assert len(pc.eligible(pool, rows, date(2026, 7, 27))) == 1


def test_never_evaluated_ticker_is_eligible():
    pool = [{"ticker": "NEWCO", "size": "big", "region": "US"}]
    assert len(pc.eligible(pool, [], date(2026, 7, 27))) == 1


# --- fallback fairness ------------------------------------------------------

def test_fallback_prefers_the_least_visited_company_over_the_stalest():
    rows = [
        # Visited four times, and the stalest of the two -> must NOT win.
        row("HOG", "2026-01-05"), row("HOG", "2026-02-05"),
        row("HOG", "2026-03-05"), row("HOG", "2026-04-05"),
        # Visited once, more recent -> wins on fewest visits.
        row("FRESH", "2026-05-01"),
    ]
    fb = pc.pick_fallback_deep(rows, date(2026, 7, 27))
    assert fb is not None and fb["ticker"] == "FRESH"


def test_staleness_breaks_ties_between_equally_visited_companies():
    rows = [row("OLDER", "2026-03-01"), row("NEWER", "2026-05-01")]
    fb = pc.pick_fallback_deep(rows, date(2026, 7, 27))
    assert fb is not None and fb["ticker"] == "OLDER"


def test_dual_listing_visits_are_pooled_when_ranking():
    rows = [
        # TSMC: four visits once the two listings are counted as one company.
        row("TSM", "2026-01-10"), row("2330.TW", "2026-02-10"),
        row("TSM", "2026-03-10"), row("2330.TW", "2026-04-10"),
        # Two visits -> fewer, so this wins even though it is more recent.
        row("OTHER", "2026-05-01"), row("OTHER", "2026-05-20"),
    ]
    fb = pc.pick_fallback_deep(rows, date(2026, 7, 27))
    assert fb is not None and fb["ticker"] == "OTHER"


def test_company_at_the_round_cap_is_excluded():
    rows = [row("MAXED", f"2026-0{i}-01") for i in range(1, 6)]  # 5 visits
    assert pc.pick_fallback_deep(rows, date(2026, 7, 27)) is None


def test_dual_listings_reach_the_round_cap_together():
    # Three visits per listing = six as one company, past the cap of five.
    rows = [row("TSM", "2026-01-01"), row("TSM", "2026-02-01"), row("TSM", "2026-03-01"),
            row("2330.TW", "2026-01-15"), row("2330.TW", "2026-02-15"),
            row("2330.TW", "2026-03-15")]
    assert pc.pick_fallback_deep(rows, date(2026, 7, 27)) is None


def test_recently_evaluated_company_is_not_re_picked():
    # 20 days old — inside the 45-day minimum gap.
    rows = [row("RECENT", "2026-07-07")]
    assert pc.pick_fallback_deep(rows, date(2026, 7, 27)) is None


def test_minimum_age_is_45_days():
    assert pc.FALLBACK_MIN_AGE_DAYS == 45


def test_high_score_tier_wins_over_a_low_score_company_with_equal_visits():
    rows = [row("CHEAP", "2026-01-01", score=3.0), row("QUALITY", "2026-02-01", score=8.5)]
    fb = pc.pick_fallback_deep(rows, date(2026, 7, 27))
    assert fb is not None and fb["ticker"] == "QUALITY"
    assert fb["fallback_reason"] == "pool_exhausted_shortlist_reeval"


def test_falls_back_to_any_verdict_when_no_high_scorer_qualifies():
    rows = [row("CHEAP", "2026-01-01", score=3.0)]
    fb = pc.pick_fallback_deep(rows, date(2026, 7, 27))
    assert fb is not None and fb["fallback_reason"] == "pool_exhausted_any_verdict_reeval"


def test_empty_log_yields_no_fallback():
    assert pc.pick_fallback_deep([], date(2026, 7, 27)) is None


def test_unparseable_dates_and_blank_tickers_are_skipped_not_fatal():
    rows = [row("", "2026-01-01"), row("BAD", "not-a-date"), row("OK", "2026-01-02")]
    fb = pc.pick_fallback_deep(rows, date(2026, 7, 27))
    assert fb is not None and fb["ticker"] == "OK"


def test_non_numeric_score_is_treated_as_zero_not_an_error():
    rows = [row("WEIRD", "2026-01-01", score="n/a")]
    fb = pc.pick_fallback_deep(rows, date(2026, 7, 27))
    assert fb is not None and fb["fallback_reason"] == "pool_exhausted_any_verdict_reeval"


def test_fallback_returns_the_most_recent_listing_of_the_company():
    rows = [row("TSM", "2026-01-01"), row("2330.TW", "2026-02-01")]
    fb = pc.pick_fallback_deep(rows, date(2026, 7, 27))
    assert fb is not None and fb["ticker"] == "2330.TW"


# --- hyper-growth reservation ------------------------------------------------

def test_eligible_still_returns_hyper_growth_names():
    """eligible() is size-agnostic; main() does the reserving, so the pool
    statistics can report how many were held back."""
    pool = [{"ticker": "PLTR", "size": "hyper_growth", "region": "US"}]
    assert len(pc.eligible(pool, [], date(2026, 7, 27))) == 1


def test_quality_slots_never_select_a_hyper_growth_name():
    pool = [{"ticker": "PLTR", "size": "hyper_growth", "region": "US"},
            {"ticker": "MSFT", "size": "big", "region": "US"}]
    assert pc.pick(pool, "big")["ticker"] == "MSFT"
    assert pc.pick(pool, "small_growth") is None


def test_micro_still_rides_the_small_growth_slot():
    pool = [{"ticker": "TINY", "size": "micro", "region": "US"}]
    assert pc.pick(pool, "small_growth")["ticker"] == "TINY"


def test_consecutive_fallback_days_do_not_repeat_a_company():
    """The actual bug: rank-by-staleness returned the same handful in rotation."""
    rows = [row(t, "2026-01-0%d" % i) for i, t in enumerate("ABCDE", start=1)]
    picked = []
    day = date(2026, 7, 27)
    for offset in range(5):
        fb = pc.pick_fallback_deep(rows, date(day.year, day.month, day.day + offset))
        assert fb is not None
        picked.append(fb["ticker"])
        rows.append(row(fb["ticker"], f"2026-07-{27 + offset:02d}"))
    assert len(set(picked)) == 5, f"repeats within one cycle: {picked}"


# --- slot budget (30-minute wall-clock cut, 2026-07-31) ----------------------

def run_main(monkeypatch, capsys, pool, log_rows=()):
    """Drive main() with an in-memory pool. Returns the parsed JSON result."""
    monkeypatch.setattr(pc, "load_prefiltered", lambda: list(pool))
    monkeypatch.setattr(pc, "load_log", lambda: list(log_rows))
    assert pc.main() == 0
    return json.loads(capsys.readouterr().out)


def cand(ticker, size="big", region="US"):
    return {"ticker": ticker, "size": size, "region": region, "sector": "Tech"}


def test_a_run_is_one_deep_plus_exactly_n_screens(monkeypatch, capsys):
    """The 30-minute budget lives or dies on this count. At 5 tickers the job
    measured 28-32 min and the timeout kill produced no email at all."""
    pool = [cand(f"US{i}") for i in range(6)] + [cand(f"EU{i}", region="EU") for i in range(6)]
    res = run_main(monkeypatch, capsys, pool)
    assert res["deep"]["ticker"]
    assert len(res["screens"]) == pc.N_SCREENS == 2


def test_the_non_us_guarantee_survives_the_cut(monkeypatch, capsys):
    pool = [cand(f"US{i}") for i in range(6)] + [cand(f"EU{i}", region="EU") for i in range(6)]
    res = run_main(monkeypatch, capsys, pool)
    non_us = [s for s in res["screens"] if s["region"] not in ("US", "?")]
    assert len(non_us) >= pc.N_NON_US_SCREENS == 1


def test_the_sized_screen_takes_the_bucket_the_deep_dive_did_not(monkeypatch, capsys):
    """With one size-diverse slot, a fixed 'big' preference would starve
    small_growth forever — the run must still span both size classes."""
    pool = ([cand(f"B{i}", size="big") for i in range(4)]
            + [cand(f"S{i}", size="small_growth") for i in range(4)]
            + [cand(f"EU{i}", region="EU") for i in range(4)])
    # Last deep was 'big', so today's deep is small_growth and the screen must be big.
    res = run_main(monkeypatch, capsys, pool,
                   log_rows=[row("OLD", "2026-01-01", size="big", mode="deep")])
    assert res["deep"]["size"] == "small_growth"
    sizes = {s["size"] for s in res["screens"]}
    assert "big" in sizes, f"size diversity lost: {res['screens']}"


def test_screen_follows_the_size_actually_picked_not_the_intended_one(monkeypatch, capsys):
    """When the intended deep bucket is empty, pick() falls back — and keying the
    screen on the intended size would then aim it at the bucket the deep just took."""
    # Last deep was 'big', so today intends small_growth; the pool has none, so the
    # deep falls back to big and the screen must NOT also be the last big name.
    pool = ([cand("B1", size="big"), cand("B2", size="big")]
            + [cand("EU1", region="EU")])
    res = run_main(monkeypatch, capsys, pool,
                   log_rows=[row("OLD", "2026-01-01", size="big", mode="deep")])
    assert res["deep"]["size"] == "big"
    assert len(res["screens"]) == pc.N_SCREENS
    assert res["deep"]["ticker"] not in {s["ticker"] for s in res["screens"]}


def test_no_hyper_growth_name_reaches_a_quality_slot(monkeypatch, capsys):
    """The non-US slot takes any size, so the reservation must happen upstream."""
    pool = ([cand("PLTR", size="hyper_growth")]
            + [cand("HYPE_EU", size="hyper_growth", region="EU")]
            + [cand(f"US{i}") for i in range(3)]
            + [cand(f"EU{i}", region="EU") for i in range(3)])
    res = run_main(monkeypatch, capsys, pool)
    chosen = [res["deep"]] + res["screens"]
    assert all(c["size"] != "hyper_growth" for c in chosen), chosen
    assert res["pool_stats"]["hyper_growth_reserved"] == 2


def test_an_all_us_pool_still_fills_every_screen_slot(monkeypatch, capsys):
    """No non-US candidate must not cost us a slot — it warns, then backfills."""
    pool = [cand(f"US{i}") for i in range(8)]
    res = run_main(monkeypatch, capsys, pool)
    assert len(res["screens"]) == pc.N_SCREENS
    assert "EU" not in {s["region"] for s in res["screens"]}


def test_the_size_slot_does_not_eat_the_only_non_us_candidate(monkeypatch, capsys):
    """Size slots take any region, so claiming them first lets one swallow the sole
    non-US name and break the region guarantee. The deep is forced onto a US big here
    (last deep was small_growth) so the only way EU1 can be lost is that ordering."""
    pool = [cand("B1"), cand("B2"), cand("EU1", size="small_growth", region="EU")]
    res = run_main(monkeypatch, capsys, pool,
                   log_rows=[row("OLD", "2026-01-01", size="small_growth", mode="deep")])
    assert res["deep"]["region"] == "US"
    assert len(res["screens"]) == pc.N_SCREENS
    assert "EU1" in {s["ticker"] for s in res["screens"]}


def test_screens_never_duplicate_the_deep_dive(monkeypatch, capsys):
    pool = [cand("ONLY_US"), cand("ONLY_EU", region="EU")]
    res = run_main(monkeypatch, capsys, pool)
    tickers = [res["deep"]["ticker"]] + [s["ticker"] for s in res["screens"]]
    assert len(tickers) == len(set(tickers)), tickers
