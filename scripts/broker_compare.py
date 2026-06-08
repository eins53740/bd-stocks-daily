"""
broker_compare.py — Broker cost comparator (Phase 8).

Reads the curated reference data in ``brokers.yaml`` and, for the spec's seven
example markets, computes the **total round-trip cost** (buy + sell) of a trade
per broker — EXCLUDING brokers that do not offer that market — at two
representative trade sizes (small vs large). It then emits, per market:

  * a cost matrix (broker -> {small, large} total round-trip cost in EUR), and
  * a broker recommendation per investor profile (small frequent trader vs
    large buy-and-hold), with the cheapest applicable broker for each.

Writes ``_brokers.json`` for the dashboard and prints a readable summary.

Pure / network-free by design. The cost-math helpers are PURE (no I/O) so the
Phase-8 unit tests exercise them directly. The only "parsing" is a tiny,
purpose-built YAML reader for the fixed shape of ``brokers.yaml`` (stdlib-only,
consistent with build_dashboard.py's no-dependency contract).

Trade sizes (documented):
  * SMALL = EUR 1,000   — a frequent retail buy, fixed minimums dominate.
  * LARGE = EUR 25,000  — a buy-and-hold position, percentage fees dominate.

Cost-formula components, per leg (buy and sell each counted once):
    leg_cost = max(commission_min, notional * commission_pct/100,
                   capped at commission_max if set)
             + flat_fee
             + notional * fx_fee_pct/100        (only if market currency != base currency)
  round_trip = leg_cost(buy) + leg_cost(sell)
Per-applicable *recurring* fees (custody/market-data/dividend) are reported as
context notes but NOT folded into the round-trip number — they are annual or
event-based, not per-trade.

Usage:
  python broker_compare.py                 # compute, write _brokers.json, print summary
  python broker_compare.py --out FILE       # override output path
  python broker_compare.py --yaml FILE      # override brokers.yaml path
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

SCRIPT_DIR = Path(__file__).resolve().parent
YAML_PATH = SCRIPT_DIR / "brokers.yaml"
ROOT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
OUT_JSON = ROOT / "_brokers.json"

# Representative trade sizes in EUR (documented in the module docstring).
SMALL_EUR = 1_000.0
LARGE_EUR = 25_000.0

# The seven example markets the spec asks for, in display order.
MARKET_ORDER = ["US", "IE", "PT", "TW", "HK", "JP", "CN_SZ"]


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ----------------------------------------------------------------------------
# PURE cost math (unit-tested — no I/O)
# ----------------------------------------------------------------------------

def leg_cost(notional: float, market_fee: dict, fx_fee_pct: float, fx_applies: bool) -> float:
    """Cost of ONE leg (a buy or a sell) in EUR.

    commission = max(commission_min, notional * commission_pct/100), then
    capped at commission_max when that cap is set (non-null). flat_fee is added
    on top. FX conversion cost is added only when ``fx_applies`` (market
    currency differs from the broker's base currency).
    """
    pct = float(market_fee.get("commission_pct") or 0.0)
    cmin = float(market_fee.get("commission_min") or 0.0)
    cmax = market_fee.get("commission_max")
    flat = float(market_fee.get("flat_fee") or 0.0)

    commission = notional * pct / 100.0
    if commission < cmin:
        commission = cmin
    if cmax is not None and commission > float(cmax):
        commission = float(cmax)

    fx = (notional * float(fx_fee_pct or 0.0) / 100.0) if fx_applies else 0.0
    return commission + flat + fx


def round_trip_cost(notional: float, market_fee: dict, fx_fee_pct: float, fx_applies: bool) -> float:
    """Total buy+sell round-trip cost in EUR (two legs at the same notional)."""
    return 2.0 * leg_cost(notional, market_fee, fx_fee_pct, fx_applies)


def fx_applies(market_currency: str, base_currency: str) -> bool:
    """FX conversion cost applies when the market trades in a currency other
    than the broker's base/funding currency."""
    return (market_currency or "").upper() != (base_currency or "").upper()


def brokers_for_market(brokers: dict, market_key: str) -> list[str]:
    """Broker ids that actually offer ``market_key`` (have a fee block for it).
    Brokers without the market are EXCLUDED — this is the market-exclusion
    logic the tests assert (a PT-only broker must not surface for Taiwan)."""
    out = []
    for bid, b in brokers.items():
        markets = (b or {}).get("markets") or {}
        if market_key in markets:
            out.append(bid)
    return out


def cost_matrix_for_market(
    brokers: dict, market_key: str, market_currency: str,
    small_eur: float, large_eur: float,
) -> list[dict]:
    """Per-applicable-broker round-trip cost at small & large sizes for one market.

    Returns a list of rows sorted by the small-size cost ascending (cheapest
    first), each:
      {broker, name, small, large, fx_applies, notes:{...}}
    """
    rows = []
    for bid in brokers_for_market(brokers, market_key):
        b = brokers[bid]
        mf = b["markets"][market_key]
        base = b.get("base_currency") or "EUR"
        fxa = fx_applies(market_currency, base)
        fxp = float(b.get("fx_fee_pct") or 0.0)
        rows.append({
            "broker": bid,
            "name": b.get("name") or bid,
            "small": round(round_trip_cost(small_eur, mf, fxp, fxa), 2),
            "large": round(round_trip_cost(large_eur, mf, fxp, fxa), 2),
            "fx_applies": fxa,
            "approx": bool(mf.get("approx")),
            "as_of": mf.get("as_of"),
            "notes": {
                "custody_fee": b.get("custody_fee"),
                "market_data_fee": mf.get("market_data_fee"),
                "dividend_fee": mf.get("dividend_fee"),
                "other_costs": mf.get("other_costs"),
                "source": mf.get("source"),
            },
        })
    rows.sort(key=lambda r: r["small"])
    return rows


def recommend(rows: list[dict]) -> dict:
    """Recommendation per investor profile from a market's cost rows.

    * small frequent trader  -> minimise the SMALL round-trip cost.
    * large buy-and-hold     -> minimise the LARGE round-trip cost.
    Returns {} when no broker serves the market. The two picks can differ —
    that small-vs-large flip is exactly what the unit tests assert.
    """
    if not rows:
        return {}
    best_small = min(rows, key=lambda r: r["small"])
    best_large = min(rows, key=lambda r: r["large"])
    return {
        "small_frequent_trader": {
            "broker": best_small["broker"],
            "name": best_small["name"],
            "cost": best_small["small"],
        },
        "large_buy_and_hold": {
            "broker": best_large["broker"],
            "name": best_large["name"],
            "cost": best_large["large"],
        },
    }


def support_matrix(brokers: dict, market_order: list[str]) -> dict:
    """{broker -> {market -> bool}} coverage table for the dashboard."""
    out = {}
    for bid, b in brokers.items():
        markets = (b or {}).get("markets") or {}
        out[bid] = {m: (m in markets) for m in market_order}
    return out


# ----------------------------------------------------------------------------
# Tiny purpose-built YAML reader (fixed shape of brokers.yaml; stdlib-only)
# ----------------------------------------------------------------------------

def _coerce(val: str):
    """Coerce a scalar YAML token to bool/int/float/None/str."""
    v = val.strip()
    if v == "" or v == "null" or v == "~":
        return None
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        if "." in v or "e" in low:
            return float(v)
        return int(v)
    except ValueError:
        return v


def _strip_comment(line: str) -> str:
    """Remove a trailing ' #...' comment that is not inside quotes."""
    out = []
    in_s = in_d = False
    i = 0
    while i < len(line):
        c = line[i]
        if c == "'" and not in_d:
            in_s = not in_s
        elif c == '"' and not in_s:
            in_d = not in_d
        elif c == "#" and not in_s and not in_d:
            # comment starts only if preceded by whitespace or line start
            if i == 0 or line[i - 1] in " \t":
                break
        out.append(c)
        i += 1
    return "".join(out)


def _parse_inline_map(s: str) -> dict:
    """Parse a single-line flow map like { label: "x", currency: USD }."""
    s = s.strip()
    if s.startswith("{"):
        s = s[1:]
    if s.endswith("}"):
        s = s[:-1]
    out = {}
    # split on commas not inside quotes
    parts, cur, in_s, in_d = [], [], False, False
    for c in s:
        if c == "'" and not in_d:
            in_s = not in_s
        elif c == '"' and not in_s:
            in_d = not in_d
        if c == "," and not in_s and not in_d:
            parts.append("".join(cur)); cur = []
        else:
            cur.append(c)
    if cur:
        parts.append("".join(cur))
    for p in parts:
        if ":" not in p:
            continue
        k, _, v = p.partition(":")
        out[k.strip()] = _coerce(v)
    return out


def load_brokers_yaml(path: Path) -> dict:
    """Parse the fixed-shape brokers.yaml into a Python dict.

    Supports exactly the constructs the file uses: nested 2-space-indented
    mappings, scalar values, inline ``{ ... }`` flow maps, and full-line/
    trailing comments. Not a general YAML parser.
    """
    root: dict = {}
    # stack of (indent, container)
    stack: list[tuple[int, dict]] = [(-1, root)]

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        if ":" not in content:
            continue
        key, _, val = content.partition(":")
        key = key.strip()
        val = val.strip()

        # pop to parent at this indent level
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]

        if val == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        elif val.startswith("{"):
            parent[key] = _parse_inline_map(val)
        else:
            parent[key] = _coerce(val)

    return root


