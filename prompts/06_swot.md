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

OUTPUT (strict format) — this fills the four cells of the §2.18a 2×2 table, so
emit the CELL CONTENTS, not headings. One block of text per quadrant, in the
order Threats/Risks, Strengths, Weaknesses, Opportunities.

Inside a cell, write 3-6 separate items (Threats/Risks may run to 8), each on its
own line separated by `<br>` — a literal `<br>`, which is what renders as a line
break inside both an Obsidian table cell and the HTML report.

Every item starts with its MATERIALITY TAG and follows this shape:

  **MATERIAL** — claim, with the number that supports it (ROIC 27.66%)<br>
  *minor* — claim, with its number (share count +3.40% 5y)<br>

- **MATERIAL** means: this would change the VERDICT or the POSITION SIZE. If it
  would do neither, it is `*minor*`. Apply the test to each item honestly — a
  SWOT where everything is material ranks nothing, and one where nothing is
  material says the analysis found no reason to act.
- Every factual claim ends with the number that supports it in parentheses, e.g.
  "(Net debt/EBITDA 4.6×)", or is tagged `(inferred)` when it is judgement rather
  than a figure in the inputs.
- No score, no verdict line — this is a qualitative overlay, not a rating.

RULES:
- Ground-truth rule: every number you cite must come from the inputs above —
  never invent a figure. Narrative/opinion is allowed but must be tagged
  `(inferred)`.
- Every scanner flag that is `bad` or `warn` in {RED_FLAGS_JSON} must appear
  somewhere in Threats/Risks or Weaknesses. A statement check the scanner failed
  cannot be absent from the SWOT — that is the specific gap this rule closes.
- Be specific and balanced; no boilerplate.

{STYLE_RULES}
```
