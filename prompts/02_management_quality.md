# Prompt 02 — Management quality

Feeds deep-dive §2.3. Runs in Phase 2.5. The numeric score this prompt emits
feeds back into the composite score via `finalize_score.py`.

Substitutions:
- `{COMPANY}`, `{TICKER}`, `{NUMBERS_JSON}`
- `{ANNUAL_NARRATIVE}` — CEO letter + management discussion
- `{QUARTERLY_NARRATIVE}` — latest quarterly report
- `{SHAREHOLDER_JSON}` — `shareholder_structure` block from analyze_ticker.py (insider %, institutional %, recent insider transactions). v2.1+.

```
ROLE: Buy-side analyst evaluating management behaviour.

COMPANY: {COMPANY} ({TICKER})

TASK: Assess whether management will compound or destroy capital.

EVALUATE (with evidence from filings, letters, transcripts if available):
1. Integrity: do they tell the truth in tough times? (Look for clear
   acknowledgement of misses, not just celebrations of wins.)
2. Long-term thinking: do they sacrifice short-term EPS for durable value?
3. Capital allocation: reinvestment, buybacks, M&A discipline — smart or empire-building?
   Cross-check with the JSON: buyback history (`capital_returns.buybacks_ttm`),
   dilution trend (`capital_returns.shares_change_5y_pct`), ROIC level (`fundamentals.roic_ttm`).
4. Communication: clear and honest, or jargon and spin?
5. Execution: promises vs results over 3–5 years.
6. **Roster & skin in the game** (Borja #5, v2.1+): name CEO + CFO + tenure from
   the annual narrative; cross-check insider ownership and recent insider
   transactions from `{SHAREHOLDER_JSON}`. Flag explicitly:
   - Insider ownership < 1% on a founder-era company → "skin-in-the-game gap"
   - Net insider selling > $10M in last 12 months → "insider distribution flag"
   - Comp package heavily skewed to short-dated equity / RSUs with no
     performance vest → "comp-vs-performance misalignment"
   These flags are evidence to lower the score, not automatic disqualifiers.

INPUTS:
- analyse_ticker JSON: {NUMBERS_JSON}
- Shareholder structure JSON: {SHAREHOLDER_JSON}
- Annual narrative: {ANNUAL_NARRATIVE}
- Quarterly narrative: {QUARTERLY_NARRATIVE}
- Earnings-call transcripts are NOT available. If an item requires transcript
  evidence you do not have, mark it "(assumption — evidence gap)" and lower
  confidence in the final score.

OUTPUT (strict format — downstream scripts parse this):
  Management Quality Score: X.X/10
  **Named roster**: CEO {name} (tenure {years}), CFO {name} (tenure {years}); insider ownership {pct}%.
  One-paragraph verdict (3–5 sentences) with key evidence cited.
  If below 7/10, prefix the verdict with "PROCEED WITH CAUTION:"

RULES:
- Use only official sources (letters, calls, filings, insider transactions).
- No opinions — behaviour patterns only.
- The numeric score must be on its own line, format "Management Quality Score: X.X/10".

{STYLE_RULES}
```
