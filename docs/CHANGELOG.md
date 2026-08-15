# CHANGELOG — `/bd-stocks-daily`

The version record: **what shipped, when, and what it closed**. One entry per version,
newest first.

Three files, three jobs — don't merge them:

| File | Holds |
|---|---|
| `docs/CHANGELOG.md` (this file) | **what shipped**, per version |
| `docs/ROADMAP.md` | **what has not shipped** — open backlog only, with reason + trigger |
| `StocksDaily/docs/STRATEGY_GUIDE.md` §10 | **why** — the analytical rationale behind shipped items |

**Release checklist** (every version, no exceptions):
1. bump `scripts/version.py` → 2. append an entry here → 3. move shipped items out of
`ROADMAP.md` → 4. record the real test count → 5. `git tag -a vX.Y`.

The report footer watermark reads the same `__version__`, so a skipped bump shows up on the
face of every report.

> **Why this file exists.** Until 2026-08-15 the version history lived as a stack of bold
> paragraphs inside `SKILL.md` (~35 % of that file) and was duplicated in `README.md`. It
> drifted: the `SKILL.md` H1 claimed "v4.1 Phase H" while the body already documented v4.2,
> and the stated test count was wrong in four places (249 / 413 / 422 / 439 / 449 / 459
> against an actual 854). Only `v3.1` had ever been tagged — v4, v4.1 and v4.2 shipped
> untagged, which made "which version wrote this report?" unanswerable.
>
> Test counts below are **historical** — each is what the suite measured at that release.
> They are deliberately not restated to today's number.

---

## v4.3 — *in progress*

Wave-based upgrade. See `~/.claude/plans/` for the master plan. Waves land one at a time.

### Wave 0 — baseline & truth-in-docs (2026-08-15)
- **Committed the v4.2 work** that had accumulated uncommitted on disk (25 files), so v4.3
  has a rollback point. Tagged `v4.2`.
- **Backfilled the missing tags** `v4` (`5cb6823`) and `v4.1` (`bf05181`).
- **Fixed the stale `SKILL.md` H1** (claimed v4.1 Phase H at v4.2) and README's test count
  (249 → 854).
- **Fixed a real test defect**: `test_exactly_one_smtp_transaction` asserted
  `len(recipients) == 1`. That broke the moment a second digest recipient was added
  legitimately, and it never caught the failure it was named for — `main()` sending twice.
  Now counts `sendmail()` transactions: one delivery, however many addresses it carries.
- Created this changelog, plus `scripts/version.py` as the single source of the version
  string (the H1 drifted precisely because the version lived in prose).
