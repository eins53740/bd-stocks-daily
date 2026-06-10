"""
live_prices.py — Fetch live prices for the dashboard's Technical buy-range check.

Called by build_dashboard.py (subprocess, non-fatal) with the tickers that carry a
technical read. Writes _live_prices.json; the stdlib dashboard only reads the file.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

OUT_DEFAULT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily") / "_live_prices.json"


def fetch_price(tk) -> float | None:
    try:
        px = tk.fast_info["last_price"]
        if px:
            return round(float(px), 4)
    except Exception:
        pass
    try:
        px = (tk.info or {}).get("regularMarketPrice")
        return round(float(px), 4) if px else None
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", required=True, help="comma-separated ticker list")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    args = ap.parse_args()

    import yfinance as yf

    prices: dict[str, float] = {}
    for t in [x.strip() for x in args.tickers.split(",") if x.strip()]:
        px = fetch_price(yf.Ticker(t))
        if px is not None:
            prices[t] = px
        else:
            print(f"WARN: no live price for {t}", file=sys.stderr)

    Path(args.out).write_text(
        json.dumps(
            {
                "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "prices": prices,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"wrote {args.out} ({len(prices)} prices)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
