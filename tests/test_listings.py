"""
Unit tests for listings.py — one company, many tickers.

Regression cover for the dual-listing duplication: TSMC held 7 evaluations in
_log.csv across TSM and 2330.TW (two of them two days apart) because three alias
tables disagreed about which side was canonical. The rule under test is that the
HOME line is the company, and the ADR is just another venue.

Network-free: the only function that touches yfinance is probe_listing, and every
test here either skips the probe or injects a fake one.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import listings as L  # noqa: E402


# --- registry integrity -----------------------------------------------------

def test_every_symbol_maps_to_exactly_one_company():
    seen = {}
    for g in L.REGISTRY:
        for sym in [g["home"]] + [a["ticker"] for a in g["also"]]:
            assert sym not in seen, f"{sym} claimed by {seen.get(sym)} and {g['company']}"
            seen[sym] = g["company"]


def test_home_is_never_repeated_in_also():
    for g in L.REGISTRY:
        assert g["home"] not in [a["ticker"] for a in g["also"]]


def test_no_alias_chains():
    # company_key must be idempotent: resolving a resolved key changes nothing.
    for g in L.REGISTRY:
        for sym in [g["home"]] + [a["ticker"] for a in g["also"]]:
            assert L.company_key(L.company_key(sym)) == L.company_key(sym)


def test_every_registry_symbol_has_a_known_market():
    # An unknown Yahoo suffix would silently render the wrong currency in the
    # "where can I buy this" table.
    import markets
    for g in L.REGISTRY:
        for sym in [g["home"]] + [a["ticker"] for a in g["also"]]:
            assert markets.market_meta(sym)["known"], sym


# --- identity ---------------------------------------------------------------

def test_home_listing_is_canonical_not_the_adr():
    assert L.company_key("TSM") == "2330.TW"
    assert L.company_key("2330.TW") == "2330.TW"
    assert L.company_key("NVO") == "NOVO-B.CO"
    assert L.company_key("BABA") == "9988.HK"


def test_unmapped_ticker_is_its_own_company():
    assert L.company_key("NVDA") == "NVDA"
    assert L.listing_rows("NVDA") == []


def test_identity_tolerates_whitespace_and_non_strings():
    assert L.company_key("  TSM ") == "2330.TW"
    assert L.company_key(None) == ""          # type: ignore[arg-type]
    assert L.company_key(True) == "True"      # YAML 1.1 turns a bare ON into True


def test_is_home():
    assert L.is_home("2330.TW")
    assert not L.is_home("TSM")
    assert L.is_home("NVDA")  # single-listed names are their own home


def test_all_tickers_puts_home_first():
    assert L.all_tickers("TSM") == ["2330.TW", "TSM"]
    assert L.all_tickers("SHELL.AS")[0] == "SHEL.L"
    assert L.all_tickers("NVDA") == ["NVDA"]


# --- venues -----------------------------------------------------------------

def test_market_key_maps_only_brokered_markets():
    assert L.market_key("TSM") == "US"
    assert L.market_key("2330.TW") == "TW"
    assert L.market_key("RYA.IR") == "IE"
    # Amsterdam is not priced in brokers.yaml — None, never a guessed cost.
    assert L.market_key("ASML.AS") is None


def test_listing_rows_carry_venue_and_ratio():
    rows = {r["ticker"]: r for r in L.listing_rows("TSM")}
    assert rows["2330.TW"]["home"] is True
    assert rows["2330.TW"]["currency"] == "TWD"
    assert rows["TSM"]["kind"] == "adr"
    assert "5" in rows["TSM"]["ratio"]  # the ratio people get wrong


def test_listing_table_is_empty_for_single_listed():
    assert L.listing_table("NVDA") == ""


def test_listing_table_marks_home_and_uses_broker_costs():
    md = L.listing_table("TSM", broker_costs={"TW": "IBKR — €12.40"})
    assert "**2330.TW**" in md          # home is bolded
    assert "IBKR — €12.40" in md
    assert "| — |" in md                # US row has no cost supplied


# --- preferred_listing ------------------------------------------------------

def test_preferred_listing_skips_network_when_asked():
    r = L.preferred_listing("TSM", probe=False)
    assert r["ticker"] == "2330.TW" and r["switched"] is True
    assert r["probes"] == {}


def test_single_listed_is_returned_untouched():
    r = L.preferred_listing("NVDA", probe=False)
    assert r["ticker"] == "NVDA" and r["switched"] is False


def _fake_probes(monkeypatch, ratios: dict):
    monkeypatch.setattr(L, "probe_listing", lambda t, use_cache=True: {
        "ticker": t, "n": 0, "total": len(L.PROBE_FIELDS),
        "ratio": ratios.get(t, 0.0), "missing": [], "error": None,
    })


def test_home_wins_on_equal_coverage(monkeypatch):
    _fake_probes(monkeypatch, {"2330.TW": 1.0, "TSM": 1.0})
    assert L.preferred_listing("TSM")["ticker"] == "2330.TW"


def test_home_wins_when_only_slightly_thinner(monkeypatch):
    # 0.88 vs 1.0 is above the 0.80 tolerance — this is the real Samsung case.
    _fake_probes(monkeypatch, {"005930.KS": 0.88, "SSUN.F": 1.0})
    r = L.preferred_listing("005930.KS")
    assert r["ticker"] == "005930.KS" and r["switched"] is False


def test_alternative_wins_when_home_is_materially_thinner(monkeypatch):
    _fake_probes(monkeypatch, {"2330.TW": 0.4, "TSM": 1.0})
    r = L.preferred_listing("2330.TW")
    assert r["ticker"] == "TSM"
    assert "below the" in r["reason"]


def test_rate_limited_probe_does_not_hand_the_run_to_the_adr(monkeypatch):
    # Both probes empty means yfinance is sick, not that the home line is thin.
    # Falling back to the ADR here would undo the policy on exactly the bad days.
    _fake_probes(monkeypatch, {})
    r = L.preferred_listing("TSM")
    assert r["ticker"] == "2330.TW"
    assert "inconclusive" in r["reason"]


def test_probe_failure_is_reported_not_raised(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("429 Too Many Requests")
    monkeypatch.setitem(sys.modules, "yfinance", type("m", (), {"Ticker": boom})())
    out = L.probe_listing("TSM", use_cache=False)
    assert out["ratio"] == 0.0 and "429" in out["error"]


# --- unmapped-ADR detection -------------------------------------------------

def test_adr_suspicion_flags_usd_traded_foreign_reporter():
    msg = L.adr_suspicion("XYZ", {"currency": "USD", "financialCurrency": "JPY"})
    assert msg and "unmapped ADR" in msg


def test_adr_suspicion_silent_for_ordinary_us_stock():
    assert L.adr_suspicion("NVDA", {"currency": "USD", "financialCurrency": "USD"}) is None


def test_adr_suspicion_silent_for_already_mapped_and_non_us():
    assert L.adr_suspicion("TSM", {"currency": "USD", "financialCurrency": "TWD"}) is None
    assert L.adr_suspicion("2330.TW", {"currency": "TWD", "financialCurrency": "TWD"}) is None


# --- the bug this module exists to kill -------------------------------------

@pytest.mark.parametrize("a,b", [("TSM", "2330.TW"), ("SAP", "SAP.DE"),
                                 ("ASML", "ASML.AS"), ("NVO", "NOVO-B.CO"),
                                 ("BABA", "9988.HK"), ("RYAAY", "RYA.IR")])
def test_pairs_that_actually_duplicated_in_the_log_now_collapse(a, b):
    assert L.company_key(a) == L.company_key(b)
