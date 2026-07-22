"""
second_opinion.py — v4 Phase G: 3-persona LLM opinion panel.

An independent second read (spec §10b, scan-2 p01 + idea #8). One non-authoring
model chain (Groq→Gemini via llm_client), three prompted personas — **value /
growth / contrarian** — each scoring conviction 0–100 (50 = neutral, 100 = buy
now, Bruno's scale). The disagreement is the point: a wide spread, or a gap vs the
skill's own composite, gets flagged.

Independence, not echo: the panel sees the **evidence** (the numbers the report
cites) but NOT the authoring composite/verdict — those are excluded from the model
input by construction. The composite is read once, locally, only to flag divergence.

Overlay-only: merges an additive `opinion_panel` key; never touches the composite/
verdict/top_strip. Deep-dives only. A dead persona (bad JSON / provider error /
missing key) degrades to a "not available" card without blocking the others or the
run. Cards are labelled *opinion* — exempt from the ground-truth rule, like the
management score. Runs under ambient Python312 (llm_client needs the SDKs).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
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

import llm_client  # noqa: E402

DIVERGENCE_PTS = 25  # spread or median-vs-composite gap that flags "divergence"


def log(msg: str) -> None:
    print(f"[second_opinion] {msg}", file=sys.stderr)


# ===================================================================
# Personas
# ===================================================================
_SCALE = ("Score conviction 0-100 where 50 = neutral/hold, 100 = strong buy now, "
          "0 = strong avoid. The verdict MUST match the number: "
          "buy_now>=75, accumulate 60-74, hold 40-59, avoid<40. "
          "Reply with STRICT JSON only: "
          '{"verdict": "<one of: buy_now|accumulate|hold|avoid>", '
          '"conviction_0_100": <int>, "one_liner": "<<=140 chars>"}.')

PERSONAS = [
    {"name": "value",
     "system": "You are a value investor in the Graham/Klarman tradition. You care "
               "about price vs intrinsic value, margin of safety, balance-sheet "
               "resilience and downside protection. You distrust rich multiples. " + _SCALE},
    {"name": "growth",
     "system": "You are a growth investor in the Fisher/Lynch tradition. You care "
               "about revenue durability, reinvestment runway, unit economics, moat "
               "compounding and TAM. You tolerate a premium for quality growth. " + _SCALE},
    {"name": "contrarian",
     "system": "You are a bear-first contrarian. You look for what consensus is "
               "missing, why this could be a value trap or a crowded long, and where "
               "the reported numbers might flatter reality. Default to scepticism. " + _SCALE},
]


# ===================================================================
# Pure functions (unit-tested)
# ===================================================================
def compact_evidence(data: dict) -> dict:
    """The numbers the report cites — EXCLUDING scores.composite and verdict, so the
    personas form an independent read rather than echoing the skill's own call."""
    iv = data.get("intrinsic_value") or {}
    rf = data.get("red_flags") or {}
    ab = data.get("alpha_beta") or {}
    xp = data.get("exit_plan") or {}
    return {
        "ticker": data.get("ticker"),
        "company_name": data.get("company_name"),
        "sector": data.get("sector"),
        "currency": data.get("currency"),
        "price_current": data.get("price_current"),
        "metrics": data.get("top_strip"),
        "gates_detail": data.get("gates_detail"),
        "gates_passed": data.get("gates_passed"),
        "piotroski_fscore": data.get("piotroski_fscore"),
        "altman_zscore": data.get("altman_zscore"),
        "lynch_category": data.get("lynch_category"),
        "intrinsic_value": {
            "fair_value_range": iv.get("fair_value_range"),
            "mos_class": iv.get("mos_class"),
            "mos_pct": iv.get("mos_pct"),
            "blend": iv.get("blend"),
        },
        "red_flags": {
            "verdict": (rf.get("summary") or {}).get("verdict"),
            "bad": (rf.get("summary") or {}).get("bad"),
            "beneish_m": (rf.get("beneish") or {}).get("m_score"),
            "income_score": (rf.get("income") or {}).get("subscore_0_10"),
            "balance_score": (rf.get("balance") or {}).get("subscore_0_10"),
            "cashflow_score": (rf.get("cashflow") or {}).get("subscore_0_10"),
        },
        "return_profile": {
            "beta": ab.get("beta"), "alpha_ann_pct": ab.get("alpha_ann_pct"),
            "realized_return_ann_pct": ab.get("realized_return_ann_pct"),
            "capm_expected_return_ann_pct": ab.get("capm_expected_return_ann_pct"),
            "price_cagr_ladder": ab.get("price_cagr_ladder"),
        },
        "exit_plan": {"target_exit_pe": xp.get("target_exit_pe"),
                      "thesis_broken_trigger": xp.get("thesis_broken_trigger")},
        "consensus": data.get("consensus"),
        "management_score": data.get("management_score"),
        "management_flag": data.get("management_flag"),
        "bear_case_trigger": data.get("bear_case_trigger"),
    }


