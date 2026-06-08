# Prompt 03a — Growth decomposition

Feeds first half of deep-dive §2.7. Runs in Phase 2.5.

Substitutions: `{COMPANY}`, `{TICKER}`, `{NUMBERS_JSON}`, `{ANNUAL_NARRATIVE}`

```
ROLE: Fundamentals-driven analyst.

COMPANY: {COMPANY} ({TICKER})

TASK: Break down where revenue growth actually came from over the last 5–7 years.

INPUTS:
- analyse_ticker JSON (revenue_cagr_5y, revenue stability, lynch_category already computed): {NUMBERS_JSON}
- Annual narrative (segment revenue, volume/price commentary): {ANNUAL_NARRATIVE}

DECOMPOSE INTO:
- Volume growth (new customers, usage, geography).
- Price / mix (real pricing power or inflation pass-through?).
- Acquisitions (organic vs inorganic — cite deal names + year if possible).

FOR EACH SOURCE:
- Classify as Structural (repeatable) or Temporary (cycle, one-off, reset).
- Cite evidence from filings (page or section).

OUTPUT:
- Executive summary (5–7 bullets).
- Detailed breakdown by lever (300–500 words total).

RULES: No valuation. No forecasts. Evidence only.

{STYLE_RULES}
```
