"""Tests for portfolio_ingest.py — Yahoo export -> _portfolio_holdings.yaml."""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from portfolio_ingest import (  # noqa: E402
    HOLDINGS_FILENAME,
    build_document,
    curated_names,
    diff_holdings,
    export_age_days,
    find_export,
    group_holdings,
    load_existing,
    lot_note,
    parse_trade_date,
    quote_currency,
    read_lots,
    write_holdings,
)

HEADER = ("Symbol,Current Price,Date,Time,Change,Open,High,Low,Volume,Trade Date,"
          "Purchase Price,Quantity,Commission,High Limit,Low Limit,Comment,Transaction Type")


def export(tmp_path: Path, *rows: str, name="portfolio.csv") -> Path:
    p = tmp_path / name
    p.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return p


def lot_row(symbol="AMD", trade_date="20230329", price="97.51", qty="8.0",
            commission="0.0", comment="", tx="BUY") -> str:
    return (f"{symbol},100.0,2026-07-29,4:00PM,1.0,99,101,98,1000,{trade_date},"
            f"{price},{qty},{commission},,,{comment},{tx}")


def quote_only_row(symbol="NVDA") -> str:
    return f"{symbol},195.60,2026-07-29,4:00PM,5.59,190,196,189,1000,,,,,,,,"


# --- date parsing -----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("20260605", "2026-06-05"),   # the format Yahoo actually writes
    ("2026-06-05", "2026-06-05"),
    ("06/05/2026", "2026-06-05"),
    ("", None),
    ("not a date", None),
    (None, None),
])
def test_trade_date_parsing(raw, expected):
    assert parse_trade_date(raw) == expected


# --- the corrupt Transaction Type column ------------------------------------

def test_comment_spill_is_stitched_back_onto_the_note():
    """Yahoo writes an unquoted Comment, so a decimal comma splits the field:
    "Taxa de Câmbio:1,82 AutoFX" arrives across Comment + Transaction Type."""
    row = {"Comment": "Taxa de Câmbio:1", "Transaction Type": "82 AutoFX"}
    assert lot_note(row) == "Taxa de Câmbio:1,82 AutoFX"


def test_a_real_transaction_type_is_not_treated_as_comment_tail():
    assert lot_note({"Comment": "IBKR (1$)", "Transaction Type": "BUY"}) == "IBKR (1$)"
    assert lot_note({"Comment": "", "Transaction Type": "BUY"}) is None


def test_spill_with_no_comment_becomes_the_whole_note():
    assert lot_note({"Comment": "", "Transaction Type": "8 USDC"}) == "8 USDC"


def test_a_corrupt_transaction_type_never_drops_the_lot(tmp_path):
    """5 of 20 real lots carry a corrupt Transaction Type; filtering on it would
    silently lose those positions."""
    src = export(tmp_path, lot_row(symbol="BTC-EUR", tx="82 AutoFX"))
    lots, _ = read_lots(src)
    assert [x["symbol"] for x in lots] == ["BTC-EUR"]


# --- currency ---------------------------------------------------------------

@pytest.mark.parametrize("symbol,expected", [
    ("BTC-EUR", "EUR"),    # markets.currency_of answers USD here — the bug this guards
    ("ETH-USD", "USD"),
    ("NEXO-USD", "USD"),
])
def test_crypto_pair_currency_comes_from_its_own_suffix(symbol, expected):
    assert quote_currency(symbol, lambda s: "USD") == expected


def test_equity_currency_defers_to_the_markets_lookup():
    assert quote_currency("2330.TW", lambda s: "TWD") == "TWD"


def test_currency_lookup_failure_degrades_to_eur():
    assert quote_currency("XYZ.AS", lambda s: (_ for _ in ()).throw(RuntimeError)) == "EUR"


# --- reading the export -----------------------------------------------------

def test_quote_only_rows_are_watchlist_not_holdings(tmp_path):
    src = export(tmp_path, lot_row(), quote_only_row(), quote_only_row("META"))
    lots, warnings = read_lots(src)
    assert len(lots) == 1
    assert warnings == []


