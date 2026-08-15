"""
Unit tests for v4 Phase F — render_report.py.

Pure logic (stdlib only, uv-safe): action-verb map, gate-family derivation, the
inline-SVG builders' math, null renders, markdown helpers — plus a golden-file
render (self-contained: no external refs / no JS) and the frozen-md regression
(build_dashboard.slim_report must still fully populate a v4 report).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import render_report as rr  # noqa: E402


FIXTURE_MD = """---
ticker: CSCO
date: 2026-07-22
verdict: invest
score: 7.8
fair_price: 70.0
fair_price_basis: dcf
currency: USD
sector: Technology
region: US
go_no_go: GO
schema_version: "2.2"
---
# CSCO — Cisco Systems Inc — Score: 7.8/10 🟢 INVEST

> [!tldr] ⚡ TL;DR
> **Thesis**: Durable networking incumbent with rising recurring revenue.
> **Risks**: Slow top-line growth; AI-networking share unproven.
> **Action**: ACCUMULATE on weakness.

## 2.1 Business model
Cisco sells **networking** hardware and software.

| Metric | Value |
|---|---|
| Revenue | 57B |
"""

FIXTURE_JSON = {
    "ticker": "CSCO", "company_name": "Cisco Systems", "sector": "Technology",
    "region": "US", "currency": "USD", "price_current": 60.0, "fetched_at": "2026-07-22T10:00:00",
    "verdict": "invest", "altman_zscore": 4.1,
    "scores": {"composite": 7.8, "fundamentals": 8.0, "valuation": 6.0, "moat": 9.0,
               "peer": 7.0, "growth_durability": 6.5, "management": 8.5, "market_context": 6.0},
    "top_strip": {"pe_ttm": 22.0, "forward_pe": 18.0, "revenue_cagr_5y_pct": 6.0, "roic_pct": 26.0,
                  "price_return_1y_pct": 12.0, "beta_3y": 0.9, "alpha_ann_pct": 4.0},
    "intrinsic_value": {"fair_value_range": {"low": 55.0, "mid": 70.0, "high": 85.0},
                        "mos_class": "deep_value", "mos_pct": 14.3, "blend": {"value": 70.0, "n_valid": 4, "n_models": 5}},
    "red_flags": {"summary": {"verdict": "clean", "bad": 0}, "beneish": {"m_score": -2.7},
                  "income": {"subscore_0_10": 9.0}, "balance": {"subscore_0_10": 8.0}, "cashflow": {"subscore_0_10": 10.0}},
    "exit_plan": {"target_exit_pe": 24.0, "profit_take_ladder": "trim ⅓ @ 85 / ⅓ @ 105",
                  "thesis_broken_trigger": "if recurring revenue share falls"},
    "alpha_beta": {"benchmark": "^GSPC", "beta": 0.9, "alpha_ann_pct": 4.0, "realized_return_ann_pct": 15.0,
                   "capm_expected_return_ann_pct": 11.0, "lynch_prior": {"category": "stalwart",
                   "expected_return_band": "10-12%/yr", "drawdown_band": "20-30%"},
                   "price_cagr_ladder": {"1y": 12.0, "3y": 10.0, "5y": 9.0, "10y": 11.0, "depth_years": 14.9, "basis": "adj monthly"},
                   "portfolio_comparison": {"benchmark": "URTH", "portfolio": {"beta": 1.5, "alpha_ann_pct": -8.0},
                   "ticker_vs_world": {"beta": 0.95, "alpha_ann_pct": 6.0}, "verdict_beta": "dilutes", "verdict_alpha": "raises"}},
    "opinion_panel": {"personas": [{"name": "value", "available": True, "verdict": "accumulate", "conviction_0_100": 68, "one_liner": "cheap vs FCF"},
                                   {"name": "growth", "available": True, "verdict": "hold", "conviction_0_100": 55, "one_liner": "slow growth"},
                                   {"name": "contrarian", "available": False, "reason": "provider error"}],
                      "consensus_conviction": 61.5, "consensus_verdict": "accumulate", "n_available": 2,
                      "divergence": {"flag": False, "reason": "aligned"}, "model_chain": "groq→gemini"},
    "fundamentals": {"pe_ratio": 22.0, "forward_pe": 18.0, "peg": 1.8, "ps_ratio": 4.2,
                     "book_value": 12.0, "ev_revenue": 3.9, "ev_ebitda": 13.5,
                     "enterprise_value": 260_000_000_000.0, "fcf_ttm": 15_000_000_000.0},
    "score_details": {"valuation": {"ev_ebit": 16.0},
                      "peer_info": {"peer_metrics": {"CSCO": {"forward_pe": 18, "roic": 26, "revenue_cagr": 6},
                                                     "ANET": {"forward_pe": 35, "roic": 30, "revenue_cagr": 20}},
                                    "rankings": {"CSCO": {"percentile": 60}}}},
}


# ------------------------- action verb -------------------------
def test_action_verb_all_branches():
    assert rr.action_verb("reject", "deep_value", "GO") == "AVOID"
    assert rr.action_verb("fair", "rich", "GO") == "WATCH"
    assert rr.action_verb("great", "rich", "GO") == "WATCH"
    assert rr.action_verb("great", "deep_value", "GO") == "ACCUMULATE"
    assert rr.action_verb("invest", "fair", "NO-GO") == "BUY-DIP"
    assert rr.action_verb("invest", "not_computable", "GO") == "HOLD"
    assert rr.action_verb("weird", None, None) == "WATCH"


# ------------------------- gate family / radar -------------------------
def test_gate_family_scores_full():
    fam = rr.gate_family_scores(FIXTURE_JSON["scores"], FIXTURE_JSON["red_flags"])
    assert fam["Quality"] == 8.5   # mean(fundamentals 8, moat 9)
    assert fam["Value"] == 6.0 and fam["Growth"] == 6.5 and fam["Mgmt"] == 8.5
    assert fam["Health"] == 9.0    # mean(balance 8, cashflow 10)


def test_gate_family_health_falls_back_to_fundamentals():
    fam = rr.gate_family_scores({"fundamentals": 7.0}, {})
    assert fam["Health"] == 7.0


def test_radar_svg_renders_and_skips_when_thin():
    fam = rr.gate_family_scores(FIXTURE_JSON["scores"], FIXTURE_JSON["red_flags"])
    svg = rr.radar_svg(fam)
    assert "<svg" in svg and svg.count("<polygon") == 3 and "Quality 8.5" in svg
    assert rr.radar_svg({"Quality": 8.0, "Value": None, "Growth": None, "Health": None, "Mgmt": None}) == ""


# ------------------------- gauge / range / sparkline / grade -------------------------
def test_gauge_marker_pct():
    assert rr.gauge_marker_pct(60, 70) > 50   # price below fair → cheap side
    assert rr.gauge_marker_pct(80, 70) < 50   # above fair → expensive side
    assert rr.gauge_marker_pct(None, 70) is None
    assert rr.gauge_marker_pct(1, 100) == 97  # clamp
    assert rr.gauge_marker_pct(1000, 100) == 3


def test_range_bar_pcts():
    bear, base, bull = rr.range_bar_pcts(55, 70, 85)
    assert bear == 15.0 and bull == 94.0 and 15 < base < 94
    assert rr.range_bar_pcts(80, 70, 60) is None  # hi<=lo


def test_sparkline_and_grade():
    assert "<polyline" in rr.sparkline_svg([1, 2, 3])
    assert rr.sparkline_svg([1]) == ""
    assert (rr.grade_letter(80), rr.grade_letter(60), rr.grade_letter(30), rr.grade_letter(10)) == ("A", "B", "C", "D")
    assert rr.grade_letter(None) is None


# ------------------------- money / pct -------------------------
def test_fmt_money_currency_symbols():
    assert rr.fmt_money(60, "USD") == "$60.00"
    assert rr.fmt_money(60, "EUR") == "€60.00"
    assert rr.fmt_money(None, "USD") == "n/a"


# ------------------------- markdown helpers -------------------------
def test_split_frontmatter_and_extract_label():
    fm, body = rr.split_frontmatter(FIXTURE_MD)
    assert fm["ticker"] == "CSCO" and fm["verdict"] == "invest" and fm["schema_version"] == "2.2"
    assert rr.extract_label(body, "Thesis").startswith("Durable networking")
    assert rr.extract_label(body, "Action").startswith("ACCUMULATE")
    assert rr.extract_label(body, "Nonexistent") is None


def test_md_to_html_basics():
    h = rr.md_to_html("## Head\n\nA **bold** word.\n\n- one\n- two\n\n> a note")
    assert "<h2>Head</h2>" in h and "<b>bold</b>" in h and "<ul>" in h and "<blockquote>" in h


# ------------------------- golden-file render -------------------------
def test_render_is_self_contained_and_complete(tmp_path):
    md_path = tmp_path / "2026-07-22_CSCO_invest.md"
    md_path.write_text(FIXTURE_MD, encoding="utf-8")
    html = rr.render(FIXTURE_MD, FIXTURE_JSON, md_path, tmp_path, icon_b64="")
    # Self-contained + static. "Self-contained" means no external SUBRESOURCE is fetched
    # when the file is opened — not that the string "https" never appears. v4.3 adds a
    # GuruFocus <a href>, which is a hyperlink the reader chooses to follow, not a
    # resource the page loads; the old blanket ban on "https://" would have made that
    # feature untestable while proving nothing extra about offline rendering.
    assert not re.search(r'\b(src|action)\s*=\s*["\']https?://', html)
    assert not re.search(r'<link\b[^>]*href\s*=\s*["\']https?://', html, re.I)
    assert not re.search(r'@import|url\(\s*["\']?https?://', html, re.I)
    assert "<script" not in html
    assert 'src="data:image' not in html or "base64" in html  # only data-URIs allowed
    # answer-first + all v4 cards present
    assert "→ <b>ACCUMULATE</b>" in html and "INVEST" in html
    assert "Gate-family" in html and "<svg" in html            # radar rendered
    assert "Exit Plan" in html and "Valuation" in html and "Red-Flag Scanner" in html
    assert "Return profile" in html and "Opinion panel" in html and "Peer comparison" in html
    assert "Durable networking" in html                        # TL;DR thesis
    assert "Full written analysis" in html                     # appendix
    assert rr.fmt_money(60, "USD") in html                     # currency from JSON, not hardcoded €


def test_render_null_states_do_not_crash(tmp_path):
    # minimal JSON — most blocks absent → cards degrade/omit, no exception
    md_path = tmp_path / "2026-07-22_X_fair.md"
    minimal_md = "---\nticker: X\ndate: 2026-07-22\nverdict: fair\ncurrency: EUR\n---\n# X — X Corp — Score: 4.5/10\n\n**Thesis**: t\n\n**Action**: WATCH\n"
    md_path.write_text(minimal_md, encoding="utf-8")
    html = rr.render(minimal_md, {"ticker": "X", "currency": "EUR", "verdict": "fair"}, md_path, tmp_path, "")
    assert "WATCH" in html and "<script" not in html


# ------------------------- FROZEN MD CONTRACT regression -------------------------
def test_frozen_md_contract_slim_report_still_populates(tmp_path):
    """Phase-F acceptance gate: build_dashboard.slim_report must fully populate on
    a v4 report md (unchanged contract)."""
    import datetime as dt
    import build_dashboard as bd
    md_path = tmp_path / "2026-07-22_CSCO_invest.md"
    md_path.write_text(FIXTURE_MD, encoding="utf-8")
    slim = bd.slim_report(md_path, dt.date(2026, 7, 22))
    assert slim is not None
    assert slim["ticker"] == "CSCO" and slim["date"] == "2026-07-22"
    assert slim["verdict"] == "invest" and slim["score"] == 7.8
    assert slim["thesis"] and slim["thesis"].startswith("Durable networking")
    assert slim["risks"] and slim["action"]


def test_num_coerces_frontmatter_numeric_strings():
    """Frontmatter values arrive as strings; _num must coerce them or the TL;DR fair
    price / score fall back to n/a on every report (QA MAJOR, 2026-07-23)."""
    assert rr._num("138.15") == 138.15      # fair_price from frontmatter
    assert rr._num("7.8") == 7.8            # score from frontmatter
    assert rr._num(42) == 42 and rr._num(3.5) == 3.5   # real numbers still pass
    assert rr._num("N/A") is None and rr._num("") is None
    assert rr._num(None) is None and rr._num(True) is None   # bools are not numbers


# ------------------------- metrics glossary (session 2) -------------------------
import metrics_glossary as mg  # noqa: E402


def test_glossary_covers_all_nine_metrics_fully():
    ids = [m for ids in mg.families().values() for m in ids]
    assert ids == ["pe", "peg", "ps", "pb", "earnings_yield",
                   "ev_sales", "ev_ebitda", "ev_ebit", "fcf_ev"]
    for mid in ids:
        e = mg.entry(mid)
        assert e and e["label"] and e["family"]
        for field in ("advantages", "limitations", "when_to_use", "reference"):
            assert e[field].strip(), f"{mid}.{field} empty"


def test_glossary_families_ordering_and_membership():
    fams = mg.families()
    assert list(fams) == ["Equity multiples", "Enterprise multiples"]
    assert fams["Equity multiples"] == ["pe", "peg", "ps", "pb", "earnings_yield"]
    assert fams["Enterprise multiples"] == ["ev_sales", "ev_ebitda", "ev_ebit", "fcf_ev"]


def test_band_for_direction_and_guards():
    # lower-is-cheaper ratio
    assert mg.band_for("pe", 12) == "cheap"
    assert mg.band_for("pe", 20) == "fair"
    assert mg.band_for("pe", 40) == "rich"
    # higher-is-cheaper yield
    assert mg.band_for("earnings_yield", 9) == "cheap"
    assert mg.band_for("earnings_yield", 6) == "fair"
    assert mg.band_for("earnings_yield", 2) == "rich"
    # guards: unknown / missing / non-positive → None (never call a loss "cheap")
    assert mg.band_for("pe", 0) is None
    assert mg.band_for("pe", -5) is None
    assert mg.band_for("pe", None) is None
    assert mg.band_for("nope", 10) is None


# ------------------------- metric families (session 2) -------------------------
def test_metric_values_computed():
    v = rr.metric_values(FIXTURE_JSON)
    assert v["pe"] == 22.0 and v["peg"] == 1.8 and v["ps"] == 4.2
    assert v["pb"] == 5.0                                   # 60 / 12
    assert round(v["earnings_yield"], 2) == 4.55            # 100 / 22
    assert v["ev_sales"] == 3.9 and v["ev_ebitda"] == 13.5 and v["ev_ebit"] == 16.0
    assert round(v["fcf_ev"], 2) == 5.77                    # 100 * 15e9 / 260e9


def test_metric_values_null_when_fundamentals_absent():
    v = rr.metric_values({"ticker": "X"})
    assert all(val is None for val in v.values())


def test_build_metric_families_full_and_cheatsheet():
    html = rr.build_metric_families(FIXTURE_JSON)
    assert 'id="metrics"' in html and "NEW" in html
    assert "Equity multiples" in html and "Enterprise multiples" in html
    assert "22.0×" in html and "4.5%" in html and "5.0×" in html      # P/E, earnings yield, P/B
    assert 'title="' in html                                          # tooltip on screen
    assert 'class="cheat"' in html                                    # print grey column
    assert 'details class="cheat-m"' in html                          # mobile expandable
    assert "tint-" in html                                            # value band tint


def test_build_metric_families_omits_when_empty():
    assert rr.build_metric_families({"ticker": "X"}) == ""


# ------------------------- index hub (session 2) -------------------------
def _write_report(dir_, date, ticker, verdict, score, go="GO"):
    md = (f"---\nticker: {ticker}\ndate: {date}\nverdict: {verdict}\nscore: {score}\n"
          f"go_no_go: {go}\ncurrency: USD\n---\n# {ticker}\n\n**Thesis**: t\n\n**Action**: A\n")
    (dir_ / f"{date}_{ticker}_{verdict}.md").write_text(md, encoding="utf-8")
    (dir_ / f"{date}_{ticker}_{verdict}.html").write_text("<html></html>", encoding="utf-8")


def test_index_reports_discovers_and_sorts(tmp_path):
    _write_report(tmp_path, "2026-07-23", "CSCO", "invest", 7.8)
    _write_report(tmp_path, "2026-07-23", "AAPL", "great", 9.1)
    _write_report(tmp_path, "2026-07-22", "OLD", "fair", 5.0)   # other date → excluded
    (tmp_path / "index.html").write_text("x", encoding="utf-8")  # must not self-include
    rows = rr.index_reports(tmp_path, "2026-07-23")
    assert [r["ticker"] for r in rows] == ["AAPL", "CSCO"]       # sorted by score desc
    assert rows[0]["score"] == 9.1 and rows[0]["action"] == "HOLD"  # great, mos absent in fm → HOLD by contract


def test_build_index_html_renders_and_degrades(tmp_path):
    _write_report(tmp_path, "2026-07-23", "CSCO", "invest", 7.8)
    html = rr.build_index_html(tmp_path, "2026-07-23", "")
    assert "<script" not in html and "http://" not in html
    assert 'href="2026-07-23_CSCO_invest.html"' in html and "CSCO" in html
    empty = rr.build_index_html(tmp_path, "2020-01-01", "")
    assert "No reports rendered" in empty
