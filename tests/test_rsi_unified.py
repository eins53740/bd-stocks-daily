"""R18: analyze_ticker's RSI must be the SAME indicator as technical_score's.

It used to compute Cutler's RSI (`rolling(14).mean()`) and publish it as `rsi_14`, while
technical_score published BD_Finance's Wilder-style value as `technical.rsi`. On ROVI.MC
2026-08-17 the two read 32.6 and 48.7 -- both internally correct, and near-oversold versus
neutral is not a rounding difference.

The formula is checked here against a replica of BD_Finance/technical/rsi.py rather than
against an import of it: importing that module executes its top level, which calls
yf.download() for AMZN, GOOG and MSFT at 5-minute resolution, and a network-free suite cannot
do that. technical_score.py imports it for real and defends by stubbing yfinance first, so
the pipeline itself makes no such call.
"""
import numpy as np
import pandas as pd
import pytest


def _synthetic_close(n=300, seed=7):
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0005, 0.02, n)
    return pd.Series(100 * np.exp(np.cumsum(steps)))


def analyze_ticker_rsi(close):
    """The formula as it now stands in analyze_ticker.py (kept in sync by these asserts)."""
    delta = close.diff()
    ag = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14).mean()
    al = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14).mean()
    last_gain, last_loss = ag.iloc[-1], al.iloc[-1]
    if not (last_loss and last_loss > 0 and last_loss == last_loss):
        return None
    return float(100 - (100 / (1 + last_gain / last_loss)))


def bd_finance_rsi(close, n=14):
    """Verbatim replica of BD_Finance/technical/rsi.py -- the authoritative implementation."""
    change = close - close.shift(1)
    gain = pd.Series(np.where(change >= 0, change, 0), index=close.index)
    loss = pd.Series(np.where(change < 0, -1 * change, 0), index=close.index)
    ag = gain.ewm(alpha=1 / n, min_periods=n).mean()
    al = loss.ewm(alpha=1 / n, min_periods=n).mean()
    return float(100 - (100 / (1 + ag.iloc[-1] / al.iloc[-1])))


def cutler_rsi(close):
    """The OLD analyze_ticker formula, kept so the divergence stays visible."""
    d = close.diff()
    up = d.clip(lower=0).rolling(14).mean()
    dn = -d.clip(upper=0).rolling(14).mean()
    return float(100 - (100 / (1 + up.iloc[-1] / dn.iloc[-1])))


@pytest.mark.parametrize("seed", [1, 7, 42, 2026])
def test_analyze_ticker_rsi_matches_the_authoritative_one(seed):
    close = _synthetic_close(seed=seed)
    assert analyze_ticker_rsi(close) == pytest.approx(bd_finance_rsi(close), abs=1e-9)


def test_the_two_methods_genuinely_disagree():
    """Guards against the fix being vacuous: if Cutler and Wilder agreed, there was no bug.
    Measured live on 2026-08-18: ROVI.MC 30.77 vs 50.96, MSFT 77.33 vs 63.01."""
    close = _synthetic_close(seed=7)
    assert abs(cutler_rsi(close) - bd_finance_rsi(close)) > 1.0


def test_the_shipped_source_uses_the_ewm_form_and_says_which():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "scripts" / "analyze_ticker.py").read_text(encoding="utf-8")
    assert "ewm(alpha=1 / 14, min_periods=14)" in src, "must be the Wilder-style EWM"
    assert 'delta.clip(lower=0).rolling(14).mean()' not in src, "the Cutler form must be gone"
    assert '"rsi_14_method"' in src, "the method has to be named in the JSON"


def test_flat_series_yields_none_not_a_divide_by_zero():
    flat = pd.Series([50.0] * 100)
    assert analyze_ticker_rsi(flat) is None
