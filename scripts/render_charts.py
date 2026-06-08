r"""
render_charts.py — Generates PNG charts for a deep-dive report.

Produces 4 PNGs in C:\BD_Obsidian\Personal\Finance\StocksDaily\IMG\:
 - {date}_{ticker}_price.png  : 1Y price + SMA50/200 + volume
 - {date}_{ticker}_radar.png  : 7-axis radar score (incl. Management Quality)
 - {date}_{ticker}_peers.png  : peer comparison bar (placeholder if peer_info not provided)
 - {date}_{ticker}_dcf.png    : DCF bear/base/bull fan

Input: --ticker, optional --analysis-json (stdin fallback) with composite breakdown.
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

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402


DEFAULT_IMG_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily\IMG")


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def safe_ticker_filename(ticker: str) -> str:
    return ticker.replace("/", "_").replace("\\", "_")


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

    print(json.dumps({
        "ticker": args.ticker,
        "img_dir": str(img_dir),
        "stem": stem,
        "charts": results,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