# ----------------------------------------------------------------------------
# Build bundle + I/O
# ----------------------------------------------------------------------------

def build_bundle(data: dict, small_eur: float = SMALL_EUR, large_eur: float = LARGE_EUR) -> dict:
    """Compute the full _brokers.json bundle from parsed YAML data."""
    brokers = data.get("brokers") or {}
    meta = data.get("markets_meta") or {}

    markets_out = []
    for mk in MARKET_ORDER:
        m_meta = meta.get(mk) or {}
        currency = m_meta.get("currency") or "EUR"
        rows = cost_matrix_for_market(brokers, mk, currency, small_eur, large_eur)
        markets_out.append({
            "key": mk,
            "label": m_meta.get("label") or mk,
            "currency": currency,
            "region": m_meta.get("region"),
            "n_brokers": len(rows),
            "rows": rows,
            "recommendation": recommend(rows),
        })

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "today": dt.date.today().isoformat(),
        "trade_sizes": {"small_eur": small_eur, "large_eur": large_eur},
        "n_brokers": len(brokers),
        "broker_profiles": {
            bid: {"name": b.get("name") or bid, "profile": b.get("profile"),
                  "base_currency": b.get("base_currency"), "fx_fee_pct": b.get("fx_fee_pct"),
                  "custody_fee": b.get("custody_fee")}
            for bid, b in brokers.items()
        },
        "support_matrix": support_matrix(brokers, MARKET_ORDER),
        "markets": markets_out,
        "caveat": ("Fee schedules change often and many figures are estimates "
                   "(approx). Verify on the broker's live tariff page before acting. "
                   "Recurring custody/market-data/dividend fees are reported as "
                   "context, not folded into the per-trade round-trip cost."),
    }


