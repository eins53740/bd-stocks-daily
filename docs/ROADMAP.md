# ROADMAP — `/bd-stocks-daily` (live backlog)

**Created 2026-07-30.** Forward-looking queue only. The *historical* record of what
shipped and why lives in `STRATEGY_GUIDE.md §10` (items 1–14, closed at the v3
Phase 9 review) and in the wave plans; this file tracks only what is **not
deployed**, with the reason and the trigger that would unblock it.

Effort: **S** ≤ 2 h · **M** 3–6 h · **L** > 6 h.
State: **READY** (plan written, no blocker) · **AGREED-DEFERRED** (decided not to
do now, on purpose) · **GATED** (waiting on an external trigger) · **BACKLOG** (no
ETA) · **WON'T DO** (decided against).

---

## Now — READY, nothing blocking

*(R1 removed 2026-08-15 — **shipped**. `update_shortlist.py` gained `_rank()` (L119) and
`_supersedes()` (L129, used L146) in the v4.2 work committed as `70d02d6`. The entry had gone
stale on disk while the fix sat uncommitted, and the v4.3 plan re-scheduled work that was
already done as a result — the reason this file must be pruned when things ship, not just
appended to. Recorded in `CHANGELOG.md` under v4.2.)*

### R2. Macro gauges — Buffett Indicator + M2 regime + forward-profit horizons — **M**

`_macro/<date>.md` §6 and §7 have been rendering "not available" because these
three gauges are WebFetch-sourced and no source is pinned in `macro_daily.md`.

- **Decided 2026-07-30** (Bruno): build it. Chosen over the segments chart because
  the cost is one-off — the `_macro/` cache is daily, so there is **zero per-run
  cost** once the sources are pinned.
- **Plan**: FRED `M2SL` for the liquidity regime (clean public JSON API);
  market-cap-to-GDP for the Buffett Indicator needs a source picked and pinned;
  index-level forward-profit horizons (3m/6m/1Y/2Y/3Y) from the same
  multpl/gurufocus family already used for P/E and CAPE.
- **Constraint**: keep the existing per-gauge independent degradation — one dead
  source must never blank the section, and **"not available" always beats an
  estimate**.

*(R3 removed 2026-08-15 — **shipped** with v4.3 wave 4.2. `run_prefilter.py` now promotes
ANSWERED pending entrants (pass or fail) into `_universe.yaml` before wiping PENDING, so a
ticker added through `--add-ticker` survives past one Monday. Answered rather than only
passing, deliberately: the universe is the WORK LIST, not the pool, and a name that fails
this quarter may pass the next. Names that keep ERRORING are still handled by RETRY/PAUSED.
A test asserts the promotion happens before the wipe — reversed, it would promote nothing.
See `CHANGELOG.md` v4.3 wave 4.)*

### R6. The balance sheet's `shares` row can be a currency amount — **S**

`analyze_ticker._STMT_ROWS["balance"]["shares"]` resolves
`("Share Issued", "Ordinary Shares Number", "Common Stock")` in order, and **"Common Stock"
is a par value in currency on some filers**, not a share count.

- **Found** 2026-08-15 by the v4.3 §3.1 audit (finding D2) while building the asset-play
  test. Measured: across 122 reports where book value per share is computable two ways, all
  but five sit within 3×, but a middle band of **1.7–2.9×** is this fall-through — IBM 6.41
  vs 16.44, AMAT 16.49 vs 48.75, plus LRCX, DE, UNP, CTAS, PG, EMR.
- **Why it was not fixed with the finding**: the row feeds `red_flags`' balance checks,
  whose sub-score feeds the financial-quality star rating. Changing the extraction silently
  re-rates published reports, so it needs its own change with its own before/after.
- **Mitigated meanwhile**: `category_lens` treats a >5× disagreement between the two book-value
  paths as *unreliable* and refuses to publish an asset-play claim.
- **Plan**: add a share-count plausibility check (market cap / price, or the prior year's
  count) and drop the `"Common Stock"` fallback when it fails; re-render the affected
  reports deliberately.

### R7. Two broker tariffs that need a human with a browser — **S**

