# Prompt 05 — Bear case

Feeds deep-dive §2.12. Runs in Phase 2.5. The final line becomes frontmatter
field `bear_case_trigger`.

Substitutions: `{COMPANY}`, `{TICKER}`, `{NUMBERS_JSON}`, `{BULL_THESIS}`
(derive `{BULL_THESIS}` from §2.1 + §2.7 outputs + TL;DR thesis line)

```
ROLE: Devil's advocate trying to invalidate this investment.

COMPANY: {COMPANY} ({TICKER})

BULL THESIS (to be destroyed):
{BULL_THESIS}

TASK: Write the strongest case for why this stock is a bad long-term investment.

COVER:
1. Main failure mode — the single most likely way to lose money.
2. Structural weaknesses — what is hard to fix in the business model?
3. Key assumptions that might not hold.
4. What could permanently impair earnings or cash flow?
5. Why investors might be fooling themselves (narrative traps, misleading metrics).
6. Evidence that would prove the bear case right.

OUTPUT (strict format):
- 1-page memo (400–600 words), dense prose.
- FINAL LINE must be, verbatim format: "If {X} happens, the thesis is broken."
  (Downstream script parses this line into frontmatter `bear_case_trigger`.)
  Replace {X} with the concrete trigger, not a generic placeholder.

RULES:
- Use only official sources.
- No softening — be direct.
- This is intellectual honesty, not pessimism.

{STYLE_RULES}
```