def print_summary(bundle: dict) -> None:
    ts = bundle["trade_sizes"]
    print("=" * 72)
    print(f"Broker cost comparison — {bundle['n_brokers']} brokers · "
          f"small EUR {ts['small_eur']:,.0f} / large EUR {ts['large_eur']:,.0f}")
    print("=" * 72)

    # Support matrix
    print("\nMarket-support matrix (broker × market):")
    hdr = "  {:<16}".format("broker") + "".join(f"{m:>7}" for m in MARKET_ORDER)
    print(hdr)
    for bid, cov in bundle["support_matrix"].items():
        cells = "".join(("   ✓  " if cov[m] else "   -  ") for m in MARKET_ORDER)
        print("  {:<16}".format(bid) + cells)

    # Per-market cost matrix + recommendation
    for m in bundle["markets"]:
        print(f"\n── {m['label']} [{m['currency']}] — {m['n_brokers']} applicable broker(s) ──")
        if not m["rows"]:
            print("   (no broker in the set trades this market)")
            continue
        print("   {:<16}{:>12}{:>12}  {}".format("broker", "small EUR", "large EUR", "fx?"))
        for r in m["rows"]:
            flag = " ~" if r["approx"] else ""
            print("   {:<16}{:>12.2f}{:>12.2f}  {}{}".format(
                r["broker"], r["small"], r["large"], "yes" if r["fx_applies"] else "no", flag))
        rec = m["recommendation"]
        if rec:
            sf = rec["small_frequent_trader"]; lh = rec["large_buy_and_hold"]
            print(f"   → small frequent trader: {sf['broker']} (EUR {sf['cost']:.2f} round-trip)")
            print(f"   → large buy-and-hold:    {lh['broker']} (EUR {lh['cost']:.2f} round-trip)")
    print("\n(~ = figure is an estimate; verify before acting.)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", default=str(YAML_PATH))
    ap.add_argument("--out", default=str(OUT_JSON))
    ap.add_argument("--small", type=float, default=SMALL_EUR)
    ap.add_argument("--large", type=float, default=LARGE_EUR)
    args = ap.parse_args()

    yaml_path = Path(args.yaml)
    if not yaml_path.exists():
        log(f"ERROR: brokers.yaml not found at {yaml_path}")
        return 1

    data = load_brokers_yaml(yaml_path)
    bundle = build_bundle(data, args.small, args.large)

    out_path = Path(args.out)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"Wrote {out_path}")
    except OSError as e:
        log(f"WARN: could not write {out_path}: {e}")

    print_summary(bundle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
