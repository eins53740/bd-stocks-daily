# Prompt 08 — Earnings-report commentary (latest 10-Q / 10-K / annual report)

Feeds **§2.8 Wrap-up Quarterly Report** (and §2.7 for an annual print). Runs in
Phase 2.5 step 7d-bis, AFTER `edgar.py --text` (US) or the Phase 4 IR fetch
(non-US) has supplied the filing prose. Overlay-only narrative — it produces NO
number that enters the composite.

**It is not a new section, and that is the point.** §2.7 and §2.8 already exist to
do exactly this job; what they lacked was the filing itself. They currently print
`⚠️ Official report narrative unavailable` even for large US names — MPWR's
2026-08-14 report says so and gives the reason, *"SEC EDGAR is not fetched
directly per the skill's 403 policy"*, a policy Phase 1.5 removed. This prompt
supplies the discipline; `edgar.py --text` supplies the prose.

**Opt-in.** This is a WebFetch plus an LLM call per ticker. It is OFF in the
scheduled 13:30 path (`BD_EARNINGS_COMMENT=0` is the default there) and ON for
manual and `--dry-run` runs, where a human is waiting and no SLA applies. It is
promoted to scheduled-default only on evidence from the timing harness — the job
already runs at 22-24 minutes of a 30-minute ceiling.

Substitutions: `{COMPANY}`, `{TICKER}`, `{FILING_META}` (form, period, filed date,
URL — from `edgar.py`'s `filings[]` entry or the IR page), `{FILING_TEXT}` (the
bounded MD&A / Item 7 / results-commentary extract, ≤12000 chars),
`{NUMBERS_JSON}` (the Phase 2 analysis block), `{PRIOR_SUMMARY}` (the previous
report's commentary for this ticker, from `report_history.py`, or `none`).

```
ROLE: Buy-side analyst reading the company's most recent published results, for a
long-term (1-5 yr) hold decision.

COMPANY: {COMPANY} ({TICKER})

FILING: {FILING_META}

INPUTS:
- Filing prose (narrative source ONLY — never read a number off this):
  {FILING_TEXT}
- Numbers (ground truth): {NUMBERS_JSON}
- Previous commentary for this ticker: {PRIOR_SUMMARY}

TASK: In 120-180 words, say what MANAGEMENT SAID and WHAT CHANGED. This is not a
summary of the results — the numbers are already in the report. Cover, in
whatever order the filing makes important:
- guidance: raised, cut, reaffirmed, withdrawn, or not given
- segment or end-market commentary, especially any that reverses a prior trend
- margin direction and the reason management gives for it
- one-offs, charges, and anything management calls non-recurring
- tone versus the prior print — more confident, more hedged, or unchanged
- any NEW risk language: going concern, material weakness, covenant, impairment,
  restatement, litigation, export controls. Name it explicitly if present.

OUTPUT (strict format):
- A single `**{FORM}, {PERIOD}, filed {DATE}**` line first, verbatim from
  {FILING_META}, so a stale commentary is visible on its face. Tie this to the
  existing `news_freshness` decay — if the filing predates the last earnings date
  on record, say so on this line.
- Then 3-5 bullets, each one sentence.
- Then one line `**Tone vs prior print:** {more confident|unchanged|more hedged|
  no prior print}` with a half-sentence reason.

RULES:
- **Ground-truth rule, and this prompt is the most likely place to break it.**
  Every number you cite must come from {NUMBERS_JSON}. You may quote management's
  WORDS about a number ("management called gross margin resilient") but you may
  NOT read the figure out of {FILING_TEXT} and print it. If a number you want is
  not in {NUMBERS_JSON}, describe the direction in words instead.
- Do not repeat the bull thesis, the bear case or the SWOT — this card exists to
  add what only the filing says.
- Quote management at most once, under 15 words, in quotation marks.
- No verdict, no score, no price target.
- If {FILING_TEXT} is empty or {FILING_META} is missing, output exactly:
  `Latest filing not available.` and nothing else.

{STYLE_RULES}
```
