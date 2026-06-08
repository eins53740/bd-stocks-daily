# Prompt 01 — Business model (money engine)

Feeds deep-dive §2.1. Runs in Phase 2.5.

Substitutions:
- `{COMPANY}` — analyze_ticker JSON `company_name`
- `{TICKER}` — analyze_ticker JSON `ticker`
- `{NUMBERS_JSON}` — the full analyze_ticker JSON (source of truth for figures)
- `{ANNUAL_NARRATIVE}` — Phase 4 WebFetch on the annual report PDF

```
ROLE: Senior equity analyst.

COMPANY: {COMPANY} ({TICKER})

TASK: Explain how this company actually makes money.

COVER:
1. What it sells and who buys (customer type, decision process, why they pay).
2. Revenue model: recurring vs one-off vs hybrid; geographic and segment mix if material.
3. Gross margin profile and main cost drivers.
4. Business simplicity: simple, complex, project-based, or cyclical?
5. One-sentence money engine: how cash actually flows through this business.
6. **Money-flow Sankey diagram** — see required block below. Use figures from {NUMBERS_JSON}; if a sub-line (R&D, SG&A, COGS split) is not in the JSON, take it from {ANNUAL_NARRATIVE} and tag the value with `(annual report p.X)`. If neither is available, mark `(not disclosed)` and skip that branch — never invent.

INPUTS (ground truth — do not invent numbers beyond these):
- analyse_ticker JSON: {NUMBERS_JSON}
- Annual report narrative: {ANNUAL_NARRATIVE}

RULES:
- Use only official filings and investor materials (annual report, IR decks, 10-K/20-F).
- Mark anything inferred as (inferred).
- No speculation, no valuation (that lives in §2.9).

OUTPUT: 300–500 words. Clear sections. Cite sources (annual report page or IR URL).

**REQUIRED Sankey block** (appended at the end of the §2.1 narrative — Mermaid `sankey-beta`). Values are TTM in the company's reporting currency, in millions; round to the nearest 100M for readability. Source-of-funds (Revenue) on the left flows into uses (COGS, R&D, SG&A, Other OpEx, Tax, Net Income). Net Income then splits into Dividends + Buybacks + Retained Earnings when those allocations are disclosed.

**Colour convention** (mermaid sankey-beta colours links by source automatically — the convention is enforced strictly only when render_charts.py emits a PNG version of the diagram):
- 🔴 Red — cost flows: COGS, R&D, SG&A, Other OpEx, Interest & Tax.
- 🟢 Green — profit flows: Gross Profit, Operating Income, Net Income, Retained Earnings.
- 🟡 Yellow/orange — capital allocation: Dividends, Buybacks.
- 🔵 Blue — neutral input: Revenue.

Reference rendering: `IMG/sankey_money_engine_demo.png` (illustrative SaaS example, 25% net margin) in the StocksDaily docs folder.

Template (replace placeholders, keep the comment lines):

````markdown
```mermaid
sankey-beta

%% Money engine — TTM, {currency} M
%% Source: analyse_ticker JSON + annual report p.X
Revenue,COGS,{cogs}
Revenue,Gross Profit,{gross_profit}
Gross Profit,R&D,{rd}
Gross Profit,SG&A,{sga}
Gross Profit,Other OpEx,{other_opex}
Gross Profit,Operating Income,{op_income}
Operating Income,Interest & Tax,{int_tax}
Operating Income,Net Income,{net_income}
Net Income,Dividends,{div}
Net Income,Buybacks,{buyback}
Net Income,Retained Earnings,{retained}
```
````

After the diagram, add a one-line caption:
> *Cada euro de receita transforma-se em ~{net_margin_pct}% de net income; o maior dreno é {biggest_cost_bucket} ({biggest_cost_pct}%).*

{STYLE_RULES}
```
