r"""
render_charts.py — Generates PNG charts for a deep-dive report.

Produces PNGs in C:\BD_Obsidian\Personal\Finance\StocksDaily\IMG\:
 - {date}_{ticker}_price.png      : 1Y price + SMA50/200 + volume
 - {date}_{ticker}_radar.png      : 7-axis radar score (incl. Management Quality)
 - {date}_{ticker}_peers.png      : peer comparison bar (placeholder if peer_info not provided)
 - {date}_{ticker}_dcf.png        : DCF bear/base/bull fan
 - {date}_{ticker}_ebitda_fcf.png : EBITDA bars + FCF line with forecast tail (from _fin_history/)
 - {date}_{ticker}_ni_pe.png      : annual net income bars vs own-history P/E line (v4 Phase A)
 - {date}_{ticker}_relperf.png    : 2.5y relative performance vs region index + sector ETF
 - {date}_{ticker}_segments.png   : revenue-by-segment grouped bars (from _segments/)

Input: --ticker, optional --analysis-json (stdin fallback) with composite breakdown.
The _fin_history/ and _segments/ input dirs sit beside IMG under the StocksDaily root.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from datetime import date
from pathlib import Path

# Force UTF-8 on Windows stdout/stderr
for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402

# Reuse the region-benchmark map from the sibling technical_score module (same
# scripts dir). Importing it is network-free — it only defines constants/fns.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from technical_score import BENCH_BY_SUFFIX, DEFAULT_BENCH  # noqa: E402


DEFAULT_IMG_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily\IMG")

# Sector -> US SPDR sector ETF proxy. Keys are the yfinance `sector` strings
# (info["sector"], surfaced as analysis JSON field `sector`).
SECTOR_ETF = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Financials": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}

# Forecast-basis codes (from financial_history.py) -> short human captions.
_FORECAST_BASIS_LABELS = {
    "consensus_revenue_x_trailing_margin": "consensus revenue × trailing margin (derived estimate)",
    "trend_extrapolation_no_consensus": "trend extrapolation (no consensus)",
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def safe_ticker_filename(ticker: str) -> str:
    return ticker.replace("/", "_").replace("\\", "_")


def _num_or_nan(v) -> float:
    """Coerce a value to float, mapping None / non-numeric to NaN so bar/line
    plotting skips it rather than crashing."""
    try:
        if v is None:
            return float("nan")
        f = float(v)
        return f
    except (TypeError, ValueError):
        return float("nan")


def _money_fmt(x, pos=None) -> str:
    """Axis formatter — auto-scale to K / M / B."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return ""
    ax = abs(x)
    if ax >= 1e9:
        return f"{x / 1e9:.1f}B"
    if ax >= 1e6:
        return f"{x / 1e6:.0f}M"
    if ax >= 1e3:
        return f"{x / 1e3:.0f}K"
    return f"{x:.0f}"


def chart_price(ticker: str, outfile: Path) -> bool:
    try:
        h = yf.Ticker(ticker).history(period="1y")
        if h.empty:
            log(f"price chart: empty history for {ticker}")
            return False
        close = h["Close"]
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        volume = h["Volume"]

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(10, 6), gridspec_kw={"height_ratios": [3, 1]}, sharex=True
        )
        ax1.plot(close.index, close.values, label="Close", linewidth=1.5, color="#1f77b4")
        ax1.plot(sma50.index, sma50.values, label="SMA50", linewidth=1, color="#ff7f0e", alpha=0.8)
        ax1.plot(sma200.index, sma200.values, label="SMA200", linewidth=1, color="#d62728", alpha=0.8)
        ax1.set_title(f"{ticker} — Price 1Y", fontsize=14, fontweight="bold")
        ax1.set_ylabel("Price")
        ax1.legend(loc="upper left")
        ax1.grid(True, alpha=0.3)
        ax2.bar(volume.index, volume.values, color="#7f7f7f", alpha=0.6, width=1.0)
        ax2.set_ylabel("Volume")
        ax2.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(outfile, dpi=100, bbox_inches="tight")
        plt.close()
        return True
    except Exception as e:
        log(f"price chart fail: {e}")
        return False


