"""
pick_candidates.py — Selecciona 5 tickers do pool pre-filtrado para avaliação diária.

Regras:
- 1 deep-dive + 4 screens
- Deep alterna big <-> small_growth stateful (last_mode em _log.csv)
- Screens: 1 big + 1 small_growth + 2 non-USA (region != US, qualquer size)
- Dedupe: tickers avaliados nos últimos 183 dias são excluídos
- Round: se ticker já foi avaliado antes (com gap >183d), round += 1
- Identidade por EMPRESA, não por listing: um ADR e a sua cotação local
  (TSM / 2330.TW) partilham janela de dedupe, contador de rounds e antiguidade
  (ver TICKER_ALIASES)
- Fallback (pool esgotada): escolhe a empresa MENOS visitada, antiguidade só
  como desempate — evitar o carrossel quinzenal dos mesmos high-scorers

Output: JSON em stdout. Info para stderr.
"""
from __future__ import annotations

import csv
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Force UTF-8 on Windows stdout/stderr
for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import yaml

OUT_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
PREFILTERED = OUT_DIR / "_prefiltered.yaml"
LOG = OUT_DIR / "_log.csv"

DEDUPE_DAYS = 183
# Minimum gap before a name may be re-evaluated in fallback mode. At 14 days the
# handful of tickers scoring >= 7.5 formed a fortnightly carousel — TSMC came
# round six times in three months. 45 days is long enough that the rotation has
# to work through the whole high-score set before repeating.
FALLBACK_MIN_AGE_DAYS = 45
FALLBACK_MAX_ROUND = 5       # cap re-evaluation rounds to avoid infinite loops on perma-stale tickers
FALLBACK_SHORTLIST_MIN_SCORE = 7.5

