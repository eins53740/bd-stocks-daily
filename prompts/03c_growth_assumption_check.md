# Prompt 03c — Growth assumption validation

Feeds end of deep-dive §2.7. Runs in Phase 2.5 after 03a + 03b.

Substitutions: `{COMPANY}`, `{TICKER}`, `{NUMBERS_JSON}`, `{GROWTH_ASSUMPTION}`
(derive `{GROWTH_ASSUMPTION}` from JSON: "revenue_cagr_5y" historic rate + 5y duration)

```
ROLE: Sceptical long-term investor.

COMPANY: {COMPANY} ({TICKER})

GROWTH ASSUMPTION (implicit in the DCF and Peer scoring):
{GROWTH_ASSUMPTION}

TASK: Test this assumption against reality.

CHECK AGAINST:
1. Company's own history — when did it achieve similar growth? What stopped it?
2. Competitor behaviour — did peers sustain this rate? What broke?
3. Constraint alignment — do the limits identified in 03b allow this rate for this duration?

OUTPUT:
- Verdict: one of "Supported" / "Weakly supported" / "Not supported"
- Which part is most fragile: rate, duration, or drivers?
- What must go right for the assumption to hold?

RULE: Do NOT adjust the assumption to make it work. Be explicit.

{STYLE_RULES}
```
