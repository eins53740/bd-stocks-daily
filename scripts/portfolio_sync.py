"""
portfolio_sync.py — Phase 4 step 1.

Read live equity holdings from the BankBD SQLite DB (READ-ONLY), map tickers to
their canonical Yahoo symbol via ``canon()`` (reused from portfolio_deepdive_gap.py),
skip non-equity holdings via ``classify_nonequity()``, fetch live prices from
yfinance, reconcile against the stored last market value, and emit a JSON bundle.

The BankBD DB is opened with the SQLite URI ``file:...?mode=ro`` and is NEVER
written to. Verify byte-identity before/after if you need proof.

Output (stdout): JSON bundle of per-holding dicts. A human summary goes to stderr.

Usage:
  python portfolio_sync.py                      # real BankBD DB -> JSON on stdout
  python portfolio_sync.py --db PATH            # override DB path (testing)
  python portfolio_sync.py --no-prices          # skip yfinance (use stored value)
  python portfolio_sync.py --out FILE           # also write the JSON to FILE
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

# --- Reuse canon() / classify_nonequity() from the gap script (locked decision) ---
_GAP = Path(r"C:\Github\.scripts\portfolio_deepdive_gap.py")


def _load_gap_helpers():
    """Import canon() and classify_nonequity() from portfolio_deepdive_gap.py.

    That script runs top-level I/O on import (reads portfolio.csv / _log.csv), so we
    can't simply ``import`` it. Instead we exec only the helper definitions by
    extracting the EQUIV_GROUPS / canon / classify_nonequity block. To stay robust we
    exec the source up to the "# --- Read portfolio symbols" sentinel, which is pure
    definitions with no file I/O.
    """
    src = _GAP.read_text(encoding="utf-8")
    sentinel = "# --- Read portfolio symbols"
    idx = src.find(sentinel)
    if idx == -1:
        raise RuntimeError(f"sentinel not found in {_GAP}; gap script layout changed")
    defs = src[:idx]
    ns: dict = {}
    exec(compile(defs, str(_GAP), "exec"), ns)  # noqa: S102 — trusted local file
    return ns["canon"], ns["classify_nonequity"]


canon, classify_nonequity = _load_gap_helpers()

# Canonical BankBD DB path (matches bankbd.config.database_url default: sqlite:///bankbd.db
# resolved against the repo root).
DEFAULT_DB = Path(r"C:\Github\BD\Finance\BankBD\bankbd.db")

# yfinance asset_type values that are NOT equities (belt-and-suspenders on top of
# classify_nonequity, which keys off the ticker string).
NON_EQUITY_ASSET_TYPES = {"crypto", "bond", "etf"}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def ro_uri(db_path: Path) -> str:
    """Return the read-only SQLite URI for a path (forward slashes, file: scheme)."""
    return "file:" + db_path.resolve().as_posix() + "?mode=ro"


def fetch_holdings(db_path: Path) -> list[dict]:
    """Read positions + their latest PositionValue from BankBD. READ-ONLY."""
    uri = ro_uri(db_path)
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        # Latest position_values row per position (by date), joined to positions+account.
        rows = conn.execute(
            """
            SELECT p.id            AS position_id,
                   p.ticker        AS ticker,
                   p.exchange      AS exchange,
                   p.quantity      AS quantity,
                   p.avg_buy_price AS avg_buy_price,
                   p.currency      AS currency,
                   p.asset_type    AS asset_type,
                   a.name          AS account_name,
                   a.type          AS account_type,
                   pv.date         AS value_date,
                   pv.market_price AS stored_price,
                   pv.market_value_eur AS stored_value_eur,
                   pv.unrealized_pnl   AS stored_pnl
            FROM positions p
            JOIN accounts a ON a.id = p.account_id
            LEFT JOIN (
                SELECT position_id, MAX(date) AS md
                FROM position_values GROUP BY position_id
            ) latest ON latest.position_id = p.id
            LEFT JOIN position_values pv
                   ON pv.position_id = p.id AND pv.date = latest.md
            WHERE p.quantity <> 0
            ORDER BY p.ticker
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetch_live_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch last close per Yahoo symbol via yfinance. Best-effort; missing -> absent."""
    if not symbols:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        log("WARN: yfinance not installed — skipping live prices.")
        return {}

    out: dict[str, float] = {}
    # Batch download (1d) is cheaper than per-ticker .info.
    try:
        data = yf.download(
            tickers=" ".join(sorted(set(symbols))),
            period="2d",
            interval="1d",
            progress=False,
            group_by="ticker",
            threads=True,
            auto_adjust=False,
        )
    except Exception as e:  # noqa: BLE001
        log(f"WARN: yfinance batch download failed ({e}); prices unavailable.")
        return {}

    syms = sorted(set(symbols))
    for s in syms:
        try:
            if len(syms) == 1:
                close = data["Close"]
            else:
                close = data[s]["Close"]
            series = close.dropna()
            if len(series):
                out[s] = float(series.iloc[-1])
        except Exception:  # noqa: BLE001
            continue
    return out


def reconcile(rows: list[dict], live: dict[str, float]) -> list[dict]:
    """Build per-holding dicts; classify, map, value, compute weights."""
    holdings: list[dict] = []
    for r in rows:
        ticker = (r["ticker"] or "").strip()
        if not ticker:
            continue
        asset_type = (r["asset_type"] or "stock").lower()
        ne = classify_nonequity(ticker)
        is_equity = ne is None and asset_type not in NON_EQUITY_ASSET_TYPES
        cticker = canon(ticker)

        qty = float(r["quantity"] or 0.0)
        avg = r["avg_buy_price"]
        cost_basis = float(avg) * qty if avg not in (None, "") else None
        live_price = live.get(cticker) or live.get(ticker)

        # Market value: prefer live price * qty if available; fall back to stored EUR value.
        stored_value = r["stored_value_eur"]
        if live_price is not None:
            market_value = live_price * qty
        elif stored_value not in (None, ""):
            market_value = float(stored_value)
        else:
            market_value = None

        holdings.append({
            "ticker": ticker,
            "canon_ticker": cticker,
            "account": r["account_name"],
            "account_type": r["account_type"],
            "asset_type": asset_type,
            "is_equity": is_equity,
            "non_equity_class": ne,
            "quantity": qty,
            "avg_buy_price": float(avg) if avg not in (None, "") else None,
            "cost_basis": cost_basis,
            "currency": r["currency"] or "EUR",
            "live_price": live_price,
            "stored_price": float(r["stored_price"]) if r["stored_price"] not in (None, "") else None,
            "stored_value_eur": float(stored_value) if stored_value not in (None, "") else None,
            "value_date": r["value_date"],
            "market_value": market_value,
            "unrealized_pnl": (
                (live_price - float(avg)) * qty
                if live_price is not None and avg not in (None, "")
                else (float(r["stored_pnl"]) if r["stored_pnl"] not in (None, "") else None)
            ),
        })

    # Portfolio weight over EQUITY market value only (the dashboard is an equity view).
    equity_total = sum(
        h["market_value"] for h in holdings if h["is_equity"] and h["market_value"]
    )
    for h in holdings:
        if h["is_equity"] and h["market_value"] and equity_total > 0:
            h["weight"] = h["market_value"] / equity_total
        else:
            h["weight"] = None
    return holdings


def build_bundle(holdings: list[dict], db_path: Path) -> dict:
    equities = [h for h in holdings if h["is_equity"]]
    equity_total = sum(h["market_value"] for h in equities if h["market_value"]) or 0.0
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_db": str(db_path),
        "n_positions": len(holdings),
        "n_equities": len(equities),
        "equity_market_value": equity_total,
        "holdings": holdings,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB), help="BankBD SQLite DB path (read-only)")
    ap.add_argument("--no-prices", action="store_true", help="skip yfinance live prices")
    ap.add_argument("--out", default=None, help="optional path to also write the JSON bundle")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        log(f"ERROR: BankBD DB not found at {db_path}")
        return 1

    log(f"Opening BankBD READ-ONLY: {ro_uri(db_path)}")
    rows = fetch_holdings(db_path)
    log(f"Positions in DB (qty != 0): {len(rows)}")

    # Build the equity symbol set for price fetch (canonical Yahoo symbols).
    eq_syms = []
    for r in rows:
        t = (r["ticker"] or "").strip()
        if not t:
            continue
        if classify_nonequity(t) is None and (r["asset_type"] or "stock").lower() not in NON_EQUITY_ASSET_TYPES:
            eq_syms.append(canon(t))

    live = {} if args.no_prices else fetch_live_prices(eq_syms)
    if eq_syms and not args.no_prices:
        log(f"Live prices fetched: {len(live)}/{len(set(eq_syms))} symbols")

    holdings = reconcile(rows, live)
    bundle = build_bundle(holdings, db_path)

    # Human summary.
    log("=" * 64)
    log(f"Portfolio sync — {bundle['n_positions']} positions, "
        f"{bundle['n_equities']} equities, equity MV €{bundle['equity_market_value']:,.0f}")
    log("=" * 64)
    for h in sorted(holdings, key=lambda x: -(x["market_value"] or 0)):
        kind = "equity" if h["is_equity"] else f"skip:{h['non_equity_class'] or h['asset_type']}"
        w = f"{h['weight']*100:5.1f}%" if h["weight"] else "   —  "
        mv = f"€{h['market_value']:,.0f}" if h["market_value"] else "—"
        lp = f"{h['live_price']:.2f}" if h["live_price"] else "—"
        log(f"  {h['ticker']:<12} -> {h['canon_ticker']:<10} {kind:<14} "
            f"qty={h['quantity']:<10g} px={lp:<10} mv={mv:<12} w={w}")
    if not holdings:
        log("  (no positions in BankBD — positions table is empty; nothing to value)")

    out_json = json.dumps(bundle, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out_json, encoding="utf-8")
        log(f"Wrote {args.out}")
    print(out_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