Opened 2026-08-16 when Trading 212 was verified and the other two were not. Neither is a
research problem; both are an access problem, which is exactly why they are recorded
rather than estimated. Both brokers stay `verified: false` and excluded from every cost
matrix until filled.

- **Bankinter** — the figures are in *Preçário de Títulos, Fundos e Seguros de
  Investimento* (`banco.bankinter.pt/particulares/pdfs/precario/ptfs_c.pdf`, mirrored on
  `clientebancario.bportugal.pt`). Both refuse automated fetch: 403 on the first, encoded
  streams on the mirror. Needs: commission % and minimum for PT / other-EU / US, the
  custody schedule and any per-semester minimum, and the non-EUR conversion spread.
  A 0.1 % / €5-minimum manual-processing commission appears in search summaries and is
  recorded as `partial_unverified` — **not** used anywhere.
- **eToro** — the decisive number is the **currency conversion fee**, and eToro publishes
  it only as "varies by location, payment method and Club tier". On a USD-base account
  funded in EUR that fee is the dominant cost, so without it the broker cannot be ranked
  at all. The per-exchange commission table also renders only after selecting a country
  and exchange in the browser. What *was* confirmed: no inactivity fee, no deposit fee,
  withdrawal free from a EUR account, and USD 1–2 possible per open and per close.
- **Trading 212, minor**: interest on uninvested cash is real and paid daily with no
  minimum, but it tracks central-bank rates and is not a published constant, so no number
  is pinned. Do not let a review site's figure become one.

### R8. `bd-stocks-monitor` is the only skill not under version control — **S**

`bd-stocks-daily` is a git repo with a remote; `bd-stocks-monitor` is a bare directory.
It now holds `monitor_report.py`, `send_monitor_email.py` and a SKILL.md that a **live
weekly scheduled task** executes, so an edit that breaks it has no diff and no way back.

- **Found** 2026-08-16, immediately after the `StocksMonitor` task was registered.
- **Trigger**: none needed; this is only unscheduled because Wave 5's packaging question
  (one repo per skill vs one `bd-finance` repo for all eight) should be settled first —
  giving it a repo now and moving it in a fortnight is churn.

---

## Next — AGREED-DEFERRED

### N0. Probe FinancialReports for EU filings + new listings — **S**

The provider audit found the only credible free source of **European** filings and new
listings: FinancialReports (`financialreports.eu`, now 301→`financialfilings.com`) — 57
markets, 69,647 companies, **500 free credits/month**, 600 req/min, REST + Python SDK, and a
daily European IPO index. 500 calls/month is ample at weekly cadence.

- **Why it matters**: **no free API gives European IPOs.** Finnhub's calendar returns 142
  entries, all NASDAQ/NYSE; AlphaVantage's returns 3 rows; FMP's is `402`. yfinance has no
  IPO endpoint at all.
- **Unverified**: which fields the free 500 credits unlock, and whether the IPO index is
  exposed via API or only on the website. One free key + one probe answers both.
- **Caveat**: the domain rebranded recently — treat stability as unproven.

### N1. Revenue-segment charts, behind an opt-in `--segments` flag — **M**

- **Decided 2026-07-30** (Bruno, on my recommendation): do **not** put this in the
  scheduled path. Build it opt-in so the unattended 17:00 job never fetches a PDF,
  and pull it on demand for a name actually being studied.
- **Why not in the daily run**: this is the *only* place in the pipeline where
  numbers come from an LLM reading a filing (the documented ground-truth
  exception, `SKILL.md` Phase 2.5 step 7b). It adds a WebFetch + an LLM extraction
  to every deep-dive — new latency and a new failure mode in the job that already
  hung once and needed `run_with_timeout.ps1`.
- **Today's behaviour is fine**: `segments_available: false` degrades cleanly with
  a `⚠️ Segment data unavailable` note. Nothing is broken; this buys one chart.
- **Contract to keep**: every segment number stays tagged "company filings
  (LLM-extracted)" with a `source_url`, values only from the official table —
  never estimated or interpolated.

### N2. `op_margin_3y_delta` — Scalable Kings tie-breaker (§10 item 5) — **S**

