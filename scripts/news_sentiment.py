"""
news_sentiment.py — v4.1 Phase H: news & market sentiment overlay.

Collects recent per-ticker headlines (yfinance news = primary; optionally ONE
NewsAPI query on the user's trial key) and runs a single LLM call that classifies
them into a **stock** sentiment and a **market** sentiment, each −1..+1 with 2–3
named themes and headline citations (spec §11c Phase H, idea #6).

Overlay-only: merges an additive `news_sentiment` key; NEVER touches the composite/
verdict/top_strip (schema stays 2.2). Sentiment is *context, not a gate* — it
complements the `news_freshness` decay overlay (freshness = how stale, sentiment =
which direction). Deep-dives only.

Graceful degradation is the contract: no NewsAPI key → yfinance-only; NewsAPI
401/429/quota-exhausted → drop it for the run and continue; no headlines or no LLM
key → an "available: false" block so the report renders an *n/a card* (never a
crash, always exit 0). Runs under ambient Python312 (needs yfinance + the
groq/gemini SDKs via llm_client; the requests call is lazy + guarded).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import llm_client  # noqa: E402  (pure stdlib itself; SDKs lazy-imported inside it)

MAX_NEWS_DEFAULT = 8
BULLISH_CUTOFF = 0.15   # score >= → bullish; <= −cutoff → bearish; else neutral


def log(msg: str) -> None:
    print(f"[news_sentiment] {msg}", file=sys.stderr)


# ===================================================================
# Pure functions (stdlib only — unit-tested under uv, no network)
# ===================================================================
def parse_news_items(raw_items, max_news: int = MAX_NEWS_DEFAULT) -> list:
    """Normalise yfinance `Ticker.news` items → [{title, publisher, link, summary,
    published_at}]. Handles BOTH the new `content` schema and the legacy flat schema
    (epoch `providerPublishTime`). Pure: takes already-fetched dicts, no network."""
    out = []
    for n in (raw_items or [])[:max_news]:
        if isinstance(n, dict) and "content" in n:
            c = n["content"] or {}
            out.append({
                "title": (c.get("title") or "").strip(),
                "publisher": ((c.get("provider") or {}).get("displayName") or "").strip(),
                "link": (c.get("canonicalUrl") or {}).get("url")
                        or (c.get("clickThroughUrl") or {}).get("url") or "",
                "summary": (c.get("summary") or c.get("description") or "").strip(),
                "published_at": c.get("pubDate") or "",
            })
        elif isinstance(n, dict):
            ts = n.get("providerPublishTime")
            try:
                published = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                published = str(ts or "")
            out.append({
                "title": (n.get("title") or "").strip(),
                "publisher": (n.get("publisher") or "").strip(),
                "link": n.get("link") or "",
                "summary": (n.get("summary") or "").strip(),
                "published_at": published,
            })
    return [h for h in out if h["title"]]


def parse_newsapi_articles(articles, max_news: int = MAX_NEWS_DEFAULT) -> list:
    """Normalise NewsAPI `articles` → the same headline shape. Pure."""
    out = []
    for a in (articles or [])[:max_news]:
        if not isinstance(a, dict):
            continue
        out.append({
            "title": (a.get("title") or "").strip(),
            "publisher": ((a.get("source") or {}).get("name") or "").strip(),
            "link": a.get("url") or "",
            "summary": (a.get("description") or "").strip(),
            "published_at": a.get("publishedAt") or "",
        })
    return [h for h in out if h["title"]]


def dedupe_headlines(headlines: list, limit: int = MAX_NEWS_DEFAULT) -> list:
    """Drop case-insensitive duplicate titles, keep order, cap at `limit`."""
    seen, out = set(), []
    for h in headlines:
        key = h.get("title", "").lower()
        if key and key not in seen:
            seen.add(key)
            out.append(h)
        if len(out) >= limit:
            break
    return out


def clamp_score(value):
    """Coerce to a float sentiment in [−1, 1]; None if not numeric."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(-1.0, min(1.0, v)), 2)


