"""
A throttled yfinance is not a dead ticker — and the system must be able to tell.

Background (measured 2026-08-17): the weekly prefilter on vmhost1 rejected 76 `.AX`
names with "4/4 core fetches empty", among them Aurizon, Commonwealth Bank, Bank of
Queensland and Beach Energy. All 16 retested from another IP returned complete data
(price, AUD, market cap, history) on the FIRST call. The blackout was a 429 against one
IP, not a property of the tickers or of the ASX.

A throttled yfinance is especially nasty because it answers with an EMPTY FRAME instead
of an error, so `safe()` sees success and every downstream check merely reads "missing".

No network: yf.Ticker is replaced wholesale.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import analyze_ticker as at  # noqa: E402


class _Empty:
    """What a throttled yfinance hands back: a frame that is present but empty."""
    empty = True


class _Full:
    empty = False


class _BlackoutTicker:
    """Every core fetch empty — the 429 signature. Counts its own constructions."""
    built = 0

    def __init__(self, symbol):
        type(self).built += 1
        self.info = {}
        self.balance_sheet = _Empty()
        self.financials = _Empty()
        self.cashflow = _Empty()

    def history(self, *a, **k):
        return _Empty()


@pytest.fixture
def blackout(monkeypatch):
    _BlackoutTicker.built = 0
    slept = []
    monkeypatch.setattr(at, "yf", type("_yf", (), {"Ticker": _BlackoutTicker}))
    monkeypatch.setattr(at.time, "sleep", lambda s: slept.append(s))
    return slept


# --- the counter both the retry loop and the gate must agree on ---------------

def test_a_total_blackout_counts_four():
    assert at.core_fetches_missing({}, _Empty(), _Empty(), _Empty()) == 4


def test_a_healthy_fetch_counts_zero():
    assert at.core_fetches_missing({"x": 1}, _Full(), _Full(), _Full()) == 0


def test_a_missing_frame_is_indistinguishable_from_none():
    assert at.core_fetches_missing({"x": 1}, None, _Full(), _Full()) == 1


def test_one_gap_stays_below_the_limit():
    """A single missing statement is normal for a small non-US listing and must NOT
    trip the gate — that is the difference between thin data and no data."""
    assert at.core_fetches_missing({"x": 1}, None, _Full(), _Full()) < at.CORE_MISSING_LIMIT


# --- the retry itself --------------------------------------------------------

def test_a_blackout_is_retried_before_being_believed(blackout):
    with pytest.raises(at.ThrottleSuspected):
        at.analyze("AZJ.AX", mode="screen")
    assert _BlackoutTicker.built == at.THROTTLE_ATTEMPTS, (
        "each attempt needs a FRESH yf.Ticker — the old one caches the empty frames it "
        "already received and would replay them for ever")
    assert blackout == [at.THROTTLE_BACKOFF_S] * (at.THROTTLE_ATTEMPTS - 1)


def test_the_error_says_how_many_attempts_it_survived(blackout):
    with pytest.raises(at.ThrottleSuspected, match=r"4/4 core fetches empty after 2"):
        at.analyze("CBA.AX", mode="screen")


# --- the cross-process contract ----------------------------------------------

def test_throttle_is_a_runtimeerror():
    """Callers that catch RuntimeError must keep working — main() and the prefilter
    both did before this class existed."""
    assert issubclass(at.ThrottleSuspected, RuntimeError)


def test_the_class_name_is_the_wire_format():
    """The class NAME is the only thing that crosses the process boundary: main() emits
    `error_type: type(e).__name__` as JSON, and run_prefilter.next_retry_count() matches
    that literal string to decide whether a ticker may be paused. Rename the class
    without updating the prefilter and throttled blue chips start being paused for 30
    days again, silently."""
    assert at.ThrottleSuspected.__name__ == "ThrottleSuspected"
