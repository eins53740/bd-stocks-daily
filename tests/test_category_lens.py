"""Tests for scripts/category_lens.py (v4.3 wave 3.5).

Network-free: every fixture is synthetic, and the shapes are the ones the real corpus
produced. Several tests exist because a first version got the answer WRONG on live data
and the corrected behaviour has to stay corrected — those are marked in their docstrings
with the ticker that exposed it, so a future reader can re-run the same check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import category_lens as cl  # noqa: E402


# --- helpers ----------------------------------------------------------------
def fin(labels, revenue=None, ebitda=None, fcf=None, net_income=None, source="test"):
    n = len(labels)
    return {"source": source, "annual": {
        "labels": list(labels),
        "revenue": list(revenue) if revenue else [100.0] * n,
        "ebitda": list(ebitda) if ebitda else [None] * n,
        "fcf": list(fcf) if fcf else [None] * n,
        "net_income": list(net_income) if net_income else [None] * n,
    }}


def years(start, n):
    return [f"FY{start + i}" for i in range(n)]


def analysis(**kw):
    base = {"ticker": "TEST", "currency": "USD", "price_current": 100.0,
            "sector": "Technology", "lynch_category": "stalwart",
            "fundamentals": {"book_value": 25.0}, "statements_raw": {}}
    for k, v in kw.items():
        if k in ("fundamentals", "statements_raw") and isinstance(v, dict):
            base[k] = {**base[k], **v} if k == "fundamentals" else v
        else:
            base[k] = v
    return base


# ===================================================================
# numeric primitives
# ===================================================================
def test_booleans_are_not_numbers():
    """`True` scoring as 1.0 would silently turn a flag into a measurement."""
    assert cl._num(True) is None
    assert cl._num(False) is None
    assert cl._num("3.5") == 3.5
    assert cl._num(float("nan")) is None


def test_first_reads_the_latest_of_a_statements_pair():
    assert cl._first([12.0, 9.0]) == 12.0
    assert cl._first([None, 9.0]) is None
    assert cl._first([]) is None


@pytest.mark.parametrize("series,expect", [
    ([1, 2, 3, 4], 0.0),                 # monotone rise has no drawdown
    ([10, 5], 0.5),
    ([10, 5, 20, 10], 0.5),              # peak-to-SUBSEQUENT, not max minus min
    ([1], None),
])
def test_max_drawdown(series, expect):
    assert cl.max_drawdown(series) == expect


def test_max_drawdown_skips_non_positive_peaks():
    """A fraction of a zero or negative peak is not a percentage of anything."""
    assert cl.max_drawdown([0, -5, -10]) == 0.0


def test_down_years_counts_only_material_falls():
    assert cl.down_years([100, 84, 100, 50], threshold=0.15) == 2
    assert cl.down_years([100, 95, 90], threshold=0.15) == 0


def test_percentile_of_places_a_value_in_its_own_history():
    assert cl.percentile_of(10, [1, 2, 3, 10]) == 0.875
    assert cl.percentile_of(1, [1, 2, 3, 10]) == 0.125
    assert cl.percentile_of(5, [1, 2]) is None  # too short to mean anything


# ===================================================================
# positive_window — the AMD defect
# ===================================================================
def test_positive_window_returns_the_longest_positive_run():
    """AMD: six loss years inside a twenty-year EBITDA history produced a 319 %
    'drawdown' and five phantom cycles, because (peak-v)/peak is unbounded below zero."""
    lo, hi = cl.positive_window([1, -2, -1, 1, 2, 3, 4, -1, 5])
    assert (lo, hi) == (3, 7)


def test_positive_window_handles_all_positive_and_all_negative():
    assert cl.positive_window([1, 2, 3]) == (0, 3)
    assert cl.positive_window([-1, -2]) == (0, 0)
    assert cl.positive_window([]) == (0, 0)


def test_positive_window_treats_zero_as_not_positive():
    assert cl.positive_window([0, 0, 5, 6]) == (2, 4)


# ===================================================================
# cycle_episodes — recovery, duration, scale
# ===================================================================
def test_a_textbook_cycle_is_completed():
    eps = cl.cycle_episodes([100, 100, 60, 55, 80, 105])
    assert len(eps) == 1
    assert eps[0]["completed"] is True
    assert eps[0]["fall"] == pytest.approx(0.45)
    assert eps[0]["sustained_years"] >= cl.CYC_FALL_YEARS


def test_a_one_year_write_down_is_not_a_cycle():
    """P&G FY2019: 16.7 -> 9.4 -> 19.3 is the Gillette impairment, and it was being
    counted as a completed 54 % cycle."""
    eps = cl.cycle_episodes([16.7, 16.7, 16.7, 9.4, 19.3, 19.3])
    assert eps and eps[0]["recovered"] is True
    assert eps[0]["sustained_years"] == 1
    assert eps[0]["completed"] is False


def test_a_slow_drift_with_a_late_plunge_is_still_not_a_cycle():
    """The elapsed-time version of this test passed P&G because its peak sat eleven
    years before the impairment. Sustained-trough is the test that holds."""
    vals = [20.3, 18.8, 18.9, 18.7, 16.5, 17.8, 17.4, 14.7, 16.9, 16.5, 16.7, 9.4, 19.3]
    assert not [e for e in cl.cycle_episodes(vals) if e["completed"]]


def test_an_unrecovered_fall_stays_open():
    eps = cl.cycle_episodes([100, 90, 40, 42, 45])
    assert len(eps) == 1
    assert eps[0]["recovered"] is False and eps[0]["completed"] is False


def test_a_collapse_in_the_noise_floor_is_ignored():
    """A 90 % fall from 0.02 to 0.002 in a young company's first reported years."""
    eps = cl.cycle_episodes([0.02, 0.002, 0.002, 0.02, 5.0, 10.0])
    assert not [e for e in eps if e["completed"]]


