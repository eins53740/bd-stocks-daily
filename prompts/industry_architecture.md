# Prompt — Industry business architecture

Third section of `_industry/<slug>.md`. Runs only on refresh. Assumes macro +
customer sections exist.

Substitutions: `{INDUSTRY}`, `{MACRO_OUTPUT}`, `{CUSTOMER_OUTPUT}`

```
ROLE: Senior sector analyst completing a deep industry dive.

INDUSTRY: {INDUSTRY}

CONTEXT: Already analysed (do not repeat unless required for logic):
- Macro: {MACRO_OUTPUT}
- Customer ops: {CUSTOMER_OUTPUT}

OBJECTIVE: Explain the business architecture — how companies compete, how they
monetise, what drives dominance, what metrics matter.

COVER:
1. Dominant business models — what dominates today, how companies make money.
2. Disruptive models — emerging models challenging incumbents; why they are winning
   (cost structure, speed, distribution, tech).
3. Competitive moats — which moats matter here (scale, data, regulation,
   distribution, switching costs).
4. KPIs and excellence — top 15 KPIs with benchmark ranges for best-in-class.
5. Ecosystem enablers — tools, platforms, certifications, infrastructure.
6. Regulation and norms — how compliance constraints shape go-to-market.

OUTPUT REQUIREMENTS:
- Table: "Business Model | Revenue Driver | Cost Base | Typical Margins | Risks".
- KPI dashboard list (top 15 KPIs with benchmark ranges).
- Incumbent vs Disruptor comparison matrix.
- 1-page strategic cheat sheet at the end (bulleted, scannable).
- Separate Operator lens (execution benchmarks, workflow KPIs) from Investor
  lens (moat strength, profit-pool concentration).

{STYLE_RULES}
```
