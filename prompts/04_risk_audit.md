# Prompt 04 — 3-Layer Risk Audit

Feeds deep-dive §2.11. Runs in Phase 2.5. Replaces the flat bullet list that
used to live at §2.9.

Substitutions: `{COMPANY}`, `{TICKER}`, `{NUMBERS_JSON}`, `{ANNUAL_NARRATIVE}`, `{QUARTERLY_NARRATIVE}`

```
ROLE: Tri-disciplinary risk analyst (business / credit / industry strategist).

COMPANY: {COMPANY} ({TICKER})

INPUTS:
- analyse_ticker JSON: {NUMBERS_JSON}
- Annual narrative: {ANNUAL_NARRATIVE}
- Quarterly narrative: {QUARTERLY_NARRATIVE}

TASK: Produce a 3-layer risk audit. Each layer has its own sub-prompt.

LAYER 1 — OPERATIONAL (business analyst lens)
Cover: customer risk, growth risk, margin risk, moat risk.
For each: (a) mechanism (how it breaks), (b) evidence (is it already happening?),
(c) leading indicator to monitor.
Output: ranked risk table (3–5 rows) + 300-word analysis.

LAYER 2 — FINANCIAL (credit analyst lens)
Cover: leverage (net debt vs FCF, interest coverage, maturities), liquidity
(cash buffers, working capital swings), dilution (share count, SBC), capital
allocation discipline.
Output:
  Financial Risk Score: Low / Medium / High
  Key vulnerability (one line)
  What breaks first if conditions worsen?
If the balance sheet is strong, say so clearly and briefly.

LAYER 3 — STRUCTURAL / EXTERNAL (industry strategist lens)
Cover: regulation, technology disruption, industry power (consolidation,
pricing pressure, supplier/customer leverage), geopolitics, long-cycle demand shifts.
Output: top 3–5 structural risks ranked by likelihood × severity, each with
"already happening?" flag + signal that would confirm it's becoming material.

AI DISRUPTION CALLOUT (2 lines):
Which part of this risk map is amplified or suppressed by AI?

RULES: Use only official sources. Rank, don't enumerate. No generic risks
("competition exists") unless you can name the mechanism.

{STYLE_RULES}
```
