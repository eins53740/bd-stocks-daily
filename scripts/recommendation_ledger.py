"""recommendation_ledger.py — score the skill's own calls (v4.3 wave 4.1).

`/bd-stocks-monitor` was specced to watch "portfolio performance **and AI
recommendations**". The holdings half is straightforward. This is the other half: did the
composite actually discriminate?

Everything needed is already on disk. `_log.csv` has carried `price_at_eval` beside the
verdict since 2026-04-17 — the column survived every schema bump precisely so this became
possible (`SCORING_REVIEW_v3.md §S5`). **Do not break it.**

THE ONE NUMBER THIS EXISTS TO PRODUCE is the **spread between `invest` and `reject`**. Hit
rates and best/worst calls are interesting; the spread is the question — if names the
system called `invest` do not out-return the ones it called `reject`, the composite is not
discriminating, and no amount of new overlay work fixes that.

THREE HONESTY CONSTRAINTS, all load-bearing:

 1. **This is NOT the G1 backtest** and must never be presented as one. G1 recalibrates
    `WEIGHTS_V2_DEEP` against T+6m outcomes and is gated to ≈2026-10-17. This only
    *observes* what happened. It changes no weight and no threshold.
 2. **Refuse to annualise a short window.** The earliest row is 2026-04-17, so the longest
    window available is a few months. Annualising a 3-month 8 % move into 36 % would be the
    single most misleading number this file could print, so windows under
    `MIN_ANNUALISE_DAYS` report the raw return and the window length instead.
 3. **Compare like with like.** `price_at_eval` is in the ticker's own currency; the
    current price must be read in that same currency, and the benchmark leg must cover the
    *same* window per call — a portfolio-level benchmark return would flatter or punish
    calls made at different times.

Pure apart from an injectable price fetcher, so the suite stays network-free.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from datetime import date, datetime
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

OUT_DIR_DEFAULT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
LOG = "_log.csv"

# Verdict classes, best to worst. `great` predates the current vocabulary and still
# appears in early rows, so it is kept rather than silently folded into `invest`.
VERDICT_ORDER = ("great", "invest", "review", "fair", "reject")
BULLISH = ("great", "invest")
BEARISH = ("reject",)

MIN_ANNUALISE_DAYS = 365      # below this, report the raw return and say how long it ran
MIN_CLASS_N = 3               # a class mean below this many calls is an anecdote
BENCHMARK = "URTH"            # MSCI World ETF — the same benchmark alpha_beta.py uses
# A return this large over a window measured in months is a UNIT BREAK, not a return.
# Measured, not imagined: the first live run of this ledger printed a mean of +601 % for
# `invest` against a median of +4.63 %, and every outlier was a London name —
# `_log.csv` stores `price_at_eval` already normalised to GBP while yfinance's raw
# `history()` answers in GBp (pence), a clean factor of 100 (RR.L +10,970 %, EXPN.L
# +10,830 %, ULVR.L +9,513 %). The fetcher below now normalises, but the guard stays:
# no price source is trustworthy enough to skip it, and one such row destroys a mean.
RETURN_SANITY_PCT = 500.0


def log(msg: str) -> None:
    print(f"[recommendation_ledger] {msg}", file=sys.stderr)


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _day(s):
    try:
        return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def load_calls(out_dir: Path) -> list:
    """Every logged evaluation that carries a usable entry price.

    A row without `price_at_eval` cannot be scored and is counted, not dropped silently —
    "6 of 384 rows had no entry price" is a fact about the ledger's coverage.
    """
    path = out_dir / LOG
    if not path.is_file():
        return []
    out = []
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            px = _num(r.get("price_at_eval"))
            when = _day(r.get("date"))
            ticker = (r.get("ticker") or "").strip()
            if not ticker or when is None:
                continue
            out.append({
                "ticker": ticker, "date": when, "verdict": (r.get("verdict") or "").strip(),
                "score": _num(r.get("score")), "price_at_eval": px,
                "currency": (r.get("currency") or "").strip() or None,
                "mode": (r.get("mode") or "").strip(),
                "scorable": px is not None and px > 0,
            })
    return out


def score_call(call: dict, price_now, bench_then=None, bench_now=None,
               today: date | None = None) -> dict:
    """One call's outcome. Returns None-valued fields rather than guesses."""
    today = today or date.today()
    days = (today - call["date"]).days
    out = {**{k: call[k] for k in ("ticker", "date", "verdict", "score", "currency")},
           "days_held": days, "price_at_eval": call["price_at_eval"],
           "price_now": price_now, "return_pct": None,
           "benchmark_return_pct": None, "excess_pct": None,
           "annualised": False}
    out["unit_suspect"] = False
    p0, p1 = call["price_at_eval"], _num(price_now)
    if p0 and p0 > 0 and p1 and p1 > 0:
        ret = (p1 / p0 - 1) * 100
        if abs(ret) > RETURN_SANITY_PCT:
            # Refuse rather than assert. A quote in a different unit from the logged
            # entry price is indistinguishable from a spectacular return by arithmetic
            # alone, and a single one of these moves a class mean by hundreds of points.
            out["unit_suspect"] = True
            out["unit_note"] = (f"{ret:+.0f}% over {days}d between {p0:g} and {p1:g} — "
                                f"a unit or share-class mismatch, not a return; excluded")
        else:
            out["return_pct"] = round(ret, 2)
    b0, b1 = _num(bench_then), _num(bench_now)
    if b0 and b0 > 0 and b1 and b1 > 0:
        out["benchmark_return_pct"] = round((b1 / b0 - 1) * 100, 2)
    if out["return_pct"] is not None and out["benchmark_return_pct"] is not None:
        # Excess over the SAME window as the call, not a portfolio-level benchmark
        # return — otherwise a call made in April is judged against a period it was
        # never exposed to.
        out["excess_pct"] = round(out["return_pct"] - out["benchmark_return_pct"], 2)
    return out


