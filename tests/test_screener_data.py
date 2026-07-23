"""
Unit tests for v4.1 Phase I — screener data layer in build_dashboard.py.

Covers the stdlib YAML reader for _prefiltered.yaml, the _tmp analysis-JSON
enrichment, and the universe⋈reports join that feeds the screener bundle. No
network, no template — pure data shaping.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_dashboard as bd  # noqa: E402


UNIVERSE_YAML = """\
version: 1
last_updated: '2026-07-21'
source: prefilter_weekly
tickers:
- ticker: ADBE
  region: US
  size: big
  sector: Technology
  note: Creative cloud moat
  gates_passed: 6
  piotroski: 7
  altman_z: 6.89
  composite_score: 8.89
- ticker: EXPN.L
  region: UK
  size: big
  sector: Industrials
  gates_passed: 5
  composite_score: 7.10
"""


# ------------------------- _yaml_scalar -------------------------
def test_yaml_scalar_unquotes():
    assert bd._yaml_scalar("'2026-07-21'") == "2026-07-21"
    assert bd._yaml_scalar('"US"') == "US"
    assert bd._yaml_scalar("8.89") == "8.89"  # numbers stay strings


# ------------------------- load_universe -------------------------
def test_load_universe_parses_records(tmp_path, monkeypatch):
    p = tmp_path / "_prefiltered.yaml"
    p.write_text(UNIVERSE_YAML, encoding="utf-8")
    monkeypatch.setattr(bd, "PREFILTERED_YAML", p)
    u = bd.load_universe()
    assert [r["ticker"] for r in u] == ["ADBE", "EXPN.L"]
    assert u[0]["region"] == "US" and u[0]["composite_score"] == "8.89"
    assert u[0]["sector"] == "Technology" and u[0]["note"] == "Creative cloud moat"
    # top-level keys (version/source) are not mistaken for records
    assert all("version" not in r for r in u)


def test_load_universe_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "PREFILTERED_YAML", tmp_path / "nope.yaml")
    assert bd.load_universe() == []


# ------------------------- enrich_from_tmp -------------------------
def test_enrich_from_tmp_reads_overlays(tmp_path, monkeypatch):
    tmpd = tmp_path / "_tmp"
    tmpd.mkdir()
    (tmpd / "2026-07-22_ADBE.json").write_text(json.dumps({
        "top_strip": {"pe_ttm": 32.5, "fcf_yield_pct": 3.1},
        "alpha_beta": {"beta": 1.2, "alpha_ann_pct": 5.0},
        "intrinsic_value": {"mos_class": "fair", "mos_pct": 4.0},
    }), encoding="utf-8")
    monkeypatch.setattr(bd, "TMP_DIR", tmpd)
    e = bd.enrich_from_tmp("ADBE", "2026-07-22")
    assert e["pe"] == 32.5 and e["fcf_yield"] == 3.1
    assert e["beta"] == 1.2 and e["alpha"] == 5.0
    assert e["mos_class"] == "fair" and e["mos_pct"] == 4.0


def test_enrich_from_tmp_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "TMP_DIR", tmp_path / "_tmp")
    assert bd.enrich_from_tmp("ZZZ", "2026-07-22") == {}
    assert bd.enrich_from_tmp("ZZZ", "") == {}


# ------------------------- _report_href (existence-gated) -------------------------
def test_report_href_only_when_html_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "ROOT", tmp_path)
    (tmp_path / "2026-07-22_ADBE_invest.html").write_text("x", encoding="utf-8")
    assert bd._report_href("2026-07-22_ADBE_invest.md") == "2026-07-22_ADBE_invest.html"
    # no sibling .html on disk → no dead link
    assert bd._report_href("2026-07-22_ZZZ_screen.md") is None
    assert bd._report_href(None) is None


# ------------------------- build_screener -------------------------
def _reports():
    return [{
        "ticker": "ADBE", "region": "US", "sector": "Technology", "size": "big",
        "score": 8.2, "verdict": "invest", "gates_passed": 6, "piotroski": 7,
        "altman": 6.9, "tech_score": 7.5, "go_no_go": "GO",
        "fair_price": 600.0, "price": 500.0, "currency": "USD",
        "date": "2026-07-22", "filename": "2026-07-22_ADBE_invest.md",
    }]


def test_build_screener_joins_and_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "TMP_DIR", tmp_path / "_tmp")  # no _tmp → enrich empty
    monkeypatch.setattr(bd, "ROOT", tmp_path)
    (tmp_path / "2026-07-22_ADBE_invest.html").write_text("x", encoding="utf-8")  # so href resolves
    universe = [{"ticker": "ADBE", "region": "US", "sector": "Technology", "size": "big",
                 "composite_score": "8.89", "gates_passed": "6"},
                {"ticker": "EXPN.L", "region": "UK", "sector": "Industrials",
                 "composite_score": "7.10"}]
    rows = bd.build_screener(_reports(), universe)
    by = {r["ticker"]: r for r in rows}
    # ADBE evaluated: uses the report score (8.2), not the prefilter composite (8.89)
    assert by["ADBE"]["evaluated"] is True and by["ADBE"]["composite"] == 8.2
    assert by["ADBE"]["verdict"] == "invest" and by["ADBE"]["upside"] == 20.0
    assert by["ADBE"]["report_href"] == "2026-07-22_ADBE_invest.html"
    # EXPN.L pool-only: falls back to prefilter composite, no report link
    assert by["EXPN.L"]["evaluated"] is False and by["EXPN.L"]["composite"] == 7.10
    assert by["EXPN.L"]["report_href"] is None


def test_build_screener_deep_beats_screen_same_day(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "TMP_DIR", tmp_path / "_tmp")
    monkeypatch.setattr(bd, "ROOT", tmp_path)  # no .html → hrefs None, fine
    deep = {"ticker": "TTD", "score": 7.73, "verdict": "invest", "mode": "deep",
            "fair_price": 22.51, "price": 20.0, "date": "2026-07-22",
            "filename": "2026-07-22_TTD_invest.md"}
    screen = {"ticker": "TTD", "score": 7.75, "verdict": "invest", "mode": "screen",
              "fair_price": None, "price": None, "date": "2026-07-22",
              "filename": "2026-07-22_TTD_screen.md"}
    # screen sorts after deep alphabetically → would win a naive last-write; deep must win
    rows = bd.build_screener([deep, screen], universe=[])
    assert len(rows) == 1
    assert rows[0]["composite"] == 7.73 and rows[0]["fair_price"] == 22.51  # deep, not screen


def test_build_screener_includes_evaluated_outside_pool(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "TMP_DIR", tmp_path / "_tmp")
    rows = bd.build_screener(_reports(), universe=[])  # empty pool
    assert len(rows) == 1 and rows[0]["ticker"] == "ADBE" and rows[0]["evaluated"] is True


def test_build_screener_frontmatter_beta_wins_over_tmp(tmp_path, monkeypatch):
    tmpd = tmp_path / "_tmp"
    tmpd.mkdir()
    (tmpd / "2026-07-22_ADBE.json").write_text(json.dumps({
        "alpha_beta": {"beta": 1.1, "alpha_ann_pct": 9.9}, "top_strip": {"pe_ttm": 30.0},
    }), encoding="utf-8")
    monkeypatch.setattr(bd, "TMP_DIR", tmpd)
    reps = _reports()
    reps[0].update({"beta": 0.9, "alpha": 4.0, "mos_class": "fair"})  # durable frontmatter
    rows = bd.build_screener(reps, universe=[])
    assert rows[0]["beta"] == 0.9 and rows[0]["alpha"] == 4.0  # frontmatter wins
    assert rows[0]["mos_class"] == "fair"
    assert rows[0]["pe"] == 30.0  # P/E still supplemented from _tmp


def test_build_screener_enriches_when_tmp_present(tmp_path, monkeypatch):
    tmpd = tmp_path / "_tmp"
    tmpd.mkdir()
    (tmpd / "2026-07-22_ADBE.json").write_text(json.dumps({
        "top_strip": {"pe_ttm": 30.0, "fcf_yield_pct": 3.0},
        "alpha_beta": {"beta": 1.1}, "intrinsic_value": {"mos_class": "rich"},
    }), encoding="utf-8")
    monkeypatch.setattr(bd, "TMP_DIR", tmpd)
    rows = bd.build_screener(_reports(), universe=[])
    assert rows[0]["pe"] == 30.0 and rows[0]["beta"] == 1.1 and rows[0]["mos_class"] == "rich"
