"""
Phase-6 (Global Market Expansion) unit tests.

All pure / network-free:
  1. Suffix -> currency / region / accounting-standard mapping (Asia + EU + US).
  2. Stooq symbol mapping (Yahoo suffix -> Stooq CSV symbol).
  3. Stooq CSV price parse (static fixtures, no network).
  4. Local -> EUR conversion (EURxxx=X convention).
  5. stooq_price_check end-to-end with an injected fetcher (no network).
  6. Per-market caveats surface for the right regions.

The one network function (fetch via requests) is NOT exercised here — it is
injected via the `_fetcher` hook.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from markets import (  # noqa: E402
    currency_of,
    eur_fx_pair,
    market_caveats,
    market_meta,
    parse_stooq_csv,
    region_of,
    stooq_csv_url,
    stooq_price_check,
    suffix_of,
    to_eur,
    to_stooq_symbol,
)


# ------------------------- 1. Suffix -> currency / region -------------------------
def test_suffix_of():
    assert suffix_of("6502.T") == "T"
    assert suffix_of("RELIANCE.NS") == "NS"
    assert suffix_of("AAPL") == ""
    assert suffix_of("BRK-B") == ""          # hyphen is not a suffix
    assert suffix_of("005930.KS") == "KS"


def test_asia_currency_region_mapping():
    cases = {
        "6502.T": ("JP", "JPY"),
        "0700.HK": ("HK", "HKD"),
        "005930.KS": ("KR", "KRW"),
        "035720.KQ": ("KR", "KRW"),
        "RELIANCE.NS": ("IN", "INR"),
        "BOSCHLTD.BO": ("IN", "INR"),
        "2330.TW": ("TW", "TWD"),
        "5483.TWO": ("TW", "TWD"),
        "600519.SS": ("CN", "CNY"),
        "300750.SZ": ("CN", "CNY"),
    }
    for tkr, (region, currency) in cases.items():
        assert region_of(tkr) == region, tkr
        assert currency_of(tkr) == currency, tkr


def test_eu_us_mapping_backward_compat():
    assert (region_of("MSFT"), currency_of("MSFT")) == ("US", "USD")
    assert (region_of("ASML.AS"), currency_of("ASML.AS")) == ("NL", "EUR")
    assert (region_of("AZN.L"), currency_of("AZN.L")) == ("UK", "GBP")
    assert (region_of("EVO.ST"), currency_of("EVO.ST")) == ("SE", "SEK")
    assert (region_of("SHOP.TO"), currency_of("SHOP.TO")) == ("CA", "CAD")


def test_accounting_standards():
    assert market_meta("6502.T")["accounting_standard"].startswith("JP-GAAP")
    assert market_meta("600519.SS")["accounting_standard"] == "China-GAAP"
    assert market_meta("MSFT")["accounting_standard"] == "US-GAAP"
    assert market_meta("ASML.AS")["accounting_standard"] == "IFRS"
    assert market_meta("005930.KS")["accounting_standard"] == "K-IFRS"


def test_unknown_suffix_is_flagged_not_crashing():
    meta = market_meta("FOO.XYZ")
    assert meta["known"] is False
    assert meta["currency"] == "USD"          # safe default
    assert meta["region"] == "INTL"
    caveats = market_caveats("FOO.XYZ")
    assert any("unknown exchange suffix" in c for c in caveats)


def test_market_caveats_for_known_markets():
    assert any("China-GAAP" in c for c in market_caveats("600519.SS"))
    assert any("[JP]" in c for c in market_caveats("6502.T"))
    assert market_caveats("MSFT") == []       # US gets no extra caveat


# ------------------------- 2. Stooq symbol mapping -------------------------
def test_stooq_symbol_mapping():
    assert to_stooq_symbol("6502.T") == "6502.jp"
    assert to_stooq_symbol("0700.HK") == "0700.hk"
    assert to_stooq_symbol("005930.KS") == "005930.kr"
    assert to_stooq_symbol("RELIANCE.NS") == "reliance.in"
    assert to_stooq_symbol("2330.TW") == "2330.tw"
    assert to_stooq_symbol("300750.SZ") == "300750.cn"
    assert to_stooq_symbol("600519.SS") == "600519.cn"
    assert to_stooq_symbol("AAPL") == "aapl.us"


def test_stooq_symbol_unmapped_suffix():
    assert to_stooq_symbol("FOO.XYZ") is None


def test_stooq_csv_url():
    assert stooq_csv_url("6502.jp") == "https://stooq.com/q/d/l/?s=6502.jp&i=d"


# ------------------------- 3. Stooq CSV parse -------------------------
_CSV_OK = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-06-04,3500,3550,3480,3520,1200000\n"
    "2026-06-05,3520,3600,3510,3585,1500000\n"
)


def test_parse_stooq_csv_ok():
    p = parse_stooq_csv(_CSV_OK)
    assert p is not None
    assert p["close"] == 3585.0
    assert p["date"] == "2026-06-05"
    assert p["volume"] == 1500000.0


def test_parse_stooq_csv_no_data_sentinel():
    assert parse_stooq_csv("N/D") is None
    assert parse_stooq_csv("No data") is None
    assert parse_stooq_csv("") is None
    assert parse_stooq_csv("Date,Open,High,Low,Close,Volume\n") is None  # header only


def test_parse_stooq_csv_bad_close():
    bad = "Date,Open,High,Low,Close,Volume\n2026-06-05,1,2,0.5,xx,100\n"
    assert parse_stooq_csv(bad) is None


def test_parse_stooq_csv_rejects_js_challenge():
    # Stooq (mid-2026) guards the CSV endpoint with a JS proof-of-work HTML page.
    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="robots" content="noindex,nofollow"></head><body>'
        '<noscript>This site requires JavaScript to verify your browser.</noscript>'
        "</body></html>"
    )
    assert parse_stooq_csv(html) is None


def test_stooq_price_check_reports_js_challenge_cleanly():
    html = "<!doctype html><html><body>requires javascript</body></html>"
    res = stooq_price_check("2330.TW", yf_price=900.0, _fetcher=lambda u: html)
    assert res["agree"] is None
    assert res["divergences"] == []
    assert "proof-of-work" in res["error"] or "JS-gated" in res["error"]


# ------------------------- 4. Local -> EUR conversion -------------------------
def test_eur_fx_pair():
    assert eur_fx_pair("JPY") == "EURJPY=X"
    assert eur_fx_pair("USD") == "EURUSD=X"
    assert eur_fx_pair("EUR") is None
    assert eur_fx_pair("") is None


def test_to_eur():
    # 1,000,000 JPY at 160 JPY/EUR -> 6250 EUR
    assert to_eur(1_000_000, "JPY", 160.0) == 6250.0
    # EUR passes through regardless of rate
    assert to_eur(500, "EUR", 999) == 500.0
    # USD at 1.08 USD/EUR
    assert to_eur(108, "USD", 1.08) == 100.0
    # Missing rate -> None (non-EUR)
    assert to_eur(100, "JPY", None) is None
    assert to_eur(None, "JPY", 160.0) is None


# ------------------------- 5. stooq_price_check (injected fetcher) -------------------------
def test_stooq_price_check_agree():
    res = stooq_price_check("6502.T", yf_price=3580.0, _fetcher=lambda u: _CSV_OK)
    assert res["stooq_symbol"] == "6502.jp"
    assert res["stooq_price"] == 3585.0
    assert res["checked"] == ["price"]
    assert res["divergences"] == []
    assert res["agree"] is True


def test_stooq_price_check_divergence():
    # yfinance way off vs Stooq -> divergence flagged
    res = stooq_price_check("0700.HK", yf_price=100.0, _fetcher=lambda u: _CSV_OK)
    assert res["agree"] is False
    assert any("price:" in d for d in res["divergences"])


def test_stooq_price_check_no_coverage():
    res = stooq_price_check("2330.TW", yf_price=900.0, _fetcher=lambda u: "N/D")
    assert res["error"] is not None
    assert res["divergences"] == []
    assert res["agree"] is None


def test_stooq_price_check_unmapped():
    res = stooq_price_check("FOO.XYZ", yf_price=1.0, _fetcher=lambda u: _CSV_OK)
    assert "no Stooq symbol mapping" in res["error"]


def test_stooq_price_check_fetcher_raises_is_nonfatal():
    def boom(u):  # noqa: ANN001
        raise RuntimeError("network down")

    res = stooq_price_check("6502.T", yf_price=3580.0, _fetcher=boom)
    assert "RuntimeError" in res["error"]
    assert res["agree"] is None