Add `op_margin_3y_delta` to `_compact_fund` and use it as a **tie-breaker inside
the Moat sub-score**, not as a new weight. Separates margin-expanders from
margin-stable names within the same moat score.

- **Why still deferred**: the Scalable-Kings signal overlaps a Moat component that
  `SCORING_REVIEW_v3.md §2.1` already calls double-counted. Not urgent, and adding
  it as a *weight* would need the item-12 harness.
- **Architecture**: one extra JSON field + 3 years of operating margin via
  `Ticker.financials`.

*(N3 and N4 removed 2026-08-16 — both **shipped** in v4.3 §3.1 and their evidence lives in
`AUDIT_v43.md` A2 and A1 and in `CHANGELOG.md` v4.3. They had been left in place with
SHIPPED banners "to remove at the next prune"; this is that prune. N3: an
earnings-collapse year is excluded from the P/E series and a 4-clean-year depth floor
applies to what survives — 44 usable, 3 unusable. N4: `choose_fair_price()` is the
deterministic anchor, blend → blend_median → dcf → consensus → omit, moving MSFT
$118.35 → $303.28.)*

### N5. Peer-set quality when `peers_source == by_sector` — **M**

adidas was ranked against **Amazon, McDonald's, Home Depot, Starbucks** and Nike
because yfinance could not resolve a footwear peer set. Only Nike is a peer, yet
the resulting 7.33/10 carries the full **12%** peer weight in the composite.

- **Plan**: either add a curated fallback in `peers.json` for common industries, or
  damp the peer sub-score toward neutral (5.0) when the source is `by_sector` —
  the same honesty the `none` case already gets.

---

## Gated — waiting on a trigger

### G3. Gate calibration — the evidence, held until G1 — **M**

The v4.3 §3.1 audit measured the seven gates over **267** analyses and found three things
that a recalibration should start from. **Nothing was changed**: `gates_passed` contributes
3 of the 10 points of the fundamentals sub-score, which carries 35 % of a composite frozen
at v2.2.

- **Gate 7 (`quick ratio > 1.5`) is the binding gate at 32 % pass, and it points against the
  mandate.** It is a lender's test; the Quality Compounder mandate prizes **negative working
  capital** — subscription software billing a year in advance, restaurants, retailers,
  insurance float — and those businesses fail it structurally, costing ≈0.4 composite points.
- **Gate 4 (`ROE 5y > 5 %`) passes 85 %** and barely discriminates, on a mandate whose moat
  multiplier keys at ROIC > 25 %.
- **The v2.2 gate-5 growth bypass fired twice in 267 evaluations** (0.7 %).

- **Trigger**: the same one as **G1** — T+6m outcome data, first possible ≈2026-10-17.
  Candidates to test then: Gate 7 → current ratio, or > 1.0, or demoted to a warning;
  Gate 4 → 10–12 %. Do not guess. See `AUDIT_v43.md` Lens 1.

### G1. Naive backtest to calibrate `WEIGHTS_V2_DEEP` (§10 item 12) — **M**

T+6m / T+12m attribution of `price_at_eval` vs benchmark, replacing
educated-guess weights with measured ones. **Still gated as of 2026-07-30.**

- `_log.csv`: 259 rows, 253 with `price_at_eval`, earliest **2026-04-17**, span
  **3 months**. Rows old enough for T+6m: **0**. For T+12m: **0**.
- **Trigger dates**: first T+6m attribution possible **≈ 2026-10-17**; first T+12m
  **≈ 2027-04-17**.
- **The clock is protected**: `price_at_eval` has survived every schema bump
  including v2.1 → v2.2, so the 12-month clock has never been reset
  (`SCORING_REVIEW_v3.md §S5`). Do not break that column.

### G2. Sector-specific dynamic weights in the Valuation sub-score (§10 item 8) — **M**

Detect `lynch_category` and adjust the sub-weights *inside* Valuation (never the
top-level composite weights). **Blocked on G1** — changing weight magnitudes
without a backtest is an educated guess on top of an educated guess
(`SCORING_REVIEW_v3.md §4`).

---

## Backlog — no ETA

