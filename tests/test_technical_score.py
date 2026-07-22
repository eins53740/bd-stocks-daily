"""
Phase-3 unit tests for the Technical Analysis layer (technical_score.py).

Two groups, both network-free:
  A. Indicator REUSE — feed a fixed in-memory OHLCV fixture through the BD_Finance
     indicator modules (rsi/atr) + the replicated MACD, asserting hand-verified
     values (RSI≈78.17, ATR=2.0, MACD≈2.545, signal≈2.362 on the 40-bar ramp).
  B. Pure scoring logic — technical_score / GO-NO-GO / entry-zone / ATR stop /
     risk level, plus the >=7.0 fundamental gate (verified via subprocess so the
     skip-path is exercised end-to-end).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from technical_score import (  # noqa: E402
    BENCH_BY_SUFFIX,
    assess,
    build_indicators,
    compute_score_components,
    entry_zone,
    go_no_go,
    macd_lines,
    relative_strength,
    risk_level_from_atr_pct,
    stop_loss_from_atr,
    support_resistance,
)


# --------------------------------------------------------------------------- #
# Fixture: deterministic 40-bar ramp. High = close+1, Low = close-1 (TR ≡ 2).  #
# --------------------------------------------------------------------------- #
@pytest.fixture
def ramp_ohlcv() -> pd.DataFrame:
    n = 40
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    prices = [100.0]
    for i in range(1, n):
        step = 1.0 if i % 3 else -0.5
        prices.append(round(prices[-1] + step, 4))
    close = pd.Series(prices, index=idx)
    return pd.DataFrame(
        {"Open": close, "High": close + 1.0, "Low": close - 1.0,
         "Close": close, "Adj Close": close, "Volume": 1000},
        index=idx,
    )


# ----------------------- A. indicator reuse ----------------------- #
def test_reused_indicators_match_hand_values(ramp_ohlcv):
    ind = build_indicators(ramp_ohlcv, bench_close=None)
    # Hand-verified against the BD_Finance modules on this exact fixture.
    assert ind["price"] == 119.5
    assert ind["rsi"] == pytest.approx(78.17, abs=0.05)
    assert ind["atr"] == pytest.approx(2.0, abs=1e-6)
    assert ind["macd"] == pytest.approx(2.5451, abs=0.001)
    assert ind["macd_signal"] == pytest.approx(2.3616, abs=0.001)
    # ATR% = 2.0 / 119.5
    assert ind["atr_pct"] == pytest.approx(2.0 / 119.5, abs=1e-4)


def test_macd_lines_matches_manual_ewm(ramp_ohlcv):
    macd, sig = macd_lines(ramp_ohlcv)
    close = ramp_ohlcv["Adj Close"]
    exp_macd = (close.ewm(span=12, min_periods=12).mean()
                - close.ewm(span=26, min_periods=26).mean())
    exp_sig = exp_macd.ewm(span=9, min_periods=9).mean()
    assert float(macd.dropna().iloc[-1]) == pytest.approx(float(exp_macd.dropna().iloc[-1]))
    assert float(sig.dropna().iloc[-1]) == pytest.approx(float(exp_sig.dropna().iloc[-1]))


def test_support_resistance(ramp_ohlcv):
    sup, res = support_resistance(ramp_ohlcv, lookback=60)
    # Low = close-1, min close is the start area; High = close+1, max at the end.
    assert sup == pytest.approx(float(ramp_ohlcv["Low"].min()))
    assert res == pytest.approx(float(ramp_ohlcv["High"].max()))


# ----------------------- B.1 stop-loss = f(ATR) ----------------------- #
def test_stop_loss_is_function_of_atr():
    # 2x ATR below price
    assert stop_loss_from_atr(100.0, 2.0, mult=2.0) == 96.0
    assert stop_loss_from_atr(100.0, 2.0, mult=1.5) == 97.0
    # Wider ATR -> deeper stop
    assert stop_loss_from_atr(100.0, 5.0, mult=2.0) == 90.0


def test_stop_loss_none_on_bad_input():
    assert stop_loss_from_atr(None, 2.0) is None
    assert stop_loss_from_atr(100.0, None) is None
    assert stop_loss_from_atr(0, 2.0) is None
    assert stop_loss_from_atr(100.0, -1.0) is None


def test_risk_level_buckets():
    assert risk_level_from_atr_pct(0.01) == "Low"
    assert risk_level_from_atr_pct(0.03) == "Med"
    assert risk_level_from_atr_pct(0.06) == "High"
    assert risk_level_from_atr_pct(None) == "Med"


# ----------------------- B.2 relative strength ----------------------- #
def test_relative_strength():
    assert relative_strength(0.20, 0.05) == 0.15
    assert relative_strength(-0.10, 0.05) == -0.15
    assert relative_strength(None, 0.05) is None


# ----------------------- B.3 entry zone ----------------------- #
def test_entry_zone_uses_support_or_sma50():
    # support 95, sma50 92, price 100 -> lower = max floor below price = 95
    ez = entry_zone(price=100.0, support=95.0, sma50=92.0)
    assert ez == [95.0, 100.0]


def test_entry_zone_fallback_when_no_floor_below_price():
    # both floors above price -> 4% fallback band
    ez = entry_zone(price=100.0, support=110.0, sma50=120.0)
    assert ez == [96.0, 100.0]


def test_entry_zone_none_without_price():
    assert entry_zone(None, 95.0, 92.0) is None


# ----------------------- B.4 score components ----------------------- #
def test_score_strong_uptrend_high():
    ind = {
        "price": 120, "sma50": 110, "sma200": 100, "rsi": 60,
        "macd": 2.0, "macd_signal": 1.0, "adx": 35, "rel_strength": 0.12,
        "vol_ratio": 1.6, "breakout": True,
    }
    out = compute_score_components(ind)
    # All sub-scores near max -> technical score should be high (>= 9).
    assert out["technical_score"] >= 9.0
    assert out["components"]["trend"] == 1.0
    assert out["components"]["breakout"] == 1.0


def test_score_downtrend_low():
    ind = {
        "price": 80, "sma50": 90, "sma200": 100, "rsi": 25,
        "macd": -2.0, "macd_signal": -1.0, "adx": 15, "rel_strength": -0.20,
        "vol_ratio": 0.5, "breakout": False,
    }
    out = compute_score_components(ind)
    assert out["technical_score"] <= 3.5
    assert out["components"]["trend"] == 0.0
    assert out["components"]["macd"] == 0.0


# ----------------------- B.5 GO / NO-GO ----------------------- #
def test_go_when_aligned():
    ind = {"price": 120, "sma200": 100, "rsi": 60, "macd": 2.0, "macd_signal": 1.0}
    verdict, reasons = go_no_go(8.0, ind)
    assert verdict == "GO"


def test_no_go_below_sma200():
    ind = {"price": 90, "sma200": 100, "rsi": 60, "macd": 2.0, "macd_signal": 1.0}
    verdict, reasons = go_no_go(8.0, ind)
    assert verdict == "NO-GO"
    assert any("SMA200" in r for r in reasons)


def test_no_go_low_tech_score():
    ind = {"price": 120, "sma200": 100, "rsi": 60, "macd": 2.0, "macd_signal": 1.0}
    verdict, _ = go_no_go(5.5, ind)
    assert verdict == "NO-GO"


def test_no_go_overbought():
    ind = {"price": 120, "sma200": 100, "rsi": 85, "macd": 2.0, "macd_signal": 1.0}
    verdict, reasons = go_no_go(8.0, ind)
    assert verdict == "NO-GO"
    assert any("overbought" in r.lower() for r in reasons)


# ----------------------- B.6 assess() end-to-end (pure) ----------------------- #
def test_assess_combined_score_weighting():
    indicators = {
        "price": 120, "sma50": 110, "sma200": 100, "rsi": 60,
        "macd": 2.0, "macd_signal": 1.0, "adx": 35, "rel_strength_6m": 0.12,
        "vol_ratio": 1.6, "breakout": True, "atr": 3.0, "atr_pct": 0.025,
        "support": 112.0,
    }
    out = assess(indicators, fundamental_score=8.0)
    # combined = 0.6*fund + 0.4*tech
    assert out["combined_score"] == pytest.approx(
        round(0.6 * 8.0 + 0.4 * out["technical_score"], 2))
    assert out["go_no_go"] == "GO"
    assert out["risk_level"] == "Med"
    # stop-loss is a [tight, wide] pair, both below price
    sl = out["suggested_stop_loss"]
    assert sl[0] > sl[1]  # 1.5x ATR is shallower (higher) than 2x ATR
    assert sl[1] == 120 - 2 * 3.0
    assert out["entry_zone"][1] == 120


# ----------------------- B.7 extended benchmark map (no network) ----------------------- #
def test_bench_by_suffix_extended_entries():
    # Verified live against yfinance at implementation time (see technical_score
    # comment). ^PSI20 is delisted on Yahoo, hence PSI20.LS for Lisbon.
    expected = {
        ".TW": "^TWII", ".TWO": "^TWII", ".IR": "^ISEQ", ".SS": "000001.SS",
        ".SZ": "399001.SZ", ".KS": "^KS11", ".KQ": "^KQ11", ".NS": "^NSEI",
        ".BO": "^BSESN", ".ST": "^OMX", ".SW": "^SSMI", ".MC": "^IBEX",
        ".MI": "FTSEMIB.MI", ".LS": "PSI20.LS", ".BR": "^BFX", ".OL": "^OSEAX",
        ".CO": "^OMXC25", ".HE": "^OMXH25", ".WA": "WIG20.WA", ".VI": "^ATX",
        ".TO": "^GSPTSE", ".AX": "^AXJO",
    }
    for suffix, sym in expected.items():
        assert BENCH_BY_SUFFIX.get(suffix) == sym, f"{suffix} -> {BENCH_BY_SUFFIX.get(suffix)!r} != {sym!r}"


# ----------------------- B.8 >=7.0 gate via subprocess ----------------------- #
def test_fundamental_gate_skips_below_7(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "technical_score.py"),
         "--ticker", "TEST", "--fundamental-score", "6.5", "--no-persist"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["skipped"] is True
    assert "6.5" in out["reason"]