def test_two_separate_cycles_are_counted_separately():
    vals = [100, 60, 55, 100, 105, 60, 55, 100]
    assert len([e for e in cl.cycle_episodes(vals) if e["completed"]]) == 2


# ===================================================================
# annual_series
# ===================================================================
def test_margins_are_derived_on_the_same_year_index():
    s = cl.annual_series(fin(years(2020, 3), revenue=[100, 200, 400],
                             ebitda=[20, 60, 40], net_income=[10, 20, None]))
    assert s["ebitda_margin"] == [0.2, 0.3, 0.1]
    assert s["net_margin"] == [0.1, 0.1, None]
    assert s["years"] == 3


def test_a_missing_history_is_empty_not_short():
    s = cl.annual_series(None)
    assert s["years"] == 0 and s["labels"] == []


def test_a_zero_revenue_year_does_not_divide():
    s = cl.annual_series(fin(years(2020, 2), revenue=[0, 100], ebitda=[5, 10]))
    assert s["ebitda_margin"] == [None, 0.1]


# ===================================================================
# the cyclical test
# ===================================================================
def test_cyclical_refuses_to_speak_below_the_depth_floor():
    s = cl.annual_series(fin(years(2022, 4), ebitda=[10, 5, 3, 9]))
    f = cl.test_cyclical(s, "Energy")
    assert f["detected"] is None and f["confidence"] == "none"
    assert any("needs" in n for n in f["not_computable"])


def test_cyclical_detects_a_real_cycle():
    rev = [100] * 10
    eb = [30, 32, 34, 12, 10, 20, 33, 35, 36, 37]
    f = cl.test_cyclical(cl.annual_series(fin(years(2016, 10), revenue=rev, ebitda=eb)),
                         "Basic Materials")
    assert f["detected"] is True
    assert f["metrics"]["completed_cycles"] >= 1


def test_cyclical_rejects_a_compounder():
    eb = [10, 12, 14, 16, 19, 22, 26, 30, 35, 41]
    f = cl.test_cyclical(cl.annual_series(fin(years(2016, 10), ebitda=eb)), "Technology")
    assert f["detected"] is False
    assert f["metrics"]["completed_cycles"] == 0


def test_secular_decline_is_named_and_is_not_a_cycle():
    """IBM: EBITDA fell 74 % across the Kyndryl spin and never came back. The first
    version called that cyclical at HIGH confidence."""
    eb = [25, 24, 22, 20, 18, 15, 13, 12, 11, 11]
    f = cl.test_cyclical(cl.annual_series(fin(years(2016, 10), ebitda=eb)), "Technology")
    assert f["secular_decline"] is True
    assert f["detected"] is False
    assert any("secular" in e for e in f["evidence"])


