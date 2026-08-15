"""star_ratings.py — five ⭐ quality dimensions, computed from published bands.

WHY this is 100 % deterministic Python and not "mostly Python with an LLM residual".
A star printed in a report is a **structured number**, so an LLM-set star breaks the
ground-truth rule (`SKILL.md:56`) exactly as surely as an LLM-set P/E would. The first
draft of the v4.3 plan proposed letting the model set the residual judgement; that would
have been an undeclared third exception to a rule the whole system rests on. So: every
star comes from thresholds published in `docs/STAR_RATINGS.md`, or the dimension renders
`n/a`. There is no third option and no prose that quietly becomes a number.

WHY published bands rather than a relative ranking. A star scale with no stated
thresholds is not comparable across companies, which is the entire point of the request —
"is this a 4-star balance sheet?" has to mean the same thing for IBM and for Lynas.

OVERLAY-ONLY. Nothing here touches `scores.composite` (frozen at v2.2) or the verdict.
The stars re-express what the analysis already found; they never re-decide it.

HONEST PROXIES. Two dimensions cannot be measured directly from a numbers JSON and are
scored on named proxies instead — `revenue_stability_0_1` for revenue recurrence, gross
margin for pricing power. `docs/STAR_RATINGS.md` names each proxy beside its band, because
a star whose provenance is unstated is indistinguishable from a guess.

Pure stdlib: consumes the analysis dict, returns a dict. No network, no matplotlib.
"""
from __future__ import annotations

import math

# A dimension needs this fraction of its components to be computable before it earns a
# star at all. Below it, `n/a` — a two-of-six star is a number pretending to be an
# assessment, and it would sit in a report next to genuinely-earned ones.
MIN_COVERAGE = 0.5

MAX_STARS = 5


