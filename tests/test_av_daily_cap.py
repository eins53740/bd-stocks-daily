"""Alpha Vantage daily-cap handling — the per-IP finding of 2026-08-15.

MEASURED, not assumed: burning one AV key to its 25/day limit and then probing four
other, previously-working keys got all four refused by name, within seconds, from this
machine. The free cap is enforced against the source IP. Two consequences these tests
lock in:

  1. A daily-cap refusal must NOT be retried. The old code retried every refusal
     identically, spending 20 s and a second counted call per endpoint to receive the
     same refusal — against an allowance that was already gone machine-wide.
  2. A per-minute throttle must STILL be retried, because that one does clear.

The classifier decides which, so it is tested on AV's real message text rather than a
paraphrase.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import financial_history as fh  # noqa: E402

# The verbatim refusal AV returned on 2026-08-15 once the IP's allowance was spent.
DAILY_MSG = {
    "Note": ("We have detected your API key as EQMU1JB8VIFTL1RH and our standard API "
             "rate limit is 25 requests per day. Please visit "
             "https://www.alphavantage.co/premium/ if you would like to target a "
             "higher API call frequency.")
}
RATE_MSG = {
    "Note": ("Thank you for using Alpha Vantage! Our standard API call frequency is "
             "5 calls per minute and 500 calls per day.")
}


class TestRefusalClassifier:
    def test_the_real_daily_cap_message_is_classified_daily(self):
        assert fh._av_refusal_kind(DAILY_MSG) == "daily"

    def test_a_per_minute_note_is_classified_rate(self):
        # Note this message also contains "calls per day" for the 500/day figure, but
        # the phrase that matters is "requests per day" in the refusal above. Guard the
        # discrimination explicitly -- getting this backwards would disable the retry
        # for genuine transient throttles.
        assert fh._av_refusal_kind(RATE_MSG) == "rate"

    def test_information_key_is_read_as_well_as_note(self):
        assert fh._av_refusal_kind(
            {"Information": "... 25 requests per day ..."}) == "daily"

    @pytest.mark.parametrize("payload", [
        {"quarterlyReports": []}, None, "", 42, {"Note": ""},
    ])
    def test_non_refusals_classify_as_none(self, payload):
        assert fh._av_refusal_kind(payload) is None

    def test_is_throttled_keeps_its_old_contract(self):
        """_av_is_throttled is still consumed by fetch_alphavantage's logging."""
        assert fh._av_is_throttled(DAILY_MSG) is True
        assert fh._av_is_throttled(RATE_MSG) is True
        assert fh._av_is_throttled({"quarterlyReports": []}) is False
        assert fh._av_is_throttled(None) is False


class TestRetryPolicy:
    def test_a_daily_cap_is_never_retried_and_never_sleeps(self, monkeypatch):
        """The whole point: no second call, no 20 s wait, on an allowance that is gone."""
        calls_made = []
        monkeypatch.setattr(fh, "_http_get_json",
                            lambda url: calls_made.append(url) or DAILY_MSG)
        slept = []
        payload, calls = fh._av_get_with_retry("http://x", "CASH_FLOW",
                                               sleep=slept.append)
        assert calls == 1, "a daily cap must cost exactly one call, not two"
        assert slept == [], "sleeping cannot clear a cap that resets at midnight"
        assert fh._av_refusal_kind(payload) == "daily"

    def test_a_per_minute_throttle_is_still_retried(self, monkeypatch):
        """Regression guard: the fix must not disable the retry that fixed the
        all-None FCF column (see cache_has_fcf)."""
        responses = [RATE_MSG, {"quarterlyReports": [{"x": 1}]}]
        monkeypatch.setattr(fh, "_http_get_json", lambda url: responses.pop(0))
        slept = []
        payload, calls = fh._av_get_with_retry("http://x", "CASH_FLOW",
                                               sleep=slept.append)
        assert payload == {"quarterlyReports": [{"x": 1}]}
        assert calls == 2
        assert slept == [fh.AV_THROTTLE_DELAY_S]


class TestFetchShortCircuit:
    def _patch(self, monkeypatch, responses):
        seen = []

        def fake(url):
            seen.append(url)
            return responses.pop(0)

        monkeypatch.setattr(fh, "_http_get_json", fake)
        monkeypatch.setattr(fh, "_default_sleep", lambda s: None)
        return seen

    def test_a_capped_income_call_skips_the_cashflow_call_entirely(self, monkeypatch):
        """Firing CASH_FLOW after INCOME_STATEMENT was refused for the day is a
        guaranteed-useless request, and on a per-IP cap it cannot succeed."""
        seen = self._patch(monkeypatch, [DAILY_MSG])
        hist, calls, capped = fh.fetch_alphavantage("IBM", "KEY")
        assert hist is None
        assert capped is True
        assert calls == 1, "one refused call, not two"
        assert len(seen) == 1 and "INCOME_STATEMENT" in seen[0]
        assert not any("CASH_FLOW" in u for u in seen)

    def test_a_healthy_fetch_reports_not_capped(self, monkeypatch):
        income = {
            "quarterlyReports": [{
                "fiscalDateEnding": "2026-03-31", "totalRevenue": "100",
                "ebitda": "20", "netIncome": "10", "reportedCurrency": "USD",
            }],
            "annualReports": [{
                "fiscalDateEnding": "2025-12-31", "totalRevenue": "400",
                "ebitda": "80", "netIncome": "40", "reportedCurrency": "USD",
            }],
        }
        cashflow = {"quarterlyReports": [{
            "fiscalDateEnding": "2026-03-31",
            "operatingCashflow": "30", "capitalExpenditures": "5",
        }], "annualReports": []}
        self._patch(monkeypatch, [income, cashflow])
        hist, calls, capped = fh.fetch_alphavantage("IBM", "KEY")
        assert capped is False
        assert calls == 2
        assert hist is not None and hist["source"] == "alphavantage"


def test_saturating_the_budget_blocks_every_later_node():
    """The cross-process half of the fix.

    Each pipeline node is its own process, so an in-memory flag cannot travel between
    financial_history and valuation_bands. The budget FILE is the only shared channel;
    saturating it is what makes one node's discovery of the cap stop the others from
    re-discovering it one wasted call at a time.
    """
    today = "2026-08-15"
    budget = {"date": today, "calls": 4}
    assert fh.av_budget_allows(budget, today, fh.AV_DAILY_LIMIT) is True
    budget["calls"] = max(budget["calls"], fh.AV_DAILY_LIMIT)   # what main() does
    assert fh.av_budget_allows(budget, today, fh.AV_DAILY_LIMIT) is False
    # ...and it must still clear at the date rollover, or the skill would be wedged
    # off Alpha Vantage permanently.
    assert fh.av_budget_allows(budget, "2026-08-16", fh.AV_DAILY_LIMIT) is True