def test_a_lot_without_a_purchase_price_is_skipped_loudly(tmp_path):
    src = export(tmp_path, lot_row(symbol="ZZZ", price=""))
    lots, warnings = read_lots(src)
    assert lots == []
    assert any("no purchase price" in w for w in warnings)


def test_negative_quantity_is_flagged_for_manual_review(tmp_path):
    src = export(tmp_path, lot_row(symbol="AMD", qty="-3"))
    lots, warnings = read_lots(src)
    assert len(lots) == 1
    assert any("negative quantity" in w for w in warnings)


def test_a_csv_that_is_not_a_yahoo_export_is_rejected(tmp_path):
    p = tmp_path / "portfolio.csv"
    p.write_text("ticker,buy_date,buy_price,quantity\nAMD,2023-03-29,97.51,8\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a Yahoo portfolio export"):
        read_lots(p)


def test_commission_and_note_survive_the_read(tmp_path):
    src = export(tmp_path, lot_row(commission="4.9", comment="deGiro"))
    lots, _ = read_lots(src)
    assert lots[0]["commission"] == 4.9
    assert lots[0]["note"] == "deGiro"


# --- grouping ---------------------------------------------------------------

def test_multiple_lots_aggregate_with_a_quantity_weighted_cost():
    lots = [
        {"symbol": "SEM.LS", "qty": 55.0, "price": 17.96, "date": "2025-12-22", "note": None, "commission": None},
        {"symbol": "SEM.LS", "qty": 56.0, "price": 17.70, "date": "2025-12-19", "note": "impulso", "commission": None},
    ]
    h = group_holdings(lots)[0]
    assert h["quantity"] == 111.0
    assert h["avg_cost"] == pytest.approx(round((55 * 17.96 + 56 * 17.70) / 111, 4))
    assert [lot["date"] for lot in h["lots"]] == ["2025-12-22", "2025-12-19"]  # newest first
    assert h["lots"][1]["note"] == "impulso"


def test_curated_names_are_preserved_and_never_invented():
    lots = [{"symbol": "2330.TW", "qty": 20.0, "price": 2390.0, "date": "2026-06-05",
             "note": None, "commission": None}]
    assert group_holdings(lots, {"2330.TW": "TSMC"})[0]["name"] == "TSMC"
    assert group_holdings(lots, {})[0]["name"] == "2330.TW"


def test_asset_type_comes_from_the_classifier():
    lots = [{"symbol": "BTC-EUR", "qty": 1.0, "price": 100.0, "date": None,
             "note": None, "commission": None}]
    assert group_holdings(lots, classify=lambda t: "crypto")[0]["asset_type"] == "crypto"
    assert group_holdings(lots, classify=lambda t: None)[0]["asset_type"] == "equity"


def test_a_broken_classifier_does_not_break_the_ingest():
    lots = [{"symbol": "AMD", "qty": 1.0, "price": 1.0, "date": None, "note": None, "commission": None}]
    def boom(_):
        raise RuntimeError("classifier down")
    assert group_holdings(lots, classify=boom)[0]["asset_type"] == "equity"


def test_holdings_come_out_ticker_sorted():
    lots = [{"symbol": s, "qty": 1.0, "price": 1.0, "date": None, "note": None, "commission": None}
            for s in ("PYPL", "AMD", "COIN")]
    assert [h["ticker"] for h in group_holdings(lots)] == ["AMD", "COIN", "PYPL"]


def test_a_lot_with_no_date_omits_the_key_rather_than_guessing():
    lots = [{"symbol": "AMD", "qty": 1.0, "price": 1.0, "date": None, "note": None, "commission": None}]
    assert "date" not in group_holdings(lots)[0]["lots"][0]


# --- diff -------------------------------------------------------------------

