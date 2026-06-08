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

**REQUIRED Sankey block** (appended at the end of the §2.1 narrative — Mermaid `sankey-beta`). Values are TTM in the company's reporting currency, in millions; round to the nearest 100M for readability. **In-flow** (source of funds — Revenue) enters on the left; **out-flows** (uses — COGS, R&D, SG&A, Other OpEx, Interest & Tax, capex) exit on the right; value-creation nodes (Gross Profit → Operating Income → Net Income → Retained Earnings) form the green spine through the middle. Net Income then splits into Dividends + Buybacks + Retained Earnings when those allocations are disclosed; if FCF / capex are disclosed, branch Operating Income → Capex (cost) and the residual toward FCF.

#### Standardised colour palette (apply to EVERY diagram — no exceptions)

Mermaid `sankey-beta` colours links **by their source node** when `linkColor: source` is set, and node colours are assigned with a `sankey.nodeColors` map in the diagram's YAML config header. Use exactly these hex values so diagrams are visually consistent across sectors:

| Category | Nodes | Hex | Swatch |
|----------|-------|-----|--------|
| **Revenue / in-flow** (neutral source) | Revenue | `#2563eb` | 🔵 blue |
| **Value-creation & profit** (RESERVED — green only) | Gross Profit, Operating Income, Net Income, FCF, Retained Earnings | `#16a34a` | 🟢 green |
| **Operating costs** | COGS, R&D, SG&A, Other OpEx | `#dc2626` | 🔴 red |
| **Interest & Tax** (non-operating drains) | Interest & Tax | `#b45309` | 🟤 amber-brown |
| **Capex / investment out-flow** | Capex | `#7c3aed` | 🟣 purple |
| **Capital allocation** (returns to holders) | Dividends, Buybacks | `#ca8a04` | 🟡 gold |

Rules:
- **Green is reserved strictly for value-creation & profit metrics** (Gross Profit, Operating Income, Net Income, FCF, Retained Earnings). Never colour a cost or a payout green.
- Costs are warm (red operating / amber interest-tax); capital uses are cool-distinct (purple capex, gold shareholder returns); the lone neutral input is blue.
- Keep flows left→right: Revenue (in) → profit spine (green) → out-flows (red/amber/purple/gold).
- `linkColor: source` makes every link inherit its source node's colour, so a flow *out of* Gross Profit is green, a flow *into* COGS is red, etc. — this is what enforces the palette visually.
- Source caption, TTM basis, millions rounding, and the `(annual report p.X)` / `(not disclosed)` tagging rules are unchanged.

The diagram is valid `sankey-beta` and renders in Obsidian's bundled Mermaid (v11+). `nodeColors` is the official Mermaid API for pinning node hex; some renderer versions still fall back to the default theme palette for it, so the **legend caption below is mandatory** — it guarantees the reader always sees the green-=-value-creation mapping even when a renderer ignores `nodeColors`. Always keep `linkColor: source` (universally honoured) so links are at least consistently coloured by their origin node.

Reference rendering: `IMG/sankey_money_engine_demo.png` (illustrative SaaS example, 25% net margin) in the StocksDaily docs folder.

Template (replace placeholders, keep the config header + `nodeColors` map exactly):

````markdown
```mermaid
---
config:
  sankey:
    showValues: true
    linkColor: source
    nodeAlignment: justify
    nodeColors:
      Revenue: "#2563eb"
      Gross Profit: "#16a34a"
      Operating Income: "#16a34a"
      Net Income: "#16a34a"
      FCF: "#16a34a"
      Retained Earnings: "#16a34a"
      COGS: "#dc2626"
      R&D: "#dc2626"
      SG&A: "#dc2626"
      Other OpEx: "#dc2626"
      Interest & Tax: "#b45309"
      Capex: "#7c3aed"
      Dividends: "#ca8a04"
      Buybacks: "#ca8a04"
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
- The `nodeColors` map assigns each node its palette hex; drop any entry whose node maps to a `(not disclosed)` value, and drop the matching flow line too — never emit a flow with a blank or invented value.
- The `Operating Income,Capex` branch is optional: include it only when capex is disclosed in the JSON or annual report; otherwise omit both that flow line and the `Capex` entry in `nodeColors`.
- Keep the diagram body as bare `source,target,value` CSV rows after the `sankey-beta` line — the only addition versus a plain diagram is the YAML `config` header.

After the diagram, add a one-line caption **and the mandatory colour legend** (both required — the legend conveys the palette even if the renderer ignores `nodeColors`):
> *Cada euro de receita transforma-se em ~{net_margin_pct}% de net income; o maior dreno é {biggest_cost_bucket} ({biggest_cost_pct}%).*
>
> *Legenda: 🔵 receita · 🟢 criação de valor/lucro · 🔴 custos operacionais · 🟤 juros & impostos · 🟣 capex · 🟡 retorno a accionistas.*

{STYLE_RULES}
```
