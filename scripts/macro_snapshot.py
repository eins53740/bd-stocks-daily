"""
macro_snapshot.py - Daily macro/market snapshot bookkeeping + yfinance pull.

Two modes:
  --check  Emit a JSON directive on stdout (NO network). Signals whether today's
           `_macro/<date>.md` exists, which older file to fall back to, and whether
           the previous country-macro table is still fresh (<=7 days).
  --fetch  Pull index / rate / commodity / crypto quotes via yfinance, compute 1d
           and 1w percentage changes, write `_macro/<date>.json` and print it.

Like ensure_industry_cache.py, --check does NOT generate content. The narrative
`_macro/<date>.md` is written by the LLM (SKILL.md macro phase, prompts/macro_daily.md).
This script only signals freshness (--check) and provides ground-truth numbers (--fetch).

--check output schema:
  {
    "date": "2026-07-15",
    "md_path": "...\\_macro\\2026-07-15.md",
    "json_path": "...\\_macro\\2026-07-15.json",
    "exists": false,
    "stale": true,
    "reason": "missing" | "expired" | "fresh",
    "fallback_md": "...\\_macro\\2026-07-12.md" | null,
    "fallback_age_days": 3 | null,
    "country_table_fresh": false
  }

--fetch output schema:
  {
    "date": "2026-07-15",
    "fetched_at": "2026-07-15T17:03:11",
    "metrics": {
      "^GSPC": {"last": 5123.4, "chg_1d_pct": 0.42, "chg_1w_pct": 1.30},
      "^VIX":  {"error": "no data"},
      ...
    }
  }
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

OUT_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily\_macro")
COUNTRY_TABLE_MAX_AGE_DAYS = 7

# Snapshot universe: indices, volatility, rate, FX, commodities, crypto.
TICKERS = [
    "^GSPC", "^NDX", "^STOXX", "^GDAXI", "^FTSE", "^N225", "^HSI",  # indices
    "^VIX", "^TNX",                                                  # vol + US 10y
    "EURUSD=X",                                                      # FX
    "BZ=F", "GC=F",                                                  # Brent, gold
    "BTC-USD",                                                       # crypto
]

_DATE_MD_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")

# Force UTF-8 on Windows
for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _log(msg: str) -> None:
    print(f"[macro_snapshot] {msg}", file=sys.stderr)


# ------------------------- Pure computation (unit-tested, no network) -------------------------
def compute_changes(closes: list[float]) -> dict:
    """1d and 1w percentage changes from a list of daily closes (oldest -> newest).

    - last       = closes[-1]              (None if no closes)
    - chg_1d_pct = last vs closes[-2]      (None if <2 closes)
    - chg_1w_pct = last vs closes[-6]      (5 trading days back; None if <6 closes)
    Division-by-zero on a zero reference close degrades to None rather than raising.
    """
    result: dict = {"last": None, "chg_1d_pct": None, "chg_1w_pct": None}
    if not closes:
        return result
    last = float(closes[-1])
    result["last"] = last
    if len(closes) >= 2:
        prev = float(closes[-2])
        if prev:
            result["chg_1d_pct"] = round((last / prev - 1.0) * 100.0, 2)
    if len(closes) >= 6:
        week_ago = float(closes[-6])
        if week_ago:
            result["chg_1w_pct"] = round((last / week_ago - 1.0) * 100.0, 2)
    return result


def parse_country_table_date(md_text: str) -> date | None:
    """Extract `country_table_date` from YAML frontmatter. None if absent/unparseable."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", md_text, re.DOTALL)
    if not m:
        return None
    g = re.search(r"^country_table_date:\s*(\S+)", m.group(1), re.MULTILINE)
    if not g:
        return None
    raw = g.group(1).strip().strip("'\"")
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except ValueError:
        return None


