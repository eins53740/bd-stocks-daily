"""
company_names.py — ticker → readable company name.

`_log.csv` stores tickers only, so every surface built from it says `WKL.AS` and
`0175.HK` and leaves you to remember which company that is. The names exist —
just never in the same place twice — so this collects them once into
`_company_names.json` and everything else reads that.

Sources, best first:
  1. `_tmp/{date}_{ticker}.json` -> `company_name`  (413/413 analysis JSONs carry it)
  2. the report H1: `# TICKER — Company Name — Score: ...`  (212/269 reports)
  3. `listings.REGISTRY` -> the curated name for dual-listed companies
  4. nothing — callers fall back to the bare ticker rather than invent a name

stdlib only, no network. Rebuilding is a filesystem sweep, so the cache is a
speed optimisation, never a source of truth: `--rebuild` regenerates it from
scratch and is safe to run any time.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

OUT_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
CACHE = OUT_DIR / "_company_names.json"

# `# TSM — Taiwan Semiconductor Manufacturing Company Limited — Score: 8.14/10 🟢 INVEST`
# Em-dash or hyphen, because both appear across the archive.
_H1_RE = re.compile(r"^#\s+(\S+)\s+[—–-]\s+(.+?)\s+[—–-]\s+Score:", re.M)
_REPORT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+?)(?:_(growth))?_([a-z]+)\.md$")

# Legal-form noise that makes a shortlist column unreadable. Stripped only from
# the END of a name, so "S.A. Industries" (were it to exist) survives intact.
_SUFFIX_NOISE = re.compile(
    r"[,\s]+(?:"
    r"inc\.?|corp\.?|corporation|co\.?|company|ltd\.?|limited|plc|"
    r"n\.?v\.?|s\.?a\.?(?:\.?s)?|s\.?p\.?a\.?|a\.?g\.?|ab(?:\s*\(publ\))?|"
    r"a/s|as|oyj|asa|holdings?|group|the"
    r")\.?$", re.I)

MAX_NAME_CHARS = 34


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def shorten(name: str, limit: int = MAX_NAME_CHARS) -> str:
    """A name that fits in a table cell. Trims legal suffixes first (they carry
    no information in a shortlist), truncates only if still too long."""
    s = (name or "").strip()
    prev = None
    while s and s != prev:            # "Evolution AB (publ)" -> "Evolution"
        prev = s
        s = _SUFFIX_NOISE.sub("", s).strip()
    s = s or (name or "").strip()
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s


def _from_analysis_jsons(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    tmp = root / "_tmp"
    if not tmp.is_dir():
        return out
    for p in sorted(tmp.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        t, n = d.get("ticker"), d.get("company_name")
        if isinstance(t, str) and isinstance(n, str) and t.strip() and n.strip():
            out[t.strip()] = n.strip()      # later files win — sorted = newest last
    return out


def _from_report_titles(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for folder in (root, root / "_archive"):
        if not folder.is_dir():
            continue
        for p in sorted(folder.glob("*.md")):
            if not _REPORT_RE.match(p.name):
                continue
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                continue
            m = _H1_RE.search(head)
            if m:
                out[m.group(1).strip()] = m.group(2).strip()
    return out


def _from_registry() -> dict[str, str]:
    try:
        import listings
    except Exception:
        return {}
    out = {}
    for g in listings.REGISTRY:
        for sym in listings.all_tickers(g["home"]):
            out[sym] = g["company"]
    return out


def build(root: Path | None = None) -> dict[str, str]:
    """Full sweep. Later sources overwrite earlier ones, so the priority order
    reads bottom-up: registry < report titles < analysis JSONs."""
    root = root or OUT_DIR
    names = _from_registry()
    names.update(_from_report_titles(root))
    names.update(_from_analysis_jsons(root))
    return dict(sorted(names.items()))


def load(root: Path | None = None, rebuild: bool = False) -> dict[str, str]:
    root = root or OUT_DIR
    cache = root / CACHE.name
    if not rebuild and cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    names = build(root)
    try:
        cache.write_text(json.dumps(names, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log(f"company-name cache write failed (non-fatal): {exc}")
    return names


def name_for(ticker: str, names: dict[str, str] | None = None) -> str | None:
    """Readable name for a ticker, or None. Falls back across the company's other
    listings — an ADR-era report may hold the name the home line never recorded."""
    names = load() if names is None else names
    t = (ticker or "").strip()
    if t in names:
        return names[t]
    try:
        import listings
        for alt in listings.all_tickers(t):
            if alt in names:
                return names[alt]
    except Exception:
        pass
    return None


def label(ticker: str, names: dict[str, str] | None = None,
          limit: int = MAX_NAME_CHARS) -> str:
    """`TICKER (Company)` when the name is known, plain `TICKER` when it isn't.
    Never invents — an unknown name renders as the ticker alone."""
    n = name_for(ticker, names)
    return f"{ticker} ({shorten(n, limit)})" if n else ticker


def main() -> int:
    ap = argparse.ArgumentParser(description="ticker -> company name cache")
    ap.add_argument("ticker", nargs="?")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    names = load(rebuild=args.rebuild)
    if args.ticker:
        print(label(args.ticker, names))
        return 0
    if args.list:
        for t, n in names.items():
            print(f"{t:14s} {n}")
        return 0
    print(json.dumps({"cached": len(names), "path": str(CACHE)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
