"""category_lens.py — cyclical / turnaround / asset-play detection (v4.3 wave 3.5).

WHY THIS EXISTS AT ALL. `analyze_ticker.lynch_category()` is eight lines and covers
four of Lynch's six categories:

    if rev_cagr_5y is None:                            return "unknown"
    if rev_cagr_5y >= 0.20:                            return "fast_grower"
    if rev_cagr_5y >= 0.05 and (roe_5y or 0) >= 0.10:  return "stalwart"
    if rev_cagr_5y < 0.05:                             return "slow_grower"
    return "cyclical"

Turnaround and asset play are absent from the enum entirely, and "cyclical" is not a
test — it is the residual bucket for 5 % ≤ CAGR < 20 % with ROE < 10 %. Cyclicality is
about EARNINGS AMPLITUDE ACROSS A CYCLE; a two-variable point estimate never looks at
amplitude, so a steady low-ROE compounder is labelled cyclical and a genuine cyclical at
peak earnings is labelled `stalwart`. The second error is the expensive one: at the peak
a cyclical shows record margins and a low trailing P/E, which is exactly what Gate 2
rewards. This module exists to name that trap before the gate does.

WHY IT DOES NOT SIMPLY FIX `lynch_category()`. That function feeds the Growth-durability
sub-score and the Lynch return/drawdown prior in `alpha_beta.py`. Changing it would move
`scores.composite`, which is frozen at v2.2 and which v4.3 may not touch. So the
classification ships as an additive `category_lens` key ALONGSIDE `lynch_category`, and
where the two disagree the block says so in words rather than quietly overwriting one.

WHAT IT IS NOT. This is a LENS, not a mandate change. The mandate stays Quality
Compounder; `STRATEGY_GUIDE.md` rejects Deep Value and Net-Nets as incompatible. A
cyclical still prints its Quality Compounder score — the category card explains why that
score reads the way it does. Category-SPECIFIC WEIGHTS are roadmap G2, blocked on the G1
backtest until ≈2026-10-17, and nothing here anticipates them.

WHAT IT REFUSES TO CLAIM. An asset play needs a REALISATION CATALYST, and no catalyst is
derivable from a numbers JSON — a holding-company discount that has persisted for twenty
years and one about to be closed by a break-up look identical here. So `catalyst` is
always null with a stated reason, and the asset-play flag is explicitly "recognised and
explained", never "buy". Same discipline as the rest of the system: sparse renders blank,
never zero, and never an inference dressed as a measurement.

Pure stdlib. Consumes the analysis JSON plus the `_fin_history` annual cache; no network,
no yfinance, no extra API call. Thresholds are published in `docs/CATEGORIES.md` — a
classifier with unpublished cut points is not reproducible, which is the same reason the
star ratings (2.8) carry their bands in a doc.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from markets import normalize_gbx  # noqa: E402  (stdlib-only module; see test_asset_play)

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

OUT_DIR_DEFAULT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")

# --- published thresholds (docs/CATEGORIES.md) ------------------------------
# Cyclical. Amplitude is measured on the EBITDA margin (percentage points) and on the
# EBITDA level (peak-to-trough fraction). Both are needed: margin alone would flag a
# company whose mix changed once, level alone would flag any single bad year.
CYC_MIN_YEARS = 6
CYC_AMPLITUDE_PP = 8.0        # max-min EBITDA margin, in percentage points
CYC_STRONG_AMPLITUDE_PP = 10.0
CYC_DRAWDOWN = 0.30           # deepest peak-to-trough fall in EBITDA
CYC_DOWN_YEAR = 0.15          # a year counts as "down" at -15 % EBITDA or worse
CYC_PEAK_PERCENTILE = 0.80    # margin this high in its own range = late-cycle
# A CYCLE HAS TO COME BACK. Measured on IBM's real 20-year EBITDA history, the first
# version of this test called IBM cyclical at high confidence: EBITDA fell 74 % peak to
# trough across the Kyndryl spin-off and the mainframe-to-software transition, over two
# down years. That is a SECULAR DECLINE with a mix change on top — one way, no return —
# and a drawdown statistic alone cannot tell the two apart. A drawdown only counts toward
# cyclicality once the series has recovered CYC_RECOVERY of the fall; anything else is
# reported as secular decline, which is a genuinely useful and completely different fact.
CYC_FALL_LEG = 0.20           # a down leg has to be this deep to open an episode
CYC_RECOVERY = 0.50           # and regain this much of it before the episode counts
# A CYCLE ALSO TAKES TIME. Second corpus run, second correction: P&G showed a 54 % fall
# and a "completed cycle" because FY2019 EBITDA dropped to 9.4bn between 16.7 and 19.3 —
# the Gillette impairment, a single-year accounting event. MSFT and DECK failed the same
# way on one-year dips. An industry cycle has duration; a write-down does not.
#
# The test is a SUSTAINED trough, not elapsed time from the peak: P&G survived the
# elapsed-time version because its peak sat eleven years before the impairment, so a
# one-year plunge inherited a decade of slow drift and looked long. Requiring
# CYC_FALL_YEARS CONSECUTIVE observations below the fall threshold kills that — P&G has
# exactly two such years in twenty and they are four years apart, while AMD's FY2022 and
# FY2023 sit side by side, which is what a semiconductor cycle actually looks like.
CYC_FALL_YEARS = 2
# And it has to happen at a meaningful scale. A "90 % collapse" from 0.02bn to 0.002bn in
# a young company's first reported years is noise, not a cycle.
CYC_PEAK_FLOOR_FRAC = 0.05    # episode peak, as a fraction of the series maximum
# Sectors where cyclicality is the base rate. EVIDENCE ONLY — never decisive, because
# "Industrials" contains both a steel mill and a payroll processor.
CYCLICAL_SECTORS = {
    "energy", "basic materials", "materials", "consumer cyclical",
    "industrials", "real estate",
}

# Turnaround. The inflection must be RECENT or it is just history.
TURN_MIN_YEARS = 4
TURN_LOOKBACK = 5             # the loss must sit within this many years of the latest
TURN_ALTMAN_DISTRESS = 1.8    # below this, survival is the question, not the recovery
TURN_CURRENT_RATIO_MIN = 1.0
TURN_NETDEBT_EBITDA_MAX = 4.0

# Asset play. P/B is the screen; tangible book is the confirmation, because a P/B of 0.9
# on a balance sheet that is mostly goodwill is not an asset play, it is an impairment
# waiting to be booked.
ASSET_PB_STRONG = 1.0
ASSET_PB_MODERATE = 1.3
ASSET_PTB_MAX = 1.5
# How far the two book-value paths may disagree before the metric is declared unreliable.
# Set from the corpus, not from taste: across 122 cross-checkable reports the ratio is
# below 3 for all but five names, and those five are unit errors (TSM's USD ADR against
# TWD book, 43x; SSUN.F, 59x). The 1.7–2.9 middle band is NOT error — it is the balance
# extractor's `shares` row falling through to "Common Stock", which on some filers is a
# par value in currency rather than a share count (recorded as an audit finding). So the
# tolerance catches order-of-magnitude breaks and leaves that noise alone, because a
# check that fires on a quarter of the corpus is a check nobody reads.
PB_CROSSCHECK_TOL = 5.0
# And a floor no real equity trades below. BRK-B printed 0.001x book because yfinance
# reports its per-share book on the A-share basis against a B-share quote — a 1,500x
# unit error that would otherwise have been published as the asset play of the century.
PB_PLAUSIBLE_MIN = 0.05
CATALYST_NOTE = ("realisation catalyst is not derivable from financial data — a permanent "
                 "holding-company discount and an imminent break-up look identical here; "
                 "see the report narrative")

CATEGORIES = ("cyclical", "turnaround", "asset_play")
# Tie-break when more than one fires. A cyclical AT THE TROUGH also looks like a
# turnaround (losses then recovery), and the distinction matters for what you do next:
# a turnaround is judged on survival, a cyclical on mid-cycle earnings. Cyclical wins
# that tie because the recovery is the cycle doing its job, not management fixing
# anything. Asset play is last: it is a valuation observation, not a business one.
PRECEDENCE = ("cyclical", "turnaround", "asset_play")


def log(msg: str) -> None:
    print(f"[category_lens] {msg}", file=sys.stderr)


# ===================================================================
# numeric helpers (pure)
# ===================================================================
def _num(v):
    """Numeric or None. Booleans are not numbers — `True` must never score 1.0."""
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


def _first(seq):
    """First element of a [latest, prior] statements_raw pair, or None."""
    if isinstance(seq, (list, tuple)) and seq:
        return _num(seq[0])
    return _num(seq)


def max_drawdown(series: list) -> float | None:
    """Deepest peak-to-SUBSEQUENT-trough fall, as a fraction of the peak.

    Peak-to-subsequent, not max-minus-min: a company that lost money early and then
    compounded for a decade has a huge max-minus-min and no drawdown at all, and calling
    that cyclical would be exactly backwards. Peaks at or below zero are skipped — the
    fraction is meaningless there and would print a nonsense 300 %.
    """
    vals = [_num(v) for v in series]
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None
    peak, worst = None, 0.0
    for v in vals:
        if peak is None or v > peak:
            peak = v
        if peak and peak > 0:
            worst = max(worst, (peak - v) / peak)
    return round(worst, 4)


def positive_window(values: list) -> tuple:
    """Longest contiguous run of strictly-positive observations, as (start, end_exclusive).

    Ratio arithmetic needs a positive denominator. AMD's twenty-year EBITDA history
    contains six loss years, and running the drawdown formula across them produced a
    319 % "drawdown" and five phantom cycles — `(peak - v) / peak` is unbounded once `v`
    goes negative. The loss years are not noise to be smoothed away, they are the
    TURNAROUND test's evidence; the cyclical test simply cannot speak about them, so it
    confines itself to the longest stretch where the arithmetic means something and
    reports which stretch that was.
    """
    vals = [_num(v) for v in values]
    best = (0, 0)
    i = 0
    while i < len(vals):
        if vals[i] is None or vals[i] <= 0:
            i += 1
            continue
        j = i
        while j < len(vals) and vals[j] is not None and vals[j] > 0:
            j += 1
        if (j - i) > (best[1] - best[0]):
            best = (i, j)
        i = j
    return best


def cycle_episodes(series: list, min_fall: float = CYC_FALL_LEG,
                   min_recovery: float = CYC_RECOVERY,
                   min_fall_years: int = CYC_FALL_YEARS,
                   peak_floor_frac: float = CYC_PEAK_FLOOR_FRAC) -> list:
    """Peak → trough → recovery episodes. Recovery and duration are what make it a cycle.

    Walks the series once, tracking the running peak. A fall of `min_fall` from that peak
    opens an episode; the episode CLOSES (and counts as completed) once the series has
    regained `min_recovery` of the peak-to-trough distance. An episode still open at the
    end is returned with `completed=False` — that is the shape of a secular decline, and
    reporting it as such is the whole point of doing this rather than taking a
    max-drawdown number at face value.

    Two qualifiers, both added because the corpus said so and neither guessable from the
    spec: the fall must take `min_fall_years` observations (a one-year drop is a
    write-down, see CYC_FALL_YEARS), and the peak must be at least `peak_floor_frac` of
    the series maximum (a collapse inside the noise floor of a young company is not a
    cycle). Each episode carries the indices so the caller can name the years.
    """
    vals = [_num(v) for v in series]
    out = []
    if len([v for v in vals if v is not None]) < 3:
        return out
    scale = max((v for v in vals if v is not None), default=0.0)
    floor = scale * peak_floor_frac if scale > 0 else 0.0

    peak_i = next((i for i, v in enumerate(vals) if v is not None), None)
    if peak_i is None:
        return out
    ep = None
    for i in range(peak_i + 1, len(vals)):
        v = vals[i]
        if v is None:
            continue
        pk = vals[peak_i]
        if ep is None:
            if pk > 0 and pk >= floor and (pk - v) / pk >= min_fall:
                ep = {"peak": pk, "peak_i": peak_i, "trough": v, "trough_i": i,
                      "recovery": 0.0, "completed": False}
            elif v > pk:
                peak_i = i
            continue
        if v < ep["trough"]:
            ep["trough"], ep["trough_i"] = v, i
        span = ep["peak"] - ep["trough"]
        if span > 0:
            ep["recovery"] = round(max(ep["recovery"], (v - ep["trough"]) / span), 4)
        if ep["recovery"] >= min_recovery:
            _close(ep, vals, min_fall, min_fall_years, min_recovery)
            out.append(ep)
            peak_i, ep = (i if v > ep["peak"] else ep["peak_i"]), None
    if ep is not None:
        _close(ep, vals, min_fall, min_fall_years, min_recovery)
        out.append(ep)
    return out


def _close(ep: dict, vals: list, min_fall: float, min_fall_years: int,
           min_recovery: float) -> None:
    """Finish an episode: its depth, and whether the trough was SUSTAINED.

    `sustained_years` counts the longest run of CONSECUTIVE observations between the peak
    and the recovery that sat at or below `peak × (1 - min_fall)`. That, not elapsed time,
    is what separates a cycle from a write-down (see CYC_FALL_YEARS).
    """
    span = ep["peak"] - ep["trough"]
    ep["fall"] = round(span / ep["peak"], 4) if ep["peak"] > 0 else None
    ep["fall_years"] = ep["trough_i"] - ep["peak_i"]
    limit = ep["peak"] * (1.0 - min_fall)
    run = best = 0
    for k in range(ep["peak_i"] + 1, min(len(vals), ep["trough_i"] + 1 + min_fall_years)):
        v = vals[k]
        if v is not None and v <= limit:
            run += 1
            best = max(best, run)
        else:
            run = 0
    ep["sustained_years"] = best
    ep["recovered"] = ep.get("recovery", 0) >= min_recovery
    ep["completed"] = ep["recovered"] and best >= min_fall_years


def down_years(series: list, threshold: float = CYC_DOWN_YEAR) -> int:
    """How many year-over-year falls of `threshold` or worse the series contains.

    This is what separates a cycle from an accident. One bad year is 2020; two or more
    across a decade is an industry that breathes.
    """
    vals = [_num(v) for v in series]
    n = 0
    for prev, cur in zip(vals, vals[1:]):
        if prev is None or cur is None or prev <= 0:
            continue
        if (prev - cur) / prev >= threshold:
            n += 1
    return n


def percentile_of(value, series: list) -> float | None:
    """Where `value` sits inside its own history, 0..1. Ties count as half."""
    v = _num(value)
    vals = [_num(x) for x in series]
    vals = [x for x in vals if x is not None]
    if v is None or len(vals) < 3:
        return None
    below = sum(1 for x in vals if x < v)
    equal = sum(1 for x in vals if x == v)
    return round((below + equal / 2.0) / len(vals), 4)


def _flag(detected=None, confidence=None, **rest) -> dict:
    out = {"detected": detected, "confidence": confidence,
           "evidence": [], "metrics": {}, "not_computable": []}
    out.update(rest)
    return out


# ===================================================================
# series assembly
# ===================================================================
def annual_series(fin_history: dict | None) -> dict:
    """Pull the annual spine out of the `_fin_history` cache.

    Returns labels + revenue + ebitda + fcf + net_income + the derived EBITDA and net
    margins, all aligned to the same year index. Missing series come back empty rather
    than short — a margin computed from two different year sets is worse than no margin.
    """
    out = {"labels": [], "revenue": [], "ebitda": [], "fcf": [], "net_income": [],
           "ebitda_margin": [], "net_margin": [], "years": 0, "source": None}
    ann = ((fin_history or {}).get("annual") or {})
    labels = list(ann.get("labels") or [])
    if not labels:
        return out
    out["labels"] = labels
    out["source"] = (fin_history or {}).get("source")
    for key in ("revenue", "ebitda", "fcf", "net_income"):
        vals = list(ann.get(key) or [])
        vals = (vals + [None] * len(labels))[:len(labels)]
        out[key] = [_num(v) for v in vals]
    for margin_key, num_key in (("ebitda_margin", "ebitda"), ("net_margin", "net_income")):
        out[margin_key] = [
            (n / r) if (n is not None and r not in (None, 0) and r > 0) else None
            for n, r in zip(out[num_key], out["revenue"])
        ]
    out["years"] = len(labels)
    return out


# ===================================================================
# the three tests
# ===================================================================
def test_cyclical(series: dict, sector: str | None) -> dict:
    """Earnings amplitude across the available history — a test, not a residual bucket."""
    f = _flag()
    sector_l = (sector or "").strip().lower()
    if sector_l in CYCLICAL_SECTORS:
        f["evidence"].append(f"sector base rate: {sector} is cycle-exposed (supporting only)")
    f["metrics"]["sector_prior"] = sector_l in CYCLICAL_SECTORS

    all_labels = series.get("labels") or []
    lo, hi = positive_window(series.get("ebitda") or [])
    ebitda = (series.get("ebitda") or [])[lo:hi]
    margins = [v for v in (series.get("ebitda_margin") or [])[lo:hi] if v is not None]
    years = len([v for v in ebitda if v is not None])
    total_years = series.get("years") or 0
    f["metrics"]["years_available"] = years
    f["metrics"]["years_total"] = total_years
    if lo or hi < total_years:
        window = f"{all_labels[lo]}–{all_labels[hi - 1]}" if hi > lo and hi <= len(all_labels) else "?"
        f["metrics"]["window"] = window
        f["evidence"].append(
            f"amplitude measured over {window} — the longest run of positive EBITDA "
            f"inside a {total_years}y history (loss years belong to the turnaround test)")
    if years < CYC_MIN_YEARS or len(margins) < 3:
        f["not_computable"].append(
            f"needs {CYC_MIN_YEARS} annual years of positive EBITDA, has {years}")
        f["confidence"] = "none"
        return f

    amplitude_pp = round((max(margins) - min(margins)) * 100, 2)
    dd = max_drawdown(ebitda)
    downs = down_years(ebitda)
    episodes = cycle_episodes(ebitda)
    completed = [e for e in episodes if e.get("completed")]
    # An episode can fail `completed` two ways, and only one of them is a decline: it
    # never recovered (secular), or it recovered from a one-year dip that was never
    # sustained (a write-down). Reading "not completed" as "declining" printed NVDA as a
    # secular decline that had "regained 552 %" of its fall — a sentence that refutes
    # itself. `recovered` is the field that answers this question.
    open_leg = next((e for e in episodes if not e.get("recovered")), None)
    latest_margin = next((v for v in reversed((series.get("ebitda_margin") or [])[lo:hi])
                          if v is not None), None)
    pct = percentile_of(latest_margin, margins)
    f["metrics"].update({
        "ebitda_margin_amplitude_pp": amplitude_pp,
        "ebitda_max_drawdown": dd,
        "down_years": downs,
        "completed_cycles": len(completed),
        "deepest_completed_fall": max((e.get("fall") or 0 for e in completed), default=None),
        "latest_ebitda_margin": None if latest_margin is None else round(latest_margin, 4),
        "margin_percentile": pct,
    })

    # A one-way fall that never came back is a different animal, and naming it is more
    # useful than mislabelling it. It is also disqualifying for the cyclical read:
    # mid-cycle earnings are meaningless when there is no cycle to be mid of.
    f["secular_decline"] = bool(
        open_leg and (open_leg.get("fall") or 0) >= CYC_DRAWDOWN and not completed)
    if f["secular_decline"]:
        f["evidence"].append(
            f"EBITDA fell {open_leg['fall']:.0%} from its peak and has regained only "
            f"{open_leg['recovery']:.0%} of it — a secular decline, not a cycle")

    deepest = max((e.get("fall") or 0 for e in completed), default=0.0)
    deep = deepest >= CYC_DRAWDOWN
    wide = amplitude_pp >= CYC_AMPLITUDE_PP
    repeated = len(completed) >= 2
    if completed and deep and (repeated or amplitude_pp >= CYC_STRONG_AMPLITUDE_PP):
        f["detected"], f["confidence"] = True, "high" if repeated else "moderate"
        f["evidence"].append(
            f"{len(completed)} completed cycle(s) in {years}y, deepest {deepest:.0%} over "
            f"{max((e.get('fall_years') or 0) for e in completed)}y and recovered; "
            f"margin range {amplitude_pp:.1f}pp")
    elif completed and (deep or (wide and repeated)):
        f["detected"], f["confidence"] = True, "moderate"
        f["evidence"].append(
            f"{len(completed)} completed cycle(s), deepest {deepest:.0%}; margin range "
            f"{amplitude_pp:.1f}pp over {downs} down year(s)")
    elif not completed:
        f["detected"], f["confidence"] = False, "high" if years >= 10 else "moderate"
        f["evidence"].append(
            f"no completed peak-trough-recovery cycle in {years}y "
            f"(deepest fall {dd:.0%}, never regained {CYC_RECOVERY:.0%} of it)")
    else:
        f["detected"], f["confidence"] = False, "high" if years >= 10 else "moderate"
        f["evidence"].append(
            f"cycles present but shallow: deepest {deepest:.0%}, margin range "
            f"{amplitude_pp:.1f}pp, {downs} down year(s)")

    # The trap, and the reason this module was written.
    if f["detected"] and pct is not None and pct >= CYC_PEAK_PERCENTILE:
        f["peak_earnings_warning"] = True
        f["evidence"].append(
            f"LATE-CYCLE: current EBITDA margin sits in the top {(1 - pct):.0%} of its own "
            f"{years}y range — trailing P/E is measured on peak earnings and will read cheap")
    else:
        f["peak_earnings_warning"] = False
    return f


def test_turnaround(series: dict, analysis: dict) -> dict:
    """A loss-to-profit inflection, judged on survival before recovery."""
    f = _flag()
    fund = analysis.get("fundamentals") or {}
    ni = series.get("net_income") or []
    fcf = series.get("fcf") or []
    years = series.get("years") or 0
    f["metrics"]["years_available"] = years

    usable = [(k, v) for k, v in (("net_income", ni), ("fcf", fcf))
              if len([x for x in v if x is not None]) >= TURN_MIN_YEARS]
    if not usable:
        f["not_computable"].append(
            f"needs {TURN_MIN_YEARS} annual years of net income or FCF")
        f["confidence"] = "none"
        return f

    inflected_on = []
    never_profitable = []
    for key, vals in usable:
        idx = [i for i, v in enumerate(vals) if v is not None]
        latest_i = idx[-1]
        if vals[latest_i] is None or vals[latest_i] <= 0:
            continue
        window = [i for i in idx if latest_i - i <= TURN_LOOKBACK and i != latest_i]
        losses = [i for i in window if vals[i] is not None and vals[i] < 0]
        if not losses:
            continue
        # A TURNAROUND IS A BUSINESS THAT BROKE AND IS BEING FIXED. A company reaching
        # profitability for the first time never turned around — it arrived. The corpus
        # made the distinction concrete: PLTR (losses from IPO to 2022, profitable since)
        # was flagged a turnaround beside adidas, whose FY2023 loss followed two decades
        # of profit. Lynch's category is the second one, and the difference decides what
        # you underwrite — a recovery to a known earnings power, or a first ascent to an
        # unknown one. So the record must contain profit BEFORE the loss.
        prior_profit = [i for i in idx if i < losses[0] and vals[i] is not None and vals[i] > 0]
        label = (series.get("labels") or ["?"] * (losses[-1] + 1))[losses[-1]]
        if not prior_profit:
            never_profitable.append(key)
            f["evidence"].append(
                f"{key} was never positive before the loss run ending {label} — first "
                f"profitability, not a turnaround")
            continue
        inflected_on.append(key)
        f["evidence"].append(
            f"{key} positive before the loss, negative in {label}, positive again in the "
            f"latest year")
    f["metrics"]["inflection_series"] = inflected_on
    f["metrics"]["first_profitability_only"] = never_profitable

    # Survival first — Gates 1/4/5 reject every turnaround by construction, so the
    # question a report has to answer is not "is it growing" but "does it get there".
    z = _num(analysis.get("altman_zscore"))
    cr = _num(fund.get("current_ratio"))
    nde = _num(fund.get("net_debt_ebitda"))
    stmts = (analysis.get("statements_raw") or {})
    op = _first((stmts.get("income") or {}).get("operating_income"))
    interest = _first((stmts.get("income") or {}).get("interest_expense"))
    coverage = (op / abs(interest)) if (op is not None and interest not in (None, 0)) else None
    f["metrics"].update({
        "altman_zscore": z, "current_ratio": cr, "net_debt_ebitda": nde,
        "interest_coverage": None if coverage is None else round(coverage, 2),
    })
    risks = []
    if z is not None and z < TURN_ALTMAN_DISTRESS:
        risks.append(f"Altman Z {z:.2f} < {TURN_ALTMAN_DISTRESS} (distress zone)")
    if cr is not None and cr < TURN_CURRENT_RATIO_MIN:
        risks.append(f"current ratio {cr:.2f} < {TURN_CURRENT_RATIO_MIN}")
    if nde is not None and nde > TURN_NETDEBT_EBITDA_MAX:
        risks.append(f"net debt/EBITDA {nde:.1f}x > {TURN_NETDEBT_EBITDA_MAX}x")
    for m in ("altman_zscore", "current_ratio", "net_debt_ebitda"):
        if f["metrics"][m] is None:
            f["not_computable"].append(f"survival input missing: {m}")
    f["survival_risks"] = risks

    if not inflected_on:
        f["detected"], f["confidence"] = False, "high"
        if not never_profitable:
            f["evidence"].append("no loss-to-profit inflection in the available history")
        return f
    f["detected"] = True
    f["confidence"] = "moderate" if risks else "high"
    if risks:
        f["evidence"].append("recovery is real but the balance sheet is not yet safe: "
                             + "; ".join(risks))
    return f


def test_asset_play(analysis: dict) -> dict:
    """P/B against TANGIBLE book. The catalyst is deliberately not claimed."""
    f = _flag()
    fund = analysis.get("fundamentals") or {}
    # Pence, measured not assumed. RIO.L priced at 7927 GBp against a book value of
    # 28.31 GBP printed a P/B of 280x on the first run — the quote is in pence and the
    # per-share book value is not. Every London name would have been declared "no asset
    # discount" for the wrong reason. markets.normalize_gbx is the canonical fix and is
    # imported rather than re-derived; it is stdlib-only, so this module stays pure.
    price, price_ccy = normalize_gbx(_num(analysis.get("price_current")),
                                     analysis.get("currency") or "")
    f["metrics"]["price_currency"] = price_ccy or None
    bvps = _num(fund.get("book_value"))
    pb = (price / bvps) if (price is not None and bvps not in (None, 0) and bvps > 0) else None
    f["metrics"]["price_to_book"] = None if pb is None else round(pb, 3)

    bal = ((analysis.get("statements_raw") or {}).get("balance") or {})
    equity = _first(bal.get("stockholders_equity"))
    shares = _first(bal.get("shares"))

    # CROSS-CHECK THE PER-SHARE BOOK VALUE AGAINST THE BALANCE SHEET. yfinance's
    # `bookValue` is not always on the same basis as the quote: BRK-B priced against an
    # A-share book value printed 0.001x, and TSM's USD ADR against TWD book printed 82x.
    # Both would have been asserted as facts — one a spectacular asset play, the other a
    # dismissal. Equity/shares from `statements_raw` is an independent path to the same
    # number, so when the two disagree by more than PB_CROSSCHECK_TOL the honest output
    # is "unreliable", not a number. Same rule the rest of the system uses: refuse rather
    # than assert.
    pb_stmt = None
    if (price and equity is not None and shares not in (None, 0)
            and shares > 0 and equity > 0):
        pb_stmt = price / (equity / shares)
        f["metrics"]["price_to_book_from_statements"] = round(pb_stmt, 3)
    if pb is not None and pb_stmt is not None:
        ratio = max(pb, pb_stmt) / min(pb, pb_stmt) if min(pb, pb_stmt) > 0 else None
        if ratio is not None and ratio > PB_CROSSCHECK_TOL:
            f["metrics"]["price_to_book_unreliable"] = True
            f["not_computable"].append(
                f"P/B disagrees between sources ({pb:.2f}x from `book_value`, "
                f"{pb_stmt:.2f}x from equity/shares) — different share class or "
                f"reporting currency; no asset-play claim is made")
            f["detected"], f["confidence"] = None, "none"
            f["catalyst"] = None
            f["catalyst_note"] = CATALYST_NOTE
            return f
    combined = _first(bal.get("goodwill_and_intangibles"))
    if combined is None:
        gw = _first(bal.get("goodwill"))
        intang = _first(bal.get("intangibles"))
        combined = None if (gw is None and intang is None) else (gw or 0.0) + (intang or 0.0)
    tangible_equity = None
    if equity is not None and combined is not None:
        tangible_equity = equity - combined
    elif _first(bal.get("net_tangible_assets")) is not None:
        tangible_equity = _first(bal.get("net_tangible_assets"))
    ptb = None
    if tangible_equity is not None and shares not in (None, 0) and shares > 0 and price:
        tbvps = tangible_equity / shares
        ptb = (price / tbvps) if tbvps > 0 else None
        f["metrics"]["tangible_book_per_share"] = round(tbvps, 4)
    f["metrics"]["price_to_tangible_book"] = None if ptb is None else round(ptb, 3)
    f["metrics"]["intangible_share_of_equity"] = (
        round(combined / equity, 4) if (combined is not None and equity
                                        not in (None, 0) and equity > 0) else None)

    # The catalyst is the whole thesis and it is not in this JSON. Saying so is the
    # honest output; inferring one from a low multiple is how a value trap gets bought.
    f["catalyst"] = None
    f["catalyst_note"] = CATALYST_NOTE

    if pb is None:
        f["not_computable"].append("price or book value per share missing")
        f["confidence"] = "none"
        return f
    if pb < PB_PLAUSIBLE_MIN:
        f["metrics"]["price_to_book_unreliable"] = True
        f["not_computable"].append(
            f"P/B of {pb:.4f}x is not a valuation, it is a unit mismatch between the "
            f"quote and the reported book value per share")
        f["detected"], f["confidence"] = None, "none"
        return f
    if tangible_equity is not None and tangible_equity <= 0:
        f["detected"], f["confidence"] = False, "high"
        f["evidence"].append("book value is entirely intangible — tangible equity is "
                             "negative, so there is no asset backing to buy")
        return f
    if ptb is None:
        f["not_computable"].append("tangible book not derivable (goodwill/intangibles "
                                   "rows absent) — P/B is unconfirmed")

    tangible_ok = ptb is None or ptb <= ASSET_PTB_MAX
    if pb <= ASSET_PB_STRONG and tangible_ok:
        f["detected"], f["confidence"] = True, "high" if ptb is not None else "moderate"
        f["evidence"].append(f"trades at {pb:.2f}x book"
                             + (f", {ptb:.2f}x tangible book" if ptb is not None else ""))
    elif pb <= ASSET_PB_MODERATE and tangible_ok:
        f["detected"], f["confidence"] = True, "moderate"
        f["evidence"].append(f"trades at {pb:.2f}x book — near asset value, not below it")
    else:
        f["detected"], f["confidence"] = False, "high"
        reason = f"{pb:.2f}x book"
        if ptb is not None and not tangible_ok:
            reason += f" but {ptb:.2f}x TANGIBLE book — the discount is goodwill, not assets"
        f["evidence"].append(f"no asset-value discount: {reason}")
    return f


# ===================================================================
# assembly
# ===================================================================
LYNCH_AGREEMENT_NOTES = {
    ("cyclical", "stalwart"): (
        "the classic misread: at peak earnings a cyclical shows high ROE and steady "
        "revenue growth, which is precisely the stalwart test"),
    ("cyclical", "fast_grower"): (
        "revenue is growing because the cycle is early, not because the market is"),
    ("cyclical", "slow_grower"): (
        "flat 5y revenue can be a cycle measured peak-to-peak"),
    ("turnaround", "slow_grower"): (
        "5y CAGR is depressed by the loss years the recovery is leaving behind"),
    ("turnaround", "fast_grower"): (
        "growth off a collapsed base is arithmetic, not durability"),
}


def compute(analysis: dict, fin_history: dict | None = None) -> dict:
    """Full `category_lens` block. Pure — same inputs in, same block out."""
    series = annual_series(fin_history)
    sector = analysis.get("sector")
    flags = {
        "cyclical": test_cyclical(series, sector),
        "turnaround": test_turnaround(series, analysis),
        "asset_play": test_asset_play(analysis),
    }
    detected = [c for c in PRECEDENCE if flags[c].get("detected")]
    primary = detected[0] if detected else None

    lynch = analysis.get("lynch_category")
    agrees = None
    note = None
    if primary is not None and lynch:
        agrees = (primary == lynch)
        if not agrees:
            note = LYNCH_AGREEMENT_NOTES.get((primary, lynch))
            if note is None:
                note = (f"`lynch_category` reads {lynch} from 5y revenue CAGR and ROE "
                        f"alone; the amplitude/inflection tests read {primary}")
    elif primary is None and lynch == "cyclical":
        # Only contradict the residual bucket when the amplitude test ACTUALLY RAN.
        # `detected is None` means no annual history was cached, and "the test finds no
        # cycle" would then be a claim about a test that never executed — the same class
        # of overstatement the ground-truth rule exists to prevent.
        if flags["cyclical"].get("detected") is False:
            agrees = False
            note = ("`lynch_category` says cyclical, but that is its RESIDUAL bucket "
                    "(5% ≤ CAGR < 20% with ROE < 10%) — the amplitude test finds no cycle")
        else:
            note = ("`lynch_category` says cyclical from its residual bucket; the "
                    "amplitude test could not run (no annual history cached)")

    return {
        "schema": "category_lens/1",
        "primary": primary,
        "detected": detected,
        "flags": flags,
        "lynch_category": lynch,
        "agrees_with_lynch": agrees,
        "disagreement_note": note,
        "depth_years": series.get("years") or 0,
        "history_source": series.get("source"),
        "peak_earnings_warning": bool(flags["cyclical"].get("peak_earnings_warning")),
        "mandate_note": ("a lens, not a mandate change — the mandate stays Quality "
                         "Compounder and the composite is untouched"),
    }


def render_lines(block: dict) -> list:
    """Human-readable summary lines (stderr / report fallback). No formatting decisions
    that the HTML card is entitled to make differently."""
    out = []
    primary = block.get("primary")
    out.append(f"primary: {primary or 'none of the three (default lens applies)'}")
    for key in CATEGORIES:
        f = (block.get("flags") or {}).get(key) or {}
        state = {True: "YES", False: "no", None: "n/a"}[f.get("detected")]
        out.append(f"  {key:<11} {state:<4} ({f.get('confidence') or 'n/a'})"
                   + (" — " + " · ".join(f["evidence"]) if f.get("evidence") else ""))
    if block.get("peak_earnings_warning"):
        out.append("  ⚠ peak-earnings trap: trailing P/E is measured on cycle-high earnings")
    if block.get("disagreement_note"):
        out.append(f"  vs lynch_category={block.get('lynch_category')}: "
                   f"{block['disagreement_note']}")
    return out


def _load_fin_history(ticker: str, out_dir: Path, explicit: str | None) -> dict | None:
    if explicit:
        try:
            return json.loads(Path(explicit).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log(f"fin-history {explicit}: {exc}")
            return None
    safe = ticker.replace("/", "-").replace("\\", "-")
    for cand in (out_dir / "_fin_history" / f"{safe}.json",
                 OUT_DIR_DEFAULT / "_fin_history" / f"{safe}.json"):
        if cand.is_file():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                log(f"fin-history {cand}: {exc}")
                return None
    log(f"no _fin_history cache for {ticker} — amplitude tests will report n/a")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Cyclical / turnaround / asset-play lens over an analysis JSON.")
    ap.add_argument("json_path")
    ap.add_argument("--fin-history", help="explicit _fin_history JSON (default: auto-resolve)")
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--update", action="store_true",
                    help="merge the block into the analysis JSON under `category_lens`")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    path = Path(args.json_path)
    try:
        analysis = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 0

    fh = _load_fin_history(analysis.get("ticker") or path.stem,
                           Path(args.out_dir), args.fin_history)
    block = compute(analysis, fh)

    if args.update:
        analysis["category_lens"] = block
        path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        log(f"merged category_lens into {path.name}")
    if args.pretty:
        for line in render_lines(block):
            print(line, file=sys.stderr)
    print(json.dumps(block, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
