"""
pick_candidates.py — Selecciona 3 tickers do pool pre-filtrado para avaliação diária.

Regras:
- 1 deep-dive + 2 screens
- Deep alterna big <-> small_growth stateful (last_mode em _log.csv)
- Screens: 1 big + 1 small_growth
- Dedupe: tickers avaliados nos últimos 183 dias são excluídos
- Round: se ticker já foi avaliado antes (com gap >183d), round += 1

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
FALLBACK_MIN_AGE_DAYS = 14   # don't re-eval a ticker that was deep-dived this week
FALLBACK_MAX_ROUND = 5       # cap re-evaluation rounds to avoid infinite loops on perma-stale tickers
FALLBACK_SHORTLIST_MIN_SCORE = 7.5


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


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
    for row in reversed(log_rows):
        if row.get("ticker") == ticker:
            try:
                return datetime.strptime(row["date"], "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
    return None


def ticker_round(ticker: str, log_rows: list[dict]) -> int:
    """1-based: first evaluation is round 1, second is round 2, ...
    Counts distinct dates — a same-day screen+deep pair is one visit."""
    dates = {r.get("date") for r in log_rows if r.get("ticker") == ticker}
    return len(dates) + 1


def eligible(tickers: list[dict], log_rows: list[dict], today: date) -> list[dict]:
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
      1. Stalest active shortlist (score >= 7.5, age >= 14d, round < 5).
      2. Stalest any-verdict ticker (age >= 14d, round < 5).
      3. None — empty log, fresh install. Caller falls through to today's
         "all_deduped" exit + bat-side email guard handles the day.
    """
    if not log_rows:
        return None

    candidates = []  # list of (last_eval_date, ticker, last_row, last_round)
    seen_round = {}
    last_seen = {}
    for row in log_rows:
        t = row.get("ticker")
        if not t:
            continue
        try:
            d = datetime.strptime(row["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        # Track most-recent eval per ticker
        if t not in last_seen or d > last_seen[t]:
            last_seen[t] = d
            seen_round[t] = row
        # Round = distinct eval dates per ticker (same-day screen+deep = one visit)
    round_dates: dict[str, set] = {}
    for row in log_rows:
        t = row.get("ticker")
        if t:
            round_dates.setdefault(t, set()).add(row.get("date"))
    rounds = {t: len(ds) for t, ds in round_dates.items()}

    cutoff = today - timedelta(days=FALLBACK_MIN_AGE_DAYS)

    # Tier 1: shortlist (high-score, fresh enough to be on shortlist)
    tier1 = []
    tier2 = []
    for t, last in last_seen.items():
        if last > cutoff:
            continue  # too recent
        if rounds.get(t, 0) >= FALLBACK_MAX_ROUND:
            continue  # round-cap
        row = seen_round[t]
        try:
            score = float(row.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        entry = (last, t, row, rounds.get(t, 0))
        if score >= FALLBACK_SHORTLIST_MIN_SCORE:
            tier1.append(entry)
        tier2.append(entry)

    if tier1:
        tier1.sort()  # oldest first
        last, t, row, _ = tier1[0]
        log(f"FALLBACK: tier-1 shortlist re-eval, picking stalest score>={FALLBACK_SHORTLIST_MIN_SCORE}: {t} (last {last})")
        return {
            "ticker": t,
            "size": row.get("size", "big") or "big",
            "region": row.get("region", "?"),
            "sector": row.get("sector", "?"),
            "note": row.get("notes", "") or "",
            "fallback_reason": "pool_exhausted_shortlist_reeval",
        }

    if tier2:
        tier2.sort()
        last, t, row, _ = tier2[0]
        log(f"FALLBACK: tier-2 any-verdict re-eval, picking oldest: {t} (last {last})")
        return {
            "ticker": t,
            "size": row.get("size", "big") or "big",
            "region": row.get("region", "?"),
            "sector": row.get("sector", "?"),
            "note": row.get("notes", "") or "",
            "fallback_reason": "pool_exhausted_any_verdict_reeval",
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
    else:
        pool = eligible(tickers, log_rows, today)

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
        },
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    log(f"OK: picked deep={result['deep']['ticker']} ({deep_size}), "
        f"screens={[s['ticker'] for s in result['screens']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
