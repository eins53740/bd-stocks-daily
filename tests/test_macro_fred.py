"""Tests for the §6 regime gauges — roadmap R2.

Network-free: `fetch_series` is the only function that touches FRED, and nothing here
calls it. The fixtures carry the units and shapes FRED actually returned on 2026-08-16.

The property this file exists for is the **units assertion**. `NCBEILQ027S` is published in
millions of dollars and `GDP` in billions; a helper that passed numbers through unconverted
would publish a Buffett Indicator wrong by a factor of 1000. That one is loud enough to be
caught — a thousands-vs-millions pairing would not be, which is why the check is on the
unit string rather than on whether the answer looks sensible.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import macro_fred as mf  # noqa: E402


def series(sid, units, obs, error=None, freq="M"):
    return {"series_id": sid, "units": units, "frequency": freq,
            "observations": obs, "error": error}


# Real shapes, 2026-08-16: M2 monthly newest-first, 13 points so YoY is computable.
M2_OBS = [("2026-06-01", 23155.2), ("2026-05-01", 23010.0), ("2026-04-01", 22890.0),
          ("2026-03-01", 22670.0), ("2026-02-01", 22500.0), ("2026-01-01", 22400.0),
          ("2025-12-01", 22300.0), ("2025-11-01", 22200.0), ("2025-10-01", 22100.0),
          ("2025-09-01", 22050.0), ("2025-08-01", 22000.0), ("2025-07-01", 21950.0),
          ("2025-06-01", 21942.0)]


# --- units, the reason this module has tests --------------------------------

@pytest.mark.parametrize("units,expected", [
    ("Billions of Dollars", 1000.0),
    ("Millions of U.S. Dollars", 1.0),
    ("Thousands of Dollars", 0.001),
    ("billions of dollars", 1000.0),          # case-insensitive
    ("  Billions of Dollars  ", 1000.0),      # and whitespace-tolerant
])
def test_known_units_convert_to_billions(units, expected):
    assert mf.to_billions(1000.0, units) == pytest.approx(expected)


@pytest.mark.parametrize("units", [
    "Index 1941-43=10", "Percent", "Persons", None, "", "Chained 2017 Dollars",
])
def test_an_unrecognised_unit_returns_none_rather_than_the_raw_number(units):
    """Passing the number through is how a 1000x error gets published."""
    assert mf.to_billions(1000.0, units) is None


def test_the_millions_vs_billions_trap_is_actually_caught():
    """The concrete pairing: equities in millions, GDP in billions. Unconverted the ratio
    reads 190 000 %; converted it reads 218 %."""
    eq = series("NCBEILQ027S", "Millions of U.S. Dollars",
                [("2026-01-01", 69_511_600.0)], freq="Q")
    gdp = series("GDP", "Billions of Dollars", [("2026-01-01", 31_865.7)], freq="Q")
    got = mf.buffett_indicator(eq, gdp)
    assert got["ratio_pct"] == pytest.approx(218.1, abs=0.5)
    assert got["equities_usd_bn"] == pytest.approx(69_511.6, abs=1)


def test_an_unknown_unit_blocks_the_ratio_entirely():
    eq = series("NCBEILQ027S", "Zorkmids", [("2026-01-01", 1.0)], freq="Q")
    gdp = series("GDP", "Billions of Dollars", [("2026-01-01", 100.0)], freq="Q")
    got = mf.buffett_indicator(eq, gdp)
    assert got["ratio_pct"] is None
    assert "unrecognised units" in got["error"]


# --- the quarters have to line up -------------------------------------------

def test_the_ratio_uses_a_quarter_both_series_cover():
    """The equities series lags GDP by a quarter. Mixing Q1 equities with Q2 GDP is a
    different statistic, so the newest COMMON quarter wins and is reported."""
    eq = series("NCBEILQ027S", "Millions of U.S. Dollars",
                [("2026-01-01", 69_511_600.0), ("2025-10-01", 68_000_000.0)], freq="Q")
    gdp = series("GDP", "Billions of Dollars",
                 [("2026-04-01", 32_500.0), ("2026-01-01", 31_865.7),
                  ("2025-10-01", 31_000.0)], freq="Q")
    got = mf.buffett_indicator(eq, gdp)
    assert got["as_of"] == "2026-01-01"
    assert got["gdp_usd_bn"] == pytest.approx(31_865.7)


def test_no_overlapping_quarter_is_an_error_that_names_both_ends():
    eq = series("NCBEILQ027S", "Millions of U.S. Dollars",
                [("2025-01-01", 1.0)], freq="Q")
    gdp = series("GDP", "Billions of Dollars", [("2026-04-01", 1.0)], freq="Q")
    got = mf.buffett_indicator(eq, gdp)
    assert got["ratio_pct"] is None
    assert "2025-01-01" in got["error"] and "2026-04-01" in got["error"]


def test_a_non_positive_gdp_is_refused_rather_than_divided_by():
    eq = series("NCBEILQ027S", "Millions of U.S. Dollars",
                [("2026-01-01", 1.0)], freq="Q")
    gdp = series("GDP", "Billions of Dollars", [("2026-01-01", 0.0)], freq="Q")
    assert mf.buffett_indicator(eq, gdp)["ratio_pct"] is None


# --- M2 ----------------------------------------------------------------------

def test_m2_reports_level_yoy_and_the_three_month_rate():
    got = mf.m2_regime(series("M2SL", "Billions of Dollars", M2_OBS))
    assert got["as_of"] == "2026-06-01"
    assert got["level_usd_bn"] == pytest.approx(23155.2)
    assert got["yoy_pct"] == pytest.approx(5.53, abs=0.02)
    # 3m annualised turns before YoY does, which is the point of carrying it.
    assert got["three_month_annualised_pct"] > got["yoy_pct"]


@pytest.mark.parametrize("yoy,label", [
    (-2.0, "contracting"), (-0.1, "contracting"), (0.0, "flat"), (3.9, "flat"),
    (4.0, "expanding"), (7.9, "expanding"), (8.0, "rapidly expanding"), (25.0,
                                                                         "rapidly expanding"),
])
def test_the_regime_bands_are_published_and_exhaustive(yoy, label):
    assert mf.classify_m2(yoy) == label


def test_no_yoy_means_no_regime_label():
    """A label with nothing behind it is worse than a gap."""
    assert mf.classify_m2(None) is None
    short = mf.m2_regime(series("M2SL", "Billions of Dollars", M2_OBS[:4]))
    assert short["yoy_pct"] is None and short["regime"] is None
    assert short["level_usd_bn"] is not None      # what IS known is still reported


def test_m2_in_an_unknown_unit_publishes_nothing():
    got = mf.m2_regime(series("M2SL", "Index 2015=100", M2_OBS))
    assert got["level_usd_bn"] is None
    assert "unrecognised units" in got["error"]


# --- independent degradation, the Phase D acceptance gate --------------------

def test_a_dead_series_does_not_blank_the_other_gauge():
    """One failure must never take the section down with it."""
    dead = series("M2SL", None, [], error="HTTPError 500")
    got = mf.m2_regime(dead)
    assert got["error"] == "HTTPError 500" and got["level_usd_bn"] is None

    eq = series("NCBEILQ027S", "Millions of U.S. Dollars",
                [("2026-01-01", 69_511_600.0)], freq="Q")
    gdp = series("GDP", "Billions of Dollars", [("2026-01-01", 31_865.7)], freq="Q")
    assert mf.buffett_indicator(eq, gdp)["ratio_pct"] is not None


def test_an_empty_observation_list_is_an_error_not_a_zero():
    got = mf.m2_regime(series("M2SL", "Billions of Dollars", []))
    assert got["error"] and got["level_usd_bn"] is None


def test_no_api_key_yields_two_errors_and_still_returns_a_block():
    block = mf.build(None)
    assert block["m2"]["error"] and block["buffett"]["error"]
    assert block["forward_profit_note"]


def test_the_forward_profit_gap_is_explained_not_hidden():
    """§7 stays unavailable. The note has to say WHY, or the next reader re-opens it."""
    note = mf.FORWARD_PROFIT_NOTE
    assert "licensed" in note and "not a pinned source" in note


# --- the merge is additive ---------------------------------------------------

def test_merging_never_touches_the_metrics_block(tmp_path):
    """`macro_snapshot.py` owns `metrics`. Overlay-only, same rule as every --update."""
    target = tmp_path / "2026-08-16.json"
    target.write_text(json.dumps({"metrics": {"spy": 1.0}, "breadth": {"p": 2.8}}),
                      encoding="utf-8")
    mf.merge_into({"m2": {"regime": "expanding"}}, target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["metrics"] == {"spy": 1.0}
    assert data["breadth"] == {"p": 2.8}
    assert data["regime"]["m2"]["regime"] == "expanding"


def test_merging_into_a_missing_or_corrupt_file_still_writes(tmp_path):
    fresh = tmp_path / "new.json"
    mf.merge_into({"m2": {}}, fresh)
    assert json.loads(fresh.read_text(encoding="utf-8"))["regime"] == {"m2": {}}

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    mf.merge_into({"m2": {}}, broken)
    assert "regime" in json.loads(broken.read_text(encoding="utf-8"))


@pytest.mark.parametrize("stored,expected", [
    ("abcdef0123456789abcdef0123456789", "abcdef0123456789abcdef0123456789"),
    ('"abcdef0123456789abcdef0123456789"', "abcdef0123456789abcdef0123456789"),
    ("'abcdef0123456789abcdef0123456789'", "abcdef0123456789abcdef0123456789"),
    ("  abcdef0123456789abcdef0123456789  ", "abcdef0123456789abcdef0123456789"),
    ('" abcdef0123456789abcdef0123456789 "', "abcdef0123456789abcdef0123456789"),
    ("", None), ("   ", None), (None, None), ('""', None),
])
def test_the_key_is_cleaned_before_use(stored, expected):
    """A key stored with quotes is 34 characters instead of 32 and FRED answers 400, which
    reads like a revoked key rather than a stray pair of quotes."""
    assert mf.clean_key(stored) == expected


def test_a_quoted_key_would_otherwise_be_the_wrong_length():
    """The failure mode itself, stated as a test so nobody 'simplifies' the strip away."""
    raw = '"' + "a" * 32 + '"'
    assert len(raw) == 34
    assert len(mf.clean_key(raw)) == 32
