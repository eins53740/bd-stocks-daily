# Prompt — Daily macro & market snapshot

Feeds the daily `_macro/<DATE>.md` file. Runs once per day from the macro phase.
The Python numbers in `{PYTHON_METRICS_JSON}` come from `macro_snapshot.py --fetch`
(yfinance ground truth) — never overwrite them. Valuation and country-macro figures
are NOT in the JSON and must be sourced via WebFetch with a citation each.

Substitutions:
- `{DATE}` — today, ISO (e.g. 2026-07-15)
- `{PYTHON_METRICS_JSON}` — the `--fetch` JSON block (indices, VIX, 10y, FX, commodities, crypto)
- `{COUNTRY_TABLE_FRESH}` — `yes` if the previous country-macro table is <=7 days old, else `no`
- `{PREVIOUS_MACRO_MD}` — full contents of the most recent `_macro/*.md`, or `none`

```
ROLE: Senior macro strategist writing the daily market brief for a private client.

DATE: {DATE}
PYTHON METRICS (ground truth — do not alter or re-estimate these numbers):
{PYTHON_METRICS_JSON}

COUNTRY TABLE FRESH: {COUNTRY_TABLE_FRESH}
PREVIOUS MACRO FILE:
{PREVIOUS_MACRO_MD}

OBJECTIVE: Produce the COMPLETE content of `_macro/{DATE}.md` — frontmatter first,
then the four sections below, then the disclaimer. Output only the file content.

FRONTMATTER (YAML, exactly this shape):
---
date: {DATE}
country_table_date: <today {DATE} if you re-fetch Section 3; else copy the value from the previous file verbatim>
sources:
  - <one line per external source you cited, with URL>
schema_version: "1"
---

SECTION 1 — Markets today & this week
- A compact table built ONLY from {PYTHON_METRICS_JSON}: columns Index/Asset | Last | 1d % | 1w %.
  Use friendly labels (^GSPC = S&P 500, ^NDX = Nasdaq 100, ^STOXX = STOXX 600,
  ^GDAXI = DAX, ^FTSE = FTSE 100, ^N225 = Nikkei 225, ^HSI = Hang Seng,
  ^VIX = VIX, ^TNX = US 10y yield, EURUSD=X = EUR/USD, BZ=F = Brent, GC=F = Gold, BTC-USD = Bitcoin).
- Any ticker with an "error" entry: show "not available" in its cells — never invent a number.
- 3–4 sentences of commentary: what moved today, and the week's direction. Tie to the numbers.

SECTION 2 — US market valuation
- S&P 500 trailing P/E, forward P/E, P/S, and EV/EBITDA if findable.
- Each value MUST carry its source + as-of date, fetched via WebFetch from multpl.com,
  WSJ market data, or gurufocus. If a metric cannot be sourced, write "not available".
- NEVER estimate a valuation figure. A sourced "not available" beats a guess.

SECTION 3 — Country macro (US, Euro Area, China, Japan)
- Table with one row per economy: GDP growth (latest quarter), CPI YoY, policy rate,
  unemployment — each cell carrying source + as-of date.
- If COUNTRY TABLE FRESH = no: re-fetch via WebFetch and set country_table_date to {DATE}.
- If COUNTRY TABLE FRESH = yes: copy the Section 3 table from the PREVIOUS MACRO FILE
  verbatim and keep its country_table_date. Do not re-fetch.

SECTION 4 — Read-through for equities
- 4–6 sentences maximum. Tie directly to the numbers in Sections 1–3: what the tape,
  valuation and macro backdrop imply for equity risk today. Be decisive.

DISCLAIMER (last line, verbatim):
> [!warning] 🤖 Auto-generated. Not investment advice. Verify all figures before acting.

{STYLE_RULES}
```
