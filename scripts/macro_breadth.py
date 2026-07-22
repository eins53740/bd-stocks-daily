"""
macro_breadth.py — Market breadth + sector-tendency gauges for the daily macro §8.

v4 Phase D. Pure-yfinance, no scraping: two ground-truth gauges Bruno sketched
(scan-2 p07 breadth divergence; 12-idea list #10 sector tendencies w/ volume).

Two gauges:
  * BREADTH — RSP/SPY (equal-weight vs cap-weight) close ratio vs its own multi-year
    history: percentile + trend arrow. A low/falling percentile = narrow mega-cap
    leadership; a mean-reverting one = broadening.
  * SECTORS — the 11 SPDR sector ETFs (XLK/XLV/XLF/XLE/XLI/XLY/XLP/XLU/XLB/XLRE/XLC)
    plus SPY as the overall-market line: 20d-vs-60d MA trend (↑/→/↓) + volume direction
    + a "volume confirms the trend?" check (recent volume vs its own 20d MA).

Two modes (mirrors macro_snapshot.py):
  --fetch   Pull quotes via yfinance, compute both gauges, print {breadth, sectors}
            JSON to stdout (NO file write — inspection / live spot-check).
  --update  Same fetch, then merge the additive `breadth` + `sectors` keys into
            `_macro/<date>.json` (created if missing). NEVER touches the existing
            `metrics` block — overlay-only, same additive-merge convention as
            valuation_bands.py / red_flags.py `--update`.

The pure functions (breadth_stats, sector_trend + helpers) are network-free and
unit-tested with static series. Only fetch_breadth / fetch_sectors touch yfinance.
Every gauge degrades independently: a bad symbol becomes an `{"error": ...}` entry
so one failure never blanks the whole section (Phase D acceptance gate).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

OUT_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily\_macro")

# SPDR sector ETFs (GICS 11), rendered in this order. SPY carries the overall line.
SECTOR_ETFS: list[tuple[str, str]] = [
    ("XLK", "Technology"),
    ("XLC", "Communication Services"),
    ("XLY", "Consumer Discretionary"),
    ("XLP", "Consumer Staples"),
    ("XLE", "Energy"),
    ("XLF", "Financials"),
    ("XLV", "Health Care"),
    ("XLI", "Industrials"),
    ("XLB", "Materials"),
    ("XLRE", "Real Estate"),
    ("XLU", "Utilities"),
]

# Trend deadband: |short/long - 1| below this reads as flat (→) rather than a move.
TREND_DEADBAND = 0.005  # 0.5%
BREADTH_LOOKBACK = 20    # trading days for the breadth trend arrow

# Force UTF-8 on Windows (arrows/glyphs in JSON output).
for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _log(msg: str) -> None:
    print(f"[macro_breadth] {msg}", file=sys.stderr)


# ------------------------- Pure computation (unit-tested, no network) -------------------------
def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 6) if xs else None


def _percentile_rank(series: list[float], value: float) -> float | None:
    """Percentile rank (0–100) of `value` within `series` (weak rank, half-credit ties).

    All-time high → ~99+, all-time low → ~0.5, single-element series → 50.0.
    """
    n = len(series)
    if n == 0:
        return None
    below = sum(1 for v in series if v < value)
    equal = sum(1 for v in series if v == value)
    return round(100.0 * (below + 0.5 * equal) / n, 1)


def _arrow(rel: float, deadband: float = TREND_DEADBAND) -> str:
    """↑ / ↓ / → from a relative change, with a symmetric deadband around zero."""
    if rel > deadband:
        return "↑"
    if rel < -deadband:
        return "↓"
    return "→"


def breadth_stats(ratio_series: list[float], *, lookback: int = BREADTH_LOOKBACK) -> dict:
    """Breadth stats from an aligned RSP/SPY daily-close ratio series (oldest→newest).

    Returns {ratio_now, min, mean, max, percentile, trend, depth_days}. The trend
    arrow compares the latest ratio to `lookback` trading days earlier (deadband
    TREND_DEADBAND); with too little history it degrades to None. Empty input
    returns {"error": ...} so the caller can render "not available".
    """
    if not ratio_series:
        return {"error": "no ratio data"}
    now = float(ratio_series[-1])
    trend: str | None = None
    if len(ratio_series) > lookback:
        ref = float(ratio_series[-1 - lookback])
        if ref:
            trend = _arrow(now / ref - 1.0)
    return {
        "ratio_now": round(now, 6),
        "min": round(min(ratio_series), 6),
        "mean": _mean(ratio_series),
        "max": round(max(ratio_series), 6),
        "percentile": _percentile_rank(ratio_series, now),
        "trend": trend,
        "depth_days": len(ratio_series),
    }


def sector_trend(closes: list[float], volumes: list[float]) -> dict:
    """Trend + volume-confirmation for one instrument (oldest→newest, aligned).

    trend         ↑/→/↓ from the 20d vs 60d MA (deadband TREND_DEADBAND); "na" if
                  <60 closes.
    vol_direction "rising"/"falling" from the recent 5d mean volume vs the 20d MA;
                  None if <20 volumes.
    confirms      True  — a real move: a non-flat trend on rising volume (up on
                          rising volume, or down on rising volume = distribution);
                  False — a non-flat trend on falling volume (suspect);
                  None  — flat trend, or volume direction unavailable.

    Insufficient history degrades each field independently rather than raising;
    empty closes return {"error": ...}.
    """
    if not closes:
        return {"error": "no data"}
    ma20 = _mean(closes[-20:]) if len(closes) >= 20 else None
    ma60 = _mean(closes[-60:]) if len(closes) >= 60 else None

    trend = "na"
    if ma20 is not None and ma60 is not None and ma60:
        trend = _arrow(ma20 / ma60 - 1.0)

    vol_ma20 = _mean(volumes[-20:]) if len(volumes) >= 20 else None
    vol_recent = _mean(volumes[-5:]) if len(volumes) >= 5 else None
    vol_direction = None
    if vol_ma20 is not None and vol_recent is not None:
        vol_direction = "rising" if vol_recent > vol_ma20 else "falling"

    confirms: bool | None = None
    if trend in ("↑", "↓") and vol_direction is not None:
        confirms = vol_direction == "rising"

    return {
        "ma20": ma20,
        "ma60": ma60,
        "trend": trend,
        "vol_ma20": vol_ma20,
        "vol_recent": vol_recent,
        "vol_direction": vol_direction,
        "confirms": confirms,
    }


# ------------------------- Network (yfinance) -------------------------
def fetch_breadth() -> dict:
    """RSP/SPY breadth gauge from yfinance max-history closes (best-effort)."""
    try:
        import pandas as pd
        import yfinance as yf

        spy = yf.Ticker("SPY").history(period="max")["Close"].dropna()
        rsp = yf.Ticker("RSP").history(period="max")["Close"].dropna()
        if spy.empty or rsp.empty:
            return {"error": "no SPY/RSP data"}
        df = pd.concat([spy, rsp], axis=1, join="inner").dropna()
        df.columns = ["spy", "rsp"]
        if df.empty:
            return {"error": "no overlapping SPY/RSP dates"}
        ratio = (df["rsp"] / df["spy"]).tolist()
        stats = breadth_stats([float(x) for x in ratio])
        stats["as_of"] = df.index[-1].date().isoformat()
        stats["note"] = (
            "RSP/SPY equal-weight vs cap-weight; low/falling percentile = narrow "
            "mega-cap leadership, mean-reverting = broadening"
        )
        return stats
    except Exception as e:  # noqa: BLE001 - best-effort, degrade to error entry
        _log(f"breadth: {e}")
        return {"error": str(e)}


def _fetch_one_trend(symbol: str) -> dict:
    """Pull 1y of closes+volumes for one symbol and reduce to sector_trend()."""
    import yfinance as yf

    hist = yf.Ticker(symbol).history(period="1y")
    if hist is None or hist.empty:
        return {"error": "no data"}
    closes = [float(c) for c in hist["Close"].dropna().tolist()]
    volumes = [float(v) for v in hist["Volume"].fillna(0).tolist()]
    row = sector_trend(closes, volumes)
    return row


def fetch_sectors() -> dict:
    """Sector-tendency table (11 SPDR ETFs) + SPY overall-market line (best-effort)."""
    as_of = None
    try:
        import yfinance as yf

        spy_hist = yf.Ticker("SPY").history(period="1y")
        if spy_hist is not None and not spy_hist.empty:
            as_of = spy_hist.index[-1].date().isoformat()
    except Exception as e:  # noqa: BLE001
        _log(f"sectors as_of: {e}")

    def _row(symbol: str, name: str) -> dict:
        try:
            r = _fetch_one_trend(symbol)
        except Exception as e:  # noqa: BLE001 - one bad ETF never aborts the table
            _log(f"{symbol}: {e}")
            r = {"error": str(e)}
        r = {"symbol": symbol, "name": name, **r}
        return r

    market = _row("SPY", "S&P 500 (overall)")
    rows = [_row(sym, name) for sym, name in SECTOR_ETFS]
    return {"as_of": as_of, "market": market, "rows": rows}


def compute() -> dict:
    """Both gauges as one {breadth, sectors} payload."""
    _log("fetching breadth (SPY/RSP) + 11 sector ETFs")
    return {"breadth": fetch_breadth(), "sectors": fetch_sectors()}


# ------------------------- --update merge (overlay-only) -------------------------
def update_macro_json(out_dir: Path, today: date | None = None, payload: dict | None = None) -> dict:
    """Merge additive `breadth`+`sectors` keys into `_macro/<date>.json`.

    Loads the existing snapshot (created minimal if absent) and rewrites it with the
    two new keys added. The existing `metrics` block is never read or altered —
    overlay-only. `payload` is injectable for tests (skips the network).
    """
    today = today or date.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{today.isoformat()}.json"

    data: dict
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            _log(f"could not parse {json_path.name} ({e}); re-initialising")
            data = {"date": today.isoformat()}
    else:
        data = {"date": today.isoformat()}

    payload = payload if payload is not None else compute()
    data["breadth"] = payload.get("breadth")
    data["sectors"] = payload.get("sectors")
    data["breadth_updated_at"] = datetime.now().isoformat(timespec="seconds")

    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _log(f"merged breadth+sectors into {json_path}")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Daily macro breadth + sector tendencies: --fetch (print) or --update (merge into _macro json)."
    )
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fetch", action="store_true", help="Compute both gauges, print JSON (no file write).")
    mode.add_argument("--update", action="store_true", help="Merge breadth+sectors into _macro/<date>.json.")
    ap.add_argument("--out-dir", default=str(OUT_DIR), help="Macro output dir (default: StocksDaily/_macro).")
    args = ap.parse_args()

    if args.fetch:
        res = compute()
    else:
        res = update_macro_json(Path(args.out_dir))

    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
