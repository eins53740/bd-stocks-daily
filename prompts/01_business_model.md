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

**REQUIRED Sankey block** (appended at the end of the §2.1 narrative — Mermaid `sankey-beta`). Values are TTM in the company's reporting currency, in millions; round to the nearest 100M for readability. **In-flow** (source of funds — Revenue) enters on the left; **out-flows** (uses — COGS, R&D, SG&A, Other OpEx, Interest & Tax, capex) exit on the right; value-creation nodes (Gross Profit → Operating Income → Net Income → Retained Earnings) form the spine through the middle. Net Income then splits into Dividends + Buybacks + Retained Earnings when those allocations are disclosed; if FCF / capex are disclosed, branch Operating Income → Capex (cost) and the residual toward FCF.

#### Colours: do NOT try to set them — v4.3, measured

**`sankey.nodeColors` is not a Mermaid API.** The string does not appear anywhere in
mermaid 11.12's distribution, which is the version behind both mermaid-cli and Obsidian's
bundled renderer. Until v4.3 this prompt asserted the opposite, so every diagram carried a
15-line config map that did nothing, plus a mandatory colour legend describing a palette the
reader never saw — verified against `2026-08-12_FAE.MC_review.md`, which emits the full map
and still renders in the default hues. `themeVariables.cScale0..N` was tested as an
alternative and is ignored for sankey too: node colours come from a hard-coded d3 scheme.

So: **emit no colour config and no colour legend.** The HTML report's caption says the hues
carry no meaning and the diagram reads left to right, which is true. Say nothing you cannot
show.

- `showValues` and `linkColor` **are** honoured; keep the two-key config header below.
- Meaning is carried by **position and width**, not hue: Revenue enters left, costs leave
  the spine, the spine narrows to Net Income, allocation splits at the right.

Template (replace placeholders; the config header is two keys, nothing more):

````markdown
```mermaid
---
config:
  sankey:
    showValues: true
    linkColor: gradient
---
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
Operating Income,Capex,{capex}
Operating Income,Net Income,{net_income}
Net Income,Dividends,{div}
Net Income,Buybacks,{buyback}
Net Income,Retained Earnings,{retained}
```
````

Notes on the template:
- Drop any flow line whose value is `(not disclosed)` — never emit a flow with a blank or
  invented value, and never balance a diagram with a plug figure.
- The `Operating Income,Capex` branch is optional: include it only when capex is disclosed.
- Keep the diagram body as bare `source,target,value` CSV rows after the `sankey-beta` line.
- Source caption, TTM basis, millions rounding, and the `(annual report p.X)` /
  `(not disclosed)` tagging rules are unchanged.

After the diagram, add a one-line caption. **No colour legend** — see above.
> *Cada euro de receita transforma-se em ~{net_margin_pct}% de net income; o maior dreno é {biggest_cost_bucket} ({biggest_cost_pct}%).*

{STYLE_RULES}
```
