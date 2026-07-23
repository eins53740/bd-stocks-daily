"""
Unit tests for v4.1 Phase H — news_sentiment.py.

Pure parsing/validation + orchestration with the network and llm_client mocked
(no yfinance, no NewsAPI, no model). Verifies both yfinance news schemas, NewsAPI
normalisation, dial validation/clamping, graceful degrade (no headlines / dead
model → available:false, never crash), and overlay-only merge.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import news_sentiment as ns  # noqa: E402


SAMPLE = {"ticker": "CSCO", "company_name": "Cisco Systems",
          "scores": {"composite": 7.8}, "verdict": "invest"}

NEW_SCHEMA = [{"content": {"title": "Cisco beats on earnings",
                           "provider": {"displayName": "Reuters"},
                           "canonicalUrl": {"url": "http://x/1"},
                           "summary": "Strong quarter", "pubDate": "2026-07-22T10:00:00Z"}}]
LEGACY_SCHEMA = [{"title": "Cisco guides higher", "publisher": "Bloomberg",
                  "link": "http://x/2", "summary": "Raised guidance",
                  "providerPublishTime": 1_753_180_800}]


# ------------------------- news parsing (both schemas) -------------------------
def test_parse_new_schema():
    out = ns.parse_news_items(NEW_SCHEMA)
    assert len(out) == 1
    assert out[0]["title"] == "Cisco beats on earnings"
    assert out[0]["publisher"] == "Reuters"
    assert out[0]["link"] == "http://x/1"


def test_parse_legacy_schema_epoch_to_iso():
    out = ns.parse_news_items(LEGACY_SCHEMA)
    assert out[0]["title"] == "Cisco guides higher"
    assert out[0]["published_at"].startswith("2025-")  # epoch normalised to ISO


def test_parse_drops_titleless_and_caps():
    raw = [{"title": ""}, {"title": "keep me"}]
    out = ns.parse_news_items(raw, max_news=5)
    assert [h["title"] for h in out] == ["keep me"]
    assert ns.parse_news_items(NEW_SCHEMA * 10, max_news=3) and \
        len(ns.parse_news_items(NEW_SCHEMA * 10, max_news=3)) == 3


def test_parse_newsapi_articles():
    arts = [{"title": "Macro selloff", "source": {"name": "CNBC"},
             "url": "http://n/1", "description": "Rates fear", "publishedAt": "2026-07-22"}]
    out = ns.parse_newsapi_articles(arts)
    assert out[0]["publisher"] == "CNBC" and out[0]["title"] == "Macro selloff"


def test_dedupe_case_insensitive():
    hl = [{"title": "Same News"}, {"title": "same news"}, {"title": "Other"}]
    out = ns.dedupe_headlines(hl)
    assert [h["title"] for h in out] == ["Same News", "Other"]


# ------------------------- score / label / emoji -------------------------
def test_clamp_score():
    assert ns.clamp_score(0.5) == 0.5
    assert ns.clamp_score(2.0) == 1.0 and ns.clamp_score(-3) == -1.0
    assert ns.clamp_score("nan-text") is None and ns.clamp_score(None) is None


def test_label_and_emoji_bands():
    assert ns.label_for(0.4) == "bullish" and ns.sentiment_emoji(0.4) == "📈"
    assert ns.label_for(-0.4) == "bearish" and ns.sentiment_emoji(-0.4) == "📉"
    assert ns.label_for(0.05) == "neutral" and ns.sentiment_emoji(0.05) == "➖"
    assert ns.label_for(None) == "n/a"


# ------------------------- dial / sentiment validation -------------------------
def test_clean_dial_clamps_and_caps_lists():
    dial = ns._clean_dial({"score": 0.9, "themes": ["a", "b", "c", "d"],
                           "citations": ["h1", "h2", "h3", "h4"]})
    assert dial["score"] == 0.9 and dial["label"] == "bullish"
    assert len(dial["themes"]) == 3 and len(dial["citations"]) == 3


def test_validate_sentiment_ok():
    res = {"ok": True, "provider": "groq", "model": "m",
           "data": {"stock_sentiment": {"score": 0.3, "themes": ["earnings beat"]},
                    "market_sentiment": {"score": -0.2, "themes": ["rate fear"]}}}
    v = ns.validate_sentiment(res)
    assert v["available"] and v["stock"]["score"] == 0.3 and v["market"]["label"] == "bearish"


def test_validate_sentiment_degrades():
    assert ns.validate_sentiment({"ok": False, "error": "no key"})["available"] is False
    # model returned no numeric scores → unavailable
    empty = {"ok": True, "data": {"stock_sentiment": {"themes": []},
                                  "market_sentiment": {}}}
    assert ns.validate_sentiment(empty)["available"] is False


# ------------------------- collect_headlines (mocked I/O) -------------------------
def test_collect_prefers_yfinance_and_notes_no_newsapi(monkeypatch):
    monkeypatch.setattr(ns, "fetch_yfinance_news", lambda t, m: (ns.parse_news_items(NEW_SCHEMA), None))
    out = ns.collect_headlines("CSCO", "Cisco", 8, keys={})  # no api_key_newsapi
    assert out["sources_used"] == ["yfinance.news"]
    assert any("yfinance-only" in w for w in out["warnings"])


def test_collect_merges_newsapi_when_key_present(monkeypatch):
    monkeypatch.setattr(ns, "fetch_yfinance_news", lambda t, m: (ns.parse_news_items(NEW_SCHEMA), None))
    monkeypatch.setattr(ns, "fetch_newsapi",
                        lambda q, k, m: (ns.parse_newsapi_articles(
                            [{"title": "extra", "source": {"name": "AP"}}]), None))
    out = ns.collect_headlines("CSCO", "Cisco", 8, keys={"api_key_newsapi": "trial"})
    assert "newsapi" in out["sources_used"]
    assert {h["title"] for h in out["headlines"]} == {"Cisco beats on earnings", "extra"}


def test_collect_newsapi_quota_dropped(monkeypatch):
    monkeypatch.setattr(ns, "fetch_yfinance_news", lambda t, m: (ns.parse_news_items(NEW_SCHEMA), None))
    monkeypatch.setattr(ns, "fetch_newsapi", lambda q, k, m: ([], "newsapi dropped: HTTP 429"))
    out = ns.collect_headlines("CSCO", "Cisco", 8, keys={"api_key_newsapi": "trial"})
    assert "newsapi" not in out["sources_used"]
    assert any("429" in w for w in out["warnings"])
    assert out["headlines"]  # yfinance headlines survive


# ------------------------- run() (mocked collect + llm) -------------------------
def _write_sample(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps(SAMPLE), encoding="utf-8")
    return p


def test_run_no_headlines_degrades(tmp_path, monkeypatch):
    p = _write_sample(tmp_path)
    monkeypatch.setattr(ns, "collect_headlines",
                        lambda *a, **k: {"headlines": [], "sources_used": [], "warnings": ["none"]})
    block = ns.run(str(p), keys={})
    assert block["available"] is False and block["n_headlines"] == 0
    assert "error" not in block  # still merges → n/a card, not omitted


def test_run_happy_path(tmp_path, monkeypatch):
    p = _write_sample(tmp_path)
    monkeypatch.setattr(ns, "collect_headlines", lambda *a, **k: {
        "headlines": ns.parse_news_items(NEW_SCHEMA), "sources_used": ["yfinance.news"], "warnings": []})
    monkeypatch.setattr(ns.llm_client, "complete_json", lambda *a, **k: {
        "ok": True, "provider": "groq", "model": "m",
        "data": {"stock_sentiment": {"score": 0.4, "themes": ["earnings beat"],
                                     "citations": ["Cisco beats on earnings"]},
                 "market_sentiment": {"score": 0.1, "themes": ["calm"]}}})
    block = ns.run(str(p), keys={})
    assert block["available"] and block["stock"]["score"] == 0.4
    assert block["n_headlines"] == 1 and block["headlines"][0]["title"] == "Cisco beats on earnings"


def test_run_no_ticker_errors(tmp_path):
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"company_name": "x"}), encoding="utf-8")
    assert "error" in ns.run(str(p), keys={})


# ------------------------- overlay-only merge -------------------------
def test_merge_is_overlay_only(tmp_path):
    p = _write_sample(tmp_path)
    ns.merge_into_analysis(str(p), {"available": True, "stock": {"score": 0.4}})
    back = json.loads(p.read_text(encoding="utf-8"))
    assert back["news_sentiment"]["stock"]["score"] == 0.4
    assert back["scores"]["composite"] == 7.8   # untouched
    assert back["verdict"] == "invest"           # untouched
