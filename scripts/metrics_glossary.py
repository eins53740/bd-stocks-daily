"""
metrics_glossary.py — v4 Phase F (session 2): static valuation-metric cheat-sheet.

Pure, offline reference data for the report's "Valuation metric families" card.
No API, no I/O — just the per-metric advantages / limitations / when-to-use /
reference bands, grouped into the two families the spec (§11) prescribes:

    Equity multiples      : P/E, PEG, P/S, P/B, earnings yield
    Enterprise multiples  : EV/Sales, EV/EBITDA, EV/EBIT, FCF/EV

`render_report.py` imports this to build the greyed cheat-sheet (tooltip on
screen, <details> on mobile, grey column in print). Stdlib-only → runs under uv
AND ambient and is fully unit-testable.
"""
from __future__ import annotations

# Ordered families → metric ids. Order here IS the render order.
FAMILIES: dict[str, list[str]] = {
    "Equity multiples": ["pe", "peg", "ps", "pb", "earnings_yield"],
    "Enterprise multiples": ["ev_sales", "ev_ebitda", "ev_ebit", "fcf_ev"],
}

# Per-metric static reference. `bands` = (cheap_edge, rich_edge); `higher_cheaper`
# flags yield-style metrics where a BIGGER number means cheaper (earnings yield,
# FCF/EV). Bands are broad rule-of-thumb anchors — sector context still rules.
GLOSSARY: dict[str, dict] = {
    # ---- Equity (uses market cap / share price; sensitive to leverage) ----
    "pe": {
        "label": "P/E",
        "family": "Equity multiples",
        "advantages": "Universally quoted; quick read on how many years of current "
                      "earnings the price embeds.",
        "limitations": "Meaningless on losses; distorted by one-off items, buybacks "
                       "and different debt levels between peers.",
        "when_to_use": "Steady, profitable compounders vs their own history and "
                       "same-sector peers.",
        "reference": "cheap <15× · fair 15–25× · rich >25×",
        "bands": (15.0, 25.0),
        "higher_cheaper": False,
        "unit": "x",
    },
    "peg": {
        "label": "PEG",
        "family": "Equity multiples",
        "advantages": "Normalises P/E for growth — lets a fast grower and a slow one "
                      "be compared on one axis.",
        "limitations": "Only as good as the growth estimate; unstable when growth is "
                       "near zero or negative.",
        "when_to_use": "Growth names where a bare P/E looks optically expensive.",
        "reference": "cheap <1.0 · fair 1.0–2.0 · rich >2.0",
        "bands": (1.0, 2.0),
        "higher_cheaper": False,
        "unit": "",
    },
    "ps": {
        "label": "P/S",
        "family": "Equity multiples",
        "advantages": "Works even when earnings are negative; revenue is harder to "
                      "manipulate than net income.",
        "limitations": "Ignores margins and capital structure entirely — a low P/S "
                       "can hide a broken cost base.",
        "when_to_use": "Early-stage / turnaround / cyclical names with depressed or "
                       "absent profits.",
        "reference": "cheap <2× · fair 2–5× · rich >5×",
        "bands": (2.0, 5.0),
        "higher_cheaper": False,
        "unit": "x",
    },
    "pb": {
        "label": "P/B",
        "family": "Equity multiples",
        "advantages": "Anchored to balance-sheet equity; a natural fit for asset-heavy "
                      "and financial businesses.",
        "limitations": "Book value understates intangible-heavy / asset-light firms; "
                       "buybacks below book distort it.",
        "when_to_use": "Banks, insurers, REITs and other book-value-driven models.",
        "reference": "cheap <1.5× · fair 1.5–3× · rich >3×",
        "bands": (1.5, 3.0),
        "higher_cheaper": False,
        "unit": "x",
    },
    "earnings_yield": {
        "label": "Earnings yield",
        "family": "Equity multiples",
        "advantages": "P/E inverted into a %, directly comparable to bond yields and "
                      "the cost of capital.",
        "limitations": "Same earnings-quality caveats as P/E; negative when the firm "
                       "loses money.",
        "when_to_use": "Cross-asset comparison — is the equity out-yielding the "
                       "risk-free rate?",
        "reference": "cheap >8% · fair 4–8% · rich <4%",
        "bands": (4.0, 8.0),
        "higher_cheaper": True,
        "unit": "%",
    },
    # ---- Enterprise (capital-structure neutral; compare across leverage) ----
    "ev_sales": {
        "label": "EV/Sales",
        "family": "Enterprise multiples",
        "advantages": "Capital-structure neutral revenue multiple; usable when EBITDA "
                      "or earnings are negative.",
        "limitations": "Blind to profitability — pairs best with a gross-margin check.",
        "when_to_use": "High-growth / pre-profit names, or margin-normalising peers.",
        "reference": "cheap <2× · fair 2–5× · rich >5×",
        "bands": (2.0, 5.0),
        "higher_cheaper": False,
        "unit": "x",
    },
    "ev_ebitda": {
        "label": "EV/EBITDA",
        "family": "Enterprise multiples",
        "advantages": "Neutral to leverage and D&A policy — the standard for comparing "
                      "peers with different debt.",
        "limitations": "Ignores capex intensity and interest; flatters capital-heavy "
                       "businesses.",
        "when_to_use": "Cross-peer / cross-border comparison of operating value.",
        "reference": "cheap <10× · fair 10–15× · rich >15×",
        "bands": (10.0, 15.0),
        "higher_cheaper": False,
        "unit": "x",
    },
    "ev_ebit": {
        "label": "EV/EBIT",
        "family": "Enterprise multiples",
        "advantages": "Charges depreciation as the real cost it is — the Magic-Formula "
                      "cheapness gauge.",
        "limitations": "Sensitive to depreciation policy; distorted for firms with "
                       "large non-operating items.",
        "when_to_use": "Capex-heavy businesses where EBITDA overstates cash earnings.",
        "reference": "cheap <12× · fair 12–18× · rich >18×",
        "bands": (12.0, 18.0),
        "higher_cheaper": False,
        "unit": "x",
    },
    "fcf_ev": {
        "label": "FCF/EV",
        "family": "Enterprise multiples",
        "advantages": "Free-cash-flow yield on the whole enterprise — the hardest, "
                      "least gameable cheapness read.",
        "limitations": "Lumpy for cyclical capex; a single heavy-investment year can "
                       "depress it misleadingly.",
        "when_to_use": "Mature cash generators; the final sanity check on a buy case.",
        "reference": "cheap >6% · fair 3–6% · rich <3%",
        "bands": (3.0, 6.0),
        "higher_cheaper": True,
        "unit": "%",
    },
}


def families() -> dict[str, list[str]]:
    """Ordered {family_label: [metric_id, ...]} — the render order for the card."""
    return {fam: list(ids) for fam, ids in FAMILIES.items()}


def entry(metric_id: str) -> dict | None:
    """Static glossary entry for a metric id, or None if unknown."""
    return GLOSSARY.get(metric_id)


def band_for(metric_id: str, value) -> str | None:
    """Classify a metric value as 'cheap' | 'fair' | 'rich'.

    Returns None when the metric is unknown or the value is missing / non-positive
    (a negative multiple signals losses, not cheapness — never call it 'cheap')."""
    g = GLOSSARY.get(metric_id)
    if g is None or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v != v or v <= 0:  # NaN or non-positive
        return None
    lo, hi = g["bands"]
    if g["higher_cheaper"]:
        # bigger = cheaper (yields): >hi cheap, <lo rich
        return "cheap" if v > hi else ("rich" if v < lo else "fair")
    # smaller = cheaper (ratios): <lo cheap, >hi rich
    return "cheap" if v < lo else ("rich" if v > hi else "fair")
