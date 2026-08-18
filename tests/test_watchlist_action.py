"""Tests for the R17 fix: watchlist.py reports its own writes into the analysis JSON.

The defect was not a wrong number -- it was a stated action that did not happen, which no
numeric check can catch. These tests pin the data channel that replaces the guess.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import watchlist as wl  # noqa: E402
import render_report as rr  # noqa: E402


def _result(**kw):
    base = {"ticker": "TEST", "action": "absent", "eligible": False, "held": False,
            "score": 7.5, "mos_class": "rich", "target": 100.0, "fair_low": 90.0,
            "currency": "EUR", "watchlist_size": 4, "warnings": []}
    base.update(kw)
    return base


# --- explain_action: every non-membership path names WHICH predicate bit --------------

def test_kept_reads_as_on_the_list_with_the_alert_price():
    on, why = wl.explain_action(_result(action="kept"))
    assert on is True
    assert "100.0" in why and "EUR" in why


def test_below_score_bar_says_so():
    on, why = wl.explain_action(_result(score=6.12))
    assert on is False
    assert "6.12" in why and "7.0" in why


def test_held_names_are_excluded_explicitly():
    on, why = wl.explain_action(_result(held=True))
    assert on is False and "already held" in why


def test_not_rich_names_name_the_mos_class():
    on, why = wl.explain_action(_result(mos_class="fair"))
    assert on is False and "fair" in why and "rich" in why


def test_missing_target_is_stated_not_hidden():
    on, why = wl.explain_action(_result(target=None))
    assert on is False and "fair_value_range.mid" in why


def test_removed_is_distinct_from_never_added():
    on, why = wl.explain_action(_result(action="removed"))
    assert on is False and "removed" in why


def test_rovi_regression_the_report_would_have_said_not_on_the_list():
    """ROVI.MC 2026-08-17: composite 7.25, and the report claimed it was already listed."""
    on, why = wl.explain_action(_result(ticker="ROVI.MC", action="absent", score=7.25,
                                       mos_class="fair", target=50.82, currency="EUR"))
    assert on is False
    assert "not on the watch-list" in why


# --- the writeback ------------------------------------------------------------------

def test_writeback_adds_one_additive_key(tmp_path):
    jp = tmp_path / "2026-08-17_TEST.json"
    data = {"ticker": "TEST", "currency": "EUR", "schema_version": "2.2"}
    jp.write_text(json.dumps(data), encoding="utf-8")

    wl.write_action_to_analysis(str(jp), data, _result(action="kept"))
    back = json.loads(jp.read_text(encoding="utf-8"))

    assert back["schema_version"] == "2.2", "overlay-only: schema untouched"
    wa = back["watchlist_action"]
    assert wa["on_list"] is True
    assert wa["target"] == 100.0
    assert "100.0" in wa["reason"]


def test_writeback_never_raises_on_an_unwritable_path(tmp_path):
    """Bookkeeping must not be able to fail a run."""
    bad = tmp_path / "no_such_dir" / "x.json"
    wl.write_action_to_analysis(str(bad), {"ticker": "TEST"}, _result())  # must not raise


def test_run_writes_the_key_only_with_update(tmp_path):
    jp = tmp_path / "2026-08-17_TEST.json"
    jp.write_text(json.dumps({
        "ticker": "TEST", "currency": "EUR",
        "scores": {"composite": 7.5},
        "intrinsic_value": {"mos_class": "rich", "mos_pct": -30,
                            "fair_value_range": {"low": 90, "mid": 100, "high": 110}},
    }), encoding="utf-8")

    wl.run(str(jp), tmp_path, "2026-08-17", do_update=False)
    assert "watchlist_action" not in json.loads(jp.read_text(encoding="utf-8"))

    wl.run(str(jp), tmp_path, "2026-08-17", do_update=True)
    assert json.loads(jp.read_text(encoding="utf-8"))["watchlist_action"]["on_list"] is True


# --- the renderer -------------------------------------------------------------------

def test_renderer_says_nothing_without_the_block():
    assert rr.build_watchlist_state({}) == "", "no block => no claim in either direction"


def test_renderer_prints_the_recorded_reason():
    html = rr.build_watchlist_state({"watchlist_action": {
        "on_list": False, "reason": "not on the watch-list: composite 7.25 is below the 7.0 bar"}})
    assert "7.25" in html and "not narrated" in html


def test_renderer_marks_membership_with_a_star():
    html = rr.build_watchlist_state({"watchlist_action": {
        "on_list": True, "reason": "on the watch-list, alert at 50.82 EUR"}})
    assert "⭐" in html and "50.82" in html


# --- the prompt contract ------------------------------------------------------------

def test_style_rules_forbid_asserting_side_effects():
    txt = (Path(__file__).resolve().parents[1] / "prompts" / "_style_rules.md").read_text(encoding="utf-8")
    assert "NEVER ASSERT A SIDE EFFECT" in txt
    assert "_watchlist.csv" in txt, "the ban names the exact fabrication that happened"