def chart_radar(scores: dict, ticker: str, outfile: Path) -> bool:
    try:
        labels = ["Fundamentals", "Valuation", "Moat", "Peer", "Growth Dur.", "Management", "Market Ctx."]
        keys = ["fundamentals", "valuation", "moat", "peer", "growth_durability", "management", "market_context"]
        # Validation: refuse to draw if scores are missing/incomplete. Producing
        # a near-zero radar with a misleading "Composite: 0/10" title is worse
        # than no chart at all — it hides the upstream pipeline bug.
        # Management may legitimately be None (screen mode); accept 5/7 component
        # keys present (excluding management) plus composite as the minimum bar.
        non_mgmt_keys = [k for k in keys if k != "management"]
        present_non_mgmt = sum(1 for k in non_mgmt_keys if scores.get(k) is not None)
        if present_non_mgmt < 5 or scores.get("composite") is None:
            log(
                f"radar: scores incomplete (non-mgmt keys present={present_non_mgmt}/6, "
                f"composite={scores.get('composite')!r}); SKIPPING radar to avoid misleading output"
            )
            return False
        # Management may be None (screen mode or Phase 2.5 failed). Fall back to 5.0 neutral
        # so the radar doesn't collapse the axis to zero and distort the shape.
        vals = [float(scores.get(k) if scores.get(k) is not None else (5.0 if k == "management" else 0)) for k in keys]

        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        vals_plot = vals + [vals[0]]
        angles_plot = angles + [angles[0]]

        fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
        ax.fill(angles_plot, vals_plot, color="#1f77b4", alpha=0.25)
        ax.plot(angles_plot, vals_plot, color="#1f77b4", linewidth=2)
        ax.set_ylim(0, 10)
        ax.set_xticks(angles)
        ax.set_xticklabels(labels, fontsize=11)
        ax.set_yticks([2, 4, 6, 8, 10])
        ax.set_yticklabels(["2", "4", "6", "8", "10"], fontsize=9)
        ax.grid(True, alpha=0.4)
        composite = scores.get("composite", 0)
        ax.set_title(f"{ticker} — Composite: {composite}/10", fontsize=14, fontweight="bold", pad=20)
        plt.tight_layout()
        plt.savefig(outfile, dpi=100, bbox_inches="tight")
        plt.close()
        return True
    except Exception as e:
        log(f"radar chart fail: {e}")
        return False


_PEER_CHART_METRICS = [
    ("pe", "P/E", True),
    ("ev_ebitda", "EV/EBITDA", True),
    ("peg", "PEG", True),
    ("roe", "ROE", False),
    ("net_margin", "Net margin", False),
    ("fcf_yield", "FCF yield", False),
]


