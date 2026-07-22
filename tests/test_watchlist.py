"""
Unit tests for v4 Phase E — watchlist.py.

Pure-function + tmp_path CSV round-trip; no network. Covers the one-line
membership rule (keep iff composite>=7 AND mos_class=='rich' AND fair-low
available AND not held) and every removal it subsumes — buy (held), quality
loss (score<7), graduation to cheap (mos leaves 'rich') — plus the CSV contract
read by send_email.py.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import watchlist as wl  # noqa: E402


# ------------------------- eligibility -------------------------
def test_eligible_quality_and_rich_with_target():
    assert wl.is_watchlist_eligible(8.1, "rich", 120.0) is True


def test_not_eligible_below_quality_floor():
    assert wl.is_watchlist_eligible(6.9, "rich", 120.0) is False


def test_not_eligible_when_not_rich():
    assert wl.is_watchlist_eligible(8.5, "fair", 120.0) is False
    assert wl.is_watchlist_eligible(8.5, "deep_value", 120.0) is False
    assert wl.is_watchlist_eligible(8.5, "not_computable", 120.0) is False


def test_not_eligible_without_target():
    assert wl.is_watchlist_eligible(8.5, "rich", None) is False
    assert wl.is_watchlist_eligible(8.5, "rich", 0) is False


def test_should_be_on_list_requires_not_held():
    assert wl.should_be_on_list(8.5, "rich", 120.0, held=False) is True
    assert wl.should_be_on_list(8.5, "rich", 120.0, held=True) is False


# ------------------------- distance-to-target -------------------------
def test_distance_above_target_is_positive():
    assert wl.distance_to_target_pct(150.0, 120.0) == 25.0


def test_distance_at_or_below_target_triggers():
    assert wl.distance_to_target_pct(120.0, 120.0) == 0.0
    assert wl.distance_to_target_pct(108.0, 120.0) == -10.0  # triggered


def test_distance_none_and_bad_inputs():
    assert wl.distance_to_target_pct(None, 120.0) is None
    assert wl.distance_to_target_pct(100.0, None) is None
    assert wl.distance_to_target_pct(100.0, 0) is None
    assert wl.distance_to_target_pct("x", 120.0) is None


# ------------------------- row ops -------------------------
def test_remove_ticker_case_insensitive():
    rows = [{"ticker": "CSCO"}, {"ticker": "ADSK"}]
    assert wl.remove_ticker(rows, "csco") == [{"ticker": "ADSK"}]


def test_upsert_preserves_added_date_on_replace():
    rows = [{"ticker": "ADSK", "added_date": "2026-07-01", "score": "8.0"}]
    new = {"ticker": "ADSK", "added_date": "2026-07-22", "score": "8.4"}
    out = wl.upsert_row(rows, new)
    assert len(out) == 1
    assert out[0]["added_date"] == "2026-07-01"  # first-seen date kept
    assert out[0]["score"] == "8.4"              # rest refreshed


def test_upsert_appends_new_ticker():
    rows = [{"ticker": "CSCO", "added_date": "2026-07-01"}]
    out = wl.upsert_row(rows, {"ticker": "ADSK", "added_date": "2026-07-22"})
    assert [r["ticker"] for r in out] == ["CSCO", "ADSK"]


def test_build_row_fields():
    r = wl.build_row("ADSK", 250.0, "USD", 250.0, "rich", 8.4, -18.0, "2026-07-22")
    assert r["ticker"] == "ADSK" and r["target"] == 250.0
    assert r["fail_reason"] == "price rich (MoS)"
    assert r["added_date"] == "2026-07-22"
    assert "8.4/10" in r["thesis"]


# ------------------------- maintenance rule -------------------------
def test_maintenance_adds_eligible_not_held():
    rows, action = wl.apply_maintenance([], "ADSK", 8.4, "rich", 250.0,
                                        held=False, currency="USD",
                                        mos_pct=-18.0, today_iso="2026-07-22")
    assert action == "kept"
    assert rows[0]["ticker"] == "ADSK" and rows[0]["target"] == 250.0


def test_maintenance_removes_when_bought():
    start = [{"ticker": "ADSK", "added_date": "2026-07-01"}]
    rows, action = wl.apply_maintenance(start, "ADSK", 8.4, "rich", 250.0,
                                        held=True, currency="USD",
                                        mos_pct=-18.0, today_iso="2026-07-22")
    assert action == "removed" and rows == []


def test_maintenance_removes_on_quality_loss():
    start = [{"ticker": "ADSK", "added_date": "2026-07-01"}]
    rows, action = wl.apply_maintenance(start, "ADSK", 6.2, "rich", 250.0,
                                        held=False, currency="USD",
                                        mos_pct=-18.0, today_iso="2026-07-22")
    assert action == "removed" and rows == []


def test_maintenance_removes_on_graduation_to_cheap():
    start = [{"ticker": "ADSK", "added_date": "2026-07-01"}]
    rows, action = wl.apply_maintenance(start, "ADSK", 8.4, "fair", 250.0,
                                        held=False, currency="USD",
                                        mos_pct=5.0, today_iso="2026-07-22")
    assert action == "removed" and rows == []


def test_maintenance_absent_when_not_eligible_and_not_present():
    rows, action = wl.apply_maintenance([{"ticker": "CSCO"}], "ADSK", 5.0,
                                        "fair", 250.0, held=False, currency="USD",
                                        mos_pct=1.0, today_iso="2026-07-22")
    assert action == "absent"
    assert [r["ticker"] for r in rows] == ["CSCO"]


# ------------------------- CSV round-trip -------------------------
def test_csv_round_trip_and_contract(tmp_path):
    row = wl.build_row("ADSK", 250.0, "USD", 250.0, "rich", 8.4, -18.0, "2026-07-22")
    wl.write_watchlist(tmp_path, [row])
    # Header matches the documented contract in column order.
    with (tmp_path / wl.WATCHLIST_FILENAME).open(encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert header == wl.COLUMNS
    back = wl.load_watchlist(tmp_path)
    assert back[0]["ticker"] == "ADSK" and back[0]["mos_class"] == "rich"


def test_load_watchlist_missing_is_empty(tmp_path):
    assert wl.load_watchlist(tmp_path) == []
