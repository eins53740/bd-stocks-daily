"""Tests for the declarative screeners (v4.3 wave 4.3).

The point of `screeners.yaml` is that a screen becomes a file you can read, diff and
version — presets used to live in browser localStorage: invisible, unshareable, and lost
with the cache. These pin the loader's refusals and the one rule that makes a screen
honest: a missing metric is NOT a failed filter.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_dashboard as bd  # noqa: E402

YAML = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily\screeners.yaml")


def rows():
    return [
        {"ticker": "GOOD", "roic": 0.30, "gross_margin": 0.60, "score": 8.0,
         "gates_passed": 7, "pe": 22.0, "ps": 5.0},
        {"ticker": "BAD", "roic": 0.05, "gross_margin": 0.20, "score": 4.0,
         "gates_passed": 2, "pe": 8.0, "ps": 0.5},
        {"ticker": "THIN", "score": 6.0},          # carries almost nothing
    ]


def screen(**kw):
    base = {"key": "t", "label": "T", "filters": [{"metric": "roic", "op": "gte",
                                                   "value": 0.20}]}
    base.update(kw)
    return base


# --- the loader refuses rather than half-applies -----------------------------
def test_the_shipped_file_parses_and_carries_every_default(tmp_path):
    screens = bd.load_screeners(YAML)
    keys = {s["key"] for s in screens}
    assert {"quality_compounder", "magic_formula", "garp", "buffett_moat",
            "scalable_kings", "dividend_compounder", "net_payout_yield",
            "high_fcf_yield", "deep_value_watch"} <= keys


def test_a_missing_file_is_not_an_error(tmp_path):
    assert bd.load_screeners(tmp_path / "nope.yaml") == []


def test_a_screen_with_an_unknown_operator_is_dropped_not_half_applied(tmp_path):
    """A filter that quietly does nothing is worse than a missing screen, because the
    result still looks like a screen."""
    p = tmp_path / "s.yaml"
    p.write_text("version: 1\nscreeners:\n"
                 "  - {key: bad, label: Bad, filters: [{metric: roic, op: WAT, value: 1}]}\n"
                 "  - {key: ok, label: OK, filters: [{metric: roic, op: gte, value: 0.2}]}\n",
                 encoding="utf-8")
    got = bd.load_screeners(p)
    assert [s["key"] for s in got] == ["ok"]


def test_a_screen_without_filters_is_dropped(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("version: 1\nscreeners:\n  - {key: empty, label: Empty}\n", encoding="utf-8")
    assert bd.load_screeners(p) == []


def test_unreadable_yaml_does_not_take_the_dashboard_down(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("version: 1\nscreeners: [ unclosed\n", encoding="utf-8")
    assert bd.load_screeners(p) == []


# --- the honesty rule --------------------------------------------------------
def test_a_missing_metric_makes_a_row_not_evaluable_never_rejected():
    ok, evaluable = bd.screener_matches({"ticker": "THIN"}, screen())
    assert (ok, evaluable) == (False, False)


def test_not_evaluable_rows_are_counted_separately_from_failures():
    out = bd.apply_screeners(rows(), [screen()])[0]
    assert out["n_pass"] == 1              # GOOD
    assert out["n_not_evaluable"] == 1     # THIN
    assert out["n_rows"] == 3              # BAD simply failed


def test_a_type_mismatch_is_not_evaluable_rather_than_a_crash():
    ok, evaluable = bd.screener_matches({"roic": "n/a"}, screen())
    assert (ok, evaluable) == (False, False)


@pytest.mark.parametrize("op,value,row,expect", [
    ("gte", 0.2, {"roic": 0.3}, True), ("gte", 0.2, {"roic": 0.1}, False),
    ("lte", 12, {"roic": 8}, True), ("lte", 12, {"roic": 20}, False),
    ("eq", "US", {"roic": "US"}, True),
    ("in", ["US", "EU"], {"roic": "EU"}, True),
    ("in", ["US"], {"roic": "EU"}, False),
    ("is_true", None, {"roic": True}, True), ("is_false", None, {"roic": False}, True),
])
def test_every_operator(op, value, row, expect):
    s = screen(filters=[{"metric": "roic", "op": op, "value": value}])
    assert bd.screener_matches(row, s)[0] is expect


def test_results_are_sorted_by_the_declared_key():
    r = [{"ticker": "LO", "roic": 0.21}, {"ticker": "HI", "roic": 0.90}]
    out = bd.apply_screeners(r, [screen(sort={"metric": "roic", "dir": "desc"})])[0]
    assert out["tickers"] == ["HI", "LO"]


def test_sorting_puts_missing_values_last_rather_than_first():
    r = [{"ticker": "A", "roic": 0.30, "pe": None}, {"ticker": "B", "roic": 0.40, "pe": 9}]
    out = bd.apply_screeners(r, [screen(sort={"metric": "pe", "dir": "asc"})])[0]
    assert out["tickers"] == ["B", "A"]


# --- mandate labelling -------------------------------------------------------
def test_the_counter_thesis_screen_is_labelled_and_says_it_is_not_a_buy_list():
    deep = next(s for s in bd.load_screeners(YAML) if s["key"] == "deep_value_watch")
    assert deep["mandate"] == "counter_thesis"
    assert "NOT A BUY LIST" in deep["note"]


def test_every_shipped_screen_declares_a_mandate_and_a_note():
    for s in bd.load_screeners(YAML):
        assert s.get("mandate") in ("core", "adjacent", "counter_thesis")
        assert s.get("note")


def test_the_mandate_survives_into_the_bundle_rows():
    out = bd.apply_screeners(rows(), bd.load_screeners(YAML))
    assert {o["mandate"] for o in out} <= {"core", "adjacent", "counter_thesis"}


# --- the extended metric set -------------------------------------------------
def test_the_three_derived_metrics_are_present_and_named():
    """EBITDA margin, cash-flow/EBITDA and the P/E decision — the three the plan found
    genuinely missing."""
    got = bd.enrich_from_tmp("IBM", "2026-08-15")
    if not got:
        pytest.skip("IBM analysis JSON not on disk")
    assert got["ebitda_margin"] is not None
    assert got["cf_ebitda"] is not None
    # measured: pe_ttm IS pe_ratio rounded, so there is one honest column, not two
    assert "pe" in got and "forward_pe" in got
    assert "pe_ttm" not in got


def test_go_no_go_distinguishes_not_run_from_no():
    """`technical` only populates above the Phase 3.5 fundamentals gate, so the column
    is sparse BY DESIGN and 'not run' must not read as NO-GO."""
    got = bd.enrich_from_tmp("IBM", "2026-08-15")
    if not got:
        pytest.skip("IBM analysis JSON not on disk")
    assert "technical_run" in got and "go_no_go" in got