def chart_peers(ticker: str, peer_info: dict, outfile: Path) -> bool:
    """
    Real peer comparison: 2x3 subplot, one horizontal bar chart per metric.
    Ticker is highlighted in blue; peers in grey. Missing metrics get a
    "(no data)" placeholder so the grid stays consistent.
    """
    try:
        metrics_by = peer_info.get("peer_metrics") or {}
        rankings = peer_info.get("rankings") or {}
        industry = peer_info.get("industry", "Unknown")
        peer_tickers = peer_info.get("peer_tickers") or []
        if not metrics_by:
            # Fall back to placeholder text box. Distinguish "no peers configured"
            # (edit peers.json) from "peers identified but metrics not fetched"
            # (transient yfinance failure or wrong JSON piped in).
            if peer_tickers:
                msg = (
                    f"Peer metrics not fetched for {ticker}.\n"
                    f"Peers identified: {', '.join(peer_tickers)}\n"
                    f"Industry: {industry}\n"
                    f"(yfinance fetch failed or wrong JSON passed to render_charts)"
                )
            else:
                msg = (
                    f"Peer comparison unavailable for {ticker}\n"
                    f"Industry: {industry}\n"
                    f"(no peers configured — edit scripts/peers.json)"
                )
            fig, ax = plt.subplots(figsize=(9, 5))
            ax.text(0.5, 0.5, msg, ha="center", va="center", fontsize=12,
                    bbox=dict(boxstyle="round", facecolor="#f7f7f7"))
            ax.axis("off")
            ax.set_title(f"{ticker} — Peer Comparison ({industry})", fontsize=13, fontweight="bold")
            plt.tight_layout()
            plt.savefig(outfile, dpi=100, bbox_inches="tight")
            plt.close()
            return True

        tickers_sorted = [ticker] + [t for t in metrics_by.keys() if t != ticker]
        fig, axes = plt.subplots(2, 3, figsize=(14, 8))
        axes = axes.flatten()

        for ax, (mkey, label, lower_better) in zip(axes, _PEER_CHART_METRICS):
            vals = []
            labels_y = []
            colors = []
            for t in tickers_sorted:
                v = metrics_by.get(t, {}).get(mkey)
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    vals.append(0)
                    labels_y.append(f"{t} (n/a)")
                else:
                    # Format for display: percentages shown as %, multiples plain
                    vals.append(float(v))
                    labels_y.append(t)
                colors.append("#1f77b4" if t == ticker else "#a0a0a0")
            y = list(range(len(tickers_sorted)))
            bars = ax.barh(y, vals, color=colors, alpha=0.85)
            ax.set_yticks(y)
            ax.set_yticklabels(labels_y, fontsize=9)
            ax.invert_yaxis()  # ticker at top
            # Rank annotation
            rank = rankings.get(mkey, {}).get(ticker)
            n = len(rankings.get(mkey, {}))
            rank_note = f" — rank {rank}/{n}" if rank else ""
            dir_note = " ↓ lower=better" if lower_better else " ↑ higher=better"
            ax.set_title(f"{label}{dir_note}{rank_note}", fontsize=11, fontweight="bold")
            ax.grid(True, alpha=0.3, axis="x")
            # Value labels on bars
            for bar, v in zip(bars, vals):
                if v == 0:
                    continue
                if mkey in ("roe", "net_margin", "fcf_yield"):
                    label_txt = f"{v*100:.1f}%"
                else:
                    label_txt = f"{v:.1f}"
                ax.text(v, bar.get_y() + bar.get_height() / 2, f" {label_txt}", va="center", fontsize=8)

        fig.suptitle(f"{ticker} — Peer Comparison ({industry})", fontsize=14, fontweight="bold")
        plt.tight_layout()
        plt.savefig(outfile, dpi=100, bbox_inches="tight")
        plt.close()
        return True
    except Exception as e:
        log(f"peers chart fail: {e}")
        return False


def chart_dcf(
    ticker: str, price: float | None, dcf_base: float | None, currency: str, outfile: Path
) -> bool:
    try:
        if price is None or dcf_base is None:
            return False
        scenarios = {
            "Bear (-20%)": dcf_base * 0.8,
            "Base": dcf_base,
            "Bull (+25%)": dcf_base * 1.25,
        }
        fig, ax = plt.subplots(figsize=(8, 5))
        colors = ["#d62728", "#1f77b4", "#2ca02c"]
        for (label, val), color in zip(scenarios.items(), colors):
            ax.bar(label, val, color=color, alpha=0.7)
            ax.text(label, val, f"{val:.1f}", ha="center", va="bottom", fontsize=10)
        ax.axhline(price, color="black", linestyle="--", linewidth=1.5, label=f"Current: {price:.2f}")
        ax.set_ylabel(f"Intrinsic value ({currency})")
        ax.set_title(f"{ticker} — DCF scenarios vs current price", fontsize=13, fontweight="bold")
        ax.legend()
        ax.grid(True, alpha=0.3, axis="y")
        plt.tight_layout()
        plt.savefig(outfile, dpi=100, bbox_inches="tight")
        plt.close()
        return True
    except Exception as e:
        log(f"dcf chart fail: {e}")
        return False


