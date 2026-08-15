"""Tests for scripts/universe_admin.py (v4.3 wave 4.2).

Network-free: the symbol check is injected. Fixtures use the real file shapes, including
the inline-flow-map style `_universe.yaml` actually uses.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import universe_admin as ua  # noqa: E402


def exists(_t):
    return True, "resolved at 123.45"


def missing(_t):
    return False, "yfinance returned no price — symbol likely does not exist"


@pytest.fixture()
def pool(tmp_path):
    (tmp_path / ua.UNIVERSE).write_text(
        "version: 1\ntickers:\n"
        '  - {ticker: MSFT, region: US, size: big, sector: Technology, note: "Cloud, AI"}\n'
        "  - {ticker: ASML.AS, region: NL, size: big, sector: Semiconductors}\n",
        encoding="utf-8")
    (tmp_path / ua.PREFILTERED).write_text(
        "version: 1\ntickers:\n  - {ticker: NVDA, region: US}\n", encoding="utf-8")
    (tmp_path / ua.PENDING).write_text("version: 1\ntickers: []\n", encoding="utf-8")
    (tmp_path / ua.LOG).write_text(
        "ticker,date,verdict\nMSFT,2026-05-01,review\n", encoding="utf-8")
    return tmp_path


# --- parsing ----------------------------------------------------------------
def test_the_inline_flow_map_style_is_parsed(pool):
    doc = ua.load_yaml(pool / ua.UNIVERSE)
    assert [t["ticker"] for t in doc["tickers"]] == ["MSFT", "ASML.AS"]


def test_a_note_containing_a_comma_is_not_split_into_two_fields(pool):
    doc = ua.load_yaml(pool / ua.UNIVERSE)
    assert doc["tickers"][0]["note"] == "Cloud, AI"


def test_a_missing_file_returns_an_empty_document(tmp_path):
    assert ua.load_yaml(tmp_path / "nope.yaml")["tickers"] == []


# --- --add-ticker -----------------------------------------------------------
def test_a_valid_new_ticker_lands_in_pending(pool):
    res = ua.add_ticker("ADYEN.AS", pool, region="NL", sector="Technology",
                        note="Payments", _fetcher=exists)
    assert res["added"] is True
    doc = ua.load_yaml(pool / ua.PENDING)
    entry = doc["tickers"][0]
    assert entry["ticker"] == "ADYEN.AS" and entry["region"] == "NL"
    assert entry["added"] == date.today().isoformat()


@pytest.mark.parametrize("dup,where", [
    ("MSFT", "universe"), ("ASML.AS", "universe"), ("NVDA", "prefiltered pool")])
def test_duplicates_are_rejected_against_every_pool_file(pool, dup, where):
    res = ua.add_ticker(dup, pool, _fetcher=exists)
    assert res["added"] is False and where in res["reason"]


def test_a_duplicate_is_caught_case_insensitively(pool):
    assert ua.add_ticker("msft", pool, _fetcher=exists)["added"] is False


def test_adding_the_same_ticker_twice_is_rejected_the_second_time(pool):
    assert ua.add_ticker("ADYEN.AS", pool, _fetcher=exists)["added"] is True
    second = ua.add_ticker("ADYEN.AS", pool, _fetcher=exists)
    assert second["added"] is False and "pending" in second["reason"]


def test_a_nonexistent_symbol_is_rejected_before_it_costs_a_weekly_api_call(pool):
    res = ua.add_ticker("NOTREAL", pool, _fetcher=missing)
    assert res["added"] is False and "symbol check failed" in res["reason"]
    assert ua.load_yaml(pool / ua.PENDING)["tickers"] == []


@pytest.mark.parametrize("bad", ["", "   ", "WAY.TOO.LONG.A.SYMBOL.INDEED", "AB CD", "A;B"])
def test_implausible_symbols_never_reach_the_network(pool, bad):
    calls = []

    def spy(t):
        calls.append(t)
        return True, "ok"

    assert ua.add_ticker(bad, pool, _fetcher=spy)["added"] is False
    assert calls == []


def test_validation_can_be_skipped_for_offline_use(pool):
    assert ua.add_ticker("XYZ.TO", pool, validate=False)["added"] is True


def test_a_network_failure_is_not_treated_as_proof_the_symbol_is_bad(pool):
    def blip(_t):
        return False, "could not verify (ConnectionError: no route to host)"

    res = ua.add_ticker("REAL.AS", pool, _fetcher=blip)
    assert res["added"] is False
    assert "could not verify" in res["reason"]  # the reason is distinguishable


def test_the_written_file_round_trips(pool):
    ua.add_ticker("ADYEN.AS", pool, note='a "quoted" note, with comma', _fetcher=exists)
    doc = ua.load_yaml(pool / ua.PENDING)
    assert doc["tickers"][0]["note"] == "a 'quoted' note, with comma"


def test_entries_are_kept_sorted(pool):
    for t in ("ZZZ", "AAA", "MMM"):
        ua.add_ticker(t, pool, validate=False)
    got = [e["ticker"] for e in ua.load_yaml(pool / ua.PENDING)["tickers"]]
    assert got == sorted(got)


# --- --list-pending ---------------------------------------------------------
def test_never_evaluated_is_the_universe_minus_the_log(pool):
    block = ua.list_pending(pool)
    assert [e["ticker"] for e in block["never_evaluated"]] == ["ASML.AS"]
    assert block["counts"]["evaluated"] == 1


def test_pending_entrants_are_listed(pool):
    ua.add_ticker("ADYEN.AS", pool, validate=False)
    assert ua.list_pending(pool)["counts"]["pending"] == 1


def test_expired_shortlist_rows_are_read_not_recomputed(pool):
    """Recomputing the 90 days here would create a second definition of 'expired' that
    could disagree with the one the report prints."""
    (pool / ua.SHORTLIST).write_text(
        "| Ticker | Region | Score | Expires | Link |\n"
        "|---|---|---|---|---|\n"
        "| [[MSFT]] | US | 7.8 | 2026-01-01 | x |\n"
        "| PYPL | US | 7.6 | 2099-01-01 | x |\n", encoding="utf-8")
    got = ua.expired_shortlist(pool, today=date(2026, 8, 15))
    assert [g["ticker"] for g in got] == ["MSFT"]
    assert got[0]["days_ago"] == 226


def test_a_shortlist_without_an_expires_column_yields_nothing_rather_than_guessing(pool):
    (pool / ua.SHORTLIST).write_text(
        "| Ticker | Score |\n|---|---|\n| MSFT | 7.8 |\n", encoding="utf-8")
    assert ua.expired_shortlist(pool, today=date(2026, 8, 15)) == []


def test_a_missing_shortlist_is_not_an_error(tmp_path):
    assert ua.expired_shortlist(tmp_path) == []


def test_the_three_buckets_stay_separate(pool):
    """They need different actions: pending waits for Monday, never-evaluated waits for
    the picker, expired needs a human decision."""
    block = ua.list_pending(pool)
    for key in ("pending_entrants", "never_evaluated", "shortlist_expired"):
        assert key in block


def test_render_covers_every_bucket_even_when_empty(tmp_path):
    text = "\n".join(ua.render_pending(ua.list_pending(tmp_path)))
    for word in ("pending entrants", "never evaluated", "shortlist expired", "(none)"):
        assert word in text


# --- CLI --------------------------------------------------------------------
def test_cli_add_emits_json(pool, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["universe_admin.py", "--add-ticker", "ADYEN.AS",
                                      "--no-validate", "--out-dir", str(pool)])
    assert ua.main() == 0
    assert json.loads(capsys.readouterr().out)["added"] is True


def test_cli_list_emits_json(pool, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["universe_admin.py", "--list-pending",
                                      "--out-dir", str(pool)])
    assert ua.main() == 0
    assert "counts" in json.loads(capsys.readouterr().out)


# --- the R3 dependency ------------------------------------------------------
def test_r3_promotes_validated_entrants_into_the_universe():
    """`--add-ticker` on top of the old prefilter would have shipped broken by design:
    PENDING is wiped every run and `_universe.yaml` was never written, so a seeded ticker
    was evaluated exactly once and then vanished from the work list."""
    src = (SCRIPTS.parent.parent / "bd-stocks-prefilter" / "scripts"
           / "run_prefilter.py").read_text(encoding="utf-8")
    assert "roadmap R3" in src
    assert "save_yaml(UNIVERSE" in src
    # promotion must happen BEFORE pending is wiped, or it promotes nothing
    assert src.index("save_yaml(UNIVERSE") < src.index('save_yaml(PENDING, {"version": 1, "tickers": []})')
