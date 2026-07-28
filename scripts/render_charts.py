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
import chart_theme as th  # noqa: E402

th.apply_theme()


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


def _last_valid(vals) -> int | None:
    """Index of the last finite value, or None. Series tails can be NaN when a
    source is missing the most recent quarter."""
    for i in range(len(vals) - 1, -1, -1):
        v = vals[i]
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            return i
    return None


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
            2, 1, figsize=(10, 6), gridspec_kw={"height_ratios": [3.2, 1]}, sharex=True
        )
        ax1.plot(close.index, close.values, label="Close", color=th.PRIMARY, zorder=4)
        ax1.plot(sma50.index, sma50.values, label="SMA50", linewidth=1.4,
                 color=th.ACCENT, zorder=3)
        ax1.plot(sma200.index, sma200.values, label="SMA200", linewidth=1.4,
                 color=th.AQUA, zorder=2)
        # Deliberately no area fill: an area under a price line has to be anchored
        # somewhere, and any anchor other than zero invents a baseline the reader
        # will read as meaningful. Three lines carry the comparison on their own.
        last_close = float(close.iloc[-1])
        th.style_axes(ax1, title=f"{ticker} — price, 1 year",
                      subtitle=f"close {last_close:,.2f} · SMA50 / SMA200 overlay",
                      ylabel="Price", legend_row=True)
        th.label_line_end(ax1, close.index[-1], last_close, f"{last_close:,.2f}", th.PRIMARY)
        th.legend_above(ax1, ncol=3)
        ax2.bar(volume.index, volume.values, color=th.INK_MUTED, alpha=0.55, width=1.0)
        th.style_axes(ax2, ylabel="Volume")
        ax2.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
        fig.tight_layout()
        th.save(fig, outfile)
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

        fig, ax = plt.subplots(figsize=(7.2, 7.2), subplot_kw=dict(polar=True))
        ax.set_facecolor(th.SURFACE)
        ax.fill(angles_plot, vals_plot, color=th.PRIMARY, alpha=0.12, linewidth=0)
        ax.plot(angles_plot, vals_plot, color=th.PRIMARY, linewidth=2, zorder=4)
        # One dot per axis, ringed in the surface colour so it stays legible
        # where the outline crosses a spoke.
        ax.plot(angles, vals, linestyle="none", zorder=5, **th.marker_kwargs(th.PRIMARY))
        ax.set_ylim(0, 10)
        ax.set_xticks(angles)
        ax.set_xticklabels(labels, fontsize=10, color=th.INK_SECONDARY)
        ax.set_yticks([2, 4, 6, 8, 10])
        ax.set_yticklabels(["2", "4", "6", "8", "10"], fontsize=8, color=th.INK_MUTED)
        ax.set_rlabel_position(90)
        ax.grid(True, color=th.GRID, linewidth=0.8, linestyle="-")
        ax.spines["polar"].set_color(th.GRID)
        ax.spines["polar"].set_linewidth(0.8)
        # Per-axis scores sit beside their spoke — the radar's shape shows the
        # profile, the labels carry the values the radial ticks only approximate.
        for ang, val in zip(angles, vals):
            ax.annotate(f"{val:.1f}", xy=(ang, val), xytext=(0, 9),
                        textcoords="offset points", ha="center", va="center",
                        fontsize=8.5, color=th.INK_SECONDARY, fontweight="semibold")
        composite = scores.get("composite", 0)
        # Title and subtitle are set at FIGURE level, not on the axes: a polar
        # axes' title pad is measured from the square bounding box, so an
        # axes-relative subtitle lands on top of the title instead of below it.
        fig.tight_layout(rect=(0, 0, 1, 0.93))
        fig.text(0.02, 0.975, f"{ticker} — score profile", ha="left", va="top",
                 fontsize=13, fontweight="semibold", color=th.INK)
        fig.text(0.02, 0.945, f"composite {composite}/10 · each axis scored 0–10",
                 ha="left", va="top", fontsize=9, color=th.INK_MUTED)
        th.save(fig, outfile)
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
            fig, ax = plt.subplots(figsize=(9, 4.5))
            ax.text(0.5, 0.5, msg, ha="center", va="center", fontsize=11,
                    color=th.INK_SECONDARY, linespacing=1.6)
            ax.axis("off")
            ax.set_title(f"{ticker} — peer comparison", loc="left", fontsize=13,
                         fontweight="semibold", color=th.INK)
            ax.text(0.0, 1.02, industry, transform=ax.transAxes, ha="left",
                    va="bottom", fontsize=9, color=th.INK_MUTED)
            th.save(fig, outfile)
            return True

        tickers_sorted = [ticker] + [t for t in metrics_by.keys() if t != ticker]
        fig, axes = plt.subplots(2, 3, figsize=(14, 7.5))
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
                # Emphasis, not identity: the subject is the only coloured bar,
                # every peer recedes to muted grey.
                colors.append(th.PRIMARY if t == ticker else "#cfcdc5")
            y = list(range(len(tickers_sorted)))
            bars = ax.barh(y, vals, color=colors, height=th.BAR_WIDTH)
            ax.set_yticks(y)
            ax.set_yticklabels(labels_y, fontsize=9, color=th.INK_MUTED)
            # The subject's own tick label is promoted to secondary ink so the
            # eye finds it without relying on the bar colour alone.
            if ax.get_yticklabels():
                ax.get_yticklabels()[0].set_color(th.INK_SECONDARY)
                ax.get_yticklabels()[0].set_fontweight("semibold")
            ax.invert_yaxis()  # ticker at top
            # Rank annotation
            rank = rankings.get(mkey, {}).get(ticker)
            n = len(rankings.get(mkey, {}))
            rank_note = f"rank {rank}/{n} · " if rank else ""
            dir_note = "lower is better" if lower_better else "higher is better"
            ax.set_title(label, loc="left", fontsize=11, fontweight="semibold",
                         color=th.INK, pad=14)
            ax.text(0.0, 1.015, f"{rank_note}{dir_note}", transform=ax.transAxes,
                    ha="left", va="bottom", fontsize=8, color=th.INK_MUTED)
            th.style_axes(ax, grid_axis="x")
            is_pct = mkey in ("roe", "net_margin", "fcf_yield")
            if is_pct:
                # These arrive as fractions; without this the axis would read
                # 0.26 beside a label reading 26.3%.
                th.percent_axis(ax, "x")
            # Value labels on bars — the relief this palette's contrast WARN owes.
            for bar, v in zip(bars, vals):
                if v == 0:
                    continue
                if is_pct:
                    label_txt = f"{v * 100:.1f}%"
                else:
                    label_txt = f"{v:.1f}"
                ax.annotate(label_txt, xy=(v, bar.get_y() + bar.get_height() / 2),
                            xytext=(4, 0), textcoords="offset points",
                            va="center", ha="left" if v >= 0 else "right",
                            fontsize=8, color=th.INK_SECONDARY)

        fig.suptitle(f"{ticker} — peer comparison · {industry}", x=0.008, y=1.0,
                     ha="left", fontsize=14, fontweight="semibold", color=th.INK)
        fig.tight_layout(rect=(0, 0, 1, 0.97))
        th.save(fig, outfile)
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
        fig, ax = plt.subplots(figsize=(8, 4.8))
        # Status palette, legitimately: bear/base/bull mean bad/neutral/good, and
        # each is named on the x-axis, so colour never carries the meaning alone.
        colors = [th.CRITICAL, th.PRIMARY, th.GOOD]
        bar_w = th.cap_bar_width(ax, th.BAR_WIDTH, len(scenarios))
        for (label, val), color in zip(scenarios.items(), colors):
            bars = ax.bar(label, val, color=color, width=bar_w)
            # Surface halo: a scenario can land within a hair of the price
            # threshold, and without it the dashed line cuts through the digits.
            ax.annotate(f"{val:,.1f}", xy=(label, val), xytext=(0, 6),
                        textcoords="offset points", ha="center", va="bottom",
                        fontsize=10, color=th.INK_SECONDARY, fontweight="semibold",
                        zorder=7,
                        bbox=dict(boxstyle="round,pad=0.18", facecolor=th.SURFACE,
                                  edgecolor="none"))
        # Dashed here is correct and deliberate: this is a threshold, not a grid.
        ax.axhline(price, color=th.INK_SECONDARY, linestyle="--", linewidth=1.2,
                   zorder=5, label=f"current price {price:,.2f}")
        upside = (dcf_base / price - 1) * 100
        th.style_axes(
            ax, title=f"{ticker} — DCF scenarios vs price",
            subtitle=f"base case implies {upside:+.0f}% vs {price:,.2f} {currency}",
            ylabel=f"Intrinsic value ({currency})", legend_row=True,
        )
        th.legend_above(ax, ncol=3)
        fig.tight_layout()
        th.save(fig, outfile)
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

        # Forecast is the SAME entity extended, so it keeps the series hue (a
        # lighter step) and lets the hatch carry "estimated" — a separate colour
        # would read as a fourth series.
        # --- top: EBITDA bars ---
        if seg_annual:
            ax_e.bar(seg_annual, a_ebitda[:n_a], color="#cfcdc5",
                     width=th.BAR_WIDTH, label="EBITDA (annual FY)")
        if seg_hist:
            ax_e.bar(seg_hist, ebitda, color=th.PRIMARY, width=th.BAR_WIDTH,
                     label="EBITDA (quarterly)")
        if seg_fc:
            ax_e.bar(seg_fc, f_ebitda, color=th.PRIMARY_LIGHT, width=th.BAR_WIDTH,
                     hatch="//", edgecolor=th.PRIMARY, linewidth=0.6,
                     label="EBITDA (forecast)")
        # Trailing-twelve-month trend over the quarterly bars. Fiscal seasonality
        # makes the raw quarters a sawtooth; without this the eye reads noise and
        # misses the decade-long compounding that is the whole point of the chart.
        if seg_hist and len(seg_hist) >= 4:
            ttm_e = th.trailing_avg(ebitda)
            pts = [(seg_hist[i], v) for i, v in enumerate(ttm_e) if v is not None]
            if pts:
                ax_e.plot([x for x, _ in pts], [y for _, y in pts], color=th.INK,
                          linewidth=2.0, zorder=6, solid_capstyle="round",
                          label="TTM ÷ 4 (trend)")

        # Title lives on the figure, not the axes: `legend_above` claims the strip
        # directly above ax_e, and an axes title would sit underneath it.
        _title = f"{fin_history.get('ticker', '')} — EBITDA & free cash flow".lstrip(" —")
        _subtitle = (f"{n_q} quarters of history · source {source}"
                     + (" · dark line = trailing-twelve-month average"
                        if seg_hist and len(seg_hist) >= 4 else ""))
        th.style_axes(ax_e, ylabel=f"EBITDA ({currency})")
        ax_e.yaxis.set_major_formatter(fmt)
        th.legend_above(ax_e, ncol=4)
        if seg_hist:
            last = _last_valid(ebitda)
            if last is not None:
                th.value_chip(ax_e, seg_hist[last], ebitda[last],
                              _money_fmt(ebitda[last]), th.PRIMARY)

        # --- bottom: FCF line + markers ---
        if seg_annual:
            ax_f.plot(seg_annual, a_fcf[:n_a], color="#b8b6ad", linewidth=1.4,
                      linestyle=":", label="FCF (annual FY)")
        if seg_hist:
            # Area fill gives the FCF panel the same visual weight as the bar panel
            # above it; a bare line reads as secondary next to a block of bars.
            ax_f.fill_between(seg_hist, 0, fcf, color=th.AQUA, alpha=0.15,
                              linewidth=0, zorder=2)
            ax_f.plot(seg_hist, fcf, color=th.AQUA, label="FCF (quarterly)",
                      zorder=4, **th.marker_kwargs(th.AQUA))
        if seg_fc:
            join_x = ([seg_hist[-1]] + seg_fc) if seg_hist else seg_fc
            join_y = ([fcf[-1]] + f_fcf) if seg_hist else f_fcf
            ax_f.plot(join_x, join_y, color=th.AQUA, linestyle="--", zorder=3,
                      label="FCF (forecast)", **th.marker_kwargs(th.AQUA))
        if seg_hist and len(seg_hist) >= 4:
            ttm_f = th.trailing_avg(fcf)
            pts = [(seg_hist[i], v) for i, v in enumerate(ttm_f) if v is not None]
            if pts:
                ax_f.plot([x for x, _ in pts], [y for _, y in pts], color=th.INK,
                          linewidth=2.0, zorder=6, solid_capstyle="round",
                          label="TTM ÷ 4 (trend)")
        ax_f.axhline(0, color=th.AXIS, linewidth=0.8, zorder=1)
        th.style_axes(ax_f, ylabel=f"FCF ({currency})")
        ax_f.yaxis.set_major_formatter(fmt)
        th.legend_above(ax_f, ncol=4)
        if seg_hist:
            last = _last_valid(fcf)
            if last is not None:
                th.value_chip(ax_f, seg_hist[last], fcf[last],
                              _money_fmt(fcf[last]), th.AQUA)

        # forecast shaded region + basis caption
        if seg_fc:
            left, right = seg_fc[0] - 0.5, seg_fc[-1] + 0.5
            for ax in (ax_e, ax_f):
                ax.axvspan(left, right, color=th.PRIMARY, alpha=0.05,
                           linewidth=0, zorder=0)
                # A tint alone is easy to miss at report scale; the rule makes the
                # actual/estimate boundary unmissable.
                ax.axvline(left, color=th.INK_MUTED, linewidth=1.0,
                           linestyle=(0, (3, 3)), zorder=7)
            cap = _FORECAST_BASIS_LABELS.get(basis, basis or "forecast")
            th.caption(ax_f, f"shaded tail = forecast · basis: {cap}")

        # Year ticks, horizontal. 40 quarters at 45° is 20 rotated labels doing the
        # work four horizontal ones do — the year is the only granularity a reader
        # navigates by. Falls back to the old thinned-label scheme when the labels
        # are not fiscal quarters (annual-only sources).
        ticks = [i for i, lbl in enumerate(all_labels) if str(lbl).endswith("Q1")]
        if len(ticks) >= 3:
            ax_f.set_xticks(ticks)
            ax_f.set_xticklabels([str(all_labels[i])[:4] for i in ticks],
                                 rotation=0, fontsize=9)
        else:
            ax_f.set_xticks(xs)
            step = max(1, len(all_labels) // 16)
            ax_f.set_xticklabels(
                [lbl if i % step == 0 else "" for i, lbl in enumerate(all_labels)],
                rotation=45, ha="right", fontsize=8,
            )
        # tight_layout first (it resolves label/axes overlap), then claim the top
        # band for the figure title — tight_layout would otherwise reclaim it.
        fig.tight_layout()
        th.figure_title(fig, _title, _subtitle)
        th.save(fig, out_path)
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
        bars = ax_ni.bar(xs, ni, color=th.PRIMARY, width=th.BAR_WIDTH,
                         label=f"Net income (annual, {currency})")
        ax_ni.axhline(0, color=th.AXIS, linewidth=0.8, zorder=1)
        th.style_axes(
            ax_ni, title=f"{ticker} — net income vs own-history P/E",
            subtitle="two scales: bars read on the left axis, the P/E line on the right",
            ylabel=f"Net income ({currency})", legend_row=True,
        )
        ax_ni.yaxis.set_major_formatter(FuncFormatter(_money_fmt))

        ax_pe = ax_ni.twinx()
        ax_pe.plot(xs, pe, color=th.ACCENT, label="P/E (FY mean price / EPS)",
                   zorder=4, **th.marker_kwargs(th.ACCENT))
        ax_pe.set_ylabel("P/E (×)", color=th.INK_SECONDARY)
        ax_pe.grid(False)
        for side in ("top", "left"):
            ax_pe.spines[side].set_visible(False)
        # The right spine and its ticks are MARKS, so they may carry the series
        # colour to bind axis to line; the label text stays in ink.
        ax_pe.spines["right"].set_visible(True)
        ax_pe.spines["right"].set_color(th.ACCENT)
        ax_pe.spines["right"].set_linewidth(1.2)
        ax_pe.tick_params(axis="y", colors=th.ACCENT, labelcolor=th.INK_MUTED,
                          length=3)

        ax_ni.set_xticks(xs)
        ax_ni.set_xticklabels([f"FY{y}" for y in years], rotation=45, ha="right",
                              fontsize=8)
        lines_ni, labels_ni = ax_ni.get_legend_handles_labels()
        lines_pe, labels_pe = ax_pe.get_legend_handles_labels()
        th.legend_above(ax_ni, ncol=2, handles=lines_ni + lines_pe,
                        labels=labels_ni + labels_pe)
        fig.tight_layout()
        th.save(fig, out_path)
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
        fig, ax = plt.subplots(figsize=(11, 5.5))
        # The subject leads; the benchmark recedes to grey; the sector proxy takes
        # the next categorical slot. Colour follows the entity, not the ranking.
        style = {
            "ticker": dict(color=th.PRIMARY, linewidth=2.4, zorder=4),
            "bench": dict(color="#b8b6ad", linewidth=1.6, zorder=2),
            "etf": dict(color=th.ACCENT, linewidth=1.6, zorder=3),
        }
        drawn = False
        ends = []  # (x, y, label, colour) for direct end labels
        for key in ("ticker", "bench", "etf"):
            if key not in series:
                continue
            sym, s = series[key]
            s = s[s.index >= start]
            if s.empty or float(s.iloc[0]) <= 0:
                continue
            norm = s / float(s.iloc[0]) * 100.0
            ax.plot(norm.index, norm.values, label=sym, **style[key])
            ends.append((norm.index[-1], float(norm.iloc[-1]), sym, style[key]["color"]))
            drawn = True
        if not drawn:
            plt.close(fig)
            return False

        # Dashed is deliberate: 100 is the common-base threshold, not a gridline.
        ax.axhline(100, color=th.AXIS, linewidth=1.0, linestyle="--", zorder=1)
        subject_end = next((e for e in ends if e[2] == ticker), None)
        subtitle = "all series indexed to 100 at the common start date"
        if subject_end:
            subtitle = (f"{ticker} at {subject_end[1]:,.0f} vs base 100 · "
                        f"all series indexed to the common start date")
        th.style_axes(ax, title=f"{ticker} — relative performance, 2.5 years",
                      subtitle=subtitle, ylabel="Indexed to 100 at start",
                      legend_row=True)
        # Direct end labels — with only 2-3 series they carry identity better than
        # a legend, which is kept as the dependable second channel.
        for x, y, sym, color in ends:
            th.label_line_end(ax, x, y, sym, color)
        ax.margins(x=0.06)
        th.legend_above(ax, ncol=3)

        notes = []
        if bench_is_fallback:
            notes.append(f"benchmark {bench} (fallback — no region index mapped)")
        if not sector or sector not in SECTOR_ETF:
            notes.append("sector proxy n/a")
        elif etf:
            notes.append(f"sector proxy {etf} (US sector ETF)")
        if notes:
            th.caption(ax, "  ·  ".join(notes))
        fig.tight_layout()
        th.save(fig, out_path)
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
        # Leave 20% of the group as air, then shave each bar so touching
        # neighbours are separated by surface, not by a drawn edge.
        fig, ax = plt.subplots(figsize=(11, 5.5))
        # Cap the bar thickness, then pack the group symmetrically around its tick:
        # a fixed gap of surface between neighbours does the separating, and the
        # whole group re-centres on the year label whatever the series count.
        width = th.cap_bar_width(ax, 0.8 / max(1, n_series) * 0.86, 3)
        gap = width * 0.18
        pitch = width + gap
        group_w = pitch * n_series - gap
        last_bars = []
        for i, (name, vals) in enumerate(rows):
            offs = x - group_w / 2 + width / 2 + i * pitch
            plotvals = [0 if math.isnan(v) else v for v in vals]
            # Fixed slot order, never cycled — `rows` is already capped at 6
            # (top-5 segments + "Other"), well inside the 8 available slots.
            bars = ax.bar(offs, plotvals, width=width, label=name,
                          color=th.SERIES[i % len(th.SERIES)])
            last_bars.append((bars[-1], plotvals[-1]))
        ax.set_xticks(x)
        ax.set_xticklabels(fy)
        th.style_axes(
            ax, title="Revenue by segment",
            subtitle=f"three fiscal years · top {min(5, len(segs))} segments"
                     + (" + Other" if len(segs) > 5 else ""),
            ylabel=f"Revenue ({currency})", legend_row=True,
        )
        ax.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
        th.legend_above(ax, ncol=3)
        # Latest-year values labelled directly: the relief the lighter slots owe
        # for sitting below 3:1 contrast against the surface.
        for bar, val in last_bars:
            if not val:
                continue
            ax.annotate(_money_fmt(val), xy=(bar.get_x() + bar.get_width() / 2, val),
                        xytext=(0, 4), textcoords="offset points", ha="center",
                        va="bottom", fontsize=8, color=th.INK_SECONDARY)
        th.caption(ax, "Source: company filings (LLM-extracted) — verify against source",
                   color=th.CRITICAL)
        fig.tight_layout()
        th.save(fig, out_path)
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
