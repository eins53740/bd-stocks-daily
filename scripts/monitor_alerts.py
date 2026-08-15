"""monitor_alerts.py — the portfolio guardrails, as code (v4.3 wave 4.1).

Today these rules live only as prose in SKILL.md files, which means they are **unenforced**:
a P/E of 140 on a holding breaks a rule nobody evaluates. This module makes each one a
pure function over data the system already has, so `/bd-stocks-monitor` can state, every
week, which guardrails are being breached and by how much.

Four alerts, all from the plan, plus the two concentration rules that were already written
down but never checked:

| Alert | Rule | Source |
|---|---|---|
| bubble P/E | holding P/E > 100 | `analyze_ticker` |
| sector-relative | P/E > 3x the sector median P/E | peer/sector median |
| profit total | unrealised gain > 150 % | cost basis |
| profit annualised | > 50 %/yr since purchase | cost basis + lot date |
| concentration | one name > 20 % of the portfolio | holdings |
| crypto concentration | one coin > 5 % | holdings |

DESIGN RULES, both learned the hard way elsewhere in this system:

 * **An alert never fires on a missing number.** No P/E means "not computable", never
   "not in breach" and never a breach. Every alert carries `computable`.
 * **Annualising a short holding period is refused**, exactly as in
   `recommendation_ledger.py`: a 60 % gain over five weeks annualises to something
   absurd, and printing it beside real numbers would make the whole panel untrustworthy.

Pure stdlib, no network, no I/O. Same JSON in, same alerts out.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, datetime

# --- published thresholds ---------------------------------------------------
PE_BUBBLE = 100.0             # absolute
PE_SECTOR_MULTIPLE = 3.0      # vs the sector median
GAIN_TOTAL_PCT = 150.0        # unrealised, since purchase
GAIN_ANNUAL_PCT = 50.0        # per year, since purchase
CONCENTRATION_PCT = 20.0      # one equity name
CRYPTO_CONCENTRATION_PCT = 5.0
MIN_ANNUALISE_DAYS = 365      # below this the annualised rule does not fire at all

SEVERITY = {"info": 0, "watch": 1, "alert": 2}


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _day(v):
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v).strip()[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _alert(kind, ticker, *, fired=None, computable=True, severity="info",
           value=None, threshold=None, detail="") -> dict:
    return {"kind": kind, "ticker": ticker, "fired": bool(fired) if computable else None,
            "computable": computable, "severity": severity if fired else "info",
            "value": value, "threshold": threshold, "detail": detail}


# ===================================================================
# the four holding alerts
# ===================================================================
def bubble_pe(holding: dict) -> dict:
    pe = _num(holding.get("pe_ratio"))
    t = holding.get("ticker")
    if pe is None:
        return _alert("bubble_pe", t, computable=False,
                      detail="no P/E on the holding — not computable, not 'in the clear'")
    if pe <= 0:
        return _alert("bubble_pe", t, fired=False, value=pe, threshold=PE_BUBBLE,
                      detail="negative or zero earnings — P/E is not meaningful (NM)")
    fired = pe > PE_BUBBLE
    return _alert("bubble_pe", t, fired=fired, value=round(pe, 2), threshold=PE_BUBBLE,
                  severity="alert",
                  detail=(f"P/E {pe:.1f} is above {PE_BUBBLE:.0f}x" if fired
                          else f"P/E {pe:.1f}"))


def sector_relative_pe(holding: dict, sector_median_pe=None) -> dict:
    pe, med = _num(holding.get("pe_ratio")), _num(sector_median_pe)
    t = holding.get("ticker")
    if pe is None or pe <= 0 or med is None or med <= 0:
        return _alert("sector_relative_pe", t, computable=False,
                      detail="needs a positive holding P/E and a positive sector median")
    ratio = pe / med
    fired = ratio > PE_SECTOR_MULTIPLE
    return _alert("sector_relative_pe", t, fired=fired, value=round(ratio, 2),
                  threshold=PE_SECTOR_MULTIPLE, severity="watch",
                  detail=f"P/E {pe:.1f} vs sector median {med:.1f} = {ratio:.1f}x")


def profit_total(holding: dict) -> dict:
    cost, price = _num(holding.get("cost_basis")), _num(holding.get("price"))
    t = holding.get("ticker")
    if cost is None or cost <= 0 or price is None:
        return _alert("profit_total", t, computable=False,
                      detail="needs a cost basis and a current price")
    gain = (price / cost - 1) * 100
    fired = gain > GAIN_TOTAL_PCT
    return _alert("profit_total", t, fired=fired, value=round(gain, 1),
                  threshold=GAIN_TOTAL_PCT, severity="watch",
                  detail=f"unrealised {gain:+.0f}% since purchase")


def profit_annualised(holding: dict, today: date | None = None) -> dict:
    """Annualised gain since purchase — but only once the position is a year old.

    A 60 % gain over five weeks annualises to several hundred percent. Printing that
    beside real numbers would discredit the whole panel, so below MIN_ANNUALISE_DAYS the
    alert reports the holding period instead of firing.
    """
    today = today or date.today()
    cost, price = _num(holding.get("cost_basis")), _num(holding.get("price"))
    bought = _day(holding.get("purchase_date"))
    t = holding.get("ticker")
    if cost is None or cost <= 0 or price is None or price <= 0 or bought is None:
        return _alert("profit_annualised", t, computable=False,
                      detail="needs a cost basis, a current price and a purchase date")
    days = (today - bought).days
    if days < MIN_ANNUALISE_DAYS:
        return _alert("profit_annualised", t, computable=False,
                      detail=(f"held {days}d — under {MIN_ANNUALISE_DAYS}d, an annualised "
                              f"rate is arithmetic, not a return"))
    years = days / 365.25
    cagr = ((price / cost) ** (1 / years) - 1) * 100
    fired = cagr > GAIN_ANNUAL_PCT
    return _alert("profit_annualised", t, fired=fired, value=round(cagr, 1),
                  threshold=GAIN_ANNUAL_PCT, severity="watch",
                  detail=f"{cagr:+.0f}%/yr over {years:.1f}y")


# ===================================================================
# concentration — portfolio-level, not per holding
# ===================================================================
def concentration(holdings: list, total_value=None) -> list:
    """One row per breach. Crypto carries the tighter 5 % limit."""
    rows = [h for h in (holdings or []) if _num(h.get("value")) is not None]
    total = _num(total_value) or sum(_num(h["value"]) for h in rows)
    if not rows or not total or total <= 0:
        return [_alert("concentration", None, computable=False,
                       detail="no valued holdings — concentration not computable")]
    out = []
    for h in rows:
        weight = _num(h["value"]) / total * 100
        is_crypto = bool(h.get("is_crypto"))
        limit = CRYPTO_CONCENTRATION_PCT if is_crypto else CONCENTRATION_PCT
        fired = weight > limit
        if fired:
            out.append(_alert("crypto_concentration" if is_crypto else "concentration",
                              h.get("ticker"), fired=True, value=round(weight, 1),
                              threshold=limit, severity="alert",
                              detail=f"{weight:.1f}% of the portfolio, limit {limit:.0f}%"))
    return out


# ===================================================================
# assembly
# ===================================================================
def sector_medians(holdings: list) -> dict:
    """Median P/E per sector, from the holdings themselves.

    Using the portfolio's own names is a weak proxy for a sector median and is labelled
    as such by the caller: with two names in a sector the "median" is their average. It
    is used only when a real sector median is not supplied.
    """
    buckets: dict = {}
    for h in holdings or []:
        pe, sector = _num(h.get("pe_ratio")), h.get("sector")
        if pe is None or pe <= 0 or not sector:
            continue
        buckets.setdefault(sector, []).append(pe)
    return {s: round(statistics.median(v), 3) for s, v in buckets.items()}


def evaluate(holdings: list, *, sector_pe: dict | None = None,
             total_value=None, today: date | None = None) -> dict:
    """All alerts over a holdings list. `sector_pe` overrides the self-derived medians."""
    today = today or date.today()
    holdings = holdings or []
    derived = sector_medians(holdings)
    medians = dict(derived)
    medians.update(sector_pe or {})

    alerts = []
    for h in holdings:
        med = medians.get(h.get("sector"))
        alerts.append(bubble_pe(h))
        alerts.append(sector_relative_pe(h, med))
        alerts.append(profit_total(h))
        alerts.append(profit_annualised(h, today))
    alerts.extend(concentration(holdings, total_value))

    fired = [a for a in alerts if a.get("fired")]
    return {
        "as_of": today.isoformat(),
        "holdings": len(holdings),
        "alerts": alerts,
        "fired": sorted(fired, key=lambda a: -SEVERITY.get(a["severity"], 0)),
        "counts": {
            "fired": len(fired),
            "not_computable": sum(1 for a in alerts if not a["computable"]),
            "clear": sum(1 for a in alerts if a["computable"] and not a["fired"]),
        },
        "sector_pe_source": ("supplied" if sector_pe else
                             "derived from the portfolio's own holdings (weak proxy)"),
        "thresholds": {
            "pe_bubble": PE_BUBBLE, "pe_sector_multiple": PE_SECTOR_MULTIPLE,
            "gain_total_pct": GAIN_TOTAL_PCT, "gain_annual_pct": GAIN_ANNUAL_PCT,
            "concentration_pct": CONCENTRATION_PCT,
            "crypto_concentration_pct": CRYPTO_CONCENTRATION_PCT,
        },
    }


def render_lines(block: dict) -> list:
    c = block["counts"]
    out = [f"as of {block['as_of']} — {block['holdings']} holdings · {c['fired']} fired · "
           f"{c['clear']} clear · {c['not_computable']} not computable"]
    for a in block["fired"]:
        out.append(f"  [{a['severity'].upper():<5}] {a['kind']:<22} "
                   f"{a['ticker'] or '—':<10} {a['detail']}")
    if not block["fired"]:
        out.append("  no guardrail breached")
    if c["not_computable"]:
        out.append(f"  ({c['not_computable']} checks lacked inputs — reported as "
                   f"not computable, never as 'in the clear')")
    return out