def existing_md_files(out_dir: Path) -> list[tuple[date, Path]]:
    """`<date>.md` files in out_dir, sorted newest-date-first (by filename)."""
    files: list[tuple[date, Path]] = []
    if not out_dir.exists():
        return files
    for p in out_dir.glob("*.md"):
        m = _DATE_MD_RE.match(p.name)
        if not m:
            continue
        try:
            d = datetime.fromisoformat(m.group(1)).date()
        except ValueError:
            continue
        files.append((d, p))
    files.sort(key=lambda x: x[0], reverse=True)
    return files


def check(out_dir: Path, today: date | None = None) -> dict:
    today = today or date.today()
    md_path = out_dir / f"{today.isoformat()}.md"
    json_path = out_dir / f"{today.isoformat()}.json"
    files = existing_md_files(out_dir)
    exists = md_path.exists()

    result: dict = {
        "date": today.isoformat(),
        "md_path": str(md_path),
        "json_path": str(json_path),
        "exists": exists,
        "stale": not exists,
        "reason": "fresh" if exists else "missing",
        "fallback_md": None,
        "fallback_age_days": None,
        "country_table_fresh": False,
    }

    # When today's file is missing, fall back to the newest older file (if any).
    if not exists:
        for d, p in files:
            if d != today:
                result["fallback_md"] = str(p)
                result["fallback_age_days"] = (today - d).days
                result["reason"] = "expired"
                break

    # Country-macro freshness: read the newest existing .md's frontmatter.
    if files:
        newest = files[0][1]
        try:
            ctd = parse_country_table_date(newest.read_text(encoding="utf-8"))
        except Exception:
            ctd = None
        if ctd is not None and (today - ctd).days <= COUNTRY_TABLE_MAX_AGE_DAYS:
            result["country_table_fresh"] = True

    return result


# ------------------------- Network (yfinance) -------------------------
def fetch_metrics(tickers: list[str]) -> dict:
    """Pull each ticker's 1mo closes and reduce to compute_changes(). Per-ticker
    failures become `{"error": ...}` entries so one bad symbol never aborts the run."""
    import yfinance as yf

    metrics: dict = {}
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period="1mo")
            if hist is None or hist.empty:
                metrics[t] = {"error": "no data"}
                continue
            closes = [float(c) for c in hist["Close"].dropna().tolist()]
            if not closes:
                metrics[t] = {"error": "no closes"}
                continue
            metrics[t] = compute_changes(closes)
        except Exception as e:  # noqa: BLE001 - best-effort per ticker
            metrics[t] = {"error": str(e)}
            _log(f"{t}: {e}")
    return metrics


def fetch(out_dir: Path, today: date | None = None) -> dict:
    """Pull the quotes and MERGE `metrics` into `_macro/<date>.json`.

    Merge, not overwrite, and that is the whole point (roadmap R21). This used to write a
    fresh three-key payload, so a fetch landing after `macro_breadth --update` or
    `macro_fred --update` silently deleted their `breadth`/`sectors`/`regime` overlays --
    which made the node's position in the pipeline load-bearing and undocumented, and is
    why the daily runner was left calling `--check` (which writes nothing) instead. Now
    the three writers are all overlay-only and order between them cannot lose data.

    It owns `metrics` alone, exactly as breadth owns `breadth`/`sectors` and fred owns
    `regime`.
    """
    today = today or date.today()
    _log(f"fetching {len(TICKERS)} tickers for {today.isoformat()}")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{today.isoformat()}.json"

    data: dict
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            _log(f"could not parse {json_path.name} ({e}); re-initialising")
            data = {"date": today.isoformat()}
    else:
        data = {"date": today.isoformat()}

    data["date"] = today.isoformat()
    data["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    data["metrics"] = fetch_metrics(TICKERS)

    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _log(f"merged metrics into {json_path}")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily macro snapshot: --check freshness or --fetch quotes.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Emit freshness directive (no network).")
    mode.add_argument("--fetch", action="store_true", help="Pull quotes via yfinance and write JSON.")
    ap.add_argument("--out-dir", default=str(OUT_DIR), help="Macro output dir (default: StocksDaily/_macro).")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)

    if args.check:
        out_dir.mkdir(parents=True, exist_ok=True)
        res = check(out_dir)
    else:
        res = fetch(out_dir)

    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
