# Prompt — Daily macro & market snapshot

Feeds the daily `_macro/<DATE>.md` file. Runs once per day from the macro phase.
The Python numbers in `{PYTHON_METRICS_JSON}`, `{BREADTH_JSON}`, `{SECTORS_JSON}` and
`{REGIME_JSON}` come from `macro_snapshot.py --fetch` + `macro_breadth.py --update` +
`macro_fred.py --update` (yfinance and FRED ground truth) — never overwrite them.
**Valuation (§2) and country-macro (§5) are the only sections still sourced by WebFetch**;
each figure there needs its own citation. §6 moved to `{REGIME_JSON}` in v4.3.1 (roadmap
R2) and §7 is a documented gap, not a fetch.

Substitutions:
- `{DATE}` — today, ISO (e.g. 2026-07-15)
- `{PYTHON_METRICS_JSON}` — the `--fetch` JSON block (indices, VIX, 10y, FX, commodities, crypto)
- `{BREADTH_JSON}` — the `breadth` block from `_macro/<DATE>.json` (RSP/SPY ratio stats; may be `{"error": ...}`)
- `{SECTORS_JSON}` — the `sectors` block from `_macro/<DATE>.json` (SPY market line + 11 SPDR ETF rows; per-row `error` possible)
- `{REGIME_JSON}` — the `regime` block from `_macro/<DATE>.json` (FRED M2 + Buffett Indicator + the §7 note; each gauge may carry its own `error`)
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

REGIME (ground truth — FRED M2 + Buffett Indicator, do not alter or re-source):
{REGIME_JSON}

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
- S&P 500 trailing P/E, forward P/E, P/S, P/B, EV/EBITDA, and Shiller CAPE. For each,
  show the CURRENT value AND a historical anchor: the long-run median (P/E, P/S, CAPE)
  or the mean ±1 SD (P/E), so "rich vs history" is explicit, not implied.
- Each value MUST carry its source + as-of date, fetched via WebFetch from multpl.com
  (P/E, P/S, P/B, Shiller CAPE — each has its own page + median), WSJ market data, or
  gurufocus. If a metric cannot be sourced, write "not available".
- **Emit one table row per gauge listed above, ALWAYS — including EV/EBITDA.** A gauge
  that cannot be sourced gets a row reading "not available", never a dropped row: a
  missing row is indistinguishable from a gauge nobody looked for. EV/EBITDA in
  particular has no reliably free source, so "not available" is its expected steady
  state — that is a correct answer, not a failure.
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
**GROUND TRUTH — `{REGIME_JSON}`. Do NOT WebFetch this section, and do not recompute
anything in it.** Both gauges come from `macro_fred.py` (FRED `M2SL`, and
`NCBEILQ027S` ÷ `GDP`), which is why they finally have numbers: this section rendered
"not available" for its whole life because it asked an LLM to fetch what a pinned API
already serves. Format the block; never alter it. (Roadmap R2.)

- **Buffett Indicator** — print `ratio_pct` with its `as_of` **quarter** and the
  `source` string. Say plainly that it is a quarterly series and therefore lags: the
  equities leg trails GDP by a quarter, and the ratio is taken on the latest quarter
  both cover.
- **M2 liquidity regime** — print `level_usd_bn`, `yoy_pct`, the
  `three_month_annualised_pct` and the `regime` label. The label is **computed from
  published bands** (see `macro_fred.M2_BANDS`), so do NOT mark it `(inferred)` — it is
  as much ground truth as the level. Where the 3-month rate and the YoY point different
  ways, say so in a clause: the 3-month turns first.
- A gauge carrying a non-null `error` renders **"not available"** with the error's own
  wording. Each degrades alone; one failure never blanks the section.
- Global-CB M2 (Fed/ECB/PBOC/BOJ) is **not** in the block and must not be sourced
  elsewhere for this section — one pinned source or nothing.

SECTION 7 — Forward profit horizons (index level)
**This section is expected to say "not available", and that is a finding, not a gap.**
Index-level forward earnings are a licensed product (FactSet, LSEG, S&P) and no free,
pinnable API publishes them; a page that reprints them is not a pinned source. Print the
`forward_profit_note` from `{REGIME_JSON}` so the reason travels with the gap. Recorded
as roadmap **N6**.
- Do **not** WebFetch a number for this section. Do **not** estimate one.
- Per-ticker forward earnings are handled in each stock's own report (Phase B
  forward-target valuation) and are unaffected — this section is index-level only.

SECTION 8 — Read-through for equities
- 4–6 sentences maximum. Tie directly to the numbers in Sections 1–7: what the tape,
  valuation-vs-history, breadth, sector leadership, macro backdrop, liquidity and
  forward-profit picture imply for equity risk today. Be decisive.

DISCLAIMER (last line, verbatim):
> [!warning] 🤖 Auto-generated. Not investment advice. Verify all figures before acting.

{STYLE_RULES}
```