def label_for(score) -> str:
    if score is None:
        return "n/a"
    if score >= BULLISH_CUTOFF:
        return "bullish"
    if score <= -BULLISH_CUTOFF:
        return "bearish"
    return "neutral"


def sentiment_emoji(score) -> str:
    if score is None:
        return "❔"
    if score >= BULLISH_CUTOFF:
        return "📈"
    if score <= -BULLISH_CUTOFF:
        return "📉"
    return "➖"


def _clean_dial(raw) -> dict:
    """Validate one sentiment dial from the model → {score, label, themes, citations}."""
    d = raw if isinstance(raw, dict) else {}
    score = clamp_score(d.get("score"))
    themes = [str(t).strip()[:80] for t in (d.get("themes") or []) if str(t).strip()][:3]
    cites = [str(c).strip()[:160] for c in (d.get("citations") or []) if str(c).strip()][:3]
    return {"score": score, "label": label_for(score), "themes": themes, "citations": cites}


def validate_sentiment(result: dict) -> dict:
    """llm_client result → {available, stock, market} (or a reason on degrade)."""
    if not result.get("ok") or not isinstance(result.get("data"), dict):
        return {"available": False, "reason": result.get("error") or "no data"}
    d = result["data"]
    stock = _clean_dial(d.get("stock_sentiment") or d.get("stock"))
    market = _clean_dial(d.get("market_sentiment") or d.get("market"))
    if stock["score"] is None and market["score"] is None:
        return {"available": False, "reason": "model returned no numeric scores"}
    return {"available": True, "stock": stock, "market": market,
            "provider": result.get("provider"), "model": result.get("model")}


def build_prompt(ticker: str, company: str, headlines: list) -> str:
    lines = []
    for i, h in enumerate(headlines, 1):
        pub = f" ({h['publisher']})" if h.get("publisher") else ""
        summ = f" — {h['summary'][:200]}" if h.get("summary") else ""
        lines.append(f"{i}. {h['title']}{pub}{summ}")
    return (
        f"Classify news sentiment for {company or ticker} ({ticker}) from the "
        f"headlines below.\n"
        "Return TWO dials, each a float in [-1, 1] (−1 very negative, 0 neutral, "
        "+1 very positive):\n"
        "  • stock_sentiment — sentiment specifically about THIS company.\n"
        "  • market_sentiment — the broader market/macro tone these headlines imply.\n"
        "For each dial give 2-3 short named themes and cite the exact headline "
        "titles that drove it. Judge only what the headlines say; do not invent "
        "facts.\n"
        "Reply with STRICT JSON only:\n"
        '{"stock_sentiment": {"score": <float>, "themes": ["..."], '
        '"citations": ["<headline>"]}, "market_sentiment": {"score": <float>, '
        '"themes": ["..."], "citations": ["<headline>"]}}\n\n'
        "HEADLINES:\n" + "\n".join(lines))


# ===================================================================
# I/O (lazy imports; run under ambient Python312)
# ===================================================================
def fetch_yfinance_news(ticker: str, max_news: int) -> tuple:
    """(headlines, warning|None). Lazy-imports yfinance so the module stays uv-testable."""
    try:
        import yfinance as yf  # lazy: only ambient Python312 has it
        tk = yf.Ticker(ticker)
        return parse_news_items(tk.news or [], max_news), None
    except Exception as e:
        return [], f"yfinance.news: {type(e).__name__}: {e}"


def fetch_newsapi(query: str, key: str, max_news: int) -> tuple:
    """ONE NewsAPI query. (headlines, warning|None). Any error → drop, never raise."""
    try:
        import requests  # lazy + guarded
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={"q": query, "language": "en", "sortBy": "publishedAt",
                    "pageSize": max_news, "apiKey": key},
            timeout=10,
        )
        if resp.status_code != 200:
            return [], f"newsapi dropped: HTTP {resp.status_code}"
        payload = resp.json()
        if payload.get("status") != "ok":
            return [], f"newsapi dropped: {payload.get('code') or payload.get('status')}"
        return parse_newsapi_articles(payload.get("articles"), max_news), None
    except Exception as e:
        return [], f"newsapi dropped: {type(e).__name__}: {e}"


