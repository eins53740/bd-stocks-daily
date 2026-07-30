"""
buy_list.py — "Buy today" selection for the 17:00 digest.

Answers one question deterministically, with no LLM in the path: *of everything
evaluated and still valid, what is actually buyable at today's price, and what is
the most I should pay for it?*

Selection (all four must hold):
  1. composite >= BUY_FLOOR (the invest band — see the note on the floor below)
  2. the report has not expired (`days_left > 0`, i.e. inside the 90-day window)
  3. a **max entry price** can be stated
  4. the current price is at or below that max entry price

Max entry price, in precedence order:
  1. `fair_value_mid` — the 5-model intrinsic-value **blend**. "Never pay more than
     the central estimate." This is the same anchor the watch-list uses for its
     targets (changed from `fair_value_range.low` on 2026-07-30 because the low is
     one pessimistic model and put 21 of 24 targets out of reach), so the two
     sections can never contradict each other.
  2. the upper bound of the technical `entry_zone` — a price-anchored fallback for
     screens and v3 reports that carry no intrinsic-value block ("don't chase above
     the zone").
A name that clears the floor but yields neither is **excluded and counted**, never
silently dropped: the user asked for a max entry price per row, so a row without one
would be dishonest.

On the floor: BUY_FLOOR is 7.5 — the bottom of the `invest` verdict band. It is
deliberately ABOVE `watchlist.QUALITY_FLOOR` (7.0). A 7.0–7.4 name is `review`, not a
buy, so it belongs in the watch-list block and not here. Callers should say so rather
than let the reader infer a contradiction between two sections of one email.

`fair_price` is NOT used as an anchor: it can be a single surviving DCF, and on
2026-07-30 MSFT published $118.35 against a $390.54 price after its DCF cleared a
±70% sanity gate by 0.30pp. The blend is the honest central estimate.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Composite floor for a genuine buy = the bottom of the `invest` band.
BUY_FLOOR = 7.5

# Headroom below which a buy is flagged as a thin margin rather than a clean one.
THIN_MARGIN_PCT = 10.0

_NUM_RE = re.compile(r"\d[\d,]*\.?\d*")


def parse_entry_zone_high(zone) -> float | None:
    """Upper bound of an `entry_zone` frontmatter string.

    The stored separator varies (en dash, hyphen, and a mojibake byte when the file
    was written under a non-UTF-8 console), so the numbers are extracted rather than
    split on any one delimiter. Thousands separators are tolerated.
    """
    if zone is None:
        return None
    if isinstance(zone, (int, float)):
        return float(zone)
    found = [m.group(0).replace(",", "") for m in _NUM_RE.finditer(str(zone))]
    values = []
    for raw in found:
        try:
            values.append(float(raw))
        except ValueError:
            continue
    return max(values) if values else None


def max_entry(report: dict) -> tuple[float | None, str | None]:
    """(max_entry_price, basis) for one report. (None, None) when neither anchor exists."""
    mid = report.get("fair_value_mid")
    try:
        if mid is not None and float(mid) > 0:
            return float(mid), "fair-value blend"
    except (TypeError, ValueError):
        pass
    high = parse_entry_zone_high(report.get("entry_zone"))
    if high is not None and high > 0:
        return high, "technical entry zone"
    return None, None


def _rank(r: dict) -> tuple:
    """Latest date wins; within one date a deep report beats a same-day screen.

    The Phase-5.5 cascade writes both on one date, and the screen carries no
    intrinsic-value frontmatter — ranking it first would drop the max entry price.
    """
    return (r.get("date") or "", 1 if (r.get("mode") or "").lower() == "deep" else 0)


def latest_per_ticker(reports: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for r in reports or []:
        tk = r.get("ticker")
        if not tk:
            continue
        prev = best.get(tk)
        if prev is None or _rank(r) > _rank(prev):
            best[tk] = r
    return list(best.values())


def candidate_tickers(reports: list[dict], floor: float = BUY_FLOOR) -> list[str]:
    """Tickers whose live price the caller needs to fetch before select_buys().

    Exposed so the digest fetches prices once for exactly the names that can change
    the outcome, instead of the caller re-implementing the floor test.
    """
    out = []
    for r in latest_per_ticker(reports):
        try:
            if float(r.get("score")) < floor:
                continue
        except (TypeError, ValueError):
            continue
        if (r.get("days_left") or 0) <= 0:
            continue
        if r.get("ticker"):
            out.append(r["ticker"])
    return sorted(set(out))


def _is_held(ticker: str, holdings: list | None) -> bool:
    """Held-position check via the shared exit_plan helper (ADR aliases included).
    Any import or lookup problem degrades to False — a wrong 'ADD' label is cosmetic,
    a crashed digest is not."""
    if not holdings:
        return False
    try:
        from exit_plan import find_holding
        holding, _ = find_holding(ticker, holdings)
        return holding is not None
    except Exception:
        return False


def select_buys(reports: list[dict], live_prices: dict | None = None,
                holdings: list | None = None, floor: float = BUY_FLOOR) -> dict:
    """Buyable names, best recommendation first.

    Returns {"buys": [row, ...], "no_max_entry": [ticker, ...], "above_entry":
    [ticker, ...], "floor": floor}. `no_max_entry` and `above_entry` exist so the
    caller can report what was excluded and why instead of showing a bare table.
    """
    live_prices = live_prices or {}
    buys, no_max_entry, above_entry = [], [], []

    for r in latest_per_ticker(reports):
        try:
            score = float(r.get("score"))
        except (TypeError, ValueError):
            continue
        if score < floor:
            continue
        if (r.get("days_left") or 0) <= 0:
            continue

        ticker = r.get("ticker") or ""
        cap, basis = max_entry(r)
        if cap is None:
            no_max_entry.append(ticker)
            continue

        live = live_prices.get(ticker)
        price, source = (live, "live") if isinstance(live, (int, float)) else (r.get("price"), "eval")
        try:
            price = float(price)
        except (TypeError, ValueError):
            no_max_entry.append(ticker)  # no price to compare against the cap
            continue
        if price <= 0:
            continue

        if price > cap:
            above_entry.append(ticker)
            continue

        headroom = (cap / price - 1) * 100
        buys.append({
            "ticker": ticker,
            "company": r.get("company"),
            "score": score,
            "verdict": r.get("verdict"),
            "currency": r.get("currency") or "",
            "price": price,
            "price_source": source,
            "max_entry": cap,
            "max_entry_basis": basis,
            "headroom_pct": headroom,
            "thin": headroom < THIN_MARGIN_PCT,
            "held": _is_held(ticker, holdings),
            "go_no_go": (r.get("go_no_go") or "").upper() or None,
            "mos_class": r.get("mos_class"),
            "date": r.get("date"),
            "days_left": r.get("days_left"),
            "thesis": r.get("thesis"),
            "filename": r.get("filename"),
        })

    # Sorted by the recommendation itself (composite desc), headroom breaking ties.
    buys.sort(key=lambda b: (-b["score"], -b["headroom_pct"], b["ticker"]))
    return {"buys": buys, "no_max_entry": sorted(set(no_max_entry)),
            "above_entry": sorted(set(above_entry)), "floor": floor}


def load_holdings_safe(out_dir: Path) -> list:
    """`_portfolio_holdings.yaml` entries, or [] on any problem."""
    try:
        from exit_plan import load_holdings
        holdings, _warnings = load_holdings(out_dir)
        return holdings or []
    except Exception:
        return []