# Dual listings and dual share classes are ONE company. Without this, TSMC held
# two independent slots (TSM as the US ADR, 2330.TW as the Taiwan line): two
# dedupe windows, two round counters, twice the odds of being picked. Keys are
# alternate listings, values the canonical name they collapse into.
TICKER_ALIASES = {
    "2330.TW": "TSM",        # TSMC — Taiwan line / US ADR
    "ASML.AS": "ASML",       # ASML — Amsterdam / US ADR
    "SAP.DE": "SAP",         # SAP — Xetra / US ADR
    "SHELL.AS": "SHEL.L",    # Shell — Amsterdam / London
    "SHOP.TO": "SHOP",       # Shopify — Toronto / US
    "GOOG": "GOOGL",         # Alphabet — C shares / A shares
    "9988.HK": "BABA",       # Alibaba — Hong Kong / US ADR
    "SSUN.F": "005930.KS",   # Samsung Electronics — Frankfurt / Korea
    "SFTBY": "9984.T",       # SoftBank — US ADR / Tokyo
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def company_key(ticker: str) -> str:
    """Canonical company identity for a ticker — dedupe, rounds and staleness are
    all reckoned per company, never per listing.

    Coerces to str first: YAML 1.1 parses a bare `ON` (ON Semiconductor) as the
    boolean True, exactly as it does `NO` for Norway. Quoting in the source file
    is the real fix, but selection must never crash on one bad row.
    """
    if not isinstance(ticker, str):
        ticker = "" if ticker is None else str(ticker)
    ticker = ticker.strip()
    return TICKER_ALIASES.get(ticker, ticker)


def load_prefiltered() -> list[dict]:
    with PREFILTERED.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("tickers", [])


def load_log() -> list[dict]:
    if not LOG.exists():
        return []
    with LOG.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def last_mode_for_deep(log_rows: list[dict]) -> str | None:
    """Return size of the last deep-dive ('big' or 'small_growth'), or None."""
    for row in reversed(log_rows):
        if row.get("mode") == "deep":
            return row.get("size") or None
    return None


def ticker_last_date(ticker: str, log_rows: list[dict]) -> date | None:
    """Most recent evaluation of this ticker's COMPANY, across every listing."""
    key = company_key(ticker)
    best: date | None = None
    for row in log_rows:
        if company_key(row.get("ticker", "")) != key:
            continue
        try:
            d = datetime.strptime(row["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if best is None or d > best:
            best = d
    return best


def ticker_round(ticker: str, log_rows: list[dict]) -> int:
    """1-based: first evaluation is round 1, second is round 2, ...
    Counts distinct dates — a same-day screen+deep pair is one visit. Counted per
    company, so an ADR re-run does not reset the local line's round number."""
    key = company_key(ticker)
    dates = {r.get("date") for r in log_rows
             if company_key(r.get("ticker", "")) == key}
    return len(dates) + 1


def eligible(tickers: list[dict], log_rows: list[dict], today: date) -> list[dict]:
    """Candidates whose COMPANY has not been evaluated inside the dedupe window.
    Company-level, so evaluating the Taiwan line also puts the ADR on the bench."""
    cutoff = today - timedelta(days=DEDUPE_DAYS)
    out = []
    for t in tickers:
        last = ticker_last_date(t["ticker"], log_rows)
        if last is None or last < cutoff:
            # Enrich with size fallback
            t.setdefault("size", "big")
            out.append(t)
    return out


def pick(candidates: list[dict], size: str) -> dict | None:
    # 'micro' names ride the small_growth slot — they have no slot of their own
    # and would otherwise only ever surface via the extras shuffle.
    sizes = {size, "micro"} if size == "small_growth" else {size}
    pool = [c for c in candidates if c.get("size") in sizes]
    if not pool:
        return None
    return random.choice(pool)


def pick_fallback_deep(log_rows: list[dict], today: date) -> dict | None:
    """
    Pool-exhaustion fallback. The user wants ONE deep-dive every day, so when
    the regular pool returns nothing we re-evaluate a previously-seen ticker.

    Cascade:
      1. Least-visited active shortlist (score >= 7.5, age >= 45d, round < 5).
      2. Least-visited any-verdict company (age >= 45d, round < 5).
      3. None — empty log, fresh install. Caller falls through to today's
         "all_deduped" exit + bat-side email guard handles the day.

    Ranking is (visits, last_eval_date) — FEWEST VISITS FIRST, staleness only as
    the tie-break. Ranking by staleness alone made this a recency queue: the few
    names scoring >= 7.5 simply took turns, so a company already analysed five
    times still outranked one analysed once, and TSMC came round every fortnight.
    Counting visits per COMPANY (not per listing) closes the other half of that
    hole, where an ADR and its local line each held their own counter.
    """
    if not log_rows:
        return None

    # Aggregate per company: when did we last look, how many distinct days have we
    # spent on it, and which listing did we use most recently.
    last_seen: dict[str, date] = {}
    latest_row: dict[str, dict] = {}
    visit_dates: dict[str, set] = {}
    for row in log_rows:
        t = row.get("ticker")
        if not t:
            continue
        key = company_key(t)
        try:
            d = datetime.strptime(row["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        visit_dates.setdefault(key, set()).add(row.get("date"))
        if key not in last_seen or d > last_seen[key]:
            last_seen[key] = d
            latest_row[key] = row
    visits = {k: len(ds) for k, ds in visit_dates.items()}

    cutoff = today - timedelta(days=FALLBACK_MIN_AGE_DAYS)

    tier1 = []  # high-score companies
    tier2 = []  # any verdict
    for key, last in last_seen.items():
        if last > cutoff:
            continue  # too recent
        n_visits = visits.get(key, 0)
        if n_visits >= FALLBACK_MAX_ROUND:
            continue  # round-cap
        row = latest_row[key]
        try:
            score = float(row.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        # Sort key first, payload after — least-visited, then stalest.
        entry = (n_visits, last, key, row)
        if score >= FALLBACK_SHORTLIST_MIN_SCORE:
            tier1.append(entry)
        tier2.append(entry)

    for tier, reason, label in (
        (tier1, "pool_exhausted_shortlist_reeval",
         f"tier-1 shortlist re-eval (score>={FALLBACK_SHORTLIST_MIN_SCORE})"),
        (tier2, "pool_exhausted_any_verdict_reeval", "tier-2 any-verdict re-eval"),
    ):
        if not tier:
            continue
        tier.sort(key=lambda e: (e[0], e[1]))
        n_visits, last, key, row = tier[0]
        ticker = row.get("ticker") or key
        log(f"FALLBACK: {label}, picking least-visited: {ticker} "
            f"(company {key}, {n_visits} prior visit(s), last {last})")
        return {
            "ticker": ticker,
            "size": row.get("size", "big") or "big",
            "region": row.get("region", "?"),
            "sector": row.get("sector", "?"),
            "note": row.get("notes", "") or "",
            "fallback_reason": reason,
        }

    return None


def main() -> int:
    random.seed(date.today().toordinal())

    tickers = load_prefiltered()
    log_rows = load_log()
    today = date.today()

    if not tickers:
        log("WARN: _prefiltered.yaml empty — going straight to fallback re-eval")
        pool = []
        n_hyper = 0
    else:
        pool = eligible(tickers, log_rows, today)
        # Hyper-growth names belong to /bd_stocks_daily_growth, which scores them
        # on growth criteria. They must not leak into this quality run: the deep
        # and big/small screen slots filter on size already, but the non-US slot
        # and the extras shuffle below take ANY size, so without this they would
        # be judged by a model whose gate-5 (net margin > 10%) rejects them by
        # construction.
        n_hyper = sum(1 for c in pool if c.get("size") == "hyper_growth")
        if n_hyper:
            pool = [c for c in pool if c.get("size") != "hyper_growth"]
            log(f"INFO: {n_hyper} hyper_growth name(s) reserved for the growth lens")

    if not pool:
        # Pool exhausted — user wants one deep dive every day. Re-evaluate the
        # stalest shortlist ticker (or any-verdict if shortlist is empty too).
        log("WARN: no eligible tickers (all in 6-month dedupe window) — invoking fallback")
        fb = pick_fallback_deep(log_rows, today)
        if fb is None:
            log("WARN: fallback found nothing usable (log empty?). Graceful exit.")
            print(json.dumps({"error": "all_deduped", "date": today.isoformat()}))
            return 0
        result = {
            "date": today.isoformat(),
            "deep": {
                **fb,
                "round": ticker_round(fb["ticker"], log_rows),
            },
            "screens": [],
            "fallback_mode": True,
            "fallback_reason": fb.get("fallback_reason"),
            "pool_stats": {
                "prefiltered_total": len(tickers),
                "eligible_today": 0,
                "fallback_used": True,
            },
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        log(f"OK: fallback deep={result['deep']['ticker']} (round {result['deep']['round']})")
        return 0

    # Stateful big/small alternation for deep-dive
    last_deep = last_mode_for_deep(log_rows)
    deep_size = "small_growth" if last_deep == "big" else "big"
    deep = pick(pool, deep_size)
    if deep is None:
        # Fall back to the other size
        fallback_size = "big" if deep_size == "small_growth" else "small_growth"
        log(f"WARN: {deep_size} pool exhausted, falling back to {fallback_size}")
        deep = pick(pool, fallback_size)
        if deep is None:
            log("ERROR: both pools exhausted")
            print(json.dumps({"error": "pools_exhausted"}))
            return 1

    # Remove deep from the pool before picking screens
    remaining = [c for c in pool if c["ticker"] != deep["ticker"]]

    screen_big = pick(remaining, "big")
    screen_small = pick(remaining, "small_growth")

    screens = [s for s in (screen_big, screen_small) if s is not None]
    # If one is missing, try to pick another from the other bucket
    if len(screens) < 2:
        extras = [c for c in remaining if c not in screens]
        random.shuffle(extras)
        while len(screens) < 2 and extras:
            screens.append(extras.pop())

    # Non-USA focus: +2 screens guaranteed from non-US markets (any size).
    taken = {deep["ticker"]} | {s["ticker"] for s in screens}
    non_us = [c for c in remaining
              if c["ticker"] not in taken and c.get("region") not in ("US", "?")]
    random.shuffle(non_us)
    screens.extend(non_us[:2])
    if len(non_us) < 2:
        log(f"WARN: only {len(non_us)} non-US candidates available for the 2 non-US screen slots")

    def enrich(t: dict) -> dict:
        return {
            "ticker": t["ticker"],
            "size": t.get("size", "big"),
            "region": t.get("region", "?"),
            "sector": t.get("sector", "?"),
            "note": t.get("note", ""),
            "round": ticker_round(t["ticker"], log_rows),
        }

    result = {
        "date": today.isoformat(),
        "deep": enrich(deep),
        "screens": [enrich(s) for s in screens],
        "pool_stats": {
            "prefiltered_total": len(tickers),
            "eligible_today": len(pool),
            "last_deep_size": last_deep,
            "big_available": sum(1 for c in pool if c.get("size") == "big"),
            "small_available": sum(1 for c in pool if c.get("size") == "small_growth"),
            "non_us_available": sum(1 for c in pool if c.get("region") not in ("US", "?")),
            "hyper_growth_reserved": n_hyper,  # handled by /bd_stocks_daily_growth
        },
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    log(f"OK: picked deep={result['deep']['ticker']} ({deep_size}), "
        f"screens={[s['ticker'] for s in result['screens']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
