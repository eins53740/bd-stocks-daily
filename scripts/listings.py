"""
listings.py — One company, many tickers. The single source of truth for
cross-listing identity in the stocks pipeline.

Why this exists
---------------
Until 2026-08-05 three separate alias tables disagreed about which side of a
dual listing was canonical:

  * ``pick_candidates.TICKER_ALIASES``   collapsed 2330.TW -> TSM   (ADR wins)
  * ``portfolio_deepdive_gap.EQUIV_GROUPS`` collapsed to ``sorted(g)[0]``
    which for that same pair is 2330.TW                            (home wins)
  * ``exit_plan.ALIASES``                knew only Shell

The practical damage was visible in ``_log.csv``: TSMC held **7 evaluations
across two listings** (TSM x3, 2330.TW x4 — two of them two days apart), and
SAP was analysed as both ``SAP`` and ``SAP.DE`` inside a week. Every downstream
surface — shortlist, screener, digest — then showed the same company twice.

The rule this module encodes
----------------------------
**The home listing is the company.** An ADR is a wrapper around it: same
business, same filings, a depositary bank and an FX leg in between. So the
analysis runs on the home line, and the ADR is demoted to what it actually is —
one more venue you can buy the same company on (see :func:`listing_table`).

The one exception is data thinness. yfinance coverage is not uniform: for a few
names the US line carries fundamentals the home line simply doesn't publish to
Yahoo, and running the home line would mean scoring a company on holes.
:func:`preferred_listing` probes both and keeps the home line unless it is
*materially* thinner (see ``THINNESS_TOLERANCE``), recording the reason either
way so the choice is auditable in the report frontmatter rather than silent.

Everything here is network-free except :func:`probe_listing`, which lazily
imports yfinance. Import this module freely from selection-path code.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Windows consoles default to cp1252 and would die on the first emoji in a table.
for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import markets  # noqa: E402

OUT_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
PROBE_CACHE = OUT_DIR / "_tmp" / "_listing_probe.json"
# yfinance field coverage is a property of the listing, not of the day. Re-probing
# every run would spend two API calls per dual-listed pick to re-learn a fact that
# changes maybe once a year.
PROBE_TTL_DAYS = 30

# The home line has to be MATERIALLY thinner to lose, not merely one field short.
# 0.80 lets it drop ~3 of the 17 probed fields and still win — enough slack for
# the usual non-US gaps (payoutRatio, floatShares) without tolerating a listing
# that is missing whole statements.
THINNESS_TOLERANCE = 0.80


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
# One entry per company that trades under more than one Yahoo symbol.
#
#   home      the primary/home listing — where the company is domiciled and
#             where price discovery actually happens. This is the canonical
#             identity for dedupe, round counting and staleness.
#   also      every other symbol for the SAME economic interest.
#             kind: "primary2"    second primary listing (dual-primary)
#                   "secondary"   secondary/cross listing
#                   "adr"/"gdr"   depositary receipt
#                   "class"       another share class of the same company
#             ratio: DR-to-ordinary ratio, when it isn't 1:1. Stated because it
#                   is the number people get wrong when comparing quoted prices.
#
# Exchange, currency and region are NOT stored — markets.market_meta() derives
# them from the Yahoo suffix, and duplicating them here would be a second table
# to drift. Only the grouping and the DR ratio are genuinely new information.
#
# This table is curated by hand. It is deliberately conservative: an entry is
# only added once the pairing has been confirmed, because a wrong pairing merges
# two different companies' histories. Unmapped ADRs are caught at analysis time
# by adr_suspicion() instead of being guessed at.
REGISTRY: list[dict] = [
    {"company": "Taiwan Semiconductor Manufacturing", "home": "2330.TW",
     "also": [{"ticker": "TSM", "kind": "adr", "ratio": "1 ADR = 5 ord."}]},
    {"company": "ASML Holding", "home": "ASML.AS",
     "also": [{"ticker": "ASML", "kind": "adr", "ratio": "1 ADR = 1 ord."}]},
    {"company": "SAP", "home": "SAP.DE",
     "also": [{"ticker": "SAP", "kind": "adr", "ratio": "1 ADR = 1 ord."}]},
    {"company": "Shell", "home": "SHEL.L",
     "also": [{"ticker": "SHELL.AS", "kind": "secondary"},
              {"ticker": "SHEL", "kind": "adr", "ratio": "1 ADR = 2 ord."}]},
    {"company": "Shopify", "home": "SHOP.TO",
     "also": [{"ticker": "SHOP", "kind": "secondary"}]},
    {"company": "Alphabet", "home": "GOOGL",
     "also": [{"ticker": "GOOG", "kind": "class", "ratio": "class C, non-voting"}]},
    {"company": "Alibaba Group", "home": "9988.HK",
     "also": [{"ticker": "BABA", "kind": "adr", "ratio": "1 ADS = 8 ord."}]},
    {"company": "Samsung Electronics", "home": "005930.KS",
     "also": [{"ticker": "SSUN.F", "kind": "gdr"}]},
    {"company": "SoftBank Group", "home": "9984.T",
     "also": [{"ticker": "SFTBY", "kind": "adr", "ratio": "1 ADR = 0.5 ord."}]},
    {"company": "Ryanair Holdings", "home": "RYA.IR",
     "also": [{"ticker": "RYAAY", "kind": "adr", "ratio": "1 ADR = 5 ord."}]},
    {"company": "Fujitsu", "home": "6702.T",
     "also": [{"ticker": "FJTSY", "kind": "adr"}]},
    {"company": "Lenovo Group", "home": "0992.HK",
     "also": [{"ticker": "LNVGY", "kind": "adr", "ratio": "1 ADR = 20 ord."},
              {"ticker": "LNVGF", "kind": "adr", "ratio": "unsponsored, 1:1"}]},
    {"company": "Novo Nordisk", "home": "NOVO-B.CO",
     "also": [{"ticker": "NVO", "kind": "adr", "ratio": "1 ADR = 1 B-share"}]},
]

# Yahoo suffix -> brokers.yaml MARKET_KEY. Only the markets brokers.yaml actually
# prices; everything else resolves to None and renders as "not covered" rather
# than pretending a cost exists.
_MARKET_KEY_BY_SUFFIX = {
    "": "US", "IR": "IE", "LS": "PT", "TW": "TW", "TWO": "TW",
    "HK": "HK", "T": "JP", "JP": "JP", "SZ": "CN_SZ",
}

# Built once at import: every known symbol -> its group.
_GROUP_BY_TICKER: dict[str, dict] = {}
for _g in REGISTRY:
    _GROUP_BY_TICKER[_g["home"]] = _g
    for _alt in _g["also"]:
        _GROUP_BY_TICKER[_alt["ticker"]] = _g


def _clean(ticker: object) -> str:
    """Normalise a ticker to a stripped string.

    Coerces non-str first: YAML 1.1 parses a bare ``ON`` (ON Semiconductor) as
    the boolean True, exactly as it does ``NO`` for Norway. Quoting in the source
    file is the real fix, but identity resolution must never crash on one bad row.
    """
    if not isinstance(ticker, str):
        ticker = "" if ticker is None else str(ticker)
    return ticker.strip()


def group_for(ticker: str) -> dict | None:
    """The registry group this ticker belongs to, or None if single-listed."""
    return _GROUP_BY_TICKER.get(_clean(ticker))


def company_key(ticker: str) -> str:
    """Canonical company identity — the HOME listing.

    Dedupe windows, round counters and staleness are all reckoned per company,
    never per listing. Unmapped tickers are their own company.
    """
    t = _clean(ticker)
    g = _GROUP_BY_TICKER.get(t)
    return g["home"] if g else t


def company_name(ticker: str) -> str | None:
    """Registry display name for the company, or None if single-listed."""
    g = group_for(ticker)
    return g["company"] if g else None


def all_tickers(ticker: str) -> list[str]:
    """Every symbol for this company, home first. Single-listed -> [ticker]."""
    g = group_for(ticker)
    if not g:
        return [_clean(ticker)]
    return [g["home"]] + [a["ticker"] for a in g["also"]]


def is_home(ticker: str) -> bool:
    """True when this symbol IS the home line (or has no cross-listing at all)."""
    return company_key(ticker) == _clean(ticker)


def market_key(ticker: str) -> str | None:
    """brokers.yaml MARKET_KEY for a ticker's venue, or None when uncovered."""
    return _MARKET_KEY_BY_SUFFIX.get(markets.suffix_of(_clean(ticker)))