def clamp_conviction(value) -> int | None:
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, v))


def validate_card(name: str, result: dict) -> dict:
    """Turn a raw llm_client result into a persona card, degrading on any problem."""
    if not result.get("ok") or not isinstance(result.get("data"), dict):
        return {"name": name, "available": False, "reason": result.get("error") or "no data"}
    d = result["data"]
    conv = clamp_conviction(d.get("conviction_0_100"))
    if conv is None:
        return {"name": name, "available": False, "reason": "no numeric conviction"}
    verdict = str(d.get("verdict") or "").strip()[:24] or "n/a"
    one_liner = str(d.get("one_liner") or "").strip()[:200]
    return {"name": name, "available": True, "verdict": verdict,
            "conviction_0_100": conv, "one_liner": one_liner,
            "provider": result.get("provider"), "model": result.get("model")}


def verdict_from_median(median) -> str:
    if median is None:
        return "n/a"
    if median >= 75:
        return "buy_now"
    if median >= 60:
        return "accumulate"
    if median >= 40:
        return "hold"
    if median >= 25:
        return "cautious"
    return "avoid"


def consensus(cards: list) -> dict:
    convs = [c["conviction_0_100"] for c in cards if c.get("available")]
    if not convs:
        return {"conviction_median": None, "verdict": "n/a", "n_available": 0}
    med = round(statistics.median(convs), 1)
    return {"conviction_median": med, "verdict": verdict_from_median(med),
            "n_available": len(convs)}


def divergence(cards: list, composite) -> dict:
    """Flag when personas disagree (spread) or diverge from the skill's composite.
    composite (0-10) is read only here; it is never shown to the models."""
    convs = [c["conviction_0_100"] for c in cards if c.get("available")]
    if len(convs) < 2:
        return {"flag": False, "reason": "insufficient personas"}
    spread = max(convs) - min(convs)
    reasons = []
    if spread >= DIVERGENCE_PTS:
        reasons.append(f"persona spread {spread}pts")
    if isinstance(composite, (int, float)):
        med = statistics.median(convs)
        gap = abs(med - composite * 10.0)
        if gap >= DIVERGENCE_PTS:
            reasons.append(f"median {med:.0f} vs composite×10 {composite * 10:.0f} "
                           f"(gap {gap:.0f}pts)")
    return {"flag": bool(reasons), "reason": "; ".join(reasons) or "aligned",
            "spread": spread}


# ===================================================================
# Orchestration
# ===================================================================
def build_prompt(evidence: dict) -> str:
    return ("Evaluate this company from your investing lens using ONLY the evidence "
            "below (all figures are ground-truth; do not invent numbers). Judge the "
            "stock on its merits — you are NOT told the house verdict.\n\n"
            f"EVIDENCE (JSON):\n{json.dumps(evidence, ensure_ascii=False, default=str)}")


def run_panel(evidence: dict, keys: dict | None = None) -> list:
    prompt = build_prompt(evidence)
    cards = []
    for p in PERSONAS:
        try:
            result = llm_client.complete_json(prompt, p["system"], keys=keys)
        except Exception as e:  # llm_client never raises, but be belt-and-braces
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        cards.append(validate_card(p["name"], result))
    return cards


def run(analysis_json: str) -> dict:
    data = json.loads(Path(analysis_json).read_text(encoding="utf-8"))
    if not data.get("ticker"):
        return {"error": "analysis JSON has no ticker"}
    evidence = compact_evidence(data)
    cards = run_panel(evidence)
    cons = consensus(cards)
    composite = (data.get("scores") or {}).get("composite")  # local only; not sent to models
    div = divergence(cards, composite)
    warnings = [f"{c['name']}: {c.get('reason')}" for c in cards if not c.get("available")]
    return {
        "fetched_at": datetime.now().isoformat(),
        "personas": cards,
        "consensus_conviction": cons["conviction_median"],
        "consensus_verdict": cons["verdict"],
        "n_available": cons["n_available"],
        "divergence": div,
        "model_chain": f"{llm_client.GROQ_MODEL_DEFAULT} → {llm_client.GEMINI_MODEL_DEFAULT}",
        "warnings": warnings,
    }


def merge_into_analysis(analysis_json: str, block: dict) -> None:
    """Merge the additive `opinion_panel` key (schema stays 2.2; composite untouched)."""
    path = Path(analysis_json)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["opinion_panel"] = block
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    log(f"merged opinion_panel into {path.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description="3-persona LLM opinion panel (value/growth/contrarian)")
    ap.add_argument("--analysis-json", required=True)
    ap.add_argument("--update", action="store_true",
                    help="Merge the result into the analysis JSON (key: opinion_panel)")
    args = ap.parse_args()

    try:
        block = run(args.analysis_json)
        if args.update and "error" not in block:
            merge_into_analysis(args.analysis_json, block)
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        print(json.dumps({"error": str(e), "error_type": type(e).__name__}))
        return 0  # non-fatal: panel absent, run continues

    print(json.dumps(block, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