def summarise(scored: list, today: date | None = None) -> dict:
    """Per-verdict means, hit rates, and the number this file exists for."""
    today = today or date.today()
    usable = [s for s in scored if s.get("return_pct") is not None]
    by_class = {}
    for verdict in VERDICT_ORDER:
        rows = [s for s in usable if s["verdict"] == verdict]
        if not rows:
            continue
        rets = [s["return_pct"] for s in rows]
        excess = [s["excess_pct"] for s in rows if s["excess_pct"] is not None]
        by_class[verdict] = {
            "n": len(rows),
            "mean_return_pct": round(statistics.mean(rets), 2),
            "median_return_pct": round(statistics.median(rets), 2),
            "mean_excess_pct": round(statistics.mean(excess), 2) if excess else None,
            "beat_benchmark": (round(100 * sum(1 for e in excess if e > 0) / len(excess), 1)
                               if excess else None),
            "thin": len(rows) < MIN_CLASS_N,
        }

    bull = [s["return_pct"] for s in usable if s["verdict"] in BULLISH]
    bear = [s["return_pct"] for s in usable if s["verdict"] in BEARISH]
    spread = mean_spread = None
    if len(bull) >= MIN_CLASS_N and len(bear) >= MIN_CLASS_N:
        # The MEDIAN is the headline. On a few dozen calls over a few months one runaway
        # name owns the mean — the same reason `justified_exit_pe`, the consensus target
        # and (since the §3.1 audit) the fair-price anchor under wide dispersion all use
        # medians. The mean is still reported, beside it, so the skew stays visible.
        spread = round(statistics.median(bull) - statistics.median(bear), 2)
        mean_spread = round(statistics.mean(bull) - statistics.mean(bear), 2)

    windows = [s["days_held"] for s in usable]
    longest = max(windows) if windows else 0
    return {
        "as_of": today.isoformat(),
        "calls_total": len(scored),
        "calls_scored": len(usable),
        "window_days": {"longest": longest, "shortest": min(windows) if windows else 0,
                        "median": int(statistics.median(windows)) if windows else 0},
        "annualised": False,
        "annualise_refused_reason": (
            None if longest >= MIN_ANNUALISE_DAYS else
            f"longest window is {longest} days; annualising under {MIN_ANNUALISE_DAYS} "
            f"turns a few months of noise into a headline rate"),
        "by_verdict": by_class,
        "invest_minus_reject_pct": spread,
        "invest_minus_reject_mean_pct": mean_spread,
        "unit_suspect_excluded": sum(1 for s in scored if s.get("unit_suspect")),
        "spread_note": (
            "median spread — the single number that says whether the composite "
            "discriminates at all"
            if spread is not None else
            f"not computable — needs {MIN_CLASS_N}+ scored calls in both classes"),
        "best": sorted(usable, key=lambda s: -s["return_pct"])[:5],
        "worst": sorted(usable, key=lambda s: s["return_pct"])[:5],
        "benchmark": BENCHMARK,
        "not_a_backtest": (
            "This observes outcomes. It is NOT the G1 weight recalibration, which needs "
            "T+6m data (first possible ~2026-10-17) and changes weights — this changes "
            "nothing."),
    }


