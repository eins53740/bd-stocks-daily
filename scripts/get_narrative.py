"""
get_narrative.py — Narrative-only fallback when SEC EDGAR is blocked.

WebFetch against SEC EDGAR routinely returns 403 (rate-limit / UA gate) and other
filing aggregators are inconsistent. This script pulls narrative material from
yfinance + stockanalysis.com without hitting the SEC, so Phase 2.5 LLM prompts
can degrade gracefully instead of falling all the way back to `(inferred)`.

Outputs JSON dict:
  {
    "ticker": "NVDA",
    "company_name": "NVIDIA Corporation",
    "business_summary": "...",          # from yfinance longBusinessSummary
    "recent_news": [                    # most recent N items from yfinance news
      {"title", "publisher", "link", "summary", "published_at"},
      ...
    ],
    "ir_url": "...",                    # best-effort investor relations URL
    "sources_used": ["yfinance.info", "yfinance.news"],
    "fetch_warnings": [...],
    "narrative_quality": "good|partial|degraded"
  }

Caller (SKILL.md Phase 4) uses the combined business_summary + recent_news content
as the `{ANNUAL_NARRATIVE}` substitution for Phase 2.5 prompts.

Run: python get_narrative.py --ticker NVDA --max-news 5
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

warnings.filterwarnings("ignore")

import yfinance as yf  # noqa: E402


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def fetch_narrative(ticker: str, max_news: int = 5) -> dict:
    out = {
        "ticker": ticker,
        "company_name": ticker,
        "business_summary": "",
        "recent_news": [],
        "ir_url": "",
        "sources_used": [],
        "fetch_warnings": [],
        "narrative_quality": "degraded",
    }

    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}
    except Exception as e:
        out["fetch_warnings"].append(f"yfinance Ticker init: {e}")
        return out

    # Business summary from yfinance info
    out["company_name"] = info.get("longName") or info.get("shortName") or ticker
    summary = info.get("longBusinessSummary") or ""
    if summary:
        out["business_summary"] = summary
        out["sources_used"].append("yfinance.info.longBusinessSummary")
    else:
        out["fetch_warnings"].append("yfinance.info.longBusinessSummary missing")

    # IR URL
    website = info.get("website") or ""
    if website:
        out["ir_url"] = website.rstrip("/") + "/investors"
        out["sources_used"].append("yfinance.info.website")

    # Recent news from yfinance
    try:
        news_items = tk.news or []
        for n in news_items[:max_news]:
            # yfinance changed news schema across versions — handle both
            if isinstance(n, dict) and "content" in n:
                c = n["content"] or {}
                out["recent_news"].append({
                    "title": c.get("title") or "",
                    "publisher": (c.get("provider") or {}).get("displayName") or "",
                    "link": (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or "",
                    "summary": c.get("summary") or c.get("description") or "",
                    "published_at": c.get("pubDate") or "",
                })
            elif isinstance(n, dict):
                out["recent_news"].append({
                    "title": n.get("title", ""),
                    "publisher": n.get("publisher", ""),
                    "link": n.get("link", ""),
                    "summary": n.get("summary", ""),
                    "published_at": str(n.get("providerPublishTime", "")),
                })
        if out["recent_news"]:
            out["sources_used"].append("yfinance.news")
    except Exception as e:
        out["fetch_warnings"].append(f"yfinance.news: {e}")

    # Stockanalysis.com link (caller can WebFetch; this server is less restrictive than SEC)
    slug = ticker.lower().split(".")[0]
    out["stockanalysis_fundamentals_url"] = f"https://stockanalysis.com/stocks/{slug}/financials/"
    out["sources_used"].append("stockanalysis.com (link only)")

    # Quality grading
    has_summary = bool(out["business_summary"])
    has_news = len(out["recent_news"]) >= 2
    if has_summary and has_news:
        out["narrative_quality"] = "good"
    elif has_summary or has_news:
        out["narrative_quality"] = "partial"
    else:
        out["narrative_quality"] = "degraded"

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--max-news", type=int, default=5)
    args = ap.parse_args()

    result = fetch_narrative(args.ticker, args.max_news)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    log(
        f"get_narrative {args.ticker}: quality={result['narrative_quality']}, "
        f"summary={len(result['business_summary'])} chars, news={len(result['recent_news'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
