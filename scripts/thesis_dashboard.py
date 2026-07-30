"""
thesis_dashboard.py — Phase 5 (Investment Thesis Dashboard).

Aggregate, per shortlisted / recently-evaluated name, an *investment thesis*
view sourced ONLY from data the pipeline already produced:

  * ``_log.csv``                — verdict, score, gates_passed, management_score,
                                  management_flag, piotroski/altman (when present),
                                  bear_case_trigger
  * report frontmatter          — full scalar set incl. technical_score, go_no_go,
                                  combined_score, valuation/quality scalars (via
                                  build_dashboard.slim_report)
  * stored narratives           — Thesis / Risks / Action body fields (already
                                  extracted by slim_report)

NO new LLM pass. NO composite recomputation. The dashboard renderer computes
nothing — it only renders ``_thesis.json``.

For each name we emit:
  * Fundamental / Technical / Overall scores
  * Quality / Valuation / Risk reads (deterministic bands over stored scalars)
  * a Buy / Hold / Sell / Avoid stance with a cited rationale block.
    "Sell" is reserved for names actually HELD (per _portfolio_holdings.yaml) —
    a position you don't own cannot be sold, so an un-held name that fails the
    bar is "Avoid" instead.
  * 3–5 testable thesis pillars, each with status (intact / weakened / broken)
    and conviction (High / Med / Low) — the FS2 graft from thesis-tracker.

The derivation functions are PURE (no I/O) so the unit tests exercise them
directly with synthetic report dicts.

Usage:
  python thesis_dashboard.py                 # scan reports + _log.csv, write _thesis.json
  python thesis_dashboard.py --out FILE       # override output path
  python thesis_dashboard.py --root DIR        # override StocksDaily folder
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
OUT_JSON = ROOT / "_thesis.json"

FRESHNESS_DAYS = 90  # consistent with build_dashboard / portfolio_dashboard

WEAK_VERDICTS = {"reject", "fair"}
STRONG_VERDICTS = {"great", "invest"}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ----------------------------------------------------------------------------
# PURE derivation helpers (unit-tested — no I/O)
# ----------------------------------------------------------------------------

def overall_score(fund: float | None, tech: float | None) -> float | None:
    """Overall = 70% fundamental + 30% technical when both present; else the
    available one; None if neither. Mirrors portfolio_dashboard.overall_score."""
    if fund is None and tech is None:
        return None
    if fund is None:
        return round(tech, 2)
    if tech is None:
        return round(fund, 2)
    return round(0.70 * fund + 0.30 * tech, 2)


def quality_read(rep: dict) -> dict:
    """Quality read from Quality-Compounder gates + Piotroski F-score.
    Returns {label, detail} where label is Strong / Adequate / Weak / Unknown."""
    gates = rep.get("gates_passed")
    pio = rep.get("piotroski")
    parts = []
    if gates is not None:
        parts.append(f"{gates}/7 gates")
    if pio is not None:
        parts.append(f"Piotroski {pio}/9")
    if gates is None and pio is None:
        return {"label": "Unknown", "detail": "no quality scalars stored"}
    # Band on the dominant signal (gates), Piotroski as confirmation.
    g = gates if gates is not None else 0
    p = pio if pio is not None else 5
    if g >= 6 and p >= 6:
        label = "Strong"
    elif g >= 5 or p >= 5:
        label = "Adequate"
    else:
        label = "Weak"
    return {"label": label, "detail": " · ".join(parts)}


def valuation_read(rep: dict) -> dict:
    """Valuation read inferred from the composite score band and verdict.
    The composite already folds in the 20%-weighted Valuation component, so the
    score band is the best stored proxy without a new computation."""
    score = rep.get("score")
    verdict = (rep.get("verdict") or "").lower()
    if score is None:
        return {"label": "Unknown", "detail": "no composite score stored"}
    if verdict == "fair" or 5.0 <= score < 6.5:
        label = "Fair"
    elif score >= 7.5 or verdict in STRONG_VERDICTS:
        label = "Attractive"
    elif score < 5.0 or verdict == "reject":
        label = "Stretched"
    else:
        label = "Fair"
    return {"label": label, "detail": f"composite {score:.2f} / verdict {verdict or 'n/a'}"}


def risk_read(rep: dict) -> dict:
    """Risk read from Altman-Z (solvency), management flag, and technical risk
    level if present. Higher label == more risk."""
    altman = rep.get("altman")
    mgmt_flag = bool(rep.get("mgmt_flag"))
    tech_risk = (rep.get("tech_risk") or "").strip()
    parts = []
    score = 0  # 0 low .. higher worse
    if altman is not None:
        parts.append(f"Altman-Z {altman:.1f}")
        if altman < 1.8:
            score += 2
        elif altman < 3.0:
            score += 1
    if mgmt_flag:
        parts.append("mgmt flag")
        score += 2
    if tech_risk:
        parts.append(f"tech {tech_risk}")
        if tech_risk == "High":
            score += 2
        elif tech_risk == "Med":
            score += 1
    if not parts:
        return {"label": "Unknown", "detail": "no risk scalars stored"}
    label = "High" if score >= 3 else "Elevated" if score >= 2 else "Moderate" if score >= 1 else "Low"
    return {"label": label, "detail": " · ".join(parts)}


def derive_pillars(rep: dict) -> list[dict]:
    """Build 3–5 testable thesis pillars (FS2 graft from thesis-tracker).

    Each pillar carries:
      name, claim, status (intact|weakened|broken), conviction (High|Med|Low),
      evidence (the stored scalar that supports the status).

    Statuses/convictions are derived deterministically from stored scalars —
    no LLM, no recomputation. ``thesis_status`` (from thesis_check, when the
    caller supplies it) overrides the score-pillar status so a drift-detected
    break is reflected.
    """
    pillars: list[dict] = []

    score = rep.get("score")
    verdict = (rep.get("verdict") or "").lower()
    thesis_status = (rep.get("thesis_status") or "").lower()  # from thesis_check, optional

    # Pillar 1 — Business quality (gates + Piotroski).
    q = quality_read(rep)
    if q["label"] != "Unknown":
        gates = rep.get("gates_passed") or 0
        status = "intact" if gates >= 5 else "weakened" if gates >= 4 else "broken"
        conv = "High" if q["label"] == "Strong" else "Med" if q["label"] == "Adequate" else "Low"
        pillars.append({
            "name": "Business quality",
            "claim": "Durable, high-quality compounder (passes the 7-gate quality screen).",
            "status": status,
            "conviction": conv,
            "evidence": q["detail"],
        })

    # Pillar 2 — Valuation supports entry.
    v = valuation_read(rep)
    if v["label"] != "Unknown":
        status = {"Attractive": "intact", "Fair": "weakened", "Stretched": "broken"}.get(v["label"], "weakened")
        conv = "High" if v["label"] == "Attractive" else "Med" if v["label"] == "Fair" else "Low"
        pillars.append({
            "name": "Valuation",
            "claim": "Entry price leaves a margin of safety / acceptable risk-reward.",
            "status": status,
            "conviction": conv,
            "evidence": v["detail"],
        })

    # Pillar 3 — Balance-sheet / solvency resilience (Altman-Z).
    altman = rep.get("altman")
    if altman is not None:
        status = "intact" if altman >= 3.0 else "weakened" if altman >= 1.8 else "broken"
        conv = "High" if altman >= 3.0 else "Med" if altman >= 1.8 else "Low"
        pillars.append({
            "name": "Balance-sheet resilience",
            "claim": "Solvency headroom; low distress risk through a downturn.",
            "status": status,
            "conviction": conv,
            "evidence": f"Altman-Z {altman:.1f}",
        })

    # Pillar 4 — Management / capital allocation.
    mgmt = rep.get("mgmt")
    mgmt_flag = bool(rep.get("mgmt_flag"))
    if mgmt is not None or mgmt_flag:
        if mgmt_flag:
            status, conv = "broken", "Low"
            ev = "management red flag raised"
        elif mgmt is not None and mgmt >= 7.0:
            status, conv = "intact", "High"
            ev = f"management score {mgmt:.1f}/10"
        elif mgmt is not None and mgmt >= 5.0:
            status, conv = "weakened", "Med"
            ev = f"management score {mgmt:.1f}/10"
        else:
            status, conv = "broken", "Low"
            ev = f"management score {mgmt:.1f}/10" if mgmt is not None else "management red flag raised"
        pillars.append({
            "name": "Management & capital allocation",
            "claim": "Trustworthy management allocating capital in shareholders' interest.",
            "status": status,
            "conviction": conv,
            "evidence": ev,
        })

    # Pillar 5 — Thesis-failure guard (the stored bear_case_trigger).
    bear = (rep.get("bear_case_trigger") or "").strip()
    if bear:
        # If thesis_check flagged the overall thesis broken/weakened, reflect it here.
        status = "broken" if thesis_status == "broken" else "weakened" if thesis_status == "weakened" else "intact"
        conv = "High" if status == "intact" else "Med" if status == "weakened" else "Low"
        pillars.append({
            "name": "Thesis-failure guard",
            "claim": f"Thesis breaks if: {bear}",
            "status": status,
            "conviction": conv,
            "evidence": (f"drift check: {thesis_status}" if thesis_status
                         else "no disconfirming evidence detected yet"),
        })

    return pillars[:5]


def pillar_summary(pillars: list[dict]) -> dict:
    """Roll pillars up to {intact, weakened, broken, total, overall}."""
    n_intact = sum(1 for p in pillars if p["status"] == "intact")
    n_weak = sum(1 for p in pillars if p["status"] == "weakened")
    n_broken = sum(1 for p in pillars if p["status"] == "broken")
    if n_broken:
        overall = "broken"
    elif n_weak:
        overall = "weakened"
    elif pillars:
        overall = "intact"
    else:
        overall = "unknown"
    return {
        "intact": n_intact,
        "weakened": n_weak,
        "broken": n_broken,
        "total": len(pillars),
        "overall": overall,
    }


def derive_stance(rep: dict, pillars: list[dict], held: bool = False) -> dict:
    """Buy / Hold / Sell / Avoid stance with a cited rationale block.

    Logic (deterministic, over stored signals — mirrors the spirit of
    portfolio_dashboard.decide but framed as an entry stance, not a position
    action). Returns {stance, headline, rationale[]}.

    `held` gates the exit branch: only a position we actually own can be SOLD.
    For an un-held name the same failing signals mean AVOID (don't open it).
    Defaults to False so a missing holdings file can never invent a Sell.
    """
    verdict = (rep.get("verdict") or "").lower()
    score = rep.get("score")
    fund = rep.get("score")
    tech = rep.get("tech_score")
    overall = overall_score(fund, tech)
    go = (rep.get("go_no_go") or "").upper()
    thesis_status = (rep.get("thesis_status") or "").lower()
    summary = pillar_summary(pillars)
    bear = (rep.get("bear_case_trigger") or "").strip()

    rationale: list[str] = []

    # ---- SELL (held) / AVOID (not held): thesis broken, fundamental
    # deterioration, or weak verdict. Same evidence, different actionability.
    if thesis_status == "broken" or summary["overall"] == "broken" or verdict in WEAK_VERDICTS \
            or (score is not None and score < 5.0):
        stance = "Sell" if held else "Avoid"
        headline = (
            "Exit — thesis does not hold on a position you own."
            if held else
            "Avoid — thesis does not hold; do not open a position."
        )
        if thesis_status == "broken":
            rationale.append("Thesis-failure: pillar-integrity drift check returned BROKEN.")
        if summary["broken"]:
            broken_names = [p["name"] for p in pillars if p["status"] == "broken"]
            rationale.append(f"Deterioration: {summary['broken']} broken pillar(s) — {', '.join(broken_names)}.")
        if verdict in WEAK_VERDICTS:
            rationale.append(f"Verdict '{verdict}' signals the name failed the quality/value bar.")
        if score is not None and score < 5.0:
            rationale.append(f"Composite {score:.2f} (< 5.0) — below the investable band.")
        if bear:
            rationale.append(f"Exit condition already framed: {bear}")
        rationale.append(
            "Position is held — this is an exit decision."
            if held else
            "Not held — nothing to sell; this is a do-not-open."
        )
        return {"stance": stance, "headline": headline, "rationale": rationale}

    # ---- BUY: strong verdict/score and thesis intact and no technical NO-GO.
    strong = verdict in STRONG_VERDICTS or (overall is not None and overall >= 7.5)
    if strong and summary["overall"] == "intact" and go != "NO-GO":
        stance = "Buy"
        headline = "Buy candidate — thesis intact with positive risk-reward."
        if overall is not None:
            rationale.append(f"Driver: overall {overall} (fund {fund}, tech {tech if tech is not None else 'n/a'}) clears the 7.5 conviction line.")
        rationale.append(f"Advantage: {summary['intact']}/{summary['total']} thesis pillars intact (quality + balance-sheet support).")
        v = valuation_read(rep)
        if v["label"] == "Attractive":
            rationale.append(f"Catalyst / re-rating: valuation read '{v['label']}' ({v['detail']}) leaves room to re-rate.")
        if go == "GO":
            rationale.append("Technical: Phase-3 read is GO — entry timing confirmed.")
        if rep.get("entry_zone"):
            rationale.append(f"Suggested entry zone: {rep['entry_zone']}.")
        return {"stance": stance, "headline": headline, "rationale": rationale}

    # ---- HOLD: everything else — watch, with monitoring criteria.
    stance = "Hold"
    headline = "Hold / watch — constructive but not a clear-cut entry."
    if overall is not None:
        rationale.append(f"Reason: overall {overall} is constructive but below the 7.5 high-conviction line.")
    if summary["weakened"]:
        weak_names = [p["name"] for p in pillars if p["status"] == "weakened"]
        rationale.append(f"Monitor: {summary['weakened']} weakened pillar(s) — {', '.join(weak_names)}.")
    if go == "NO-GO":
        rationale.append("Monitor: Phase-3 technical read is NO-GO — wait for a better entry.")
    if bear:
        rationale.append(f"Monitoring criterion (sell if): {bear}")
    if not rationale:
        rationale.append("Insufficient differentiated signal — hold and re-screen at next evaluation.")
    return {"stance": stance, "headline": headline, "rationale": rationale}


def build_thesis_entry(rep: dict, held: bool = False) -> dict:
    """Compose the full per-name thesis card payload from a slim report dict."""
    pillars = derive_pillars(rep)
    summary = pillar_summary(pillars)
    stance = derive_stance(rep, pillars, held=held)
    return {
        "ticker": rep.get("ticker"),
        "held": held,
        "date": rep.get("date"),
        "sector": rep.get("sector"),
        "region": rep.get("region"),
        "size": rep.get("size"),
        "mode": rep.get("mode"),
        "verdict": rep.get("verdict"),
        "filename": rep.get("filename"),
        "days_left": rep.get("days_left"),
        "fund_score": rep.get("score"),
        "tech_score": rep.get("tech_score"),
        "overall_score": overall_score(rep.get("score"), rep.get("tech_score")),
        "quality": quality_read(rep),
        "valuation": valuation_read(rep),
        "risk": risk_read(rep),
        "stance": stance["stance"],
        "stance_headline": stance["headline"],
        "rationale": stance["rationale"],
        "pillars": pillars,
        "pillar_summary": summary,
        "thesis_text": rep.get("thesis"),
        "bear_case_trigger": rep.get("bear_case_trigger"),
    }


# ----------------------------------------------------------------------------
# I/O: scan reports (+ bear triggers from _log.csv), write _thesis.json
# ----------------------------------------------------------------------------

def load_reports(root: Path, today: dt.date) -> list[dict]:
    """Most-recent slim report per ticker, via build_dashboard.slim_report."""
    from importlib import util as _il_util

    spec = _il_util.spec_from_file_location("build_dashboard", SCRIPT_DIR / "build_dashboard.py")
    bd = _il_util.module_from_spec(spec)
    spec.loader.exec_module(bd)

    by_ticker: dict[str, dict] = {}
    for p in sorted(root.glob("*.md")):
        if not bd.REPORT_NAME_RE.match(p.name):
            continue
        slim = bd.slim_report(p, today)
        if not slim:
            continue
        t = slim["ticker"]
        prev = by_ticker.get(t)
        if prev is None or (slim.get("date") or "") > (prev.get("date") or ""):
            by_ticker[t] = slim
    return list(by_ticker.values())


def merge_bear_triggers(reports: list[dict], root: Path) -> None:
    """Backfill bear_case_trigger from _log.csv when the report frontmatter
    (slim) didn't carry it (slim_report skips multiline/bracketed values)."""
    from importlib import util as _il_util

    spec = _il_util.spec_from_file_location("build_dashboard", SCRIPT_DIR / "build_dashboard.py")
    bd = _il_util.module_from_spec(spec)
    spec.loader.exec_module(bd)

    triggers: dict[str, str] = {}
    for row in bd.load_bear_triggers():
        t = row.get("ticker")
        d = row.get("date") or ""
        if not t:
            continue
        prev = triggers.get(t)
        if prev is None or d > prev[0]:
            triggers[t] = (d, row.get("trigger") or "")
    for rep in reports:
        if not rep.get("bear_case_trigger"):
            hit = triggers.get(rep.get("ticker"))
            if hit:
                rep["bear_case_trigger"] = hit[1]


def load_held_tickers(root: Path) -> set[str]:
    """Analysis-tickers we actually own, per _portfolio_holdings.yaml.

    Reuses exit_plan.load_holdings + find_holding so held-detection has ONE
    implementation and inherits its alias map (SHEL.L -> SHELL.AS, ADR/local
    dual listings). Any failure degrades to the empty set, which is the safe
    direction: no holdings known -> no Sell stance is ever emitted.
    """
    from importlib import util as _il_util

    try:
        spec = _il_util.spec_from_file_location("exit_plan", SCRIPT_DIR / "exit_plan.py")
        xp = _il_util.module_from_spec(spec)
        spec.loader.exec_module(xp)
        holdings, warns = xp.load_holdings(root)
    except Exception as e:
        log(f"WARN: held-detection unavailable ({type(e).__name__}: {e}) — no Sell stances will be emitted")
        return set()
    for w in warns:
        log(f"WARN: {w}")
    out: set[str] = set()
    for h in holdings:
        t = (h.get("ticker") or "").strip()
        if not t:
            continue
        # Only equities are sellable through this lens; crypto has no thesis report.
        if (h.get("asset_type") or "equity") != "equity":
            continue
        out.add(t)
    # Map every alias back onto the held set so an analysis ticker that differs
    # from the holdings-yaml ticker (SHEL.L vs SHELL.AS) still resolves as held.
    for alias, target in getattr(xp, "ALIASES", {}).items():
        if target in out:
            out.add(alias)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out", default=str(OUT_JSON))
    args = ap.parse_args()

    root = Path(args.root)
    today = dt.date.today()

    reports = load_reports(root, today)
    # build_dashboard.LOG points at the same root by default; only override if needed.
    merge_bear_triggers(reports, root)

    held = load_held_tickers(root)

    entries = [build_thesis_entry(r, held=r.get("ticker") in held) for r in reports]
    # Order: actionable first — Sell outranks Buy because it concerns real money
    # already at risk; Avoid is informational only, so it sorts last.
    stance_rank = {"Sell": 0, "Buy": 1, "Hold": 2, "Avoid": 3}
    entries.sort(key=lambda e: (stance_rank.get(e["stance"], 4), -(e.get("overall_score") or 0)))

    bundle = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "today": today.isoformat(),
        "freshness_days": FRESHNESS_DAYS,
        "n_names": len(entries),
        "n_held": sum(1 for e in entries if e.get("held")),
        "held_tickers": sorted(held),
        "names": entries,
    }
    Path(args.out).write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    from collections import Counter
    stances = Counter(e["stance"] for e in entries)
    log("=" * 64)
    log(f"Thesis dashboard — {len(entries)} names ({bundle['n_held']} held)")
    log(f"Stances: {dict(stances)}")
    for e in entries:
        ps = e["pillar_summary"]
        log(f"  {e['ticker']:<12}{'*' if e.get('held') else ' '}{e['stance']:<5} ov={str(e['overall_score']):<5} "
            f"pillars {ps['intact']}i/{ps['weakened']}w/{ps['broken']}b "
            f"({ps['overall']}) | {e['stance_headline']}")
    log(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
