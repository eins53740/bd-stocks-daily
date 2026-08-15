"""Tests for the two deterministic halves of /bd-stocks-monitor (v4.3 wave 4.1):
`monitor_alerts.py` (the guardrails, previously prose-only and unenforced) and
`recommendation_ledger.py` (scoring the skill's own calls).

Network-free — the ledger's price lookup is injected.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import monitor_alerts as ma  # noqa: E402
import recommendation_ledger as rl  # noqa: E402

TODAY = date(2026, 8, 15)


def h(**kw):
    base = {"ticker": "TEST", "pe_ratio": 20.0, "sector": "Technology",
            "cost_basis": 100.0, "price": 120.0, "value": 1000.0,
            "purchase_date": "2024-01-15"}
    base.update(kw)
    return base


# ===================================================================
# alerts — a missing number never reads as "in the clear"
# ===================================================================
@pytest.mark.parametrize("fn,kw", [
    (ma.bubble_pe, {"pe_ratio": None}),
    (ma.profit_total, {"cost_basis": None}),
    (ma.profit_total, {"price": None}),
])
def test_a_missing_input_is_not_computable_not_a_pass(fn, kw):
    got = fn(h(**kw))
    assert got["computable"] is False
    assert got["fired"] is None


def test_bubble_pe_fires_above_100():
    assert ma.bubble_pe(h(pe_ratio=140.0))["fired"] is True
    assert ma.bubble_pe(h(pe_ratio=99.0))["fired"] is False


def test_a_negative_pe_is_not_meaningful_rather_than_a_breach():
    got = ma.bubble_pe(h(pe_ratio=-15.0))
    assert got["fired"] is False and "NM" in got["detail"]


def test_sector_relative_needs_both_sides():
    assert ma.sector_relative_pe(h(), None)["computable"] is False
    assert ma.sector_relative_pe(h(pe_ratio=None), 15.0)["computable"] is False


def test_sector_relative_fires_at_three_times_the_median():
    assert ma.sector_relative_pe(h(pe_ratio=46.0), 15.0)["fired"] is True
    assert ma.sector_relative_pe(h(pe_ratio=44.0), 15.0)["fired"] is False


def test_profit_total_fires_above_150_percent():
    assert ma.profit_total(h(cost_basis=100.0, price=260.0))["fired"] is True
    assert ma.profit_total(h(cost_basis=100.0, price=240.0))["fired"] is False


def test_annualised_gain_is_refused_on_a_young_position():
    """A 60 % gain over five weeks annualises to something absurd; printing it beside
    real numbers would discredit the panel."""
    got = ma.profit_annualised(h(purchase_date="2026-07-10", price=160.0), TODAY)
    assert got["computable"] is False
    assert "annualised rate is arithmetic" in got["detail"]


def test_annualised_gain_fires_once_the_position_is_old_enough():
    got = ma.profit_annualised(h(purchase_date="2024-08-15", cost_basis=100.0,
                                 price=260.0), TODAY)
    assert got["computable"] is True and got["fired"] is True
    assert got["value"] == pytest.approx(61.2, abs=1.0)      # 2.6x over ~2 years


def test_a_modest_long_held_gain_does_not_fire():
    got = ma.profit_annualised(h(purchase_date="2020-08-15", cost_basis=100.0,
                                 price=200.0), TODAY)
    assert got["fired"] is False


def test_concentration_uses_the_tighter_limit_for_crypto():
    """7% of the portfolio clears the 20% equity limit but breaches the 5% crypto one."""
    holdings = [h(ticker="BTC-EUR", value=70.0, is_crypto=True),
                h(ticker="A", value=310.0), h(ticker="B", value=310.0),
                h(ticker="C", value=310.0)]
    fired = {(a["kind"], a["ticker"]) for a in ma.concentration(holdings)}
    assert ("crypto_concentration", "BTC-EUR") in fired
    assert not any(k == "concentration" and tk == "BTC-EUR" for k, tk in fired)


def test_a_single_equity_over_twenty_percent_fires():
    holdings = [h(ticker="MSFT", value=300.0), h(ticker="V", value=700.0)]
    fired = {a["ticker"] for a in ma.concentration(holdings)}
    assert fired == {"MSFT", "V"}


def test_concentration_without_values_is_not_computable():
    got = ma.concentration([h(value=None)])
    assert got[0]["computable"] is False


def test_sector_medians_are_derived_and_labelled_as_a_proxy():
    block = ma.evaluate([h(ticker="A", pe_ratio=10.0), h(ticker="B", pe_ratio=20.0)],
                        today=TODAY)
    assert "weak proxy" in block["sector_pe_source"]
    supplied = ma.evaluate([h()], sector_pe={"Technology": 15.0}, today=TODAY)
    assert supplied["sector_pe_source"] == "supplied"


def test_supplied_sector_medians_win_over_derived():
    holdings = [h(ticker="A", pe_ratio=60.0), h(ticker="B", pe_ratio=60.0)]
    # derived median would be 60 -> ratio 1.0 -> never fires
    block = ma.evaluate(holdings, sector_pe={"Technology": 15.0}, today=TODAY)
    kinds = {a["kind"] for a in block["fired"]}
    assert "sector_relative_pe" in kinds


def test_the_published_thresholds_travel_with_the_block():
    block = ma.evaluate([h()], today=TODAY)
    assert block["thresholds"]["pe_bubble"] == 100.0
    assert block["thresholds"]["crypto_concentration_pct"] == 5.0


def test_counts_add_up():
    block = ma.evaluate([h(), h(ticker="X", pe_ratio=None)], today=TODAY)
    c = block["counts"]
    assert c["fired"] + c["not_computable"] + c["clear"] == len(block["alerts"])


def test_render_says_so_when_nothing_is_breached():
    # Five holdings so no single one breaches the 20 % concentration limit — a
    # one-holding portfolio is 100 % concentrated and legitimately fires.
    quiet = [h(ticker=f"T{i}", value=200.0) for i in range(5)]
    text = "\n".join(ma.render_lines(ma.evaluate(quiet, today=TODAY)))
    assert "no guardrail breached" in text


# ===================================================================
# ledger
# ===================================================================
def write_log(tmp_path, rows):
    head = "ticker,date,round,mode,verdict,score,gates_passed,price_at_eval,currency\n"
    body = "".join(
        f"{r['ticker']},{r['date']},1,deep,{r['verdict']},{r.get('score', 7)},5,"
        f"{r.get('price', 100)},{r.get('ccy', 'USD')}\n" for r in rows)
    (tmp_path / rl.LOG).write_text(head + body, encoding="utf-8")
    return tmp_path


def test_rows_without_an_entry_price_are_counted_not_dropped_silently(tmp_path):
    (tmp_path / rl.LOG).write_text(
        "ticker,date,verdict,price_at_eval,currency\n"
        "MSFT,2026-05-01,invest,100,USD\n"
        "AAPL,2026-05-01,invest,,USD\n", encoding="utf-8")
    block = rl.build(tmp_path, today=TODAY)
    assert block["coverage"] == {"rows": 2, "with_entry_price": 1, "without_entry_price": 1}


def test_a_unit_mismatch_is_excluded_rather_than_averaged_in():
    """The first live run printed a mean of +601% for `invest` against a median of
    +4.63%, and every outlier was a London name: _log.csv stores GBP, yfinance answers
    in pence. One such row destroys a class mean."""
    call = {"ticker": "RR.L", "date": date(2026, 7, 22), "verdict": "invest",
            "score": 7.0, "price_at_eval": 13.92, "currency": "GBP"}
    got = rl.score_call(call, 1541.0, today=TODAY)
    assert got["return_pct"] is None
    assert got["unit_suspect"] is True
    assert "not a return" in got["unit_note"]


def test_a_large_but_plausible_return_is_kept():
    call = {"ticker": "TEAM", "date": date(2026, 6, 1), "verdict": "invest",
            "score": 7.0, "price_at_eval": 81.55, "currency": "USD"}
    got = rl.score_call(call, 162.22, today=TODAY)
    assert got["return_pct"] == pytest.approx(98.9, abs=0.2)
    assert got["unit_suspect"] is False


def test_excess_is_measured_over_the_same_window_as_the_call():
    call = {"ticker": "X", "date": date(2026, 6, 1), "verdict": "invest", "score": 7.0,
            "price_at_eval": 100.0, "currency": "USD"}
    got = rl.score_call(call, 110.0, bench_then=200.0, bench_now=210.0, today=TODAY)
    assert got["return_pct"] == 10.0
    assert got["benchmark_return_pct"] == 5.0
    assert got["excess_pct"] == 5.0


def test_the_headline_spread_is_a_median_not_a_mean():
    """On a few dozen calls over a few months one runaway name owns the mean — the same
    reason the fair-price anchor switched to a median under wide dispersion."""
    scored = [rl.score_call({"ticker": f"B{i}", "date": date(2026, 6, 1),
                             "verdict": "invest", "score": 8.0,
                             "price_at_eval": 100.0, "currency": "USD"},
                            price, today=TODAY)
              for i, price in enumerate([105.0, 106.0, 400.0])]
    scored += [rl.score_call({"ticker": f"R{i}", "date": date(2026, 6, 1),
                              "verdict": "reject", "score": 3.0,
                              "price_at_eval": 100.0, "currency": "USD"},
                             price, today=TODAY)
               for i, price in enumerate([99.0, 98.0, 97.0])]
    block = rl.summarise(scored, TODAY)
    assert block["invest_minus_reject_pct"] == pytest.approx(8.0, abs=0.1)   # 6 - (-2)
    assert block["invest_minus_reject_mean_pct"] > 100                        # skewed
    assert "median spread" in block["spread_note"]


def test_a_thin_class_is_flagged_rather_than_quietly_averaged():
    scored = [rl.score_call({"ticker": "A", "date": date(2026, 6, 1), "verdict": "great",
                             "score": 9.0, "price_at_eval": 100.0, "currency": "USD"},
                            120.0, today=TODAY)]
    block = rl.summarise(scored, TODAY)
    assert block["by_verdict"]["great"]["thin"] is True
    assert block["invest_minus_reject_pct"] is None


def test_annualisation_is_refused_on_a_short_window():
    scored = [rl.score_call({"ticker": "A", "date": date(2026, 6, 1), "verdict": "invest",
                             "score": 8.0, "price_at_eval": 100.0, "currency": "USD"},
                            108.0, today=TODAY)]
    block = rl.summarise(scored, TODAY)
    assert block["annualised"] is False
    assert "turns a few months of noise" in block["annualise_refused_reason"]


def test_the_block_says_it_is_not_the_g1_backtest():
    block = rl.summarise([], TODAY)
    assert "NOT the G1" in block["not_a_backtest"]


def test_the_ledger_runs_with_no_price_source_at_all(tmp_path):
    write_log(tmp_path, [{"ticker": "MSFT", "date": "2026-05-01", "verdict": "invest"}])
    block = rl.build(tmp_path, None, today=TODAY)
    assert block["calls_total"] == 1 and block["calls_scored"] == 0


def test_an_injected_lookup_scores_the_calls(tmp_path):
    write_log(tmp_path, [
        {"ticker": "MSFT", "date": "2026-05-01", "verdict": "invest", "price": 100},
        {"ticker": "XYZ", "date": "2026-05-01", "verdict": "reject", "price": 100}])
    prices = {"MSFT": 130.0, "XYZ": 90.0}

    def lookup(t, _when):
        return prices[t], 200.0, 210.0

    block = rl.build(tmp_path, lookup, today=TODAY)
    assert block["by_verdict"]["invest"]["mean_return_pct"] == 30.0
    assert block["by_verdict"]["reject"]["mean_return_pct"] == -10.0
    assert block["by_verdict"]["invest"]["mean_excess_pct"] == 25.0


def test_a_failing_lookup_does_not_abort_the_run(tmp_path):
    write_log(tmp_path, [{"ticker": "MSFT", "date": "2026-05-01", "verdict": "invest"}])

    def boom(_t, _w):
        raise RuntimeError("network down")

    block = rl.build(tmp_path, boom, today=TODAY)
    assert block["calls_total"] == 1 and block["calls_scored"] == 0


def test_render_lines_lead_with_coverage_and_the_spread(tmp_path):
    write_log(tmp_path, [{"ticker": "MSFT", "date": "2026-05-01", "verdict": "invest"}])
    text = "\n".join(rl.render_lines(rl.build(tmp_path, None, today=TODAY)))
    assert "carry an entry price" in text and "spread" in text


# ===================================================================
# the monitor page + the skill contract
# ===================================================================
MONITOR = SCRIPTS.parent.parent / "bd-stocks-monitor"
sys.path.insert(0, str(MONITOR / "scripts"))
import monitor_report as mr  # noqa: E402


def test_every_panel_has_a_not_available_state():
    page = mr.render({}, TODAY)
    for phrase in ("alerts not available", "ledger not available",
                   "no benchmark rows supplied", "crisis replay not available"):
        assert phrase in page


def test_a_clean_portfolio_says_so_rather_than_showing_an_empty_table():
    quiet = [h(ticker=f"T{i}", value=200.0) for i in range(5)]
    page = mr.render({"alerts": ma.evaluate(quiet, today=TODAY)}, TODAY)
    assert "No guardrail breached" in page


def test_the_page_prints_the_threshold_beside_the_breach():
    page = mr.render({"alerts": ma.evaluate([h(ticker="A", pe_ratio=140.0, value=100.0),
                                             h(ticker="B", value=900.0)], today=TODAY)},
                     TODAY)
    assert "bubble_pe" in page and "100.0" in page


def test_the_survivorship_caveat_is_on_the_page_not_only_in_the_docs():
    page = mr.render({"crisis": {"episodes": [], "proxy_rules": ["x"]}}, TODAY)
    assert "Survivorship caveat" in page
    assert "chosen with hindsight" in page


def test_the_benchmark_panel_names_its_sources():
    rows = [{"label": "PT inflation (HICP)", "value_pct": None, "source": "ECB SDW",
             "note": "not available"}]
    page = mr.render({"benchmarks": rows}, TODAY)
    assert "ECB SDW" in page and "not available" in page


def test_the_ledger_panel_says_it_is_not_a_backtest(tmp_path):
    write_log(tmp_path, [{"ticker": "MSFT", "date": "2026-05-01", "verdict": "invest"}])
    page = mr.render({"ledger": rl.build(tmp_path, None, today=TODAY)}, TODAY)
    assert "NOT the G1" in page


def test_the_page_states_it_is_read_only_over_the_workbook():
    assert "never writes to the workbook" in mr.render({}, TODAY)


def test_the_disclaimer_is_present():
    assert "not investment advice" in mr.render({}, TODAY)


class TestMonitorSkillContract:
    """The skill file is the deliverable; these pin the promises that are easy to lose."""

    @pytest.fixture(scope="class")
    def skill(self):
        return (MONITOR / "SKILL.md").read_text(encoding="utf-8")

    def test_it_promises_never_to_write_to_the_workbook(self, skill):
        assert "NEVER writes to `Patrimonio BD.xlsx`" in skill
        assert "byte-identical" in skill

    def test_it_reuses_the_existing_workbook_reader(self, skill):
        assert "patrimonio.workbook" in skill or "from patrimonio import workbook" in skill
        assert "Do not re-implement" in skill

    def test_it_names_a_source_for_every_series_yfinance_cannot_provide(self, skill):
        for src in ("ECB SDW", "FRED"):
            assert src in skill
        assert "never an estimate" in skill

    def test_the_crisis_replay_carries_proxy_rules_and_the_caveat(self, skill):
        assert "proxy rule" in skill.lower()
        assert "Survivorship caveat" in skill

    def test_it_refuses_to_annualise_short_windows(self, skill):
        assert "365" in skill and "annualis" in skill.lower()

    def test_the_scheduled_task_is_path_indirect(self, skill):
        assert "BD_SKILLS_ROOT" in skill
        assert "plugin-cache" in skill or "plugin cache" in skill

    def test_it_states_it_is_not_the_g1_backtest(self, skill):
        assert "G1" in skill and "2026-10-17" in skill

    def test_it_keeps_the_plaintext_email_twin(self, skill):
        assert "text/plain" in skill
