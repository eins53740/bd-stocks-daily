# Prompt — Industry macro dynamics

Feeds the macro section of `_industry/<slug>.md`. Runs only when the cache is
missing or stale (Phase 1.5 → refresh path).

Substitutions: `{INDUSTRY}` (sector name from analyze_ticker JSON)

```
ROLE: Senior sector analyst.

INDUSTRY: {INDUSTRY}

OBJECTIVE: Map the macro structure and deep dynamics of this industry from a
strategic, structural, and operational lens (not a financial investor lens).

COVER:
1. Market overview — market size today, expected CAGR 5–10y, main demand drivers.
2. Segmentation — by use case, customer type, technology, geography. Which
   segments matter most and why.
3. Value chain — full chain from raw inputs to end user. Where margins and power concentrate.
4. Key players — typical players at each layer; global leaders, regional challengers, emerging disruptors.
5. Long-term trends — technology, regulation, sustainability, customer behaviour.
6. Historical disruptions — major milestones that changed the industry, timeline + dates.

OUTPUT REQUIREMENTS:
- Structured headings, bullet lists, tables where helpful.
- Include credible sources and URLs at the end (5–10 sources).
- Numbers where possible (market size, CAGR, major shares) with year + source.
- Provide a value-chain diagram in text (layered list).
- Provide a table: "Layer → Major Players → Role → Profit Pool".
- Provide an Industry Map Table: "Segment | Customer | Product | Key KPI | Winner Profile | Risk".
- End with a 10-bullet executive summary.
- End with an AI DISRUPTION section: which parts of the value chain get automated,
  which roles shrink, which roles become more valuable, what new entrants become possible.

{STYLE_RULES}
```
