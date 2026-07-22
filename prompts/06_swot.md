# Prompt 06 — SWOT (Threats/Risks-weighted)

Feeds the deep-dive SWOT card. Runs in Phase 2.5, AFTER `05_bear_case.md` (so
the Threats-Risks quadrant can lean on the bear trigger + the red-flag scanner).
Overlay-only narrative — it produces NO number that enters the composite.

Substitutions: `{COMPANY}`, `{TICKER}`, `{NUMBERS_JSON}`, `{RED_FLAGS_JSON}`,
`{BULL_THESIS}` (the `red_flags` block is the merged output of `red_flags.py`,
node 2.4; `{BULL_THESIS}` derives from §2.1 + wrap-up + the TL;DR thesis line).

```
ROLE: Buy-side analyst writing a disciplined SWOT for a long-term (1–5 yr) hold.

COMPANY: {COMPANY} ({TICKER})

INPUTS:
- Numbers (ground truth): {NUMBERS_JSON}
- Red-flag scanner + Beneish + statement sub-scores: {RED_FLAGS_JSON}
- Bull thesis: {BULL_THESIS}

TASK: Produce a four-quadrant SWOT. The Threats/Risks quadrant is the most
important: give it DOUBLE the depth of the others and place it FIRST in the
output. Internal factors = Strengths / Weaknesses; external factors =
Opportunities / Threats-Risks.

COVER per quadrant:
- THREATS / RISKS (lead, deepest): the external and downside forces that could
  impair the thesis — competitive, regulatory, macro, disruption, customer
  concentration. Explicitly reconcile with the red-flag scanner: name every
  scanner flag that is `bad` or `warn`, and the Beneish verdict. Cross-link the
  3-Layer Risk Audit and the Bear case (do not repeat them verbatim — add the
  external-threat lens they miss).
- STRENGTHS: durable competitive advantages, evidenced by the numbers (margins,
  ROIC/ROCE, net-payout yield, balance-sheet quality).
- WEAKNESSES: internal, fixable-or-not soft spots (the `warn`/`bad` items that
  are company-internal — leverage, margin trend, cash conversion).
- OPPORTUNITIES: realistic upside optionality (TAM, pricing, capital allocation).

OUTPUT (strict format):
- Four `### ` sub-headings in this order: `### Threats / Risks`, `### Strengths`,
  `### Weaknesses`, `### Opportunities`.
- Under each, 3–6 bullets (Threats/Risks may run to 8). Every factual claim ends
  with the number that supports it in parentheses, e.g. "(Net debt/EBITDA 4.6×)",
  or is tagged `(inferred)` when it is judgement, not a figure in the inputs.
- No score, no verdict line — this is a qualitative overlay, not a rating.

RULES:
- Ground-truth rule: every number you cite must come from the inputs above —
  never invent a figure. Narrative/opinion is allowed but must be tagged
  `(inferred)`.
- Be specific and balanced; no boilerplate.

{STYLE_RULES}
```
