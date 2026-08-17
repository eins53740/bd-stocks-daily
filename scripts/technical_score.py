"""
technical_score.py — Technical Analysis layer for fundamentally-strong tickers.

Phase 3 of the bd-stocks-daily v3 upgrade. Runs ONLY for tickers whose
Fundamental Score >= 7.0 (a quality gate — we only time entries on names that
already cleared the fundamental bar). For those, it fetches ~1y+ of daily OHLCV
(yfinance) and computes a Technical Score (0-10) + GO/NO-GO timing verdict,
entry zone, ATR-based stop-loss and risk level.

Indicator math is REUSED from BD_Finance/technical/* (no TA-Lib, pure pandas):
  rsi.rsi(DF,n=14), atr.atr(DF,n=14), adx.adx(DF,n=20),
  blnr_bnd.Boll_Band(DF,n=14), max_dd_calmar.max_dd(DF).
Those modules run yfinance downloads at *import* time, so before importing them
we inject a stub `yfinance` into sys.modules whose .download() returns a tiny
valid OHLCV frame — the module-level demo loops then run harmlessly and we get
the real indicator functions. MACD's `macd_df` is a *nested* function inside
macd.macd() and cannot be imported; its exact EWM formula is replicated verbatim
in macd_lines() below (span 12/26/9 on Adj Close — identical to macd.py).

Outputs (like analyze_ticker.py): one JSON blob on stdout. Also persists a copy
to <StocksDaily>/_technical/<TICKER>.json so anything offline (the stdlib-only
dashboard) can read it without re-fetching. The deep-report flow writes the
scalar fields into report frontmatter; build_dashboard.py reads them from there.

Args:
  --ticker            required, e.g. ASML.AS
  --fundamental-score required, float; <7.0 -> clean skip (exit 0)
  --analysis-json     optional path to analyze_ticker.py JSON (reuse price/score)
  --benchmark         optional, default auto (^GSPC for US, region index otherwise)
  --no-persist        optional, skip writing _technical/<TICKER>.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import types
import warnings
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 on Windows console
for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FUND_GATE = 7.0  # only score technicals for fundamentally-strong names
STOCKSDAILY = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
TECH_DIR = STOCKSDAILY / "_technical"

# Default benchmark per region/exchange suffix (relative-strength proxy).
BENCH_BY_SUFFIX = {
    ".AS": "^AEX", ".PA": "^FCHI", ".DE": "^GDAXI", ".MC": "^IBEX",
    ".LS": "PSI20.LS", ".MI": "FTSEMIB.MI", ".L": "^FTSE",
    ".SW": "^SSMI", ".ST": "^OMX", ".CO": "^OMXC25", ".HE": "^OMXH25",
    ".BR": "^BFX", ".AX": "^AXJO", ".TO": "^GSPTSE", ".HK": "^HSI",
    ".T": "^N225",
    # Extended coverage — all verified live against yfinance. ^PSI20 is delisted
    # on Yahoo (use PSI20.LS); ^OMX resolves (kept over the thin ^OMXS30).
    ".OL": "^OSEAX", ".WA": "WIG20.WA", ".VI": "^ATX", ".IR": "^ISEQ",
    ".TW": "^TWII", ".TWO": "^TWII", ".SS": "000001.SS", ".SZ": "399001.SZ",
    ".KS": "^KS11", ".KQ": "^KQ11", ".NS": "^NSEI", ".BO": "^BSESN",
    # ---- v4.3 expansion, every symbol re-verified live 2026-08-15 ----
    # .JP is an alias of .T for Tokyo. It had metadata but no benchmark, so any
    # ticker using it was charted against the US default while priced in JPY --
    # found by the cross-table consistency test the moment that test existed.
    ".JP": "^N225",
    ".SI": "^STI", ".SA": "^BVSP", ".MX": "^MXX", ".JK": "^JKSE",
    # Frankfurt and Hanover are secondary German venues quoting companies whose
    # primary line is Xetra, so the DAX is the right reference for both.
    ".F": "^GDAXI", ".HA": "^GDAXI",
    # TSX Venture's own index (^JX) is DELISTED on Yahoo -- measured, 404. The
    # large-cap composite is the only working proxy, and it understates venture
    # volatility, so .V relative strength reads optimistically. Say so rather than
    # leaving the suffix unmapped and silently benchmarked against the US.
    ".V": "^GSPTSE",
    # Both of these resolve but are THIN: ^TASI.SR returned 5 rows in a month and
    # ^BUX.BD returned 1. They are mapped so the market is not benchmarked against
    # the wrong country, but relative strength from them is not meaningful --
    # markets._MARKET_CAVEATS carries that warning into the report.
    ".SR": "^TASI.SR", ".BD": "^BUX.BD",
}
DEFAULT_BENCH = "^GSPC"  # US / fallback


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Reuse BD_Finance indicator modules (stub yfinance to neutralise import-time  #
# downloads, then import the real pure-pandas functions).                      #
# --------------------------------------------------------------------------- #
_BD_INDICATORS = None  # cached (rsi, atr, adx, Boll_Band, max_dd)


def _import_bd_indicators():
    """
    Resolve BD_Finance/technical/* and return the reused indicator fns.

    Those modules run a yfinance .download() at *import* time (demo loops). To
    neutralise that we temporarily swap in a stub `yfinance` (returns a tiny
    valid OHLCV frame) for the duration of the imports, then RESTORE whatever
    real yfinance was there. Imported once, then cached — so this stub swap
    never races with the real fetch in fetch_ohlcv().
    """
    global _BD_INDICATORS
    if _BD_INDICATORS is not None:
        return _BD_INDICATORS

    # RESOLVED by probing for the package itself, not hardcoded (2026-08-17). The layouts
    # genuinely differ: the laptop keeps BD_Finance under C:\Github\BD\Finance\, vmhost1 under
    # D:\Github\BD\ -- and vmhost1 has no C:\Github at all. With a single C: constant the five
    # imports below raised ModuleNotFoundError on vmhost1, which is the machine that has run
    # the pipeline since the cutover, so PHASE 3.5 (technical score + GO/NO-GO) was failing
    # there in production. Found by running this skill's suite on vmhost1, not on the laptop.
    #
    # The probe is for BD_Finance/technical/rsi.py, i.e. the thing actually imported -- a
    # directory that merely exists proves nothing.
    _parents = (
        Path(os.environ["BD_FINANCE_PARENT"]) if os.environ.get("BD_FINANCE_PARENT") else None,
        Path(r"C:\Github\BD\Finance"),
        Path(r"D:\Github\BD"),
    )
    bd_parent = next(
        (p for p in _parents if p and (p / "BD_Finance" / "technical" / "rsi.py").exists()),
        Path(r"C:\Github\BD\Finance"),
    )
    if str(bd_parent) not in sys.path:
        sys.path.insert(0, str(bd_parent))

    _idx = pd.date_range("2024-01-01", periods=30, freq="D")
    base = np.linspace(10.0, 20.0, 30)
    _df = pd.DataFrame(
        {"Open": base, "High": base + 1, "Low": base - 1,
         "Close": base, "Adj Close": base, "Volume": 1000},
        index=_idx,
    )
    stub = types.ModuleType("yfinance")
    stub.download = lambda *a, **k: _df.copy()  # type: ignore[attr-defined]

    saved = sys.modules.get("yfinance")
    sys.modules["yfinance"] = stub
    try:
        from BD_Finance.technical.rsi import rsi  # noqa: E402
        from BD_Finance.technical.atr import atr  # noqa: E402
        from BD_Finance.technical.adx import adx  # noqa: E402
        from BD_Finance.technical.blnr_bnd import Boll_Band  # noqa: E402
        from BD_Finance.technical.max_dd_calmar import max_dd  # noqa: E402
    finally:
        # Restore real yfinance (or remove the stub) so fetch_ohlcv() gets the
        # genuine module on its `import yfinance`.
        if saved is not None:
            sys.modules["yfinance"] = saved
        else:
            sys.modules.pop("yfinance", None)

    _BD_INDICATORS = (rsi, atr, adx, Boll_Band, max_dd)
    return _BD_INDICATORS


def macd_lines(df: pd.DataFrame, a: int = 12, b: int = 26, c: int = 9):
    """MACD + signal — verbatim copy of macd.macd_df (nested, not importable).
    span a=12 fast, b=26 slow, c=9 signal, on Adj Close."""
    out = df.copy()
    ma_fast = out["Adj Close"].ewm(span=a, min_periods=a).mean()
    ma_slow = out["Adj Close"].ewm(span=b, min_periods=b).mean()
    macd = ma_fast - ma_slow
    signal = macd.ewm(span=c, min_periods=c).mean()
    return macd, signal


# --------------------------------------------------------------------------- #
# Pure scoring logic (unit-tested with an in-memory fixture, no network).      #
# --------------------------------------------------------------------------- #
def _last(series) -> float | None:
    try:
        v = float(series.dropna().iloc[-1])
        return None if math.isnan(v) else v
    except Exception:
        return None


def support_resistance(df: pd.DataFrame, lookback: int = 60) -> tuple[float | None, float | None]:
    """Recent support (min low) / resistance (max high) over `lookback` bars."""
    if df is None or len(df) == 0:
        return None, None
    tail = df.tail(lookback)
    try:
        sup = float(tail["Low"].min())
        res = float(tail["High"].max())
        return sup, res
    except Exception:
        return None, None


def stop_loss_from_atr(price: float, atr_val: float, mult: float = 2.0) -> float | None:
    """ATR-based long stop: price - mult*ATR. Returns None on bad inputs."""
    if price is None or atr_val is None or price <= 0 or atr_val <= 0:
        return None
    return round(price - mult * atr_val, 2)


def risk_level_from_atr_pct(atr_pct: float | None) -> str:
    """ATR as % of price -> Low / Med / High volatility bucket."""
    if atr_pct is None:
        return "Med"
    if atr_pct < 0.02:
        return "Low"
    if atr_pct < 0.04:
        return "Med"
    return "High"


def relative_strength(stock_ret: float | None, bench_ret: float | None) -> float | None:
    """Excess 6m total return vs the benchmark (stock_ret - bench_ret)."""
    if stock_ret is None or bench_ret is None:
        return None
    return round(stock_ret - bench_ret, 4)


def compute_score_components(ind: dict) -> dict:
    """
    Map raw indicators -> seven 0-1 sub-scores, then to a weighted 0-10
    technical score. `ind` keys (all may be None):
      price, sma50, sma200, rsi, macd, macd_signal, adx, rel_strength,
      vol_ratio (recent vol / avg vol), breakout (bool), atr_pct.
    Returns {"components": {...}, "technical_score": float}.
    """
    price = ind.get("price")
    sma50 = ind.get("sma50")
    sma200 = ind.get("sma200")
    rsi = ind.get("rsi")
    macd = ind.get("macd")
    macd_signal = ind.get("macd_signal")
    adx = ind.get("adx")
    rs = ind.get("rel_strength")
    vol_ratio = ind.get("vol_ratio")
    breakout = ind.get("breakout")

    comp: dict[str, float] = {}

    # 1. Trend (price vs SMA50/SMA200, golden cross) — 0..1
    t = 0.5
    if price is not None and sma50 is not None and sma200 is not None:
        t = 0.0
        if price > sma50:
            t += 0.35
        if price > sma200:
            t += 0.35
        if sma50 > sma200:  # golden-cross structure
            t += 0.30
    comp["trend"] = round(t, 3)

    # 2. Momentum (RSI sweet spot 50-70; overbought/oversold penalised) — 0..1
    m = 0.5
    if rsi is not None:
        if 50 <= rsi <= 70:
            m = 1.0
        elif 40 <= rsi < 50:
            m = 0.6
        elif 70 < rsi <= 80:
            m = 0.5
        elif rsi > 80:
            m = 0.2          # overbought
        elif 30 <= rsi < 40:
            m = 0.4
        else:                # < 30 oversold
            m = 0.25
    comp["momentum"] = round(m, 3)

    # 3. MACD (bullish when macd > signal and > 0) — 0..1
    mac = 0.5
    if macd is not None and macd_signal is not None:
        if macd > macd_signal and macd > 0:
            mac = 1.0
        elif macd > macd_signal:
            mac = 0.65
        elif macd < macd_signal and macd < 0:
            mac = 0.0
        else:
            mac = 0.35
    comp["macd"] = round(mac, 3)

    # 4. Trend strength (ADX: >25 strong, >40 very strong, <20 weak) — 0..1
    a = 0.5
    if adx is not None:
        if adx >= 40:
            a = 1.0
        elif adx >= 25:
            a = 0.8
        elif adx >= 20:
            a = 0.5
        else:
            a = 0.3
    comp["adx"] = round(a, 3)

    # 5. Relative strength vs benchmark — 0..1
    r = 0.5
    if rs is not None:
        if rs >= 0.10:
            r = 1.0
        elif rs >= 0.0:
            r = 0.7
        elif rs >= -0.10:
            r = 0.4
        else:
            r = 0.2
    comp["rel_strength"] = round(r, 3)

    # 6. Volume trend (recent vs avg) — 0..1
    v = 0.5
    if vol_ratio is not None:
        if vol_ratio >= 1.5:
            v = 1.0
        elif vol_ratio >= 1.0:
            v = 0.7
        elif vol_ratio >= 0.7:
            v = 0.45
        else:
            v = 0.3
    comp["volume"] = round(v, 3)

    # 7. Breakout (price near/above resistance) — 0..1
    comp["breakout"] = 1.0 if breakout else 0.0

    weights = {
        "trend": 0.25, "momentum": 0.15, "macd": 0.15, "adx": 0.15,
        "rel_strength": 0.15, "volume": 0.10, "breakout": 0.05,
    }
    score01 = sum(comp[k] * w for k, w in weights.items())
    technical_score = round(10.0 * score01, 2)
    return {"components": comp, "technical_score": technical_score}


def go_no_go(technical_score: float, ind: dict) -> tuple[str, list[str]]:
    """
    GO requires: technical_score >= 6.0 AND price above SMA200 (not in a
    structural downtrend) AND RSI not extreme-overbought (<80) AND MACD not
    deeply bearish. Returns ("GO"/"NO-GO", reasons[]).
    """
    reasons: list[str] = []
    price = ind.get("price")
    sma200 = ind.get("sma200")
    rsi = ind.get("rsi")
    macd = ind.get("macd")
    macd_signal = ind.get("macd_signal")

    ok = True
    if technical_score < 6.0:
        ok = False
        reasons.append(f"technical_score {technical_score} < 6.0")
    if price is not None and sma200 is not None and price < sma200:
        ok = False
        reasons.append("price below SMA200 (structural downtrend)")
    if rsi is not None and rsi > 80:
        ok = False
        reasons.append(f"RSI {round(rsi,1)} overbought (>80)")
    if (macd is not None and macd_signal is not None
            and macd < macd_signal and macd < 0):
        ok = False
        reasons.append("MACD deeply bearish (macd<signal<0)")
    if ok:
        reasons.append("trend + momentum + strength aligned")
    return ("GO" if ok else "NO-GO"), reasons


def entry_zone(price: float | None, support: float | None,
               sma50: float | None) -> list[float] | None:
    """
    Entry zone for a long = band between the nearest meaningful support and the
    current price (buy on a pullback toward support / SMA50). Lower bound is the
    higher of support and SMA50 (but never above price); upper bound is price.
    """
    if price is None or price <= 0:
        return None
    floors = [x for x in (support, sma50) if x is not None and 0 < x < price]
    lower = max(floors) if floors else round(price * 0.96, 2)
    return [round(lower, 2), round(price, 2)]


# --------------------------------------------------------------------------- #
# Orchestration (network) — builds the indicator dict from real OHLCV.         #
# --------------------------------------------------------------------------- #
def _total_return(close: pd.Series, bars: int) -> float | None:
    try:
        s = close.dropna()
        if len(s) <= bars:
            return None
        return float(s.iloc[-1] / s.iloc[-bars - 1] - 1.0)
    except Exception:
        return None


def build_indicators(ohlcv: pd.DataFrame, bench_close: pd.Series | None) -> dict:
    """Compute every raw indicator from a real OHLCV frame (Adj Close present)."""
    rsi_fn, atr_fn, adx_fn, boll_fn, max_dd_fn = _import_bd_indicators()

    close = ohlcv["Adj Close"]
    price = _last(close)
    sma50 = _last(close.rolling(50).mean())
    sma200 = _last(close.rolling(200).mean())
    rsi_val = _last(rsi_fn(ohlcv, 14))
    macd_s, sig_s = macd_lines(ohlcv)
    macd_val, sig_val = _last(macd_s), _last(sig_s)
    atr_val = _last(atr_fn(ohlcv, 14))
    adx_val = _last(adx_fn(ohlcv, 20))
    boll = boll_fn(ohlcv, 20)
    try:
        max_dd_1y = round(float(max_dd_fn(ohlcv.tail(252))), 4)
    except Exception:
        max_dd_1y = None

    sup, res = support_resistance(ohlcv, 60)
    atr_pct = round(atr_val / price, 4) if (atr_val and price) else None

    # Volume trend: last 20 avg vs prior 100 avg
    vol_ratio = None
    if "Volume" in ohlcv:
        vol = ohlcv["Volume"].dropna()
        if len(vol) >= 120:
            recent = vol.tail(20).mean()
            base = vol.tail(120).head(100).mean()
            vol_ratio = round(float(recent / base), 3) if base else None

    # Breakout: close within 2% of, or above, 60-bar resistance
    breakout = bool(res is not None and price is not None and price >= res * 0.98)

    # Relative strength: 6m (~126 bars) excess return vs benchmark
    stock_6m = _total_return(close, 126)
    bench_6m = _total_return(bench_close, 126) if bench_close is not None else None
    rs = relative_strength(stock_6m, bench_6m)

    return {
        "price": round(price, 2) if price else None,
        "sma50": round(sma50, 2) if sma50 else None,
        "sma200": round(sma200, 2) if sma200 else None,
        "rsi": round(rsi_val, 2) if rsi_val is not None else None,
        "macd": round(macd_val, 4) if macd_val is not None else None,
        "macd_signal": round(sig_val, 4) if sig_val is not None else None,
        "atr": round(atr_val, 4) if atr_val is not None else None,
        "atr_pct": atr_pct,
        "adx": round(adx_val, 2) if adx_val is not None else None,
        "bb_upper": _last(boll["UB"]),
        "bb_lower": _last(boll["LB"]),
        "support": round(sup, 2) if sup else None,
        "resistance": round(res, 2) if res else None,
        "vol_ratio": vol_ratio,
        "breakout": breakout,
        "max_drawdown_1y": max_dd_1y,
        "rel_strength_6m": rs,
        "stock_return_6m": round(stock_6m, 4) if stock_6m is not None else None,
        "bench_return_6m": round(bench_6m, 4) if bench_6m is not None else None,
    }


def assess(indicators: dict, fundamental_score: float) -> dict:
    """Pure: indicators + fund score -> full technical verdict dict."""
    sc = compute_score_components({
        "price": indicators.get("price"),
        "sma50": indicators.get("sma50"),
        "sma200": indicators.get("sma200"),
        "rsi": indicators.get("rsi"),
        "macd": indicators.get("macd"),
        "macd_signal": indicators.get("macd_signal"),
        "adx": indicators.get("adx"),
        "rel_strength": indicators.get("rel_strength_6m"),
        "vol_ratio": indicators.get("vol_ratio"),
        "breakout": indicators.get("breakout"),
    })
    technical_score = sc["technical_score"]
    verdict, reasons = go_no_go(technical_score, indicators)
    price = indicators.get("price")
    atr_val = indicators.get("atr")
    stop = stop_loss_from_atr(price, atr_val, mult=2.0)
    stop_tight = stop_loss_from_atr(price, atr_val, mult=1.5)
    risk = risk_level_from_atr_pct(indicators.get("atr_pct"))
    ez = entry_zone(price, indicators.get("support"), indicators.get("sma50"))

    # Combined fund+tech score (60% fundamental / 40% technical).
    combined = round(0.6 * fundamental_score + 0.4 * technical_score, 2)

    return {
        "technical_score": technical_score,
        "go_no_go": verdict,
        "go_no_go_reasons": reasons,
        "entry_zone": ez,
        "risk_level": risk,
        "suggested_stop_loss": ([stop_tight, stop] if (stop and stop_tight) else None),
        "combined_score": combined,
        "score_components": sc["components"],
        "indicators": indicators,
    }


def fetch_ohlcv(ticker: str, period: str = "2y") -> pd.DataFrame:
    """Real yfinance fetch (auto_adjust=False so 'Adj Close' exists)."""
    import yfinance as _yf  # real import (BD module import already restored it)
    df = _yf.download(ticker, period=period, interval="1d",
                      auto_adjust=False, progress=False)
    if df is None or len(df) == 0:
        raise RuntimeError(f"no OHLCV data for {ticker}")
    # yfinance may return MultiIndex columns for a single ticker — flatten.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if "Adj Close" not in df.columns and "Close" in df.columns:
        df["Adj Close"] = df["Close"]
    df = df.dropna(how="any")
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--fundamental-score", required=True, type=float)
    ap.add_argument("--analysis-json", default=None)
    ap.add_argument("--benchmark", default=None)
    ap.add_argument("--no-persist", action="store_true")
    args = ap.parse_args()

    ticker = args.ticker.upper()
    fund = args.fundamental_score

    if fund < FUND_GATE:
        msg = {
            "ticker": ticker,
            "skipped": True,
            "reason": f"fundamental_score {fund} < {FUND_GATE} gate — technical layer not run",
        }
        print(json.dumps(msg, indent=2))
        log(f"SKIP {ticker}: fundamental_score {fund} < {FUND_GATE}")
        return 0

    # Benchmark selection
    bench = args.benchmark
    if not bench:
        bench = DEFAULT_BENCH
        for suf, idx in BENCH_BY_SUFFIX.items():
            if ticker.endswith(suf):
                bench = idx
                break

    # Import the BD indicator fns FIRST (with the yfinance stub) so the real
    # yfinance used by fetch_ohlcv() is never shadowed by the stub.
    _import_bd_indicators()

    try:
        ohlcv = fetch_ohlcv(ticker)
        try:
            bench_df = fetch_ohlcv(bench)
            bench_close = bench_df["Adj Close"]
        except Exception as e:
            log(f"WARN: benchmark {bench} fetch failed ({e}); relative strength = None")
            bench_close = None
        indicators = build_indicators(ohlcv, bench_close)
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        print(json.dumps({"ticker": ticker, "error": str(e),
                          "error_type": type(e).__name__}))
        return 1

    result = assess(indicators, fund)
    result.update({
        "ticker": ticker,
        "benchmark": bench,
        "fundamental_score": fund,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "schema_version": "tech-1.0",
    })

    if not args.no_persist:
        try:
            TECH_DIR.mkdir(parents=True, exist_ok=True)
            (TECH_DIR / f"{ticker}.json").write_text(
                json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log(f"WARN: could not persist _technical/{ticker}.json: {e}")

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    log(f"OK {ticker}: tech={result['technical_score']}/10 "
        f"{result['go_no_go']} combined={result['combined_score']} risk={result['risk_level']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