def listing_rows(ticker: str) -> list[dict]:
    """Venue rows for every listing of this company, home first.

    Each row: ticker, kind, exchange, currency, region, market_key, ratio, home.
    Returns [] for a single-listed name — callers render nothing rather than a
    one-row table saying "you can buy this in exactly one place".
    """
    g = group_for(ticker)
    if not g:
        return []
    rows = []
    for sym, kind, ratio in (
        [(g["home"], "primary", None)]
        + [(a["ticker"], a["kind"], a.get("ratio")) for a in g["also"]]
    ):
        meta = markets.market_meta(sym)
        rows.append({
            "ticker": sym,
            "kind": kind,
            "home": sym == g["home"],
            "exchange": meta["exchange"],
            "currency": meta["currency"],
            "region": meta["region"],
            "market_key": market_key(sym),
            "ratio": ratio,
        })
    return rows


_KIND_LABEL = {
    "primary": "🏠 primária",
    "primary2": "primária (dual)",
    "secondary": "secundária",
    "adr": "ADR",
    "gdr": "GDR",
    "class": "classe de acções",
}


def listing_table(ticker: str, broker_costs: dict | None = None) -> str:
    """Markdown "where can I buy this" block, or '' for a single-listed name.

    ``broker_costs`` is an optional ``{MARKET_KEY: "cheapest broker — €cost"}``
    map (from broker_compare.py); markets it doesn't cover render as "—" rather
    than inventing a number.
    """
    rows = listing_rows(ticker)
    if not rows:
        return ""
    g = group_for(ticker)
    costs = broker_costs or {}
    out = [
        f"### Onde comprar — {g['company']} cotada em {len(rows)} mercados",
        "",
        "| Ticker | Mercado | Moeda | Tipo | Rácio | Broker mais barato (€1500) |",
        "|--------|---------|-------|------|-------|----------------------------|",
    ]
    for r in rows:
        mark = "**" if r["home"] else ""
        cost = costs.get(r["market_key"]) if r["market_key"] else None
        out.append(
            f"| {mark}{r['ticker']}{mark} | {r['exchange']} | {r['currency']} | "
            f"{_KIND_LABEL.get(r['kind'], r['kind'])} | {r['ratio'] or '1:1'} | "
            f"{cost or '—'} |"
        )
    out += [
        "",
        f"> [!tip] Mesma empresa, mesmos fundamentais. A análise corre sobre a linha "
        f"**{g['home']}** ({markets.market_meta(g['home'])['exchange']}); as outras "
        f"linhas são o mesmo negócio com uma perna de câmbio (e, nos ADR/GDR, um "
        f"banco depositário e a sua comissão) pelo meio. Compara sempre o preço "
        f"ajustado pelo rácio antes de escolher o mercado.",
    ]
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Data-thinness probe
# --------------------------------------------------------------------------- #
# The fields the scoring model actually consumes. Coverage is measured against
# THIS set, not against everything yfinance might return, so a listing is not
# rewarded for carrying fields nobody reads.
PROBE_FIELDS = (
    "currentPrice", "marketCap", "trailingPE", "totalRevenue", "ebitda",
    "freeCashflow", "returnOnEquity", "profitMargins", "grossMargins",
    "operatingMargins", "totalDebt", "totalCash", "bookValue",
    "sharesOutstanding", "quickRatio", "currentRatio", "earningsGrowth",
)