| # | Item | Effort | Note |
|---|------|--------|------|
| B1 | Port the v4 overlays into `/bd_stocks_daily_growth` | **L** | Q4 of the skills guide (ReadNow 0245). Read `ReadNow\_markdown_\stocks_skills_guide_NOTES.md` first — it holds the port checklist. |
| B2 | `/bd-stocks-fallen-angels` sub-skill (Biggest Losers) (§10 item 13) | **M** | Counter-thesis to the compounder mandate; needs its own "fallen angels" prefilter. yfinance exposes `52WeekChange`. |
| B3 | News-sentiment NLP via BERT, own pipeline (§10 item 14) | **L** | Heavy infra (model + scraping + cache) that belongs in a separate service; incompatible with the ~$20/run budget. Phase H's LLM-classified dials already cover the use case cheaply. |
| B4 | Four yfinance names with no FCF series at all | **S** | `0175.HK, CMO.MC, FLOW.AS, INGA.AS` — thin non-US statements where FCF genuinely is not published. Correct degradation today; only worth revisiting if a second source is added. |
| B5 | `patrimonio positions` cannot write a disposal | **M** | By design: the holdings file records what is held, never a sale price, date or commission, and inventing one puts a fabricated capital gain in a tax-relevant sheet. Live case 2026-08-16: DOMO sits open on row 27 with no matching holding. Closing it needs those three inputs from a broker statement, which is a different importer. |
| B6 | Only **9 free rows** remain in the `Accoes (BD)` formula block | **S** | Lots live on rows 3–36 and `H37` is `=SUMIFS(H3:H36,N3:N36,"")`. Rows 28–36 are free; the tenth new lot has nowhere to go that the invested total can see. Extending the block means extending the SUMIFS and copying the six per-row formulas down — deliberate work, not something a writer should do on the fly. |
| B7 | The documented test command misses a dependency | **S** | `uv run --with pytest pytest tests` leaves 9 email tests failing on a `<pre>` fallback because the `markdown` package is absent from that env — a red suite that is purely environmental, which is worse than a slow one. Either add `--with markdown` everywhere it is documented, or pin the test deps in a `pyproject`. |

---

## Won't do — decided against

- **TIKR screens #7–#10** (Yield / Deep Value / Net-Nets) — incompatible with the
  Quality Compounder mandate (`STRATEGY_GUIDE.md §10`).
- **A summable 4×10 SWOT scorecard** — the SWOT stays a qualitative overlay with
  no number entering the composite (§10 item 4).
- **A standalone `/bd-stocks-timing` sub-skill** — absorbed by the Technical card
  and GO/NO-GO, which is exactly the intended scope (§10 item 10).
- **ATR trailing stops in the exit plan** — `atr_context.enabled` stays `false` by
  design: a compounder tolerates normal 20–30% drawdowns, and exit discipline is
  the P/E band plus the thesis. Trailing stops belong to the growth skill.
- **R5 — rotating the Alpha Vantage key pool** *(closed 2026-08-15, measured not assumed)*.
  The entry assumed "six keys ⇒ ~6× the throughput". Both halves were false:
  - `config/api_keys.txt` holds six entries but **five distinct keys** —
    `api_key_alphavantage` and `api_key_alphavantage1` are the same string.
  - **The free 25/day cap is enforced per SOURCE IP, not per key.** One key was burned
    to its limit (25 calls succeeded, the 26th refused); the four other keys, one of
    which had answered normally seconds earlier, were then **all refused by name** from
    this machine. Rotation cannot raise a ceiling that is not per-key.

  So this laptop has **one machine-wide allowance of 25 AV calls/day**, shared by
  `financial_history.py` and `valuation_bands.py` — which is exactly what the existing
  shared `_fin_history/_av_budget.json` counter already models. Nothing to build.

  Do **not** re-open this by adding more keys; the constraint is the IP. Raising AV
  throughput requires a paid plan, and raising **non-US** depth requires a different
  provider entirely — see **N0** (AV fundamentals are US-listed only regardless of tier).

---

## Maintaining this file

Add an item when work is **consciously not done** — with the reason and the
trigger, not just the title. Move it out when it ships, and record the outcome in
`STRATEGY_GUIDE.md §10` (the historical record) rather than leaving a DONE row
here. A roadmap of finished things is a changelog wearing the wrong hat.