def build(out_dir: Path, price_lookup=None, today: date | None = None) -> dict:
    """Full ledger. `price_lookup(ticker) -> (price_now, bench_then, bench_now)`.

    Without a lookup the ledger still reports coverage and window lengths — useful on its
    own, and it means the module is exercised end-to-end with no network in the tests.
    """
    today = today or date.today()
    calls = load_calls(out_dir)
    scorable = [c for c in calls if c["scorable"]]
    scored = []
    for c in scorable:
        px = bt = bn = None
        if price_lookup is not None:
            try:
                px, bt, bn = price_lookup(c["ticker"], c["date"])
            except Exception as exc:                       # noqa: BLE001
                log(f"{c['ticker']}: price lookup failed ({exc})")
        scored.append(score_call(c, px, bt, bn, today))
    block = summarise(scored, today)
    block["coverage"] = {
        "rows": len(calls),
        "with_entry_price": len(scorable),
        "without_entry_price": len(calls) - len(scorable),
    }
    block["calls"] = scored
    return block


def render_lines(block: dict) -> list:
    c = block["coverage"]
    out = [f"as of {block['as_of']} — {c['with_entry_price']}/{c['rows']} calls carry an "
           f"entry price; {block['calls_scored']} scored",
           f"window: median {block['window_days']['median']}d, longest "
           f"{block['window_days']['longest']}d"]
    if block.get("annualise_refused_reason"):
        out.append(f"  annualisation refused — {block['annualise_refused_reason']}")
    for verdict in VERDICT_ORDER:
        s = (block.get("by_verdict") or {}).get(verdict)
        if not s:
            continue
        beat = "n/a" if s["beat_benchmark"] is None else f"{s['beat_benchmark']:.0f}%"
        out.append(f"  {verdict:<8} n={s['n']:<4} mean {s['mean_return_pct']:+7.2f}%  "
                   f"median {s['median_return_pct']:+7.2f}%  beat {BENCHMARK} {beat}"
                   + ("   (thin)" if s["thin"] else ""))
    spread = block.get("invest_minus_reject_pct")
    mean_spread = block.get("invest_minus_reject_mean_pct")
    out.append("  invest − reject spread: "
               + (f"{spread:+.2f} pp (median){'' if mean_spread is None else f', {mean_spread:+.2f} pp (mean)'}"
                  f" — {block['spread_note']}" if spread is not None
                  else block["spread_note"]))
    if block.get("unit_suspect_excluded"):
        out.append(f"  {block['unit_suspect_excluded']} call(s) excluded as a unit "
                   f"mismatch (|return| > {RETURN_SANITY_PCT:.0f}%), not scored")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Score the skill's own calls from _log.csv (v4.3 wave 4.1).")
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--with-prices", action="store_true",
                    help="fetch current prices via yfinance (network)")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    lookup = None
    if args.with_prices:
        lookup = _yfinance_lookup()
    block = build(Path(args.out_dir), lookup)
    if args.pretty:
        for line in render_lines(block):
            print(line, file=sys.stderr)
    slim = {k: v for k, v in block.items() if k != "calls"}
    print(json.dumps(slim, ensure_ascii=False, default=str))
    return 0


def _yfinance_lookup():
    """Batched current prices + the benchmark's level at each call date.

    Prices are normalised out of GBp (pence) before they are returned, because
    `_log.csv` stores `price_at_eval` already normalised to GBP — comparing the two raw
    is a clean factor of 100 and produced every one of the first run's outliers.
    `markets.normalize_gbx` is imported rather than re-derived; it is stdlib-only.
    """
    import yfinance as yf                                   # noqa: PLC0415
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from markets import normalize_gbx                       # noqa: PLC0415
    cache: dict = {}
    bench_hist = None

    def lookup(ticker: str, when: date):
        nonlocal bench_hist
        if ticker not in cache:
            try:
                tk = yf.Ticker(ticker)
                h = tk.history(period="1d")
                px = float(h["Close"].iloc[-1]) if not h.empty else None
                ccy = ""
                try:
                    ccy = getattr(tk.fast_info, "currency", "") or ""
                except Exception:                            # noqa: BLE001
                    ccy = ""
                px, _ = normalize_gbx(px, ccy)
                cache[ticker] = px
            except Exception:                                # noqa: BLE001
                cache[ticker] = None
        if bench_hist is None:
            try:
                bench_hist = yf.Ticker(BENCHMARK).history(period="2y")
            except Exception:                                # noqa: BLE001
                bench_hist = False
        b_then = b_now = None
        if bench_hist is not None and bench_hist is not False and not bench_hist.empty:
            closes = bench_hist["Close"]
            b_now = float(closes.iloc[-1])
            prior = closes[closes.index.date <= when]
            b_then = float(prior.iloc[-1]) if len(prior) else None
        return cache[ticker], b_then, b_now

    return lookup


if __name__ == "__main__":
    raise SystemExit(main())
