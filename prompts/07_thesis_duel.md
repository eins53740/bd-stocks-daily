# Prompt 07 — Thesis duel (bull vs bear, and which one leads)

Feeds the **§0 thesis card** at the top of the deep report. Runs in Phase 2.5,
**after** `01_business_model.md` (bull material) and `05_bear_case.md` (bear
material) — it judges their output, it does not re-derive it.

Substitutions: `{COMPANY}`, `{TICKER}`, `{NUMBERS_JSON}`, `{BULL_THESIS}`,
`{BEAR_CASE}`, `{MOAT_JSON}` (the `scores.moat` value + `score_details.moat`
block), `{SECTOR}`, `{INDUSTRY_CACHE}` (the `_industry/<slug>.md` body).

**The lean is narrative only. It never enters the composite, never moves the
verdict, and is never rendered as a percentage** — see the RULES block for why.

```
ROLE: Investment committee chair. Two analysts have argued opposite sides of the
same stock. Your job is to state which case is currently better supported by the
evidence, and to be honest when neither is.

COMPANY: {COMPANY} ({TICKER})
SECTOR: {SECTOR}

BULL CASE:
{BULL_THESIS}

BEAR CASE:
{BEAR_CASE}

MOAT DATA (deterministic, computed — do not recompute):
{MOAT_JSON}

INDUSTRY CONTEXT:
{INDUSTRY_CACHE}

NUMBERS (ground truth — every figure you cite must come from here):
{NUMBERS_JSON}

TASK — produce exactly these five blocks, nothing else:

1. MOAT (2–3 sentences, lead with the source of the moat)
   Name the specific mechanism — switching costs, scale economics, network
   effect, regulatory licence, brand, cost curve position. Say what would have
   to happen for it to erode, and roughly over what horizon.
   Anchor to the computed moat score and ROIC given above; do not invent a
   different score. If the numbers say the moat is weak, say so plainly — a high
   ROIC with no identifiable mechanism is a windfall, not a moat, and you should
   name it as such.

2. BULL — three lines, each one sentence:
   CLAIM: the core reason this compounds.
   IF-RIGHT: what the business looks like in 3–5 years.
   NEEDS: the single condition that must hold for the claim to work.

3. BEAR — three lines, same shape:
   CLAIM: the core reason this loses money.
   IF-RIGHT: what the business looks like in 3–5 years.
   TRIGGER: the observable event that would confirm it.

4. LEAN — exactly one of: BULL | BEAR | BALANCED
   Then one sentence, maximum 40 words, saying which piece of evidence decided
   it. Cite a number from the JSON in that sentence.
   Choose BALANCED when the cases rest on genuinely unresolvable unknowns
   (a binary regulatory outcome, an unproven technology, a pending court case).
   BALANCED is a legitimate answer and is expected reasonably often. Do NOT lean
   BULL merely because the composite score is high — the score already reflects
   the numbers, and repeating it here adds nothing.

5. SECTOR CONTEXT — 2–3 sentences.
   Describe the structural forces acting on {SECTOR} over a 3–5 year horizon and
   state whether they currently work for or against this company. Name the
   driver (demand shift, regulation, capex cycle, substitution, consolidation)
   and say what would reverse it.
   Do NOT answer yes/no. A sector is not "tailwind: yes" — it is a set of forces
   with a direction, a strength and a reversal condition, and collapsing that to
   a flag throws away the part you would actually act on.
   If the industry cache is stale or absent, say "sector context unavailable
   (industry cache {age})" rather than reasoning from memory.

RULES:
- Never output a probability, a percentage or odds for the lean. You have no
  calibration data and no way to score yourself, so a "70% bull" would be a
  number that looks like evidence while carrying none. The direction is the
  honest resolution; the confidence is not yours to quantify.
- The lean is commentary. It must not contradict the deterministic verdict, and
  if it does, say so explicitly in the LEAN sentence — a disagreement between
  the numbers and the narrative is information, not an error to hide.
- Every claim traces to a number in the JSON or is marked "(inferred)".
- No new figures. If it is not in the JSON, it is "not available".

{STYLE_RULES}
```
