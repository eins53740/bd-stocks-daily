"""
portfolio_sync.py — Phase 4 step 1.

Read live equity holdings from the BankBD SQLite DB (READ-ONLY), map tickers to
their canonical Yahoo symbol via ``canon()`` (reused from portfolio_deepdive_gap.py),
skip non-equity holdings via ``classify_nonequity()``, fetch live prices from
yfinance, reconcile against the stored last market value, and emit a JSON bundle.

While BankBD's positions table is empty, a Yahoo Finance portfolio export can be
used instead (``--csv``); the DB path also auto-falls-back to DEFAULT_CSV when it
finds zero positions. Lot rows (Quantity set) aggregate per symbol; watchlist
rows are skipped. Market values are converted to EUR via markets.to_eur() so
weights are currency-correct.

The BankBD DB is opened with the SQLite URI ``file:...?mode=ro`` and is NEVER
written to. Verify byte-identity before/after if you need proof.

Output (stdout): JSON bundle of per-holding dicts. A human summary goes to stderr.

Usage:
  python portfolio_sync.py                      # real BankBD DB -> JSON on stdout
  python portfolio_sync.py --db PATH            # override DB path (testing)
  python portfolio_sync.py --csv [PATH]         # Yahoo Finance export instead of BankBD
  python portfolio_sync.py --no-prices          # skip yfinance (use stored value)
  python portfolio_sync.py --out FILE           # also write the JSON to FILE
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import markets  # noqa: E402 — sibling module (suffix -> currency, EUR FX)

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

# Interim holdings source while BankBD's positions table is empty: a Yahoo Finance
# portfolio export. Auto-fallback target when the DB yields zero positions.
DEFAULT_CSV = Path(r"C:\Users\bsdias\Downloads\portfolio.csv")

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


def fetch_holdings_csv(csv_path: Path) -> list[dict]:
    """Read a Yahoo Finance portfolio export. Lot rows (Quantity set) are positions;
    bare rows are watchlist entries and are skipped. Lots aggregate per symbol:
    quantity summed, buy price quantity-weighted over the lots that carry one.
    Returns rows shaped like fetch_holdings() so reconcile() works unchanged."""
    lots: dict[str, dict] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sym = (row.get("Symbol") or "").strip()
            qty = _safe_float(row.get("Quantity"))
            if not sym or not qty:
                continue
            buy = _safe_float(row.get("Purchase Price"))
            px = _safe_float(row.get("Current Price"))
            d = (row.get("Date") or "").strip().replace("/", "-")
            slot = lots.setdefault(sym, {"qty": 0.0, "cost": 0.0, "cost_qty": 0.0, "px": None, "date": None})
            slot["qty"] += qty
            if buy is not None:
                slot["cost"] += buy * qty
                slot["cost_qty"] += qty
            if px is not None:
                slot["px"] = px
            if d:
                slot["date"] = d
    rows: list[dict] = []
    for sym, s in sorted(lots.items()):
        rows.append({
            "position_id": None,
            "ticker": sym,
            "exchange": None,
            "quantity": s["qty"],
            "avg_buy_price": s["cost"] / s["cost_qty"] if s["cost_qty"] else None,
            "currency": markets.currency_of(sym),
            "asset_type": "stock",  # reconcile()'s classify_nonequity() does the real filtering
            "account_name": "Yahoo CSV",
            "account_type": "csv",
            "value_date": s["date"],
            "stored_price": s["px"],
            "stored_value_eur": None,
            "stored_pnl": None,
        })
    return rows


def _safe_float(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def fetch_eur_rates(currencies: set[str]) -> dict[str, float]:
    """EUR->currency quotes (units of `currency` per 1 EUR) via yfinance, used to
    convert native market values to EUR. EUR itself needs no rate."""
    pairs = {c: p for c in currencies if (p := markets.eur_fx_pair(c))}
    quotes = fetch_live_prices(list(pairs.values()))
    return {c: quotes[p] for c, p in pairs.items() if p in quotes}


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


def reconcile(rows: list[dict], live: dict[str, float], fx: dict[str, float] | None = None) -> list[dict]:
    """Build per-holding dicts; classify, map, value, compute weights.

    `fx` maps currency -> units per 1 EUR (from fetch_eur_rates). When given,
    natively-priced market values are converted to EUR so weights don't mix
    currencies; without it, native values pass through unchanged (legacy)."""
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
        # Original listing first: its quote currency matches `currency`. The canon
        # symbol may be a cross-listing in another currency (SHELL.AS -> SHEL.L
        # quotes in GBp and would distort the EUR value 100x), so when the quote
        # falls back to the canon symbol, re-derive the currency from ITS market.
        live_price = live.get(ticker)
        price_symbol = ticker
        if live_price is None and live.get(cticker) is not None:
            live_price = live.get(cticker)
            price_symbol = cticker
        currency = (r["currency"] or "EUR").upper()
        if live_price is not None:
            if price_symbol != ticker:
                currency = (markets.market_meta(price_symbol)["currency"] or currency).upper()
            # LSE quotes come in pence (GBp) — collapse to GBP before EUR conversion.
            if markets.suffix_of(price_symbol) == "L" and currency in ("GBP", "GBX"):
                live_price, currency = markets.normalize_gbx(live_price, "GBp")

        # Market value: live price * qty, else stored EUR value, else CSV's last
        # quote * qty. Track whether the figure is native-currency or already EUR.
        stored_value = r["stored_value_eur"]
        if live_price is not None:
            market_value = live_price * qty
            value_currency = currency
        elif stored_value not in (None, ""):
            market_value = float(stored_value)
            value_currency = "EUR"
        elif r["stored_price"] not in (None, ""):
            market_value = float(r["stored_price"]) * qty
            value_currency = currency
        else:
            market_value = None
            value_currency = currency
        if fx is not None and market_value is not None and value_currency != "EUR":
            market_value = markets.to_eur(market_value, value_currency, fx.get(value_currency))

        # P&L must land in the same currency as market_value (EUR when fx given).
        # stored_pnl comes from BankBD already in EUR; the live-computed one is native.
        if live_price is not None and avg not in (None, ""):
            unrealized_pnl = (live_price - float(avg)) * qty
            if fx is not None and currency != "EUR":
                unrealized_pnl = markets.to_eur(unrealized_pnl, currency, fx.get(currency))
        else:
            unrealized_pnl = float(r["stored_pnl"]) if r["stored_pnl"] not in (None, "") else None

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
            "unrealized_pnl": unrealized_pnl,
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
    ap.add_argument("--csv", nargs="?", const=str(DEFAULT_CSV), default=None,
                    help="read holdings from a Yahoo Finance portfolio export instead of BankBD")
    ap.add_argument("--no-prices", action="store_true", help="skip yfinance live prices")
    ap.add_argument("--out", default=None, help="optional path to also write the JSON bundle")
    args = ap.parse_args()

    db_path = Path(args.db)
    csv_path = Path(args.csv) if args.csv else None
    rows: list[dict] = []

    if csv_path is None:
        if not db_path.exists():
            log(f"ERROR: BankBD DB not found at {db_path}")
            return 1
        log(f"Opening BankBD READ-ONLY: {ro_uri(db_path)}")
        rows = fetch_holdings(db_path)
        log(f"Positions in DB (qty != 0): {len(rows)}")
        if not rows and DEFAULT_CSV.exists():
            log(f"BankBD positions table is empty — falling back to CSV export {DEFAULT_CSV}")
            csv_path = DEFAULT_CSV

    if csv_path is not None:
        if not csv_path.exists():
            log(f"ERROR: portfolio CSV not found at {csv_path}")
            return 1
        rows = fetch_holdings_csv(csv_path)
        log(f"Positions in CSV (lots aggregated per symbol): {len(rows)}")

    # Build the equity symbol set for price fetch (canonical Yahoo symbols).
    eq_syms = []
    for r in rows:
        t = (r["ticker"] or "").strip()
        if not t:
            continue
        if classify_nonequity(t) is None and (r["asset_type"] or "stock").lower() not in NON_EQUITY_ASSET_TYPES:
            eq_syms.append(t)        # original listing — currency-correct quote
            eq_syms.append(canon(t))  # canonical fallback if the original fails

    live = {} if args.no_prices else fetch_live_prices(eq_syms)
    if eq_syms and not args.no_prices:
        log(f"Live prices fetched: {len(live)}/{len(set(eq_syms))} symbols")

    # EUR conversion rates for natively-priced market values (weights must not mix currencies).
    currencies = {(r["currency"] or "EUR").upper() for r in rows}
    fx = None if args.no_prices else fetch_eur_rates(currencies)
    if fx:
        log("EUR FX rates: " + ", ".join(f"{c}={v:.4f}" for c, v in sorted(fx.items())))

    holdings = reconcile(rows, live, fx)
    bundle = build_bundle(holdings, csv_path or db_path)

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
        log("  (no positions found in the source — nothing to value)")

    out_json = json.dumps(bundle, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out_json, encoding="utf-8")
        log(f"Wrote {args.out}")
    print(out_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