def collect_headlines(ticker: str, company: str, max_news: int, keys: dict) -> dict:
    """yfinance primary + optional single NewsAPI query. Returns headlines + provenance."""
    warnings, sources = [], []
    yf_news, warn = fetch_yfinance_news(ticker, max_news)
    if warn:
        warnings.append(warn)
    if yf_news:
        sources.append("yfinance.news")
    headlines = list(yf_news)

    newsapi_key = llm_client.resolve_key("api_key_newsapi", "NEWSAPI_KEY", keys)
    if newsapi_key:
        na_news, warn = fetch_newsapi(company or ticker, newsapi_key, max_news)
        if warn:
            warnings.append(warn)
        elif na_news:
            sources.append("newsapi")
            headlines.extend(na_news)
    else:
        warnings.append("newsapi key absent — yfinance-only")

    return {"headlines": dedupe_headlines(headlines, max_news),
            "sources_used": sources, "warnings": warnings}


# ===================================================================
# Orchestration
# ===================================================================
def run(analysis_json: str, max_news: int = MAX_NEWS_DEFAULT, keys: dict | None = None) -> dict:
    data = json.loads(Path(analysis_json).read_text(encoding="utf-8"))
    ticker = data.get("ticker")
    if not ticker:
        return {"error": "analysis JSON has no ticker"}
    company = data.get("company_name") or ticker
    if keys is None:
        keys = llm_client.load_keys()

    collected = collect_headlines(ticker, company, max_news, keys)
    headlines = collected["headlines"]
    now = datetime.now().isoformat()

    if not headlines:
        return {"available": False, "reason": "no headlines found",
                "fetched_at": now, "n_headlines": 0,
                "sources_used": collected["sources_used"], "warnings": collected["warnings"]}

    prompt = build_prompt(ticker, company, headlines)
    try:
        result = llm_client.complete_json(
            prompt, "You are a financial news sentiment classifier. Output strict JSON only.",
            keys=keys, max_tokens=700, temperature=0.2)
    except Exception as e:  # llm_client never raises, but belt-and-braces
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    sent = validate_sentiment(result)

    block = {
        "fetched_at": now,
        "n_headlines": len(headlines),
        "sources_used": collected["sources_used"],
        "model_chain": f"{llm_client.GROQ_MODEL_DEFAULT} → {llm_client.GEMINI_MODEL_DEFAULT}",
        # keep a few headlines (title/publisher/date only) for the report card
        "headlines": [{"title": h["title"], "publisher": h["publisher"],
                       "published_at": h["published_at"]} for h in headlines[:6]],
        "warnings": collected["warnings"],
    }
    if sent.get("available"):
        block.update({"available": True, "stock": sent["stock"], "market": sent["market"],
                      "provider": sent.get("provider"), "model": sent.get("model")})
    else:
        block.update({"available": False, "reason": sent.get("reason")})
    return block


def merge_into_analysis(analysis_json: str, block: dict) -> None:
    """Merge the additive `news_sentiment` key (schema stays 2.2; composite untouched)."""
    path = Path(analysis_json)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["news_sentiment"] = block
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    log(f"merged news_sentiment into {path.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description="News & market sentiment overlay (yfinance + optional NewsAPI)")
    ap.add_argument("--ticker", help="informational only; the ticker is read from the analysis JSON")
    ap.add_argument("--analysis-json", required=True)
    ap.add_argument("--max-news", type=int, default=MAX_NEWS_DEFAULT)
    ap.add_argument("--update", action="store_true",
                    help="Merge the result into the analysis JSON (key: news_sentiment)")
    args = ap.parse_args()

    try:
        block = run(args.analysis_json, args.max_news)
        if args.update and "error" not in block:
            merge_into_analysis(args.analysis_json, block)
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        print(json.dumps({"error": str(e), "error_type": type(e).__name__}))
        return 0  # non-fatal: sentiment absent, run continues

    print(json.dumps(block, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