def test_a_recovered_dip_is_never_called_a_secular_decline():
    """NVDA printed 'a secular decline ... regained 552 % of it' — a sentence that
    refutes itself. `recovered`, not `completed`, answers this question."""
    eb = [10, 11, 6, 12, 30, 60, 90]
    f = cl.test_cyclical(cl.annual_series(fin(years(2019, 7), ebitda=eb)), "Technology")
    assert f["secular_decline"] is False


def test_the_peak_earnings_trap_fires_only_on_a_detected_cyclical():
    rev = [100] * 10
    eb = [30, 32, 34, 12, 10, 20, 33, 35, 36, 40]
    f = cl.test_cyclical(cl.annual_series(fin(years(2016, 10), revenue=rev, ebitda=eb)),
                         "Energy")
    assert f["detected"] and f["peak_earnings_warning"] is True
    assert any("LATE-CYCLE" in e for e in f["evidence"])

    grow = [10, 12, 14, 16, 19, 22, 26, 30, 35, 41]
    g = cl.test_cyclical(cl.annual_series(fin(years(2016, 10), revenue=rev, ebitda=grow)),
                         "Technology")
    assert g["peak_earnings_warning"] is False


def test_the_measurement_window_is_reported_when_it_is_not_the_whole_history():
    eb = [-5, -2, 10, 12, 14, 4, 3, 11, 15, 16]
    f = cl.test_cyclical(cl.annual_series(fin(years(2016, 10), ebitda=eb)), "Technology")
    assert f["metrics"]["window"] == "FY2018–FY2025"
    assert f["metrics"]["years_total"] == 10
    assert any("loss years belong to the turnaround test" in e for e in f["evidence"])


def test_the_sector_prior_is_evidence_and_never_the_verdict():
    eb = [10, 12, 14, 16, 19, 22, 26, 30, 35, 41]
    f = cl.test_cyclical(cl.annual_series(fin(years(2016, 10), ebitda=eb)), "Energy")
    assert f["metrics"]["sector_prior"] is True
    assert f["detected"] is False


# ===================================================================
# the turnaround test
# ===================================================================
def test_turnaround_detects_a_loss_to_profit_inflection():
    """adidas: two decades of profit, an FY2023 loss, profit again in FY2024."""
    ni = [900, 950, 1000, -70, 800]
    f = cl.test_turnaround(cl.annual_series(fin(years(2020, 5), net_income=ni)),
                           analysis(altman_zscore=3.4,
                                    fundamentals={"current_ratio": 1.6}))
    assert f["detected"] is True and f["confidence"] == "high"


def test_first_profitability_is_not_a_turnaround():
    """PLTR was flagged beside adidas. One recovered a known earnings power; the other
    reached profitability for the first time. They are not the same underwriting."""
    ni = [-300, -400, -200, -50, 200]
    f = cl.test_turnaround(cl.annual_series(fin(years(2020, 5), net_income=ni)),
                           analysis())
    assert f["detected"] is False
    assert f["metrics"]["first_profitability_only"] == ["net_income"]
    assert any("first profitability" in e for e in f["evidence"])


def test_a_turnaround_on_a_broken_balance_sheet_is_downgraded_not_hidden():
    ni = [900, 950, -70, 800]
    f = cl.test_turnaround(
        cl.annual_series(fin(years(2021, 4), net_income=ni)),
        analysis(altman_zscore=1.1, fundamentals={"current_ratio": 0.7,
                                                  "net_debt_ebitda": 6.0}))
    assert f["detected"] is True and f["confidence"] == "moderate"
    assert len(f["survival_risks"]) == 3


def test_an_old_loss_is_history_not_an_inflection():
    ni = [-100, 50, 60, 70, 80, 90, 100]
    f = cl.test_turnaround(cl.annual_series(fin(years(2018, 7), net_income=ni)),
                           analysis())
    assert f["detected"] is False


def test_turnaround_reports_what_it_could_not_measure():
    f = cl.test_turnaround(cl.annual_series(fin(years(2023, 2), net_income=[1, 2])),
                           analysis())
    assert f["detected"] is None
    assert f["not_computable"]


def test_interest_coverage_is_derived_from_the_statements():
    ni = [900, 950, -70, 800]
    a = analysis(statements_raw={"income": {"operating_income": [500, 400],
                                            "interest_expense": [50, 40]}})
    f = cl.test_turnaround(cl.annual_series(fin(years(2021, 4), net_income=ni)), a)
    assert f["metrics"]["interest_coverage"] == 10.0


