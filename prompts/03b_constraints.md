# Prompt 03b — Constraint analysis (Theory of Constraints)

Feeds middle of deep-dive §2.7. Runs in Phase 2.5 immediately after 03a.

Substitutions: `{COMPANY}`, `{TICKER}`, `{NUMBERS_JSON}`, `{03A_OUTPUT}`

```
ROLE: Operations strategist applying Theory of Constraints.

COMPANY: {COMPANY} ({TICKER})

CONTEXT: The growth decomposition produced:
{03A_OUTPUT}

TASK: Identify what currently limits growth.

ANSWER:
1. What is the ONE bottleneck limiting growth today? (supply, capacity, talent,
   sales-cycle length, regulation, capital, customer adoption, ...)
2. Why is it binding? (Evidence from JSON or filings.)
3. Which growth driver does it constrain (volume / price / mix)?
4. If removed, what becomes the NEXT constraint?
5. Is the bottleneck internal (controllable) or external (structural)?

OUTPUT: Constraint hierarchy (ranked table of top 3) + 250-word explanation.

RULES: This is NOT a risk list. Rank by impact on growth, not by severity of the
business continuing as a going concern. Risk list is §2.11.

{STYLE_RULES}
```
