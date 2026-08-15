"""universe_admin.py — `--add-ticker` and `--list-pending` (v4.3 wave 4.2).

Adding a name to the pool was a hand edit of `_universe_pending.yaml` (`MANUAL.md` §7.1),
which is fine until you mistype a symbol: the prefilter then burns a yfinance call on a
ticker that does not exist, files it under RETRY, and retries it every Monday forever.

WHY THIS SHIPS WITH ROADMAP R3 AND NOT BEFORE IT. `run_prefilter.py` wipes
`_universe_pending.yaml` at the end of every run, and `_universe.yaml` was never written —
so a ticker seeded through pending was evaluated **exactly once, ever**, and then dropped
out of the work list. `build_work_list()` reads UNIVERSE + PENDING + RETRY, not PREFILTERED,
so even a name that PASSED and joined the pool was never re-validated afterwards. Shipping
`--add-ticker` on top of that would have been shipping a feature that is broken by design:
you add a name, it is looked at once, and it silently disappears. R3 (promote answered
entrants into `_universe.yaml`) landed in the same change.

Ground-truth rule: the only network call here is a symbol EXISTENCE check. Nothing this
script writes is a number that reaches a report.

Usage:
  python universe_admin.py --add-ticker ASML.AS --region EU --sector Technology --note "..."
  python universe_admin.py --list-pending
  python universe_admin.py --add-ticker XYZ --no-validate     # skip the yfinance check
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

OUT_DIR_DEFAULT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")

UNIVERSE = "_universe.yaml"
PENDING = "_universe_pending.yaml"
PREFILTERED = "_prefiltered.yaml"
PAUSED = "_universe_paused.yaml"
RETRY = "_universe_retry.yaml"
LOG = "_log.csv"
SHORTLIST = "_shortlist.md"

SHORTLIST_EXPIRY_DAYS = 90     # matches `_universe.yaml: rotation.shortlist_expiry_days`
# Yahoo symbols: base, optional dotted venue suffix. Deliberately permissive on the base
# (`BRK-B`, `RDS-A`, `005930`, `2330`) and strict on shape, because the point is to catch a
# typo before it costs a weekly API call — not to re-implement Yahoo's symbol grammar.
TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,14}$")


def log(msg: str) -> None:
    print(f"[universe_admin] {msg}", file=sys.stderr)


# ===================================================================
# minimal YAML I/O (stdlib only — same constraint as run_prefilter)
# ===================================================================
def load_yaml(path: Path, default=None):
    """Read a `{version, tickers: [...]}` document without a YAML dependency.

    Handles both shapes the pool files use: inline flow maps
    (`- {ticker: MSFT, region: US}`) and block maps. Anything it cannot parse is
    skipped rather than guessed at — a mangled entry must not become a fabricated one.
    """
    if not path.is_file():
        return default if default is not None else {"version": 1, "tickers": []}
    try:
        import yaml  # noqa: PLC0415
        return yaml.safe_load(path.read_text(encoding="utf-8")) or \
            (default if default is not None else {"version": 1, "tickers": []})
    except ImportError:
        pass
    out = {"version": 1, "tickers": []}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s.startswith("- "):
            continue
        body = s[2:].strip()
        if body.startswith("{") and body.endswith("}"):
            body = body[1:-1]
        entry = {}
        for part in _split_top_level(body):
            if ":" not in part:
                continue
            k, _, v = part.partition(":")
            entry[k.strip()] = v.strip().strip('"').strip("'") or None
        if entry.get("ticker"):
            out["tickers"].append(entry)
    return out


def _split_top_level(body: str) -> list:
    """Split on commas that are not inside quotes — notes contain commas."""
    parts, buf, quote = [], [], None
    for ch in body:
        if quote:
            if ch == quote:
                quote = None
            buf.append(ch)
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p for p in parts if p.strip()]


def dump_pending(entries: list) -> str:
    lines = ["# Pending entrants — validated and merged by the weekly prefilter.",
             "# Written by `universe_admin.py --add-ticker`; safe to edit by hand.",
             "version: 1", "tickers:"]
    if not entries:
        lines[-1] = "tickers: []"
        return "\n".join(lines) + "\n"
    for e in entries:
        bits = [f"ticker: {e['ticker']}"]
        for k in ("region", "sector", "size"):
            if e.get(k):
                bits.append(f"{k}: {e[k]}")
        if e.get("added"):
            # Quoted deliberately: unquoted, pyyaml parses this back as a `date` object
            # while the stdlib fallback parser returns a `str`, so the same file would
            # round-trip to two different types depending on what is installed.
            bits.append(f'added: "{e["added"]}"')
        if e.get("note"):
            note = str(e["note"]).replace('"', "'")
            bits.append(f'note: "{note}"')
        lines.append("  - {" + ", ".join(bits) + "}")
    return "\n".join(lines) + "\n"


# ===================================================================
# validation
# ===================================================================
def validate_symbol(ticker: str, _fetcher=None) -> tuple[bool, str]:
    """(exists, note). Injectable so the test suite stays network-free."""
    if _fetcher is not None:
        return _fetcher(ticker)
    try:
        import yfinance as yf  # noqa: PLC0415
        info = yf.Ticker(ticker).fast_info
        price = None
        for attr in ("last_price", "lastPrice", "regular_market_price"):
            price = getattr(info, attr, None) or (
                info.get(attr) if hasattr(info, "get") else None)
            if price:
                break
        if price:
            return True, f"resolved at {price}"
        return False, "yfinance returned no price — symbol likely does not exist"
    except Exception as exc:                      # noqa: BLE001
        # A network failure is NOT proof the symbol is bad. Say which one it was, and
        # let the caller decide, rather than rejecting a good ticker because Wi-Fi blipped.
        return False, f"could not verify ({type(exc).__name__}: {exc})"


def add_ticker(ticker: str, out_dir: Path, *, region=None, sector=None, size=None,
               note=None, validate=True, _fetcher=None) -> dict:
    """Append one validated entrant to `_universe_pending.yaml`. Pure apart from I/O."""
    result = {"ticker": ticker, "added": False, "reason": None}
    t = (ticker or "").strip()
    if not TICKER_RE.match(t):
        result["reason"] = f"'{ticker}' is not a plausible Yahoo symbol"
        return result

    known = {}
    for name, label in ((UNIVERSE, "universe"), (PREFILTERED, "prefiltered pool"),
                        (PENDING, "pending"), (PAUSED, "paused"), (RETRY, "retry queue")):
        for e in (load_yaml(out_dir / name).get("tickers") or []):
            known.setdefault(str(e.get("ticker") or "").upper(), label)
    if t.upper() in known:
        result["reason"] = f"already in the {known[t.upper()]}"
        return result

    if validate:
        ok, why = validate_symbol(t, _fetcher)
        result["validation"] = why
        if not ok:
            result["reason"] = f"symbol check failed: {why}"
            return result

    pend = load_yaml(out_dir / PENDING)
    entries = list(pend.get("tickers") or [])
    entries.append({"ticker": t, "region": region, "sector": sector,
                    "size": size or "big", "note": note,
                    "added": date.today().isoformat()})
    entries.sort(key=lambda e: str(e.get("ticker")))
    (out_dir / PENDING).write_text(dump_pending(entries), encoding="utf-8")
    result.update(added=True, pending_count=len(entries))
    return result


# ===================================================================
# --list-pending
# ===================================================================
def _log_tickers(out_dir: Path) -> set:
    path = out_dir / LOG
    if not path.is_file():
        return set()
    with path.open(encoding="utf-8", newline="") as fh:
        return {(r.get("ticker") or "").strip() for r in csv.DictReader(fh)}


def expired_shortlist(out_dir: Path, today: date | None = None) -> list:
    """Shortlist rows past their 90-day validity, read from the rendered markdown.

    The shortlist is a table with an `Expires` column, so the expiry is read rather than
    recomputed — recomputing it here would create a second definition of "expired" that
    could disagree with the one the report prints.
    """
    path = out_dir / SHORTLIST
    if not path.is_file():
        return []
    today = today or date.today()
    out = []
    header, idx_t, idx_e = None, None, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None and any(c.lower() == "ticker" for c in cells):
            header = cells
            lower = [c.lower() for c in cells]
            idx_t = lower.index("ticker")
            idx_e = lower.index("expires") if "expires" in lower else None
            continue
        if header is None or idx_e is None or len(cells) <= max(idx_t, idx_e):
            continue
        raw = re.sub(r"[^\d\-]", "", cells[idx_e])
        try:
            when = datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if when < today:
            out.append({"ticker": re.sub(r"[^\w.\-]", "", cells[idx_t]),
                        "expired": when.isoformat(),
                        "days_ago": (today - when).days})
    return out


def list_pending(out_dir: Path, today: date | None = None) -> dict:
    """Everything awaiting attention, in three named buckets.

    Kept as three buckets rather than one merged list because they need different
    actions: pending waits for Monday, never-evaluated waits for the daily picker to
    reach it, and expired needs a decision from a human.
    """
    today = today or date.today()
    pending = [e for e in (load_yaml(out_dir / PENDING).get("tickers") or []) if e.get("ticker")]
    evaluated = _log_tickers(out_dir)
    universe = [e for e in (load_yaml(out_dir / UNIVERSE).get("tickers") or []) if e.get("ticker")]
    never = [e for e in universe if str(e.get("ticker")).strip() not in evaluated]
    expired = expired_shortlist(out_dir, today)
    return {
        "as_of": today.isoformat(),
        "pending_entrants": pending,
        "never_evaluated": never,
        "shortlist_expired": expired,
        "counts": {"pending": len(pending), "never_evaluated": len(never),
                   "universe": len(universe), "evaluated": len(evaluated),
                   "shortlist_expired": len(expired)},
    }


def render_pending(block: dict) -> list:
    c = block["counts"]
    out = [f"as of {block['as_of']} — universe {c['universe']}, evaluated at least once "
           f"{c['evaluated']}"]
    out.append(f"  pending entrants ({c['pending']}) — merged by the Monday prefilter:")
    for e in block["pending_entrants"][:20] or [{"ticker": "(none)"}]:
        out.append(f"    · {e.get('ticker')}"
                   + (f" — {e.get('note')}" if e.get("note") else ""))
    out.append(f"  never evaluated ({c['never_evaluated']}) — in the universe, no _log.csv row:")
    for e in block["never_evaluated"][:20] or [{"ticker": "(none)"}]:
        out.append(f"    · {e.get('ticker'):<12}{e.get('region') or '':<6}{e.get('sector') or ''}")
    if c["never_evaluated"] > 20:
        out.append(f"    … and {c['never_evaluated'] - 20} more")
    out.append(f"  shortlist expired ({c['shortlist_expired']}) — past the "
               f"{SHORTLIST_EXPIRY_DAYS}-day validity:")
    for e in block["shortlist_expired"][:20] or [{"ticker": "(none)"}]:
        out.append(f"    · {e.get('ticker'):<12}expired {e.get('expired')} "
                   f"({e.get('days_ago')}d ago)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Pool administration for /bd-stocks-daily.")
    ap.add_argument("--add-ticker", metavar="TICKER")
    ap.add_argument("--region")
    ap.add_argument("--sector")
    ap.add_argument("--size", choices=["big", "small_growth", "hyper_growth"])
    ap.add_argument("--note")
    ap.add_argument("--no-validate", action="store_true",
                    help="skip the yfinance existence check (offline use)")
    ap.add_argument("--list-pending", action="store_true")
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    if args.add_ticker:
        res = add_ticker(args.add_ticker, out_dir, region=args.region, sector=args.sector,
                         size=args.size, note=args.note, validate=not args.no_validate)
        log(f"{res['ticker']}: " + ("added to pending" if res["added"]
                                    else f"NOT added — {res['reason']}"))
        print(json.dumps(res, ensure_ascii=False))
        return 0
    if args.list_pending:
        block = list_pending(out_dir)
        for line in render_pending(block):
            print(line, file=sys.stderr)
        print(json.dumps(block, ensure_ascii=False))
        return 0
    ap.error("nothing to do — pass --add-ticker or --list-pending")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
