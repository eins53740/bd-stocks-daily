"""
Unit tests for v4 Phase G — second_opinion.py.

Pure logic + orchestration with llm_client mocked (no network). Verifies the
independence guarantee (composite/verdict excluded from model input), consensus
median, divergence flags, per-card degradation, and overlay-only merge.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import second_opinion as so  # noqa: E402


SAMPLE = {
    "ticker": "ADSK", "company_name": "Autodesk", "sector": "Tech",
    "currency": "USD", "price_current": 300.0,
    "top_strip": {"pe_ttm": 55.0}, "gates_detail": {"gate_2_valuation": {"pass": False}},
    "gates_passed": 6, "piotroski_fscore": 7, "altman_zscore": 6.0,
    "lynch_category": "stalwart",
    "intrinsic_value": {"fair_value_range": {"low": 250, "mid": 300, "high": 340},
                        "mos_class": "rich", "mos_pct": -18.0, "blend": {"value": 300}},
    "red_flags": {"summary": {"verdict": "clean", "bad": 0}, "beneish": {"m_score": -2.6},
                  "income": {"subscore_0_10": 9}, "balance": {"subscore_0_10": 8},
                  "cashflow": {"subscore_0_10": 10}},
    "alpha_beta": {"beta": 1.1, "alpha_ann_pct": 4.0},
    "exit_plan": {"target_exit_pe": 30.0, "thesis_broken_trigger": "if cloud growth stalls"},
    "consensus": {"recommendation": "buy"},
    "management_score": 8.5, "management_flag": False,
    "bear_case_trigger": "if seat growth stalls",
    "scores": {"composite": 8.1}, "verdict": "invest",   # MUST be excluded from evidence
}


# ------------------------- independence -------------------------
def test_compact_evidence_excludes_composite_and_verdict():
    ev = so.compact_evidence(SAMPLE)
    flat = json.dumps(ev)
    assert "composite" not in flat and '"verdict": "invest"' not in flat
    assert "scores" not in ev and "verdict" not in ev
    # but the evidence numbers are present
    assert ev["ticker"] == "ADSK" and ev["intrinsic_value"]["mos_class"] == "rich"
    assert ev["return_profile"]["beta"] == 1.1


# ------------------------- clamp / validate -------------------------
def test_clamp_conviction():
    assert so.clamp_conviction(72) == 72
    assert so.clamp_conviction(150) == 100 and so.clamp_conviction(-5) == 0
    assert so.clamp_conviction("abc") is None and so.clamp_conviction(None) is None


def test_validate_card_ok_and_degraded():
    ok = so.validate_card("value", {"ok": True, "provider": "groq", "model": "m",
                                     "data": {"verdict": "hold", "conviction_0_100": 55,
                                              "one_liner": "fairly valued"}})
    assert ok["available"] and ok["conviction_0_100"] == 55 and ok["provider"] == "groq"
    bad = so.validate_card("growth", {"ok": False, "error": "no key"})
    assert bad["available"] is False and bad["reason"] == "no key"
    noconv = so.validate_card("contrarian", {"ok": True, "data": {"verdict": "avoid"}})
    assert noconv["available"] is False


# ------------------------- consensus / verdict bands -------------------------
def test_verdict_from_median_bands():
    assert so.verdict_from_median(80) == "buy_now"
    assert so.verdict_from_median(65) == "accumulate"
    assert so.verdict_from_median(50) == "hold"
    assert so.verdict_from_median(30) == "cautious"
    assert so.verdict_from_median(10) == "avoid"
    assert so.verdict_from_median(None) == "n/a"


def test_consensus_median_over_available():
    cards = [{"name": "v", "available": True, "conviction_0_100": 70},
             {"name": "g", "available": True, "conviction_0_100": 60},
             {"name": "c", "available": False}]
    c = so.consensus(cards)
    assert c["conviction_median"] == 65 and c["n_available"] == 2 and c["verdict"] == "accumulate"


def test_consensus_all_unavailable():
    c = so.consensus([{"name": "v", "available": False}])
    assert c["conviction_median"] is None and c["verdict"] == "n/a" and c["n_available"] == 0


# ------------------------- divergence -------------------------
def test_divergence_spread_flag():
    cards = [{"available": True, "conviction_0_100": 85},
             {"available": True, "conviction_0_100": 50},
             {"available": True, "conviction_0_100": 30}]
    d = so.divergence(cards, composite=6.0)
    assert d["flag"] and "spread" in d["reason"]


def test_divergence_vs_composite_flag():
    # tight personas (median 50) but composite 8.1 → gap 31 ≥ 25
    cards = [{"available": True, "conviction_0_100": 48},
             {"available": True, "conviction_0_100": 50},
             {"available": True, "conviction_0_100": 52}]
    d = so.divergence(cards, composite=8.1)
    assert d["flag"] and "composite" in d["reason"]


def test_divergence_aligned():
    cards = [{"available": True, "conviction_0_100": 78},
             {"available": True, "conviction_0_100": 80},
             {"available": True, "conviction_0_100": 82}]
    d = so.divergence(cards, composite=8.0)  # median 80 vs 80 → gap 0, spread 4
    assert d["flag"] is False


def test_divergence_insufficient_personas():
    assert so.divergence([{"available": True, "conviction_0_100": 50}], 5.0)["flag"] is False


# ------------------------- run_panel (mocked provider) -------------------------
def test_run_panel_one_persona_fails(monkeypatch):
    calls = {"n": 0}

    def fake_complete(prompt, system, keys=None):
        calls["n"] += 1
        if calls["n"] == 2:  # second persona (growth) fails
            return {"ok": False, "error": "provider timeout"}
        return {"ok": True, "provider": "groq", "model": "m",
                "data": {"verdict": "hold", "conviction_0_100": 55, "one_liner": "ok"}}

    monkeypatch.setattr(so.llm_client, "complete_json", fake_complete)
    cards = so.run_panel({"ticker": "ADSK"})
    assert len(cards) == 3
    assert [c["available"] for c in cards] == [True, False, True]  # only growth dead


# ------------------------- overlay-only merge -------------------------
def test_merge_is_overlay_only(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps(SAMPLE), encoding="utf-8")
    so.merge_into_analysis(str(p), {"consensus_conviction": 60})
    back = json.loads(p.read_text(encoding="utf-8"))
    assert back["opinion_panel"]["consensus_conviction"] == 60
    assert back["scores"]["composite"] == 8.1  # untouched
    assert back["verdict"] == "invest"          # untouched