def chart_ebitda_fcf(fin_history: dict, out_path: Path) -> bool:
    """Two stacked panels sharing x: EBITDA (bars) on top, FCF (line+markers)
    below, over the quarterly history from financial_history.py, with an optional
    shaded forecast tail. When quarterly history is short (<12 quarters) and an
    `annual` block is present, annual bars/markers are drawn (lighter, FY-labelled)
    ahead of the quarterly tail on the same timeline. Missing points are skipped.
    Missing/invalid input -> False.
    """
    try:
        if not isinstance(fin_history, dict):
            return False
        series = fin_history.get("series") or {}
        labels = list(series.get("labels") or [])
        ebitda = [_num_or_nan(v) for v in (series.get("ebitda") or [])]
        fcf = [_num_or_nan(v) for v in (series.get("fcf") or [])]
        has_e = any(not math.isnan(v) for v in ebitda)
        has_f = any(not math.isnan(v) for v in fcf)
        if not labels or (not has_e and not has_f):
            log("ebitda_fcf chart: empty/invalid series")
            return False
        source = fin_history.get("source", "?")
        currency = fin_history.get("currency", "")
        n_q = fin_history.get("quarters_available", len(labels))

        annual = fin_history.get("annual") or {}
        use_annual = len(labels) < 12 and bool(annual.get("labels"))
        a_labels = list(annual.get("labels") or []) if use_annual else []
        a_ebitda = [_num_or_nan(v) for v in (annual.get("ebitda") or [])] if use_annual else []
        a_fcf = [_num_or_nan(v) for v in (annual.get("fcf") or [])] if use_annual else []

        forecast = fin_history.get("forecast") or None
        f_labels = list(forecast.get("labels") or []) if forecast else []
        f_ebitda = [_num_or_nan(v) for v in (forecast.get("ebitda") or [])] if forecast else []
        f_fcf = [_num_or_nan(v) for v in (forecast.get("fcf") or [])] if forecast else []
        basis = forecast.get("basis") if forecast else None

        # Unified left->right timeline: [annual] [quarterly hist] [forecast].
        n_a, n_h, n_f = len(a_labels), len(labels), len(f_labels)
        seg_annual = list(range(n_a))
        seg_hist = list(range(n_a, n_a + n_h))
        seg_fc = list(range(n_a + n_h, n_a + n_h + n_f))
        all_labels = a_labels + labels + f_labels
        xs = list(range(len(all_labels)))

        fig, (ax_e, ax_f) = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
        fmt = FuncFormatter(_money_fmt)

        # --- top: EBITDA bars ---
        if seg_annual:
            ax_e.bar(seg_annual, a_ebitda[:n_a], color="#8c9bab", alpha=0.35,
                     width=0.8, label="EBITDA (annual FY)")
        if seg_hist:
            ax_e.bar(seg_hist, ebitda, color="#1f77b4", alpha=0.85, width=0.8,
                     label="EBITDA (quarterly)")
        if seg_fc:
            ax_e.bar(seg_fc, f_ebitda, color="#9467bd", alpha=0.55, width=0.8,
                     hatch="//", edgecolor="#5e3c78", linewidth=1.0, label="EBITDA (forecast)")
        ax_e.set_ylabel(f"EBITDA ({currency})")
        ax_e.yaxis.set_major_formatter(fmt)
        ax_e.grid(True, alpha=0.3, axis="y")
        ax_e.legend(loc="upper left", fontsize=8)
        ax_e.set_title(f"EBITDA & FCF — {n_q}Q quarterly ({source})", fontsize=13, fontweight="bold")

        # --- bottom: FCF line + markers ---
        if seg_annual:
            ax_f.plot(seg_annual, a_fcf[:n_a], color="#8c9bab", alpha=0.5,
                      marker="s", linestyle=":", label="FCF (annual FY)")
        if seg_hist:
            ax_f.plot(seg_hist, fcf, color="#2ca02c", marker="o", linewidth=1.8,
                      label="FCF (quarterly)")
        if seg_fc:
            join_x = ([seg_hist[-1]] + seg_fc) if seg_hist else seg_fc
            join_y = ([fcf[-1]] + f_fcf) if seg_hist else f_fcf
            ax_f.plot(join_x, join_y, color="#2ca02c", marker="o", linewidth=1.8,
                      linestyle="--", alpha=0.8, label="FCF (forecast)")
        ax_f.axhline(0, color="#888", linewidth=0.8)
        ax_f.set_ylabel(f"FCF ({currency})")
        ax_f.yaxis.set_major_formatter(fmt)
        ax_f.grid(True, alpha=0.3, axis="y")
        ax_f.legend(loc="upper left", fontsize=8)

        # forecast shaded region + basis caption
        if seg_fc:
            left, right = seg_fc[0] - 0.5, seg_fc[-1] + 0.5
            for ax in (ax_e, ax_f):
                ax.axvspan(left, right, color="#f0e6f5", alpha=0.5, zorder=0)
            cap = _FORECAST_BASIS_LABELS.get(basis, basis or "forecast")
            ax_e.text(0.99, 0.04, f"forecast: {cap}", transform=ax_e.transAxes,
                      ha="right", va="bottom", fontsize=7.5, style="italic", color="#5e3c78")

        ax_f.set_xticks(xs)
        step = max(1, len(all_labels) // 16)
        ax_f.set_xticklabels(
            [lbl if i % step == 0 else "" for i, lbl in enumerate(all_labels)],
            rotation=45, ha="right", fontsize=7,
        )
        plt.tight_layout()
        plt.savefig(out_path, dpi=100, bbox_inches="tight")
        plt.close()
        return True
    except Exception as e:
        log(f"ebitda_fcf chart fail: {e}")
        return False


def chart_net_income_vs_pe(fin_history: dict, valuation_bands: dict,
                           ticker: str, out_path: Path) -> bool:
    """Dual-axis exit-plan chart (v4 Phase A, "USAR Gráfico"): annual net income
    as bars (left axis) vs the own-history P/E as a line (right axis).

    NI comes from fin_history["annual"] (FY labels), P/E from
    valuation_bands["pe_band"]["series"] ([{year, pe}]). The two are joined ON
    THE YEAR LABEL — fiscal-year ends differ between the sources (EPS records
    use fiscalDateEnding), so positional alignment would silently shift
    non-calendar-FY names. Years missing from either side are drawn with just
    the side they have. Missing/empty input -> False (chart skipped).
    """
    try:
        if not isinstance(fin_history, dict):
            return False
        annual = fin_history.get("annual") or {}
        labels = list(annual.get("labels") or [])
        ni_vals = list(annual.get("net_income") or [])
        currency = fin_history.get("currency", "")

        ni_by_year = {}
        for lbl, v in zip(labels, ni_vals):
            digits = "".join(ch for ch in str(lbl) if ch.isdigit())
            if digits and v is not None:
                ni_by_year[int(digits)] = float(v)

        pe_series = ((valuation_bands or {}).get("pe_band") or {}).get("series") or []
        pe_by_year = {int(p["year"]): float(p["pe"]) for p in pe_series
                      if isinstance(p, dict) and p.get("year") is not None
                      and p.get("pe") is not None}

        if not ni_by_year or not pe_by_year:
            log("ni_pe chart: missing net-income or P/E series")
            return False

        years = sorted(set(ni_by_year) | set(pe_by_year))
        xs = list(range(len(years)))
        ni = [ni_by_year.get(y, float("nan")) for y in years]
        pe = [pe_by_year.get(y, float("nan")) for y in years]

        fig, ax_ni = plt.subplots(figsize=(12, 5))
        ax_ni.bar(xs, ni, color="#1f77b4", alpha=0.8, width=0.6,
                  label=f"Net income (annual, {currency})")
        ax_ni.set_ylabel(f"Net income ({currency})")
        ax_ni.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
        ax_ni.axhline(0, color="#888", linewidth=0.8)
        ax_ni.grid(True, alpha=0.3, axis="y")

        ax_pe = ax_ni.twinx()
        ax_pe.plot(xs, pe, color="#d62728", marker="o", linewidth=1.8,
                   label="P/E (FY mean price / EPS)")
        ax_pe.set_ylabel("P/E (×)", color="#d62728")
        ax_pe.tick_params(axis="y", labelcolor="#d62728")

        ax_ni.set_xticks(xs)
        ax_ni.set_xticklabels([f"FY{y}" for y in years], rotation=45, ha="right", fontsize=8)
        ax_ni.set_title(f"{ticker} — Net income vs own-history P/E",
                        fontsize=13, fontweight="bold")
        lines_ni, labels_ni = ax_ni.get_legend_handles_labels()
        lines_pe, labels_pe = ax_pe.get_legend_handles_labels()
        ax_ni.legend(lines_ni + lines_pe, labels_ni + labels_pe,
                     loc="upper left", fontsize=8)
        plt.tight_layout()
        plt.savefig(out_path, dpi=100, bbox_inches="tight")
        plt.close()
        return True
    except Exception as e:
        log(f"ni_pe chart fail: {e}")
        return False


def chart_relperf(ticker: str, region_suffix_bench: str, sector: str | None, out_path: Path) -> bool:
    """2.5y relative performance: the ticker vs its region index vs the US sector
    SPDR ETF, each normalized to 100 at the common start date. Region index is
    resolved from BENCH_BY_SUFFIX (DEFAULT_BENCH fallback, annotated); sector ETF
    from SECTOR_ETF (omitted + noted when the sector is unmapped/None). Each series
    that fails to fetch is dropped; if all fail -> False.
    """
    try:
        suffix = region_suffix_bench or ""
        bench = BENCH_BY_SUFFIX.get(suffix, DEFAULT_BENCH)
        bench_is_fallback = suffix not in BENCH_BY_SUFFIX
        etf = SECTOR_ETF.get(sector) if sector else None

        def _fetch(sym):
            try:
                df = yf.Ticker(sym).history(period="5y")
                if df is None or df.empty or "Close" not in df:
                    return None
                s = df["Close"].dropna()
                s = s[s.index >= s.index.max() - pd.DateOffset(months=30)]
                return s if not s.empty else None
            except Exception as e:
                log(f"relperf fetch {sym}: {e}")
                return None

        series = {}
        for key, sym in (("ticker", ticker), ("bench", bench), ("etf", etf)):
            if not sym:
                continue
            s = _fetch(sym)
            if s is not None:
                series[key] = (sym, s)
        if not series:
            log("relperf: all series failed to fetch")
            return False

        # Common start = latest first-date across the fetched series.
        start = max(s.index.min() for _, (_, s) in series.items())
        fig, ax = plt.subplots(figsize=(11, 6))
        style = {
            "ticker": dict(color="#1f77b4", linewidth=2.4, zorder=3),
            "bench": dict(color="#7f7f7f", linewidth=1.4, zorder=2),
            "etf": dict(color="#ff7f0e", linewidth=1.2, zorder=1),
        }
        drawn = False
        for key in ("ticker", "bench", "etf"):
            if key not in series:
                continue
            sym, s = series[key]
            s = s[s.index >= start]
            if s.empty or float(s.iloc[0]) <= 0:
                continue
            norm = s / float(s.iloc[0]) * 100.0
            ax.plot(norm.index, norm.values, label=sym, **style[key])
            drawn = True
        if not drawn:
            plt.close()
            return False

        ax.axhline(100, color="#bbb", linewidth=0.8, linestyle="--")
        ax.set_ylabel("Indexed to 100 at start")
        ax.set_title(f"{ticker} — Relative performance (2.5y, normalized)",
                     fontsize=13, fontweight="bold")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(True, alpha=0.3)

        notes = []
        if bench_is_fallback:
            notes.append(f"benchmark: {bench} (fallback — no region index mapped)")
        if not sector or sector not in SECTOR_ETF:
            notes.append("sector proxy: n/a")
        elif etf:
            notes.append(f"sector proxy: {etf} (US sector ETF)")
        if notes:
            ax.text(0.01, 0.01, "  ·  ".join(notes), transform=ax.transAxes,
                    ha="left", va="bottom", fontsize=7.5, style="italic", color="#555")
        plt.tight_layout()
        plt.savefig(out_path, dpi=100, bbox_inches="tight")
        plt.close()
        return True
    except Exception as e:
        log(f"relperf chart fail: {e}")
        return False


def validate_segments(d) -> list[str]:
    """Pure validator for a _segments/*.json dict. Returns a list of problems
    (empty list = valid). Load-bearing structure only: `fiscal_years` (len 3) and
    a non-empty `segments` list where each entry has a name and a values list of
    length 3 whose members are numeric-or-null. Cosmetic keys (currency,
    source_url, extracted_at) are optional and not validated here.
    """
    problems: list[str] = []
    if not isinstance(d, dict):
        return ["not a dict"]
    for k in ("fiscal_years", "segments"):
        if k not in d:
            problems.append(f"missing key: {k}")
    fy = d.get("fiscal_years")
    if not isinstance(fy, list) or len(fy) != 3:
        problems.append("fiscal_years must be a list of length 3")
    segs = d.get("segments")
    if not isinstance(segs, list) or len(segs) < 1:
        problems.append("segments must be a non-empty list")
    else:
        for i, s in enumerate(segs):
            if not isinstance(s, dict):
                problems.append(f"segment[{i}] not a dict")
                continue
            if not s.get("name") or not isinstance(s.get("name"), str):
                problems.append(f"segment[{i}] missing name")
            vals = s.get("values")
            if not isinstance(vals, list) or len(vals) != 3:
                problems.append(f"segment[{i}] values must be a list of length 3")
            else:
                for j, v in enumerate(vals):
                    if v is not None and not isinstance(v, (int, float)):
                        problems.append(f"segment[{i}].values[{j}] not numeric-or-null")
    return problems


def chart_revenue_segments(segments: dict, out_path: Path) -> bool:
    """Grouped bar chart of revenue by segment across 3 fiscal years. Top-5
    segments by latest-year value are shown individually; the rest aggregate into
    "Other". Invalid input (per validate_segments) -> log problems + False.
    """
    problems = validate_segments(segments)
    if problems:
        log("revenue_segments invalid: " + "; ".join(problems))
        return False
    try:
        fy = segments["fiscal_years"]
        currency = segments.get("currency", "")
        segs = segments["segments"]

        def _latest(s):
            v = s["values"][-1]
            return float(v) if isinstance(v, (int, float)) else float("-inf")

        ordered = sorted(segs, key=_latest, reverse=True)
        top, rest = ordered[:5], ordered[5:]
        rows = [(s["name"], [_num_or_nan(v) for v in s["values"]]) for s in top]
        if rest:
            agg = []
            for j in range(3):
                vals = [s["values"][j] for s in rest if isinstance(s["values"][j], (int, float))]
                agg.append(sum(vals) if vals else float("nan"))
            rows.append(("Other", agg))

        x = np.arange(3)
        n_series = len(rows)
        width = 0.8 / max(1, n_series)
        fig, ax = plt.subplots(figsize=(11, 6))
        cmap = plt.get_cmap("tab10")
        for i, (name, vals) in enumerate(rows):
            offs = x - 0.4 + width * (i + 0.5)
            plotvals = [0 if math.isnan(v) else v for v in vals]
            ax.bar(offs, plotvals, width=width, label=name, color=cmap(i % 10), alpha=0.9)
        ax.set_xticks(x)
        ax.set_xticklabels(fy)
        ax.set_ylabel(f"Revenue ({currency})")
        ax.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
        ax.set_title("Revenue by segment", fontsize=13, fontweight="bold")
        ax.legend(loc="upper left", fontsize=8, ncol=2)
        ax.grid(True, alpha=0.3, axis="y")
        ax.text(0.99, 0.97, "Source: company filings (LLM-extracted) — verify against source",
                transform=ax.transAxes, ha="right", va="top", fontsize=7.5,
                style="italic", color="#a33")
        plt.tight_layout()
        plt.savefig(out_path, dpi=100, bbox_inches="tight")
        plt.close()
        return True
    except Exception as e:
        log(f"revenue_segments chart fail: {e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--analysis-json", help="Path to analysis JSON (from analyze_ticker.py). If omitted, reads stdin.")
    ap.add_argument("--output-dir", default=str(DEFAULT_IMG_DIR),
                    help=r"Directory for generated PNGs. Default: C:\BD_Obsidian\Personal\Finance\StocksDaily\IMG. Override for dry-run.")
    args = ap.parse_args()

    img_dir = Path(args.output_dir)
    img_dir.mkdir(parents=True, exist_ok=True)

    if args.analysis_json:
        raw = Path(args.analysis_json).read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        src = args.analysis_json
    else:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        src = "stdin"

    # Provenance — makes the next bug-hunt one-glance obvious.
    scores_keys = sorted((data.get("scores") or {}).keys())
    peer_info = (data.get("score_details") or {}).get("peer_info") or {}
    n_peer_metrics = len(peer_info.get("peer_metrics") or {})
    log(
        f"render_charts: input from {src}, {len(raw)} bytes, "
        f"scores keys = {scores_keys}, peer_metrics = {n_peer_metrics}"
    )

    safe_t = safe_ticker_filename(args.ticker)
    today = date.today().isoformat()
    stem = f"{today}_{safe_t}"

    results = {}
    results["price_chart"] = chart_price(args.ticker, img_dir / f"{stem}_price.png")
    results["radar_chart"] = chart_radar(
        data.get("scores", {}), args.ticker, img_dir / f"{stem}_radar.png"
    )
    # Peer info lives in score_details.peer_info (set by analyze_ticker v2).
    peer_info = (data.get("score_details") or {}).get("peer_info") or {
        "industry": data.get("industry") or data.get("sector") or "Unknown",
    }
    results["peers_chart"] = chart_peers(
        args.ticker,
        peer_info,
        img_dir / f"{stem}_peers.png",
    )
    results["dcf_chart"] = chart_dcf(
        args.ticker,
        data.get("price_current"),
        data.get("dcf_intrinsic"),
        data.get("currency", "USD"),
        img_dir / f"{stem}_dcf.png",
    )

    # EBITDA & FCF — reads _fin_history/<SAFE_TICKER>.json (sits beside IMG;
    # falls back to the production root so dry-runs reuse the real cache).
    fin_hist_path = img_dir.parent / "_fin_history" / f"{safe_t}.json"
    if not fin_hist_path.exists():
        fin_hist_path = DEFAULT_IMG_DIR.parent / "_fin_history" / f"{safe_t}.json"
    fin_hist = None
    if fin_hist_path.exists():
        try:
            fin_hist = json.loads(fin_hist_path.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"fin_history load fail: {e}")
    results["ebitda_fcf"] = (
        chart_ebitda_fcf(fin_hist, img_dir / f"{stem}_ebitda_fcf.png") if fin_hist else False
    )

    # NI vs P/E — exit-plan chart (v4 Phase A). Needs the fin_history annual
    # net_income series AND the pe_band.series persisted by valuation_bands.
    results["ni_pe"] = (
        chart_net_income_vs_pe(fin_hist, data.get("valuation_bands") or {},
                               args.ticker, img_dir / f"{stem}_ni_pe.png")
        if fin_hist else False
    )

    # Relative performance — sector from the analysis JSON, suffix from the ticker.
    suffix = args.ticker[args.ticker.rfind("."):] if "." in args.ticker else ""
    results["relperf"] = chart_relperf(
        args.ticker, suffix, data.get("sector"), img_dir / f"{stem}_relperf.png"
    )

    # Revenue segments — reads _segments/<SAFE_TICKER>.json (sits beside IMG;
    # falls back to the production root so dry-runs reuse the real cache).
    seg_path = img_dir.parent / "_segments" / f"{safe_t}.json"
    if not seg_path.exists():
        seg_path = DEFAULT_IMG_DIR.parent / "_segments" / f"{safe_t}.json"
    seg = None
    if seg_path.exists():
        try:
            seg = json.loads(seg_path.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"segments load fail: {e}")
    results["segments"] = (
        chart_revenue_segments(seg, img_dir / f"{stem}_segments.png") if seg else False
    )

    print(json.dumps({
        "ticker": args.ticker,
        "img_dir": str(img_dir),
        "stem": stem,
        "charts": results,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