def _cache_read() -> dict:
    try:
        return json.loads(PROBE_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cache_write(cache: dict) -> None:
    try:
        PROBE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PROBE_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception as exc:  # a cache write must never break selection
        print(f"listing probe cache write failed (non-fatal): {exc}", file=sys.stderr)


def probe_listing(ticker: str, use_cache: bool = True) -> dict:
    """How complete is yfinance's fundamental data for this exact symbol?

    Returns ``{ticker, n, total, ratio, missing, error}``. On any failure
    (rate limit, unknown symbol, yfinance absent) ``error`` is set and ``ratio``
    is 0.0 — a listing we cannot read is, for this decision, an empty one.
    """
    t = _clean(ticker)
    cache = _cache_read() if use_cache else {}
    hit = cache.get(t)
    if hit and (time.time() - hit.get("at", 0)) < PROBE_TTL_DAYS * 86400:
        return {k: v for k, v in hit.items() if k != "at"}

    result = {"ticker": t, "n": 0, "total": len(PROBE_FIELDS),
              "ratio": 0.0, "missing": list(PROBE_FIELDS), "error": None}
    try:
        import yfinance as yf
        info = yf.Ticker(t).info or {}
        present = [f for f in PROBE_FIELDS if info.get(f) not in (None, "", 0)]
        result["n"] = len(present)
        result["missing"] = [f for f in PROBE_FIELDS if f not in present]
        result["ratio"] = round(len(present) / len(PROBE_FIELDS), 3)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    if use_cache and result["error"] is None:
        cache[t] = {**result, "at": time.time()}
        _cache_write(cache)
    return result


def preferred_listing(ticker: str, probe: bool = True) -> dict:
    """Which symbol should actually be analysed for this company?

    Home wins unless it is materially thinner than the best alternative (policy
    chosen 2026-08-05). Returns::

        {ticker, home, requested, switched, reason, probes}

    ``probe=False`` skips the network entirely and returns the home line — the
    right call for tests and for any caller that just needs identity, not a
    data-quality judgement.
    """
    req = _clean(ticker)
    g = group_for(req)
    if not g:
        return {"ticker": req, "home": req, "requested": req, "switched": False,
                "reason": "single-listed — no alternative venue", "probes": {}}

    home = g["home"]
    if not probe:
        return {"ticker": home, "home": home, "requested": req,
                "switched": req != home,
                "reason": "home listing (probe skipped)", "probes": {}}

    candidates = all_tickers(req)
    probes = {c: probe_listing(c) for c in candidates}
    home_ratio = probes[home]["ratio"]
    rival, rival_ratio = max(
        ((c, p["ratio"]) for c, p in probes.items() if c != home),
        key=lambda kv: kv[1], default=(None, 0.0),
    )

    # A probe that could not read ANY listing is not evidence of thinness —
    # it is evidence of a rate limit. Falling back to the ADR on that signal
    # would silently undo the whole policy on exactly the days yfinance is sick.
    if home_ratio == 0.0 and rival_ratio == 0.0:
        return {"ticker": home, "home": home, "requested": req,
                "switched": req != home, "probes": probes,
                "reason": "home listing — probe inconclusive (no listing readable)"}

    if rival and home_ratio < THINNESS_TOLERANCE * rival_ratio:
        return {"ticker": rival, "home": home, "requested": req, "switched": True,
                "probes": probes,
                "reason": (f"{rival} kept over home {home}: yfinance coverage "
                           f"{rival_ratio:.0%} vs {home_ratio:.0%} "
                           f"(below the {THINNESS_TOLERANCE:.0%} tolerance)")}

    detail = (f"coverage {home_ratio:.0%}"
              + (f" vs {rival} {rival_ratio:.0%}" if rival else ""))
    return {"ticker": home, "home": home, "requested": req,
            "switched": req != home, "probes": probes,
            "reason": f"home listing preferred — {detail}"}


def adr_suspicion(ticker: str, info: dict) -> str | None:
    """Flag a probable ADR that the registry doesn't know about yet.

    Signal: a US-quoted line whose *reporting* currency differs from its
    *trading* currency is almost always a depositary receipt over a foreign
    company. We deliberately do NOT guess the home symbol — inventing one would
    merge two companies' histories on a hunch. We surface the gap so a human can
    add the pairing to REGISTRY.
    """
    t = _clean(ticker)
    if group_for(t) or markets.suffix_of(t) != "":
        return None
    trading = (info.get("currency") or "").upper()
    reporting = (info.get("financialCurrency") or "").upper()
    if trading == "USD" and reporting and reporting != "USD":
        return (f"{t} trades in USD but reports in {reporting} — likely an "
                f"unmapped ADR. Add its home listing to listings.REGISTRY so the "
                f"analysis runs on the primary line.")
    return None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("ticker")
    ap.add_argument("--resolve", action="store_true",
                    help="probe and print the listing that should be analysed")
    ap.add_argument("--no-probe", action="store_true",
                    help="with --resolve, skip the network and just return home")
    ap.add_argument("--table", action="store_true",
                    help="print the markdown 'where can I buy this' block")
    args = ap.parse_args()

    if args.table:
        block = listing_table(args.ticker)
        print(block if block else "")
        return 0
    if args.resolve:
        print(json.dumps(preferred_listing(args.ticker, probe=not args.no_probe),
                         indent=2))
        return 0
    print(json.dumps({
        "requested": _clean(args.ticker),
        "company": company_name(args.ticker),
        "company_key": company_key(args.ticker),
        "is_home": is_home(args.ticker),
        "listings": listing_rows(args.ticker),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
