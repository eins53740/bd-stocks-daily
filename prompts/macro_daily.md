# Prompt — Daily macro & market snapshot

Feeds the daily `_macro/<DATE>.md` file. Runs once per day from the macro phase.
The Python numbers in `{PYTHON_METRICS_JSON}`, `{BREADTH_JSON}` and `{SECTORS_JSON}`
come from `macro_snapshot.py --fetch` + `macro_breadth.py --update` (yfinance ground
truth) — never overwrite them. Valuation, regime and country-macro figures are NOT in
the JSON and must be sourced via WebFetch with a citation each.

Substitutions:
- `{DATE}` — today, ISO (e.g. 2026-07-15)
- `{PYTHON_METRICS_JSON}` — the `--fetch` JSON block (indices, VIX, 10y, FX, commodities, crypto)
- `{BREADTH_JSON}` — the `breadth` block from `_macro/<DATE>.json` (RSP/SPY ratio stats; may be `{"error": ...}`)
- `{SECTORS_JSON}` — the `sectors` block from `_macro/<DATE>.json` (SPY market line + 11 SPDR ETF rows; per-row `error` possible)
- `{COUNTRY_TABLE_FRESH}` — `yes` if the previous country-macro table is <=7 days old, else `no`
- `{PREVIOUS_MACRO_MD}` — full contents of the most recent `_macro/*.md`, or `none`

```
ROLE: Senior macro strategist writing the daily market brief for a private client.

DATE: {DATE}
PYTHON METRICS (ground truth — do not alter or re-estimate these numbers):
{PYTHON_METRICS_JSON}

BREADTH (ground truth — RSP/SPY, do not alter):
{BREADTH_JSON}

SECTORS (ground truth — SPDR ETF tendencies, do not alter):
{SECTORS_JSON}

COUNTRY TABLE FRESH: {COUNTRY_TABLE_FRESH}
PREVIOUS MACRO FILE:
{PREVIOUS_MACRO_MD}

OBJECTIVE: Produce the COMPLETE content of `_macro/{DATE}.md` — frontmatter first,
then the eight sections below, then the disclaimer. Output only the file content.

GROUND-TRUTH & DEGRADATION RULES (apply to every section):
- Numbers already supplied in a JSON block are ground truth: format and comment on
  them, never change them.
- Every figure you fetch yourself (Sections 2, 5, 6, 7) MUST carry its source + as-of
  date. If a figure cannot be sourced, write "not available" in that cell — NEVER
  estimate or invent one. A sourced "not available" beats a guess.
- Each gauge degrades INDEPENDENTLY: one failed scrape or one `{"error": ...}` JSON
  entry shows "not available" for that gauge only and NEVER blanks its section or the
  file. If a whole JSON block is `{"error": ...}`, render that one section as
  "not available today ({reason})" and keep every other section intact.

FRONTMATTER (YAML, exactly this shape — keep these keys, add nothing that breaks them):
---
date: {DATE}
country_table_date: <today {DATE} if you re-fetch Section 4; else copy the value from the previous file verbatim>
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

SECTION 2 — US market valuation vs history
- S&P 500 trailing P/E, forward P/E, P/S, P/B, and Shiller CAPE. For each, show the
  CURRENT value AND a historical anchor: the long-run median (P/E, P/S, CAPE) or the
  mean ±1 SD (P/E), so "rich vs history" is explicit, not implied.
- Each value MUST carry its source + as-of date, fetched via WebFetch from multpl.com
  (P/E, P/S, P/B, Shiller CAPE — each has its own page + median), WSJ market data, or
  gurufocus. If a metric cannot be sourced, write "not available".
- 2–3 sentences: is the index cheap / fair / rich vs its own history, and by how much.

SECTION 3 — Market breadth (equal-weight vs cap-weight)
- Built ONLY from {BREADTH_JSON} (ground truth). Report the RSP/SPY ratio now, its
  percentile within its own history (`percentile`), the min/mean/max range and the
  `depth_days` window, and the trend arrow (`trend` ↑/→/↓). Cite the `as_of` date.
- If {BREADTH_JSON} is `{"error": ...}`: "Breadth gauge not available today ({reason})".
- 1–2 sentences: a low / falling percentile = narrow mega-cap leadership; a high /
  mean-reverting one = broadening participation. Say which regime today implies.

SECTION 4 — Sector tendencies (with volume confirmation)
- Built ONLY from {SECTORS_JSON} (ground truth). First a one-line overall-market read
  from the `market` (SPY) entry: trend + volume direction + whether volume confirms.
- Then a table over `rows`: Sector | Trend (↑/→/↓, 20d vs 60d MA) | Volume (rising/falling
  vs 20d MA) | Confirms? (✓ = trend backed by rising volume; ⚠ = suspect / falling
  volume; — = flat, nothing to confirm). Map `confirms`: true→✓, false→⚠, null→—.
- Any row with an `error` field: show the sector name and "not available" across its
  cells — the rest of the table still renders.
- 1–2 sentences: which sectors lead / lag and whether the moves are volume-confirmed.

SECTION 5 — Country macro (US, Euro Area, China, Japan)
- Table with one row per economy: GDP growth (latest quarter), CPI YoY, policy rate,
  unemployment — each cell carrying source + as-of date.
- If COUNTRY TABLE FRESH = no: re-fetch via WebFetch and set country_table_date to {DATE}.
- If COUNTRY TABLE FRESH = yes: copy this table from the PREVIOUS MACRO FILE verbatim
  and keep its country_table_date. Do not re-fetch.

SECTION 6 — Liquidity & the Buffett Indicator
- **Buffett Indicator** (US total market cap / GDP): current value + its long-run trend
  line / fair-value band, source + as-of (WebFetch longtermtrends.net or
  currentmarketvaluation.com).
- **M2 liquidity regime**: US M2 level and YoY direction (WebFetch FRED series `M2SL`,
  https://fred.stlouisfed.org/series/M2SL) plus, if sourceable, global-CB M2
  (Fed/ECB/PBOC/BOJ). Give a one-word regime label (expanding / flat / contracting) —
  you MAY mark the label `(inferred)` since it is a reading of the sourced levels, but
  the underlying levels themselves must be sourced, never invented.
- Any figure not sourceable → "not available".

SECTION 7 — Forward profit horizons (index level)
- S&P 500 forward earnings / EPS trajectory at 3m / 6m / 1Y / 2Y / 3Y from consensus
  (WebFetch FactSet Earnings Insight, Yardeni, or S&P DJI), each horizon with source +
  as-of. Per-ticker forward earnings are handled in each stock's own report (Phase B
  forward-target valuation) — keep this section index-level only.
- If no forward consensus is sourceable → "not available" (do not estimate).
- 1–2 sentences: is aggregate profit growth accelerating or decelerating across the horizons.

SECTION 8 — Read-through for equities
- 4–6 sentences maximum. Tie directly to the numbers in Sections 1–7: what the tape,
  valuation-vs-history, breadth, sector leadership, macro backdrop, liquidity and
  forward-profit picture imply for equity risk today. Be decisive.

DISCLAIMER (last line, verbatim):
> [!warning] 🤖 Auto-generated. Not investment advice. Verify all figures before acting.

{STYLE_RULES}
```