# ===================================================================
# the asset-play test
# ===================================================================
def test_pence_quotes_are_normalised_before_dividing():
    """RIO.L: 7927 GBp against a 28.31 GBP book value printed 280x. Every London name
    would have been dismissed for the wrong reason."""
    f = cl.test_asset_play(analysis(currency="GBp", price_current=7927.0,
                                    fundamentals={"book_value": 28.308}))
    assert f["metrics"]["price_to_book"] == pytest.approx(2.80, abs=0.01)
    assert f["metrics"]["price_currency"] == "GBP"


def test_a_unit_mismatch_is_refused_not_published():
    """BRK-B: a B-share quote against an A-share book value, 0.001x."""
    f = cl.test_asset_play(analysis(price_current=500.0,
                                    fundamentals={"book_value": 400000.0}))
    assert f["detected"] is None
    assert f["metrics"]["price_to_book_unreliable"] is True


def test_disagreeing_book_value_paths_are_refused():
    """TSM: a USD ADR quote against TWD book, 82x from one path and 1.9x from the other."""
    a = analysis(price_current=180.0, fundamentals={"book_value": 2.2},
                 statements_raw={"balance": {"stockholders_equity": [3.0e12, None],
                                             "shares": [2.6e10, None]}})
    f = cl.test_asset_play(a)
    assert f["detected"] is None
    assert any("disagrees between sources" in n for n in f["not_computable"])


def test_a_genuine_discount_is_detected():
    """SEM.LS trades at 0.67x book — the corpus's one true asset play."""
    a = analysis(price_current=14.0, fundamentals={"book_value": 21.0},
                 statements_raw={"balance": {"stockholders_equity": [2100.0, None],
                                             "shares": [100.0, None],
                                             "goodwill": [100.0, None]}})
    f = cl.test_asset_play(a)
    assert f["detected"] is True
    assert f["metrics"]["price_to_tangible_book"] == pytest.approx(0.70, abs=0.01)


def test_a_discount_made_of_goodwill_is_not_an_asset_play():
    a = analysis(price_current=95.0, fundamentals={"book_value": 100.0},
                 statements_raw={"balance": {"stockholders_equity": [1000.0, None],
                                             "shares": [10.0, None],
                                             "goodwill_and_intangibles": [850.0, None]}})
    f = cl.test_asset_play(a)
    assert f["detected"] is False
    assert any("TANGIBLE" in e for e in f["evidence"])


def test_negative_tangible_equity_says_so():
    # The two book-value paths must AGREE here (600/10 = 60 = book_value), or the
    # cross-check refuses first and this assertion tests the wrong branch.
    a = analysis(price_current=50.0, fundamentals={"book_value": 60.0},
                 statements_raw={"balance": {"stockholders_equity": [600.0, None],
                                             "shares": [10.0, None],
                                             "goodwill_and_intangibles": [700.0, None]}})
    f = cl.test_asset_play(a)
    assert f["detected"] is False
    assert any("entirely intangible" in e for e in f["evidence"])


def test_the_combined_intangibles_row_is_not_double_counted():
    bal = {"stockholders_equity": [1000.0, None], "shares": [10.0, None],
           "goodwill": [300.0, None], "goodwill_and_intangibles": [400.0, None]}
    f = cl.test_asset_play(analysis(price_current=50.0,
                                    fundamentals={"book_value": 100.0},
                                    statements_raw={"balance": bal}))
    # 1000 - 400 (the combined row wins), never 1000 - 300 - 400.
    assert f["metrics"]["tangible_book_per_share"] == pytest.approx(60.0)


def test_the_catalyst_is_never_claimed():
    for a in (analysis(price_current=14.0, fundamentals={"book_value": 21.0}),
              analysis(price_current=500.0, fundamentals={"book_value": 400000.0})):
        f = cl.test_asset_play(a)
        assert f["catalyst"] is None
        assert "not derivable" in f["catalyst_note"]


# ===================================================================
# assembly
# ===================================================================
def test_the_block_is_overlay_only_and_says_so():
    b = cl.compute(analysis(), None)
    assert b["schema"] == "category_lens/1"
    assert "composite is untouched" in b["mandate_note"]
    assert "scores" not in b and "verdict" not in b