def test_diff_reports_added_removed_and_changed():
    old = [{"ticker": "AMD", "quantity": 8.0, "avg_cost": 97.51, "currency": "USD", "asset_type": "equity"},
           {"ticker": "GONE", "quantity": 1.0, "avg_cost": 1.0, "currency": "USD", "asset_type": "equity"}]
    new = [{"ticker": "AMD", "quantity": 12.0, "avg_cost": 97.51, "currency": "USD", "asset_type": "equity"},
           {"ticker": "NEW", "quantity": 5.0, "avg_cost": 10.0, "currency": "EUR", "asset_type": "equity"}]
    d = diff_holdings(old, new)
    assert d["added"] == ["NEW"]
    assert d["removed"] == ["GONE"]
    assert d["changed"] == [{"ticker": "AMD", "field": "quantity", "from": 8.0, "to": 12.0}]


def test_diff_ignores_float_noise():
    old = [{"ticker": "AMD", "quantity": 8.0, "avg_cost": 97.51, "currency": "USD", "asset_type": "equity"}]
    new = [{"ticker": "AMD", "quantity": 8.0 + 1e-12, "avg_cost": 97.51, "currency": "USD", "asset_type": "equity"}]
    assert diff_holdings(old, new)["changed"] == []


def test_diff_against_an_empty_file_is_all_additions():
    new = [{"ticker": "AMD", "quantity": 1.0, "avg_cost": 1.0, "currency": "USD", "asset_type": "equity"}]
    assert diff_holdings([], new) == {"added": ["AMD"], "removed": [], "changed": []}


# --- locating the export ----------------------------------------------------

def test_newest_export_wins(tmp_path):
    old = export(tmp_path, lot_row(), name="portfolio.csv")
    new = export(tmp_path, lot_row(), name="quotes.csv")
    past = time.time() - 86_400
    os.utime(old, (past, past))
    assert find_export(roots=(tmp_path,), archive=tmp_path / "empty") == new


def test_an_explicit_source_is_honoured_over_the_downloads_scan(tmp_path):
    export(tmp_path, lot_row(), name="portfolio.csv")
    explicit = tmp_path / "elsewhere.csv"
    assert find_export(explicit, roots=(tmp_path,)) == explicit


def test_no_export_found_returns_none(tmp_path):
    """Every source must be empty. `archive` defaults to the real `_exports\\` dir, so
    passing only the roots left this test asserting against the live filesystem — it
    failed the moment the archive gained its first export."""
    assert find_export(roots=(tmp_path,), archive=tmp_path / "empty") is None


def test_export_age_is_measured_in_days(tmp_path):
    src = export(tmp_path, lot_row())
    past = time.time() - 3 * 86_400
    os.utime(src, (past, past))
    assert export_age_days(src) == 3


# --- write round-trip -------------------------------------------------------

def test_written_file_round_trips_and_keeps_the_do_not_edit_header(tmp_path):
    lots = [{"symbol": "AMD", "qty": 8.0, "price": 97.51, "date": "2023-03-29",
             "note": "Taxa de Câmbio:1,82 AutoFX", "commission": None}]
    holdings = group_holdings(lots, {"AMD": "Advanced Micro Devices"})
    doc = build_document(holdings, Path("C:/x/portfolio.csv"), "2026-07-30")
    path = write_holdings(tmp_path, doc)
    assert path.name == HOLDINGS_FILENAME

    raw = path.read_text(encoding="utf-8")
    assert "do not edit by hand" in raw
    assert "portfolio_ingest.py" in raw

    back = load_existing(tmp_path)
    assert back["version"] == 1
    assert back["last_updated"] == "2026-07-30"
    h = back["holdings"][0]
    assert (h["ticker"], h["name"], h["quantity"], h["avg_cost"]) == \
           ("AMD", "Advanced Micro Devices", 8.0, 97.51)
    assert h["lots"][0]["note"] == "Taxa de Câmbio:1,82 AutoFX"
    assert curated_names(back) == {"AMD": "Advanced Micro Devices"}


def test_load_existing_on_a_missing_file_is_empty_not_an_error(tmp_path):
    assert load_existing(tmp_path) == {}


def test_build_document_records_its_provenance():
    doc = build_document([], Path("C:/x/portfolio.csv"), dt.date.today().isoformat())
    assert "portfolio_ingest.py" in doc["source"]
    assert "Yahoo Finance export" in doc["source"]
    assert "watchlist" in doc["source"]
