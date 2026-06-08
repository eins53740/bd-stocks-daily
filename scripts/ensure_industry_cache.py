"""
ensure_industry_cache.py - Bookkeeping for the per-sector industry analysis cache.

Checks whether `<OUT_DIR>/_industry/<slug>.md` exists and is fresh (<=90 days old
per its frontmatter `generated_at` date). Emits a JSON directive on stdout.

This script does NOT generate content. Content generation (macro / customer /
architecture prompts + WebFetch) is the LLM's job in SKILL.md Phase 2.5. This
script only signals whether a refresh is needed.

Output schema:
  {
    "slug": "semiconductors",
    "path": "C:/BD_Obsidian/Personal/Finance/StocksDaily/_industry/semiconductors.md",
    "exists": true,
    "stale": false,
    "reason": "fresh" | "missing" | "expired" | "unreadable",
    "age_days": 42,
    "generated_at": "2026-03-09"
  }
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

OUT_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
CACHE_DIR = OUT_DIR / "_industry"
MAX_AGE_DAYS = 90

# Force UTF-8 on Windows
for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def slugify(sector: str) -> str:
    s = sector.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unknown"


def parse_generated_at(md_text: str) -> date | None:
    # Looks for YAML frontmatter between opening --- lines and extracts generated_at.
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", md_text, re.DOTALL)
    if not m:
        return None
    fm = m.group(1)
    g = re.search(r"^generated_at:\s*(\S+)", fm, re.MULTILINE)
    if not g:
        return None
    raw = g.group(1).strip().strip("'\"")
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except ValueError:
        return None


def check(sector: str) -> dict:
    slug = slugify(sector)
    path = CACHE_DIR / f"{slug}.md"
    result = {
        "slug": slug,
        "path": str(path).replace("\\", "/"),
        "exists": path.exists(),
        "stale": True,
        "reason": "missing",
        "age_days": None,
        "generated_at": None,
    }
    if not path.exists():
        return result

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        result["reason"] = f"unreadable: {e}"
        return result

    gen = parse_generated_at(text)
    if gen is None:
        result["reason"] = "unreadable"
        return result

    age = (date.today() - gen).days
    result["generated_at"] = gen.isoformat()
    result["age_days"] = age
    if age > MAX_AGE_DAYS:
        result["stale"] = True
        result["reason"] = "expired"
    else:
        result["stale"] = False
        result["reason"] = "fresh"
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sector", required=True, help="Sector name, e.g. 'Semiconductors'")
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    res = check(args.sector)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