- **Fixed the schedule drift**, verified against the live triggers rather than any doc:
  prefilter is **Mon 14:30** (`SKILL.md` said 14:00, `SCHEDULING.md` said 16:45); the growth
  skill is a standalone **12:45** task (its SKILL.md still claimed "17:00, invoked by
  stocks-daily.bat", which predates the 2026-07-31 split); `StocksDaily`'s timeout is
  **1800 s**, not the documented 1500 s.
- **Removed four superseded `docs/*.md.bak`** (git-tracked, so recoverable). Kept
  `bd-stocks-prefilter/scripts/run_prefilter.py.bak` — it is in no repo, so deleting it would
  be irreversible for no gain.
- **`job_lock.ps1` + wiring in all four heavy bats** — the fix for the incident below.
  `StocksDaily` waits up to 45 min then **proceeds anyway** (it owns the digest — a late
  digest beats none); the three siblings wait 30 min then **skip cleanly**. Verified
  end-to-end: the lock records the calling `cmd.exe` PID (not the short-lived powershell,
  which would make every lock instantly stale), a contender aborts rather than breaking a
  live lock, a waiter acquires on release, a foreign release is refused, and stale locks are
  broken on dead-PID or age so the schedule can never wedge.
- **`node_timing.py` + 11 tests** — per-node elapsed times to `_timings/{date}.jsonl`,
  append-only so a killed run keeps what it measured. `--report` prints a per-node table
  against the 1800 s budget. This is the instrument the v4.3 budget policy depends on:
  nothing gets promoted to default-on in the scheduled path without its numbers.

**864 passed, 1 skipped.**

### Wave 1 — data foundation (2026-08-15, in progress)

**1.0 entry gate — the Alpha Vantage key pool was a dead end, and it was worth 30 minutes
to find out before writing the rotation code.** The gate asked one question: is the free
25/day cap enforced per key or per IP? Measured, not reasoned about:

- Burned `api_key_alphavantage5` with `GLOBAL_QUOTE` calls — **25 succeeded, the 26th was
  refused**.
- Immediately probed `api_key_alphavantage4`, which had answered normally **seconds
  earlier** — refused. Then keys 3, 2 and the production key — **all refused, each named in
  its own refusal message**.
- Four independent keys cannot coincidentally exhaust at the same instant, so the cap is
  **per source IP**. Key rotation buys nothing.
- Second finding along the way: the "six-key pool" is **five distinct keys** —
  `api_key_alphavantage` and `…1` are byte-identical.

**Roadmap R5 closed as WON'T DO** with the evidence recorded, so nobody re-opens it by
adding a seventh key. This machine has **one allowance of 25 AV calls/day**, shared across
every skill — which the existing `_fin_history/_av_budget.json` counter already models
correctly. Nothing to build.

**Plan item 1.1 (rotation) is dead. Plan item 1.2 (financial history for the two screen
tickers) survives** — the plan had coupled them, but the measurement shows 1.2 never needed
the pool. The real daily draw is **~4 calls** (ledger, 2026-08-14) against a guard of 20,
because with a 80-day TTL and no US cache older than **31 days**, TTL refreshes essentially
never fire; the draw is new, cache-cold US names only. Three picks all US and all cold is
~9 calls — comfortably inside the guard.

**Two defects the test exposed, both fixed:**

- **The 20 s retry was sized for a limit that no longer exists.** `AV_THROTTLE_DELAY_S`
  carried the comment *"free tier is 5 req/min — space the retry past the window"*, but the
  gate fired **24 calls at ~1/second with none refused**: there is no per-minute window on
  this tier any more, only the daily cap. Worse, the retry was unconditional, so a
  **daily-cap** refusal slept 20 s and spent a second counted call to receive the identical
  refusal — ~40 s of a 30-minute job budget and 2 wasted calls per capped US name, against
  an allowance already spent machine-wide. Refusals are now classified (`_av_refusal_kind`):
  a per-minute note still retries, a daily cap returns immediately. `fetch_alphavantage`
  also short-circuits `CASH_FLOW` when `INCOME_STATEMENT` came back capped.
- **A daily cap now saturates the budget file.** Each pipeline node is a separate process,
  so an in-memory flag cannot travel from `financial_history` to `valuation_bands`; the
  budget file is the only shared channel. One node discovering the cap now stops the others
  re-discovering it one wasted call at a time. It still clears at the date rollover — tested,
  because the failure mode of getting that wrong is being wedged off AV permanently.

**A bug in the fix, caught by its own test before it shipped**: the first classifier keyed on
the substring `"per day"` — but AV's *per-minute* note reads *"5 calls per minute and 500
calls per day"*, so it would have classified a transient throttle as an exhausted day and
**silently disabled the retry that fixed the all-None FCF column** on 10 of 33 names. The
classifier now checks `"per minute"` first, and the ordering is asserted.

**878 passed, 1 skipped** (+14).

*Operational note: the gate consumed the machine's AV allowance for 2026-08-15. No
scheduled job was affected — the ledger shows the pipeline made **zero** AV calls today (its
run had already timed out before that node) — and the allowance resets daily.*

**Known incident, 2026-08-15** — worth recording because it shaped the plan. `StocksGrowth`
and `StocksDaily` both fired at **13:36** as Task Scheduler missed-task catch-up (the machine
was asleep at their 12:45 / 13:30 triggers). They contended and **both hit their timeouts**
(growth `exit 124` at 1500 s; daily killed at 1800 s). Phase 6 never ran, so the bat's email
gate found no rows and logged `No reports for 2026-08-15 - skipping email` — **no digest was
sent**. The reports on disk for that date came from manual recovery runs. Nothing enforces
the growth-before-daily ordering that `SCHEDULING.md` calls load-bearing.

---

## v4.2 — 2026-08-05 → 2026-08-15 · tag `v4.2` · commit `70d02d6`

Composite v2.2 untouched. **854 tests.**

- **`listings.py`** — one company, many tickers. A single dual-listing registry so `TSM` and
  `2330.TW` are one position, not two. Consumed by `pick_candidates.py` (rewrite a pick to its
  home listing), `update_shortlist.py` (dedupe by company) and `report_history.py`.
- **`report_history.py`** — `--block` renders a per-company history section; `--archive`
  collapses superseded reports into `_archive/`, leaving one report per company at the root
  (latest date wins; within a date the deep beats the screen that produced it). `_log.csv`
  keeps every row — backtesting needs them.
- **`check_report_charts.py`** — the Phase 5.6 chart gate: orphan PNGs and broken links, with
  `--fix` / `--audit` / `--dry-run`.
- **`company_names.py`** — ticker → readable name cache (`_company_names.json`).
- **`token_stats.py`** — post-hoc cost accounting over the session JSONL.
- **`prompts/07_thesis_duel.md`** — the §0 card at the top of the report: moat mechanism,
  bull-vs-bear side by side, and a **LEAN** (BULL / BEAR / BALANCED, never a percentage).
  Overlay-only — the LEAN never touches the composite or the verdict.
- **ROIC invested-capital guard** (`analyze_ticker.py`, `IC_MIN_FRACTION = 0.05`) — ROIC
  returns `None` when the net-cash subtraction has hollowed the denominator below 5 % of gross
  capital, instead of emitting a divide-by-almost-zero artefact. Note the side effect: the
  Buffett moat multiplier (ROIC > 25 %) correctly does not fire for those names.
- **Digest second recipient** — `bruno.dias@secil.pt` alongside `eins.ist@gmail.com`.
- **Closes roadmap R1** — `update_shortlist.py` `_rank()` / `_supersedes()`: on a Phase 5.5
  auto-cascade the deep row now supersedes the same-day screen row, so the shortlist links the
  deep report. (The roadmap entry stayed open for weeks because the fix sat uncommitted on
  disk; that drift is what the release checklist at the top of this file exists to prevent.)

## v4.1 wave-2 — 2026-07-23 · tag `v4.1` · commit `bf05181`

Composite v2.2 untouched. **459 tests** at release.

- **Phase H — news & market sentiment** (`news_sentiment.py`, node 2.59). yfinance headlines
  (+ one optional NewsAPI query on a disposable trial key) → **one** LLM call classifying them
  into a **stock** dial and a **market** dial, each −1..+1 with themes + citations. Not in the
  composite — sentiment is context, complementing `news_freshness`. 439 tests.
- **Phase I — screener dashboard** (`build_dashboard.py`: `load_universe()`,
  `enrich_from_tmp()`, `build_screener()`). The full pre-filtered pool LEFT-JOINed with
  evaluations; category + range filters, localStorage presets, CSV export, rows deep-linking
  to the Phase-F HTML report. 449 tests.
- **`--version {v3,v4}` gate** (`version_gate.py`) — latest is always the default
  (`LATEST = VERSIONS[-1]`, never hard-coded). `v3` skips the v4 overlay nodes. Changes what
  renders, never the weights.
- **Fable audit fixes** — key-leak, fair-price n/a, screener rank, dead links.

## v4 wave-1 — 2026-07-22 → 2026-07-23 · tag `v4` · commit `5cb6823`

All seven phases overlay-only on schema 2.2 — additive JSON keys, composite byte-identical.
**422 tests** at wave close.

- **Phase B — valuation depth** (`valuation_bands.py` 2.3, `intrinsic_value.py`): own-history
  P/E & P/S bands with depth guards, FY+3 forward target (TIKR-style: target @ date, est.
  return, IRR), sensitivity table with a margin-bear row, 5-model intrinsic blend + MoS.
- **Phase A — exit & thesis plan** (`exit_plan.py` 2.55): target exit P/E, fair-value range,
  profit-take ladder, thesis-broken trigger, yield-on-cost; the `ni_pe.png` dual-axis chart.
- **Phase C — red flags** (`red_flags.py` 2.4): three-statement checks, Beneish M-score,
  earnings quality, SWOT prompt. A **pure JSON consumer** — `analyze_ticker` persists
  `statements_raw` so the scanner makes zero new API calls.
- **Phase D — macro §8** (`macro_breadth.py` 2.6): RSP/SPY breadth + 11 SPDR sector
  tendencies (pure yfinance), plus WebFetch-sourced valuation/Buffett/M2 gauges. Each gauge
  degrades independently.
- **Phase E — return profile** (`alpha_beta.py` 2.56) + **watch-list** (`watchlist.py` 2.57):
  α/β 3y, CAPM line, 1/3/5/10/15y CAGR ladder, Lynch prior, portfolio fit vs URTH; quality
  names held back only by price enter `_watchlist.csv`.
- **Phase G — opinion panel** (`second_opinion.py` 2.58, `llm_client.py`): three personas
  (value/growth/contrarian) from an **independent** model chain (Groq → Gemini), each 0–100.
  The panel sees the evidence but **not** the composite — that is what makes it independent.
- **Phase F — HTML-primary renderer** (`render_report.py` 5.7 + `report_template.html`):
  answer-first header with a deterministic action verb, 5-axis snowflake, fair-value gauge,
  base64 charts ≤1.5 MB. Session 2 added the equity-vs-enterprise metric families and the
  greyed cheat-sheet. 413 → 422 tests.

## v3.1 — 2026-07-15 · tag `v3.1`

- Quarterly EBITDA+FCF series with a hybrid 4Q forecast (`financial_history.py`, Alpha Vantage
  for US listings + yfinance fallback, 80-day cache, 20-call/day AV guard).
- Top-of-report metrics strip (`top_strip`), 3-year revenue-segments chart, 30-month
  relative-performance chart, promoted thesis/risk callouts, €1500 broker section, daily macro
  section with the `_macro/` cache.

## v3 and earlier

Predate this file. The analytical rationale for items 1–14 is recorded in
`StocksDaily/docs/STRATEGY_GUIDE.md` §10, closed at the v3 Phase 9 review. v1/v2 predate
schema 2.2 (different weights and gates) and are reachable only via git tags + worktrees.