def test_precedence_when_more_than_one_fires():
    """A cyclical at the trough also looks like a turnaround. Cyclical wins, because the
    recovery is the cycle, not management fixing anything."""
    fh = fin(years(2014, 12), revenue=[100] * 12,
             ebitda=[30, 32, 34, 12, 10, 20, 33, 35, 36, 37, 38, 39],
             net_income=[20, 22, 24, -5, -8, 5, 20, 22, 23, 24, 25, 26])
    b = cl.compute(analysis(altman_zscore=3.0), fh)
    assert "cyclical" in b["detected"]
    assert b["primary"] == "cyclical"


def test_disagreement_with_lynch_is_stated_in_words():
    fh = fin(years(2016, 10), revenue=[100] * 10,
             ebitda=[30, 32, 34, 12, 10, 20, 33, 35, 36, 37])
    b = cl.compute(analysis(lynch_category="stalwart"), fh)
    assert b["agrees_with_lynch"] is False
    assert "peak earnings" in (b["disagreement_note"] or "")


def test_the_residual_bucket_is_contradicted_only_when_the_test_actually_ran():
    """`detected is None` means no history was cached. 'The amplitude test finds no
    cycle' would then be a claim about a test that never executed."""
    ran = cl.compute(analysis(lynch_category="cyclical"),
                     fin(years(2016, 10), ebitda=[10, 12, 14, 16, 19, 22, 26, 30, 35, 41]))
    assert ran["agrees_with_lynch"] is False
    assert "finds no cycle" in ran["disagreement_note"]

    did_not_run = cl.compute(analysis(lynch_category="cyclical"), None)
    assert did_not_run["agrees_with_lynch"] is None
    assert "could not run" in did_not_run["disagreement_note"]


def test_no_category_is_a_legitimate_answer():
    b = cl.compute(analysis(), fin(years(2016, 10),
                                   ebitda=[10, 12, 14, 16, 19, 22, 26, 30, 35, 41]))
    assert b["primary"] is None and b["detected"] == []


def test_render_lines_covers_every_category():
    b = cl.compute(analysis(), None)
    text = "\n".join(cl.render_lines(b))
    for key in cl.CATEGORIES:
        assert key in text


def test_compute_is_pure():
    a = analysis()
    fh = fin(years(2016, 10), ebitda=[30, 32, 34, 12, 10, 20, 33, 35, 36, 37])
    before = json.dumps(a, sort_keys=True)
    first = cl.compute(a, fh)
    second = cl.compute(a, fh)
    assert json.dumps(a, sort_keys=True) == before
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_cli_update_merges_the_block(tmp_path, monkeypatch):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(analysis()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["category_lens.py", str(p), "--update",
                                      "--out-dir", str(tmp_path)])
    assert cl.main() == 0
    merged = json.loads(p.read_text(encoding="utf-8"))
    assert merged["category_lens"]["schema"] == "category_lens/1"
    assert merged["ticker"] == "TEST"  # nothing else disturbed


def test_the_doctrine_document_publishes_every_constant():
    """A classifier with unpublished thresholds is not reproducible — the same reason
    docs/STAR_RATINGS.md exists."""
    text = (SCRIPTS.parent / "docs" / "CATEGORIES.md").read_text(encoding="utf-8")
    for const in ("CYC_MIN_YEARS", "CYC_FALL_LEG", "CYC_RECOVERY", "CYC_FALL_YEARS",
                  "CYC_PEAK_FLOOR_FRAC", "CYC_DRAWDOWN", "CYC_PEAK_PERCENTILE",
                  "TURN_MIN_YEARS", "TURN_LOOKBACK", "TURN_ALTMAN_DISTRESS",
                  "ASSET_PB_STRONG", "ASSET_PTB_MAX", "PB_CROSSCHECK_TOL",
                  "PB_PLAUSIBLE_MIN"):
        assert const in text, f"{const} is not published in docs/CATEGORIES.md"
    assert "not a mandate change" in text.lower() or "lens, not a mandate change" in text


def test_a_broken_json_exits_clean(tmp_path, monkeypatch, capsys):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["category_lens.py", str(p)])
    assert cl.main() == 0
    assert "error" in json.loads(capsys.readouterr().out)