def _num(v):
    """Numeric or None. Booleans are not numbers here — `True` must never score 1.0."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    if isinstance(v, str):
        try:
            f = float(v.strip())
        except ValueError:
            return None
        return None if math.isnan(f) else f
    return None


def band(value, thresholds: tuple, higher_is_better: bool = True) -> int | None:
    """Map a value to 1..5 through four ascending cut points.

    `thresholds` are the four boundaries between the five stars, always written in
    ASCENDING order regardless of direction, so a reader of `docs/STAR_RATINGS.md` sees
    the same shape for "ROIC > 25 % is great" and "net debt/EBITDA > 4 is bad". The
    direction flag, not the ordering of the numbers, carries the polarity — writing the
    bad-is-high metrics backwards was the obvious alternative and it makes the published
    table unreadable.
    """
    v = _num(value)
    if v is None:
        return None
    lo, mid_lo, mid_hi, hi = thresholds
    if not (lo <= mid_lo <= mid_hi <= hi):
        raise ValueError(f"thresholds must ascend: {thresholds}")
    stars = 1 + sum(1 for t in thresholds if v >= t)
    return stars if higher_is_better else (MAX_STARS + 1 - stars)


def _dimension(components: dict, weights: dict | None = None) -> dict:
    """Average the computable components into one star, or report n/a.

    Components are equally weighted unless `weights` says otherwise, and coverage is
    measured in weight rather than in count so a heavy component going missing registers
    as the bigger gap it is.

    Rounds half UP deliberately (`math.floor(x + 0.5)`): Python's banker's rounding turns
    a 3.5 average into 3 and a 4.5 into 4, so two companies half a star apart could print
    the same number. That is a surprising result to defend in a report.
    """
    weights = weights or {}
    got = {k: v for k, v in components.items() if v is not None}
    total_w = sum(weights.get(k, 1.0) for k in components) or 0.0
    got_w = sum(weights.get(k, 1.0) for k in got)
    coverage = (got_w / total_w) if total_w else 0.0
    if coverage < MIN_COVERAGE or not got:
        return {"stars": None, "components": components, "coverage": round(coverage, 2),
                "reason": "insufficient data"}
    avg = sum(v * weights.get(k, 1.0) for k, v in got.items()) / got_w
    return {"stars": max(1, min(MAX_STARS, int(math.floor(avg + 0.5)))),
            "components": components, "coverage": round(coverage, 2),
            "avg": round(avg, 2), "reason": None}


# ---------------------------------------------------------------------------
# The five dimensions. Every threshold below is published in docs/STAR_RATINGS.md;
# change one here and change it there, or the doc stops being the contract.
# ---------------------------------------------------------------------------
def business_model(data: dict) -> dict:
    """Revenue quality, unit economics, pricing power — on NAMED PROXIES.

    None of the three is read from a filing. Revenue *recurrence* is proxied by
    `revenue_stability_0_1` (how smooth the 5-year revenue series is), *pricing power* by
    gross margin, and *scale of the engine* by the revenue CAGR. Saying so is the point:
    a smooth revenue line is evidence of recurrence, not a subscription disclosure.
    """
    f = data.get("fundamentals") or {}
    return _dimension({
        "revenue_stability": band(f.get("revenue_stability_0_1"), (0.55, 0.70, 0.82, 0.92)),
        "gross_margin": band(f.get("gross_margin_ttm"), (0.20, 0.35, 0.50, 0.65)),
        "revenue_growth": band(f.get("revenue_cagr_5y"), (0.02, 0.06, 0.12, 0.20)),
    })


def company_economics(data: dict) -> dict:
    """Return on capital, margin structure, and whether returns clear their own cost.

    The ROIC-vs-cost-of-equity spread is the economically meaningful test — a 12 % ROIC is
    excellent for a utility and value-destroying for a high-beta grower — so it is scored
    beside the absolute level rather than instead of it. Cost of equity comes from the CAPM
    block `intrinsic_value.py` already computes; no new maths, no new fetch.
    """
    f = data.get("fundamentals") or {}
    capm = ((data.get("intrinsic_value") or {}).get("capm") or {})
    roic, coe = _num(f.get("roic_ttm")), _num(capm.get("cost_of_equity"))
    spread = (roic - coe) if (roic is not None and coe is not None) else None
    return _dimension({
        "roic": band(f.get("roic_ttm"), (0.08, 0.12, 0.18, 0.25)),
        "roic_vs_cost_of_equity": band(spread, (-0.02, 0.02, 0.07, 0.14)),
        "operating_margin": band(f.get("operating_margin_ttm"), (0.05, 0.12, 0.20, 0.30)),
        "net_margin": band(f.get("net_margin_ttm"), (0.04, 0.09, 0.15, 0.22)),
    })


def competitive_advantage(data: dict) -> dict:
    """Moat: the analysis' own moat sub-score, plus whether the returns behind it held.

    `scores.moat` is already a 0-10 judgement made under published rules, so it is rescaled
    rather than re-derived — deriving a second, differently-shaped moat number would leave
    the report arguing with itself. ROE durability (TTM against the 5-year average) is the
    check on it: a moat is a return that *persists*, and a wide-moat score sitting on top
    of decaying ROE is the case worth surfacing.
    """
    f = data.get("fundamentals") or {}
    scores = data.get("scores") or {}
    moat = _num(scores.get("moat"))
    roe_ttm, roe_5y = _num(f.get("roe_ttm")), _num(f.get("roe_5y_avg"))
    # Ratio, not difference: a 4-point ROE drop means something different at 40 % than at 8 %.
    durability = (roe_ttm / roe_5y) if (roe_ttm is not None and roe_5y and roe_5y > 0) else None
    return _dimension({
        "moat_subscore": band(moat, (2.0, 4.0, 6.5, 8.5)),
        "roic_level": band(f.get("roic_ttm"), (0.08, 0.12, 0.18, 0.25)),
        "roe_durability": band(durability, (0.55, 0.75, 0.92, 1.05)),
    })


def financial_quality(data: dict) -> dict:
    """Piotroski, Altman and the red-flag scanner — three co-equal sources.

    All are existing overlay outputs, so this dimension re-expresses work already done
    rather than forming a new opinion. Altman's bands are the published grey-zone ones
    (<1.8 distress, >3.0 safe) stretched to five steps.

    The scanner's three statement sub-scores are averaged into **one** component, not
    counted as three. Counting them separately over-weighted a single source at 3-of-5,
    and it put screens over a coverage cliff: a screen has Piotroski and Altman but no
    scanner, so it scored 2/5 = 40 % and rendered `n/a` for a dimension its two available
    indicators answer perfectly well. At 2-of-3 it rates, which is the correct outcome.

    **Piotroski carries double weight, and Altman half.** Equal weights produced a flat
    column on real names — 9880.HK printed four stars off a Piotroski of 3/9, because an
    Altman Z of 8.9 pinned that component at five. That is Altman doing what it does:
    above its own "safe" threshold of 3.0 it carries **no further information**, so any
    solvent company maxes it and an unweighted average lets one saturated ratio outvote a
    nine-signal composite. Piotroski aggregates nine tests across all three statements;
    Altman is a single solvency score. The weights say so.
    """
    rf = data.get("red_flags") or {}
    subs = [_num((rf.get(n) or {}).get("subscore_0_10")) for n in ("income", "balance", "cashflow")]
    subs = [s for s in subs if s is not None]
    statement_quality = (sum(subs) / len(subs)) if subs else None
    return _dimension({
        "piotroski": band(data.get("piotroski_fscore"), (3, 5, 7, 8)),
        "altman_z": band(data.get("altman_zscore"), (1.8, 2.7, 3.5, 5.0)),
        "statement_quality": band(statement_quality, (3.0, 5.5, 7.5, 9.0)),
    }, weights={"piotroski": 2.0, "altman_z": 0.5, "statement_quality": 1.0})


def capital_allocation(data: dict) -> dict:
    """What management does with the cash — the Borja v2.1 fields, already computed.

    Share count is scored on `shares_change_5y_pct` with the polarity inverted, because a
    shrinking count is the good outcome. Reinvestment quality is proxied by ROIC: a company
    retaining earnings at 25 % ROIC is allocating well even with a 0 % payout, and scoring
    payout alone would mark exactly that company down.
    """
    f = data.get("fundamentals") or {}
    cr = data.get("capital_returns") or {}
    return _dimension({
        "net_payout_yield": band(cr.get("net_payout_yield"), (0.005, 0.02, 0.04, 0.06)),
        "share_count_trend": band(f.get("shares_change_5y_pct") if
                                  cr.get("shares_change_5y_pct") is None else
                                  cr.get("shares_change_5y_pct"),
                                  (-8.0, -2.0, 1.0, 5.0), higher_is_better=False),
        "reinvestment_return": band(f.get("roic_ttm"), (0.08, 0.12, 0.18, 0.25)),
    })


DIMENSIONS = [
    ("business_model", "Business model", business_model),
    ("company_economics", "Company economics", company_economics),
    ("competitive_advantage", "Competitive advantage", competitive_advantage),
    ("financial_quality", "Financial quality", financial_quality),
    ("capital_allocation", "Capital allocation", capital_allocation),
]


def compute(data: dict) -> dict:
    """The full `star_ratings` overlay block.

    `overall` is the mean of the dimensions that earned a star, and is **absent** unless at
    least three did — an "overall" resting on two dimensions reads like a summary of five.
    """
    out = {"dimensions": {}, "schema": "star_ratings_v1", "max_stars": MAX_STARS}
    for key, label, fn in DIMENSIONS:
        try:
            res = fn(data or {})
        except Exception as exc:  # noqa: BLE001 — an overlay must never end a run
            res = {"stars": None, "components": {}, "coverage": 0.0,
                   "reason": f"error: {type(exc).__name__}"}
        res["label"] = label
        out["dimensions"][key] = res
    earned = [d["stars"] for d in out["dimensions"].values() if d["stars"] is not None]
    out["rated_dimensions"] = len(earned)
    if len(earned) >= 3:
        out["overall"] = round(sum(earned) / len(earned), 1)
    return out


def render_stars(n) -> str:
    """"★★★☆☆" for 3, "n/a" for None. Filled/empty glyphs rather than a bare digit so the
    scale is visible without a legend."""
    if n is None:
        return "n/a"
    n = max(0, min(MAX_STARS, int(n)))
    return "★" * n + "☆" * (MAX_STARS - n)


def main() -> int:
    import argparse
    import json
    import sys
    ap = argparse.ArgumentParser(description="Compute the star-ratings overlay from an analysis JSON.")
    ap.add_argument("json_path")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()
    try:
        with open(args.json_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 0
    res = compute(data)
    if args.pretty:
        for key, _label, _fn in DIMENSIONS:
            d = res["dimensions"][key]
            print(f"{d['label']:<24} {render_stars(d['stars']):<8} "
                  f"coverage {d['coverage']:.0%}"
                  + (f"  ({d['reason']})" if d.get("reason") else ""),
                  file=sys.stderr)
        print(f"{'OVERALL':<24} {res.get('overall', 'n/a')}", file=sys.stderr)
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
