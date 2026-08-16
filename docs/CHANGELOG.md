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

## v4.3.1 — 2026-08-16 · schema 2.2 · **1567 tests**

Post-release work: the delivery decision that v4.3 left open, and two roadmap items that
were READY with nothing blocking them.

### Email delivery — the digest now carries the deep report *(decision "a + b")*
Nothing was removed. The summary cards and the inlined markdown reports stay exactly as
they were, and the deep report's **rendered HTML travels as an attachment**. The cover, the
Sankey, the SWOT quadrants, the ⭐ ratings and the eleven charts exist only in
`render_report.py`'s output, and a `file://` link to the laptop is dead on a phone. Only
the deep row is attached, under an 8 MB budget, with each skip logged; both MIME parts
announce it.

### Trading 212 verified · **R7** opened for the two that could not be
Read off Trading 212's own help centre: commission **Free**, FX **0.15 %**, custody
**Free**. It enters the cost matrices with six real markets.
- **Zero commission is not zero cost.** On US/UK the 0.15 % conversion *is* the price; on
  Euronext there is no leg and the cost is genuinely zero. A test asserts both — if the two
  rows ever read alike, the comparator has stopped modelling FX.
- **No Asian venue is offered**, so the markets map omits TW/HK/JP/CN_SZ rather than
  leaving them empty. An empty entry reads as free and wins every Asian row outright.
- eToro's entry corrected where the official page contradicted it: **no** inactivity fee,
  and "0 % commission" is not unconditional. Bankinter and eToro stay excluded — see R7.

### R6 — `statements_raw.balance.shares` is not always shares outstanding
**The roadmap's hypothesis was wrong, and measuring is what showed it.** R6 blamed the
`"Common Stock"` fall-through for being a par value in currency. Across **147** analyses
checked against `fundamentals.shares_out`, 86 agree within ±5 % and the other 61 are off in
a **continuous spectrum from 1.05× to 25.6×** — not the signature of a currency-vs-count
confusion, which would be off by orders of magnitude or not at all.

Three causes wearing one label:

| Cause | Evidence |
|---|---|
| `"Share Issued"` includes **treasury stock** | IBM 2.43× · AMAT 2.52× · MCD 2.34× · P&G 1.72× · CTAS 1.95× (55 names) |
| A different **share class or quote ratio** | TSM exactly **5.000×** — the ADR ratio · Roche 7.59× (equity certificates) · Samsung's Frankfurt line 25.6× · Atlas Copco 3.15× (A/B) |
| **Staleness**, in the other direction | SMCI 0.918× · LYC.AX 0.929× — a fiscal-year-end count with shares issued since |

- **`scripts/share_basis.py`** classifies and does **not** rewrite. The extraction is
  untouched, so no published composite, gate or verdict moves — the condition R6 was held
  open for. `CLASS_MISMATCH_RATIO = 3.0` sits in the corpus's own empty band between AMAT
  at 2.524 and Atlas Copco at 3.151.
- **`category_lens`** uses shares outstanding where the basis is correctable, and refuses
  outright where it is not. Measured before/after: **58 statement-P/B corrections**
  (IBM 16.44 → 6.76, AMAT 48.75 → 19.32, KLAC 115.53 → 53.67, MCO 40.84 → 20.63) and **2
  names newly refused** — Roche and Atlas Copco, whose basis mismatch cleared the 5 % P/B
  tolerance untouched. The tolerance was a proxy for the basis; now the basis is known.
- **`red_flags.book_value_trend` deliberately unchanged**, with the reason written into the
  code: it compares BVPS year over year on the *same* basis, and a constant basis cancels
  in the ratio. Substituting a current-day count into a prior-year figure would make it
  worse.
- The early exit on a refusal has its own test. The first attempt omitted it and the
  refusal was undone three lines later by tangible-book code; only the corpus replay showed
  it (TSM `detected` went `None` → `False`).

### R8 — `bd-stocks-monitor` put under version control
The only one of the eight finance skills with no repository, and a live weekly task
executes it. No remote yet: whether the eight become eight repos or one `bd-finance` repo
is Wave 5's open question, and choosing now would prejudge it.

---

## v4.3 — 2026-08-15 · tag `v4.3` · schema 2.2 · **1516 tests**

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

**1.2 — financial history for the two screen tickers (G-B, G-C).** Phase 2.2 now runs for
all three picks, not just the deep dive. This turned out to be an **orchestration change
only**: `chart_ebitda_fcf()` and the report path have no deep/screen gate anywhere in code,
so the restriction lived entirely in `SKILL.md` prose. Screens gain the EBITDA/FCF chart and
the `fin_history_*` frontmatter for free.

- **Measured marginal cost: 3–5 s per ticker** (~10 s for both screens) against ~6 min of
  headroom in a 22–24 min job — 0.6 % of the budget, so this ships default-on rather than
  behind a flag. Instrumented with `node_timing.py` like the other heavy nodes.
- Corrected the stale AV arithmetic in `SKILL.md` (it claimed 2 calls per deep; it is 3 —
  `INCOME_STATEMENT` + `CASH_FLOW` here plus `valuation_bands`' `EARNINGS` in the same run).
- **Half-yearly markets degrade to nothing, correctly.** `LYC.AX` (ASX) returns no quarterly
  rows at all, because Australian issuers report half-yearly. `financial_history.py` writes
  **no cache file** on total failure — right, since a failure must not be served for 80 days
  — so the chart is skipped and `fin_history_*` is omitted. That is market structure, not a
  bug, and the report says so instead of inventing a series.

**1.3 — SEC EDGAR (`scripts/edgar.py`, new).** The skill had spent months routing around
EDGAR because `SKILL.md` said it 403s. **It does not.** Measured: no `User-Agent` → 403, with
one → 200, on all three endpoints. The blocker was a missing header.

- `submissions` → 10-K / 10-Q / 8-K with dates, periods and **direct working links**
  (verified: a generated 10-Q URL returns HTTP 200 and 3.67 MB of filing).
- **8-K items become catalysts** — `2.02` earnings release, `5.02` officer departure, `4.01`
  auditor change, and `4.02` *PRIOR FINANCIALS NOT RELIABLE*, the worst signal EDGAR carries.
- `companyfacts` → XBRL US-GAAP facts, **opt-in** at 5.6 MB / 2.7 s. Annual-only
  (`fp == "FY"`, form 10-K) so a quarterly row can never stand in for a full year.
- **`--text` delivers the half the plan flagged as missing**: the filing *prose* now reaches
  `{QUARTERLY_NARRATIVE}` / `{ANNUAL_NARRATIVE}` for US names, replacing a ~1,500-char
  yfinance blurb with the real MD&A.
- **Deleted the stale "avoid SEC EDGAR — they 403" instruction**, and demoted
  `get_narrative.py` to the fallback it should always have been for US names.
- TTLs deliberately depart from the plan's single 30-day figure: **1 day** for submissions
  (a 30-day TTL would hide a new 8-K for a month, defeating the point) and 30 days for the
  heavy facts payload.

**Three real-world failures found by running it against IBM's actual 10-Q, not by reasoning
about it** — each produced output that *looked* successful:
1. The heading match failed because filers write **U+2019**, not an ASCII apostrophe.
2. After fixing that it matched the **table of contents**, because the body heading is
   `Item 2.  MANAGEMENT'S…` with irregular spacing while the contents page uses one space.
   Matching is now whitespace-flexible, and a contents block is rejected by line-shape.
3. The no-section fallback returned the filing's **hidden inline-XBRL context block** —
   pages of `http://fasb.org/us-gaap/2026#CostOfRevenue`. `first_prose()` now skips it.

Degradation is tested end-to-end and verified live: non-US → no HTTP call at all; unknown
ticker → explicit reason; **foreign private issuer** (`NVO`, a real ADR filing 20-F) →
`available: true` with an explanation rather than an error; dead network → never raises.

**965 passed, 1 skipped** (+87).

**1.4 — region coverage (IBKR Europe to buy ∪ Yahoo to monitor).** Nine suffixes that were
**already live in `_universe.yaml`** were resolving to the `INTL`/`USD` fallback — **241
tickers, 200 of them `.AX` alone**, the second-largest market in the pool after the US. The
fallback is not cosmetic: it breaks `to_eur()` FX conversion, `region_of()`, benchmark
selection and the accounting caveat.

Verified end-to-end on a real run: `LYC.AX` resolved as
`{'region':'INTL','currency':'USD','exchange':'unknown (AX)'}` before and
**`AU / AUD / ASX`** after, with the half-yearly caveat surfacing in `data_warnings`.

- **Two tiers, because the brief was a union and not an intersection.** `.SA` (Brazil),
  `.SR` (Saudi), `.JK` (Indonesia) and `.BD` (Hungary) quote on Yahoo but are not reachable
  from the IBKR Europe account, so they are **monitor-only** and flagged as such rather than
  silently offered as buyable. `is_tradable()` / `tradability()` expose it, and an *unknown*
  suffix is never reported tradable — fail closed.
- **`.SA` is Brazil (BRL), `.SR` is Saudi (SAR)**, and the universe holds both. A regression
  test asserts them apart; transposing them would price three Brazilian names in riyal.
- **`.F`/`.HA` were deliberately NOT given their own market identity.** They are thin German
  secondary venues quoting companies whose primary line is Xetra — the roadmap **R4** trap.
  `listings.py` already registers `SSUN.F` as a Samsung GDR, so identity is handled there;
  `markets.py` only adds the stale-quote caveat, which says a divergence is a *reference*
  problem before it is a data error.
- **Every new benchmark was verified live, and three failed honestly**: `^JX` (TSX Venture)
  is **delisted on Yahoo**, so `.V` falls back to `^GSPTSE` and understates venture
  volatility; `^TASI.SR` returned **5 rows in a month** and `^BUX.BD` returned **1**. All
  three are mapped — better the right country than the US default — and all three carry a
  caveat saying relative strength from them is not meaningful.

**The cross-table consistency test is the durable part.** `_SUFFIX_META` keys carry no dot,
`BENCH_BY_SUFFIX` keys do, so adding a market to one and forgetting the other is silent — and
had already happened **in both directions**. It caught `.JP` (Tokyo alias, metadata but no
benchmark, so it was charted against the US index while priced in JPY) the moment it existed.

Also fixed, and unrelated to this work: `bd-stocks-prefilter`'s suite was **red** because
`MIN_COMPOSITE` was lowered 6.0 → 5.75 on 2026-08-15 while its test still asserted 6.0 and
called the bar "unchanged". The code is the intended state (documented at the constant); the
assertion was stale. Worth noting that **`bd-stocks-prefilter` is not a git repository**, so
that skill has no rollback point.

**Gates**: full suite **1001 passed, 1 skipped**; the prefilter's own suite 27 passed; a
prefilter `--dry-run --limit 25` completed clean (21 pass / 4 fail / **0 errors**).
Expect **one-time pool churn** on the next Monday prefilter as 241 members re-price into
their real currencies.

**Known incident, 2026-08-15** — worth recording because it shaped the plan. `StocksGrowth`
and `StocksDaily` both fired at **13:36** as Task Scheduler missed-task catch-up (the machine
was asleep at their 12:45 / 13:30 triggers). They contended and **both hit their timeouts**
(growth `exit 124` at 1500 s; daily killed at 1800 s). Phase 6 never ran, so the bat's email
gate found no rows and logged `No reports for 2026-08-15 - skipping email` — **no digest was
sent**. The reports on disk for that date came from manual recovery runs. Nothing enforces
the growth-before-daily ordering that `SCHEDULING.md` calls load-bearing.

### Wave 2 — charts & report delivery (2026-08-15, in progress)

**2.3 + 2.7 + thesis duel — the HTML report stops losing content the markdown has.**
These three ship first because they *gate* the HTML-only delivery switch: `render_report.py`
had no builder for the Sankey, the SWOT or the v4.2 LEAN card, so making HTML the sole format
first would have silently dropped three sections the reader relies on.

- **`scripts/mermaid_render.py` (new)** — mermaid → transparent PNG via mermaid-cli 11.12.
  Content-addressed cache (`IMG/_mermaid/{sha}.png`, key = source + config + renderer
  version) because each render spawns headless Chromium: **measured 7.3 s cold, 3.6 s warm**
  against a 30-minute job budget with ~6 min of headroom. Fallback-first throughout —
  missing `mmdc`, a parse error, a timeout, a zero-byte cache entry and `BD_MERMAID=0` all
  return no image and no exception.
- **`build_sankey`** — the money engine reaches the HTML for the first time. **170 deep
  reports** carried a diagram Obsidian rendered and the delivered artifact did not. Embedded
  *before* the charts and its bytes passed into `build_charts(used=…)`, so the 1.5 MB image
  cap stays **one shared allowance** instead of quietly becoming one-per-builder.
- **`build_swot`** — 2×2, Threats first (the prompt weights them double). Quadrants matched
  by **label, not position**, and the parser handles both table layouts in the corpus.
  **40/40 SWOTs parse complete.**
- **`build_thesis_duel`** — bull/bear table + the LEAN verdict, with the direction reaching
  the CSS class. **10/10 duels render**; pre-v4.2 reports correctly render nothing.
- **Single-asterisk italics** now render. `*and*`, `*negative*`, `*(inferred)*` all occur in
  real prose and the asterisks were leaking into the HTML verbatim.
- **9 doc diagrams committed as PNGs** in `docs/IMG/`, source kept in a collapsed
  `<details>` — pdfgen has no mermaid support at all, so a PDF of `STRATEGY_GUIDE.md`
  previously showed a raw code block.

**Four defects found by running the new code over the whole corpus rather than one sample:**

1. **`sankey.nodeColors` is not a Mermaid API.** The string appears nowhere in mermaid
   11.12's distribution — the version behind both mermaid-cli and Obsidian. Since v3 Phase 5
   the prompt had asserted it *was* the official API, so every diagram carried a 15-line
   colour map that did nothing **and a mandatory legend describing a palette the reader never
   saw**. `themeVariables.cScale0..N` was tested as an alternative and is ignored for sankey
   too. Verified against `2026-08-12_FAE.MC_review.md`, which emits the full map and renders
   in the defaults. Prompt and `SKILL.md` corrected; the report caption now says the hues
   carry no meaning. The referenced `IMG/sankey_money_engine_demo.png` never existed either.
2. **Two mermaid preambles hid the diagram from the extractor** — a `---` YAML config block
   and an `%%{init:…}%%` directive both returned the wrong diagram kind. Fixed; **114/114**
   sankeys in the corpus now extract.
3. **`STRATEGY_GUIDE.md`'s Layer-3 diagram did not parse at all** (chained `-->` plus a
   backtick-string node containing `<slug>`) — it has been a broken block in the docs, not
   just an unexported one.
4. **`_sources/Stocks - buy 5y.md` had an unterminated fence**, and the dead P/E gate the
   audit found: node `B` routed *both* Yes and No to `C`, leaving `Reject2` ("Overvalued")
   unreachable. Both fixed before rendering, so the PNG does not bake in the bug. The note
   now carries an explicit warning that it is a **legacy source**, not the implemented
   screen — its thresholds diverge from `evaluate_gates()` (Gate 2 is
   `P/E < 35 OR (PEG < 2.5 AND ROE > 20%)`, and Gate 3 `FCF > 0` has no node at all).
   Re-cutting the ladder to match the code belongs to the §3.1 audit.

**2.8 — ⭐ five-star quality ratings, 100 % deterministic.** Five dimensions from bands
published in the new `docs/STAR_RATINGS.md`. **No LLM residual**: a star printed in a report
is a structured number, so an LLM-set star would breach the ground-truth rule exactly as an
LLM-set P/E would. Either it computes from the bands or it renders `n/a`.

- **Computed in the renderer, not persisted.** A stored star could disagree with the
  published bands after a band change; a computed one cannot. A CLI gives other consumers
  the same numbers from the same JSON.
- **Financial quality is the one weighted dimension** (Piotroski ×2, Altman ×0.5). Equal
  weights produced a flat column on real names: 9880.HK printed four stars off a Piotroski
  of 3/9 because an Altman Z of 8.9 pinned that component at five. Above its own 3.0 "safe"
  threshold Altman carries **no further information**, so an unweighted average let one
  saturated ratio outvote a nine-signal composite.
- The scanner's three statement sub-scores count as **one** component — as three they
  over-weighted a single source and pushed screens over a coverage cliff (IBM's 2026-08-15
  screen printed `n/a` for a dimension its Piotroski and Altman answer perfectly well).
- Rounding is **half up**; banker's rounding printed the same star for two companies half a
  star apart. Coverage is measured in **weight**, not count.
- Anti-drift tests assert every threshold and weight in the code appears in
  `STAR_RATINGS.md`, so "the doc is the contract" is enforced rather than hoped.

**2.4 — the one-page cover.** `build_cover` + a `.cover` section: page 1 is the answer
(verb · verdict · score · price · fair value · MoS · GO/NO-GO · ⭐ · thesis · risk · bear
trigger), then a six-group key-financials strip. Every field already existed in
`fundamentals`/`top_strip`, so this is **layout, not new computation** — zero budget cost.

- **The cover sits outside `<main>`**, directly under the header. Inside `<main>` it landed
  on printed page 2 behind the hero radar — found by print-media screenshot, which is the
  only way to see it.
- **Measured at A4** (726 × 1039 px @96dpi): four real covers land at 887–954 px. The header
  collapses to a slim band in print — every fact in it is repeated on the cover below —
  which recovers the ~90 px that had CSCO overflowing by 14. Type size is deliberately
  unchanged; a cover needing a magnifying glass defeats the purpose.
- **Never prints zero for an absence**, and `<0.01` where a real ratio would round to
  `0.00` — MPWR's D/E of 0.00486 read as a debt-free company.
- ROIC falls back to **ROE with the label changed** when the v4.2 `IC_MIN_FRACTION` guard
  returns `None`. Not a workaround: ROE is the right metric for a cash-rich balance sheet.
- A duplicated exit trigger is suppressed — `exit_plan.thesis_broken_trigger` is frequently
  a verbatim copy of `bear_case_trigger`, and printing both spent a third of the answer band
  restating one sentence.
- `COVER_PROSE_BUDGET_CHARS` is **advisory**: over budget logs, never truncates. Clipping a
  bear trigger mid-sentence is worse than a cover that runs a line long.

**2.4b — GuruFocus deep link per ticker** (`markets.gurufocus_url`, 17 venues).

The prefix is GuruFocus's own namespace, **not** the Yahoo suffix and **not reliably the ISO
10383 MIC**: Paris is `XPAR` (a MIC) but London is `LSE`, Tokyo `TSE`, Hong Kong `HKSE`,
Milan `MIL`, Copenhagen `CSE` and Taipei `TPE` — none of which are. Deriving them from the
MIC list, as first planned, would have shipped six broken links. Every mapping was **read off
GuruFocus's own pages** (breadcrumb + peer-compare strips) on 2026-08-15.

- **US symbols are bare** — `gurufocus.com/stock/IBM` resolves, which removes the NAS-vs-NYSE
  decision that was the one part of this not derivable from the ticker.
- Hong Kong pads to five digits (`0700.HK` → `HKSE:00700`, verified live).
- **Copenhagen is deliberately absent**: GuruFocus displays `CSE:NOVO B`, but both
  `CSE:NOVO%20B` and `CSE:NOVO-B` land on an empty search page. Whatever it routes on is not
  the string it shows.
- **An unverified venue gets no link**, ever. A 404 in a report you act on is worse than no
  link. 17 unmapped venues are listed by name in `markets.py` with the five-minute recipe for
  adding one.
- One existing test had to be narrowed: it banned the literal string `https://` from the HTML
  as a proxy for "self-contained". An `<a href>` is a hyperlink the reader chooses to follow,
  not a subresource the page loads, so the assertion now checks `src=`/`<link href=`/`@import`
  specifically — which is what "self-contained" actually meant.

**2.5 — valuation methods side by side, and the threshold was calibrated rather than
assumed.** `intrinsic_value.py` already computes a five-model blend; the report surfaced the
blend, which is precisely the number that conceals one model saying half what its neighbour
says. The card lays them out, shows invalid models **with their reason** instead of dropping
them, and quotes the spread.

- **The plan proposed a ~2.5× "methods disagree" banner. Measured, that fires on 61 % of
  reports.** Across the 59 analysis JSONs on disk the max/min spread of valid models runs
  p25 2.05× · **median 3.37×** · p75 5.79×, from 1.19× (0669.HK) to 40.3× (AMD). A warning
  that appears on most reports is wallpaper and the reader stops seeing it exactly when it
  matters. The banner is set at **6.0×**, which fires on ~24 % — roughly the top quartile.
- The spread is printed on **every** report regardless, so a 4× can be judged rather than
  inferred from the absence of a banner.
- The blend row no longer restates every exclusion reason — that prose is already on the
  excluded model's own row, and two paragraphs of it buried the number the row exists for.
- Closes the shape of roadmap **N4**: MSFT publishing `fair_price` $118.35 against a $550
  consensus median is now a visible disagreement rather than one blended figure.

**2.6 (part) — the cumulative index and the version watermark.**

- **`index.html` — the file the bookmark opens — is now the CUMULATIVE index**, rebuilt on
  every run via `docs/_build_index.py`; the per-date hub moves to `_index_{date}.html`. The
  two files were never duplicates, and that was the actual bug behind "the index is out of
  date": `index.html` was a single-date hub **overwritten every day**, so yesterday's
  reports vanished from it, while the cumulative index lived at `_index.html` and nothing
  scheduled its rebuild — stale since **2026-08-06**.
- `refresh_cumulative_index()` **never raises**: a missing builder, a non-zero exit, a
  timeout and an exit-0-that-writes-nothing all log and return None. Phase 6 is exactly the
  step the 2026-08-15 timeout skipped, so it must not be able to end a run after the reports
  are already on disk.
- ⚠️ `_index.html` is left on disk as an orphan rather than deleted — worth removing once
  nothing is confirmed to link to it.
- **Version watermark**: the footer gains `· user: {username} · skill v{__version__}`, read
  from `scripts/version.py`. A skipped bump is now visible on the face of every report.

Email delivery (the other half of 2.6) is **not** shipped: the plan requires choosing a
mechanism first, because `file://` links in a digest are dead on a phone, which is where the
digest is read. Nothing was removed from the current digest.

**2.1 — peers 5y.** `{date}_{ticker}_peers5y.png`: five years of **total** return
(`auto_adjust`, dividends reinvested), every series converted to EUR through
`markets.eur_fx_pair` before indexing to 100, subject against its 3-5 named competitors.

- The peer set comes from `score_details.peer_info.peer_tickers` — **the same set the peer
  sub-score ranked** — so the two peer charts can never name different companies.
- The resolution tier prints on every render and the loose tiers (`by_industry`,
  `by_sector`) are flagged **amber**. Roadmap **N5** is what an unlabelled sector fallback
  looks like: adidas ranked against Amazon, McDonald's, Home Depot and Starbucks.
- A peer whose FX cross fails to fetch is **dropped and named**, never compared
  unconverted. GBp needs no special case — a constant factor cancels in the indexing.
- The common start is the **subject's**, so a peer that listed two years ago cannot
  truncate everyone else's five-year window; a peer too short for the window is dropped.

**2.2 — long-horizon evolution.** `{date}_{ticker}_evolution.png`: price · P/E +
price/EBITDA · EBITDA + EPS, on one shared year axis. Three defects found by rendering
real data, not by reading the spec:

- **A phantom 150× multiple at MPWR FY2024.** `market cap = P/E × net income` is exact only
  if reported EPS is GAAP net income per share. AV pairs an *adjusted* EPS of 14.13 with a
  one-off-inflated $1.79bn net income → 126m implied shares against ~48m either side.
  `consistent_share_years()` now tests that premise directly against each year's nearest
  neighbours, which tolerates buyback drift and catches a spike. Rejected years are dropped
  and named in the caption.
- **A collapsed final year** from a partial-year EPS stub (MPWR `2026-06-30`) — the same
  defect `valuation_bands` hit with VEEV. `drop_offcycle_records` is **imported** from
  there rather than re-implemented, so the two cannot drift apart.
- **22 years of compounding flattened into a baseline.** The price panel switches to log
  scale above a 20× range.

The second line is called **price/EBITDA and never EV/EBITDA**, in the axis label, the
legend and the docstring: net-debt history is persisted nowhere, so an enterprise multiple
cannot be computed per year, and labelling an equity one as enterprise flatters exactly the
leveraged names where it matters.

`--freq quarterly` was specified and **dropped after checking what exists**: there is no
quarterly EPS or P/E series anywhere in the system, so the multiples panel cannot be drawn
quarterly at all, and price + EBITDA quarterly is precisely the existing `ebitda_fcf`
chart. The flag would have shipped a broken panel or a duplicate.

Depth floor measured across all 54 cached names: **25 render, 29 do not**. Every
yfinance-sourced name sits at 4 years and is blocked, as the plan predicted — this chart is
a US artefact until roadmap **N0**. (Separately observed: 9 AV names cache only 6 annual
years while 25 cache 8-31, and it is not a cache-age effect — AV's own coverage varies.)

**Image budget re-measured BEFORE adding** (plan item C2): a full MPWR deep dive now spends
**459 KB of the 1.5 MB cap**, 31%. Unchanged. Added wall-clock: **7.5 s** on a 22-24 min
budget, so both charts are default-on rather than flagged.

**2.7 — SWOT materiality.** Each item now carries **MATERIAL** or *minor* with the test in
the prompt: *would it change the verdict or the position size?* MATERIAL renders in full ink
with a red marker, minor set back in muted grey. The 40 SWOTs already on disk carry no tags
and keep rendering as prose — inventing a bullet per sentence would fabricate a structure
nobody wrote. Two prompt defects fixed alongside: the prompt asked for `###` sub-headings
while §2.18a consumes a **table**, and the `red_flags` cross-reference was described but not
required (every `bad`/`warn` flag must now appear in Threats or Weaknesses).

The **2×2 quadrant PNG is deliberately not shipped**. The corpus quadrants are dense prose,
so the image would be a wall of unreadable, unsearchable, fixed-width type duplicating the
card above it. 2.7's stated purpose — get the SWOT into the HTML at all — is served better
as text.

**2.4a — earnings commentary.** `prompts/08_earnings_commentary.md`: what management *said*
and what *changed* — guidance, segment reversals, margin direction and the reason given,
one-offs, tone versus the prior print, and any new risk language named explicitly.

The plan called this a new section, on the premise that nothing in the report reads the last
print. **That premise was wrong**: §2.7 and §2.8 have always been this job. What they lacked
was the filing, and MPWR's 2026-08-14 report says why in its own words — *"SEC EDGAR is not
fetched directly per the skill's 403 policy"* — a policy Phase 1.5 removed in wave 1.3
without anyone rewiring these sections. A new §2.6d would have been a third overlapping
section while the two originals kept printing "narrative unavailable". So the commentary
lands in §2.8/§2.7, and Phase 4 now fetches EDGAR **first** for US names with
`get_narrative.py` as the fallback — the doctrine already said this; only the instruction
still routed through the yfinance blurb.

Opt-in (`BD_EARNINGS_COMMENT`), default **off** on the 13:30 path: a WebFetch plus an LLM
call per ticker across three picks, on a job at 22-24 min of a 30-min ceiling. The
ground-truth rule is restated **inside** the prompt rather than inherited — handing an LLM a
document full of numbers and asking for prose is the likeliest place in the skill to leak an
LLM-read figure. No third exception.

**Tests**: 1268 passed, 1 skipped (from 1001 at Wave 1 close) — +267.

---

### Wave 3 — audit, doctrine & category lens (2026-08-15, in progress)

**§3.5 `category_lens.py` — cyclical / turnaround / asset play, as tests.**
`lynch_category()` covers 4 of Lynch's 6 categories and its "cyclical" is the residual
bucket, not a test. The expensive consequence runs the other way: a **cyclical at peak
earnings reads as a `stalwart`**, shows record margins and a low trailing P/E, and passes
Gate 2. `lynch_category` is left untouched (it feeds a scored component, so changing it
would move the frozen composite); the classification ships beside it and names the
disagreement in words. Thresholds published in `docs/CATEGORIES.md`.

Four corrections the 53-name corpus forced, none of them guessable from the spec:
- **Loss years break the arithmetic** — `(peak−v)/peak` is unbounded below zero, so AMD's
  six loss years produced a 319 % "drawdown" and five phantom cycles. The test now runs on
  the longest positive run and names the window it used.
- **A one-year plunge is a write-down** — P&G's FY2019 Gillette impairment counted as a
  completed 54 % cycle. Elapsed time from the peak did *not* fix it (P&G's peak sat eleven
  years earlier); **consecutive** years below the threshold does.
- **A fall that never returns is a secular decline** — IBM, called cyclical at high
  confidence across the Kyndryl spin. Reported separately, and disqualifying: there is no
  mid-cycle to revert to.
- **First profitability is not a turnaround** — PLTR was flagged beside adidas; one
  recovered a known earnings power, the other reached an unknown one.

Plus two unit errors it refuses to publish: RIO.L at **280× book** (a pence quote against a
GBP book value) and BRK-B at **0.001×** / TSM at **82×** (share class and reporting
currency), caught by cross-checking `book_value` against equity/shares with a tolerance set
from the 122-name distribution.

**§3.6 `roic_lens.py` + `docs/ROIC_vs_ROE.md` — which return metric applies.** Flags
leverage-manufactured ROE (>20 % on >1.0× D/E with <12 % ROIC — **3 of 147**), computes ROIC
vs WACC from the CAPM cost of equity already in the JSON plus a derived cost of debt (no
cost of equity ⇒ **no WACC**, never an assumed one), routes banks and insurers to ROE/ROTE
(**22 of 147**), and says out loud that the Buffett moat multiplier silently does not fire
when the net-cash guard suppresses ROIC (**12 of 147**, VEEV among them).

Both are pure JSON consumers — zero network, zero API calls, <0.1 s per ticker. New report
card **§2.20c**, new **Phase 2.4b**. `_STMT_ROWS` gains four intangibles rows, read from the
balance frame already in memory.

**§3.1 `docs/AUDIT_v43.md` — four lenses, measured against live code and the corpus.**
Three roadmap items closed with fixes:

- **R4** — Twelve Data answered `ADS.DE` from **XSTU (Stuttgart)** with a stale €182.25
  while Xetra had gapped −18 %, and the gap was logged as a yfinance `data_quality: suspect`
  flag. `td_exchange` was already captured and never read. A cross-venue gap is now named
  and excluded from `agree`; an **unrecognised venue stays silent** rather than
  manufacturing the same false flag from the other side.
- **N4** — `fair_price` came from a DCF that survived its ±70 % gate by **0.30 pp**, so MSFT
  published **\$118.35** against a live \$390.54 and a \$550 consensus. Now deterministic:
  blend → blend_median (models disagree ≥6.0×, the same threshold as the §2.11a banner) →
  dcf → consensus → omit. Measured over 62 analyses: 42 blend · 13 blend_median · 5
  consensus · 1 dcf. MSFT moves to **\$303.28**. Computed in Python, no longer transcribed
  by the LLM from a prose rule.
- **N3** — adidas' **3-year** P/E band, median 47.73×, drove a €608 target and a first trim
  rung at **2.9× the price**. Writing both of N3's conditions into one usability test was
  tried first and marked **41 of 48** cached bands unusable, ACN (16 y) and CSCO (14 y)
  among them; the shipped split excludes the collapse year from the series and applies only
  a 4-clean-year depth floor to what survives. Re-measured: **44 usable · 3 unusable**.

Findings deliberately **not** acted on, with their evidence recorded (new roadmap **G3**):
Gate 7 (`quick ratio > 1.5`) is the binding gate at **32 % pass** and selects *against* the
mandate's negative-working-capital compounders; Gate 4 passes **85 %**; the v2.2 growth
bypass fired **twice in 267**. All three move `gates_passed`, hence the composite frozen at
v2.2 — they belong to the G1 recalibration (≈2026-10-17), not to an audit. Likewise new
roadmap **R6**: the balance sheet's `shares` row falls through to `"Common Stock"`, a par
value on some filers, which would silently re-rate 40+ reports through the red-flag
sub-scores if fixed casually.

**Tests**: 1397 passed, 1 skipped (from 1268 at Wave 2 close) — +129.

---

### Wave 4 — new surfaces (2026-08-15)

**§4.0 `docs/PORTFOLIO_DATAFLOW.md`** — the prerequisite for the monitor skill, verified
from the live code, the live Task Scheduler and the run logs. The chain works: wages →
audit → report → BankBD import; last run 231 payslip values agreeing and 0 differing,
1041 snapshots imported, exit 0; all ten finance tasks `Ready`.

Two plan premises corrected by reading the code: the **BankBD importer was never broken**
(it resolves by header, Trading212/eToro/CGD are mapped, the unmapped check is
bidirectional) — what is missing is one reconciliation assert, ~1 h; and **"automate bank
cash" tops out at 10 of 17 live columns**, with PSD2 consents expiring ~90 days. The real
gap is position lots: nothing writes back to `Accoes (BD)`, and `workbook.read()` is
hard-wired to the `Dados` sheet.

**§4.1 `/bd-stocks-monitor`** — the four guardrails existed only as prose, so a P/E of 140
on a holding broke a rule nobody evaluated. `monitor_alerts.py` makes each a pure function
with `computable` on every alert. `recommendation_ledger.py` scores the skill's own calls
off `price_at_eval`.

The first live ledger run was **wrong**, and the correction is the interesting part: it
printed a mean of **+601 %** for `invest` against a **+4.63 %** median, and every outlier
was a London name — `_log.csv` stores GBP while yfinance answers in GBp. The same pence
defect that printed RIO.L at 280× book in wave 3.5, from the other direction. Fixed twice
over: the fetcher normalises, *and* a guard excludes any |return| over 500 % as a unit
mismatch, because no price source is trustworthy enough to skip it.

**The corrected answer**: 378 of 384 calls scored, `invest` median **+4.63 %**, `reject`
median **−1.34 %**, spread **+5.97 pp**, and `reject` beat the benchmark only **29 %** of
the time against ~48–50 % elsewhere. The composite discriminates, mostly on the downside.

**§4.2 `universe_admin.py`** — `--add-ticker` and `--list-pending`, shipped **with**
roadmap **R3** rather than before it: the prefilter wiped pending every run and never wrote
`_universe.yaml`, so a seeded ticker was evaluated once and vanished. First real answer:
**1441 of 1720** universe names have never had a `_log.csv` row.

**§4.3 `screeners.yaml`** — nine declarative screens replacing browser-localStorage
presets, plus the full metric set on the screener rows. The three genuinely missing
metrics: EBITDA margin (derived), cash-flow/EBITDA (from `statements_raw`), and the
"P/E TTM" question — **measured, and they are the same number**, so the screener ships
`pe` and `forward_pe` rather than one figure under two headings.

**§4.4** — growth cadence: **keep it daily**. 71 names across 15 runs with **zero repeats**
means the job is still on its first pass. The trigger to revisit is the first repeated
ticker, not a calendar date.

**§4.5 brokers** — 4 EU venues added (`.AS/.PA/.DE/.L` had no cost comparison at all) and
3 entrants (Bankinter, eToro, Trading 212) whose **tariffs were not invented**: they carry
`verified: false`, are excluded from every cost matrix, and name what must be filled in.
What *is* filled in is the statutory layer, which answers the plan's actual question —
cash at a credit institution is a **deposit** covered to €100,000; segregated client money
at a broker is **not**, and falls back to a €20–25k investor-compensation scheme.

**Tests**: 1506 passed, 1 skipped — +109.

### Wave 5 — packaging (2026-08-15, indirection only)

`skills_root.py` resolves `%BD_SKILLS_ROOT%` → its own location → the current absolute
path. **The third rule is the point**: unconfigured, everything resolves exactly where it
did before, which is what makes this safe to land ahead of the cutover. The three runtime
coupling points (`run_prefilter` imports `analyze_ticker` in-process, `growth_analyze`
shells out to it, `pick_earnings_review_targets` imports `listings.REGISTRY`) now resolve
through it. `bd-finance/.claude-plugin/` declares v4.3.0 and all eight skills.

**Not done, deliberately**: moving the skills, re-pointing the bats, re-registering any of
the ten live tasks. See `docs/PACKAGING.md` for the five-step cutover.

**Tests**: 1516 passed, 1 skipped — +10.

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

---

## Anexo — os parágrafos originais do `SKILL.md` (migrados verbatim 2026-08-15)

As entradas por versão acima são **resumos** escritos para este ficheiro. Estes são os
parágrafos originais que viviam no cabeçalho do `SKILL.md` até à v4.3 §3.3, movidos aqui
**sem alterar uma palavra** — a migração da wave 0 tinha-os resumido, e um resumo não é uma
migração. Guardados pelo detalhe operacional (nomes de ficheiros, números de spec, decisões
datadas) que os resumos deixaram cair.

**v3.1 (2026-07-15)** acrescenta ao report deep: série trimestral **EBITDA + FCF** com forecast 4Q híbrido (`financial_history.py`, Phase 2.2, cache `_fin_history/`), **metrics strip** no topo (bloco `top_strip` do analysis JSON; screens também), chart de **revenue sources** 3 anos (`_segments/`, excepção LLM documentada), chart **relative performance 30 meses** vs benchmark regional + sector ETF, tese/risco **promovidos em callouts coloridos** (labels de parser preservados), secção **§2.20 broker (€1500)** para composite ≥ 7.0, e secção **§4 macro** com cache diário `_macro/` (Phase 2.6, prompt `macro_daily.md`).

**v4 wave-1 · Phase B (2026-07-22)** acrescenta ao deep a **valuation depth** (spec rev 3 §7, overlay-only): bandas P/E & P/S da própria história (`valuation_bands.py`, Phase 2.3), forward target FY+3 TIKR-style (target @ data + est. return + IRR), sensitivity table com margin-bear row, e o bloco de **intrinsic value 5-modelos com blend + margin-of-safety** (`intrinsic_value.py`). Composite v2.2 intocado; keys aditivas no analysis JSON (`valuation_bands`, `intrinsic_value`).

**v4 wave-1 · Phase A (2026-07-22)** acrescenta ao deep o **exit & thesis plan** (spec rev 3 §6, overlay-only): bloco `exit_plan` (`exit_plan.py`, Phase 2.55) com target exit P/E (mediana da banda própria, capped), fair-value range, **profit-take ladder** ancorada no fair value (+ rung de custo 2× só para tickers held — cost basis de `_portfolio_holdings.yaml`, NÃO BankBD: positions vazias, decisão 2026-07-22), thesis-broken trigger, ATR context (OFF by default) e **yield-on-cost**; chart dual-axis **Net Income vs P/E** (`ni_pe.png`, série `pe_band.series` + `annual.net_income` novos); secção §2.12 no report + linha `Exit:` no TL;DR.

**v4 wave-1 · Phase C (2026-07-22)** acrescenta ao deep o **red-flag scanner + Beneish + 3-statement review + SWOT** (spec rev 3 §8, overlay-only): bloco `red_flags` (`red_flags.py`, Phase 2.4) com veto bearish por statement (Income/Balance/Cash-Flow), **Beneish M-score** (8 índices, flag se M > −2.22; "not computable" em non-US sem line items), earnings-quality CFO-vs-NI e dois **pills positivos** (net payout yield > 4%, ROCE ≥ 20%); **três sub-scores 0-10 determinísticos** por statement (hit-rate dos flags computáveis, pass=1/warn=0.5/bad=0) que **nunca entram no composite**; prompt novo `06_swot.md` (Phase 2.5, quadrante Threats/Risks com dupla profundidade). `analyze_ticker.py` passa a persistir um snapshot aditivo `statements_raw` (2 anos) para o scanner ser **puro consumidor do JSON — zero re-fetch, zero chamadas API novas**. Secções de report: cartão red-flag traffic-light + três sub-secções de statement + cartão SWOT. Composite v2.2 intocado; keys aditivas (`statements_raw`, `red_flags`).

**v4 wave-1 · Phase D (2026-07-22)** expande a secção macro (spec rev 3 §9, overlay-only, cache `_macro/`) para o "§8" que o Bruno esboçou — duas gauges **puras yfinance** (`macro_breadth.py --update`, Phase 2.6, keys aditivas `breadth` + `sectors` no `_macro/<date>.json`, nunca toca `metrics`): **breadth RSP/SPY** (equal-weight vs cap-weight, percentil na própria história multi-anos + seta de tendência; scan-2 p07) e **tendências sectoriais** (11 SPDR ETFs + linha SPY: tendência 20d-vs-60d MA + direcção de volume + check "volume confirma?"; idea #10) — mais três gauges **sourced via WebFetch** no prompt `macro_daily.md`: **valuation vs história** (P/E/P/S/CAPE/P/B vs mediana/±1SD), **Buffett Indicator + regime de liquidez M2** (FRED `M2SL`), e **forward-profit horizons** ao nível do índice (3m/6m/1Y/2Y/3Y). Cada gauge degrada de forma independente ("not available" — uma falha nunca apaga a secção). O report §4 embeda um resumo curto das novas gauges; detalhe completo no `_macro/<date>.md`. Composite v2.2 intocado.

**v4 wave-1 · Phase E (2026-07-22)** acrescenta ao deep o **return profile** (spec rev 3 §10, overlay-only): bloco `alpha_beta` (`alpha_beta.py`, Phase 2.56, corre sob Python312 ambiente) com **α/β** 3y vs benchmark regional (β=cov/var, α=Jensen anualizado), **linha CAPM** (realizado vs esperado, rf reutilizado de `intrinsic_value.capm.rf`), **price-CAGR ladder 1/3/5/10/15y** (closes mensais ajustados — o sinal de longo prazo, já que o CAGR de revenue raramente chega a 10/15y), **Lynch prior** (categoria → banda retorno/drawdown) e **portfolio fit** (α/β da carteira vs URTH, série ponderada FX→EUR das holdings equity, cache diário `_portfolio_riskprofile.json`) — `β 3y`/`α 3y` injectados no `top_strip` (metrics strip); secção §2.20a no report. Mais: a **watch-list price-triggered** (`watchlist.py`, Phase 2.57) — nomes de qualidade (composite ≥7) travados só pelo preço (`mos_class == "rich"`, não-held) entram no `_watchlist.csv` (target = fair-low), e o **email diário** ganha um bloco vermelho "⭐ Watch-list triggered" + tag `[WATCHLIST: n]` no assunto quando `live ≤ target`. E o cap anual de `financial_history.py` subiu de 6→20 anos (enablement dos rungs de CAGR de revenue quando a fonte for funda o suficiente). Composite v2.2 intocado.

**v4 wave-1 · Phase G (2026-07-22)** acrescenta ao deep o **opinion panel** (spec rev 3 §10b, overlay-only): bloco `opinion_panel` (`second_opinion.py`, Phase 2.58, sob Python312 ambiente) — segunda opinião de um modelo **independente** (Groq `llama-3.3-70b-versatile` → Gemini `gemini-2.0-flash`, via novo `llm_client.py` reutilizável), **3 personas** (value/growth/contrarian) que devolvem `{verdict, conviction_0_100, one_liner}` na escala 0–100 (50=neutral). **Independência garantida**: o painel vê a evidência (`compact_evidence`) mas NÃO o composite/verdict — esses são excluídos do input. Consenso = mediana; divergência sinalizada se spread≥25 ou |mediana−composite×10|≥25. Uma persona morta degrada para "not available" sem bloquear as outras. Secção §2.20b + linha no TL;DR. Composite v2.2 intocado.

**v4 wave-1 · Phase F (sessão 1, 2026-07-23)** entrega o **renderer HTML-primário** (spec §11): `render_report.py` (Phase 5.7, puro stdlib) + `report_template.html` (CSS portado do mockup locked `sample_report_v2.html`). Lê o `.md` (fonte, contrato congelado — teste de regressão `slim_report`) + o analysis JSON → escreve `{report}.html` self-contained/estático/JS-free. Header answer-first com **action verb determinístico** (`verdict × mos_class × go_no_go → ACCUMULATE/BUY-DIP/HOLD/WATCH/AVOID`), **snowflake 5-eixos** (Quality/Value/Growth/Health/Mgmt derivado dos 7 `scores`) em SVG inline, gauge fair-value + range bar, cartões A/B/C/E/G, peers A–D, PNGs base64 ≤1.5 MB, null-renders, moeda do JSON. Email intocado (HTML nunca inlined). 413 testes. **Sessão 2 (2026-07-23)**: metric families Equity-vs-Enterprise + cheat-sheet greyed em 3 modos (tooltip/`<details>`/coluna print, `metrics_glossary.py` estático) + `index.html` hub diário (`--index`); 422 testes → **wave 1 COMPLETA**.

**v4.1 wave-2 · Phase H (2026-07-23)** acrescenta ao deep o **news & market sentiment** (spec §11c Phase H, idea #6, overlay-only): bloco `news_sentiment` (`news_sentiment.py`, Phase 2.59, sob Python312 ambiente). Recolhe headlines (**yfinance news primário**; opcional **1 query** NewsAPI na trial key `api_key_newsapi` — descartável quando os créditos acabarem), depois **1 chamada LLM** (via `llm_client`) classifica-as em dois diais **stock** e **market**, cada um −1..+1 com temas + citações. **NÃO entra no composite** (sentimento é contexto, não gate) — complementa o `news_freshness`. Funde a key aditiva `news_sentiment`. Cartão de report `build_news_sentiment` (dois diais + headlines) + chip 📰 no email digest (via frontmatter `news_sentiment_stock`/`_label` → `slim_report`) + linha no TL;DR. Degrada para cartão n/a sem headlines/chave. Composite v2.2 intocado. 439 testes.

**v4.1 wave-2 · Phase I (2026-07-23)** transforma o dashboard principal num **screener** sobre o **pool pré-filtrado completo** (spec §11c Phase I, idea #11). `build_dashboard.py` ganha `load_universe()` (leitor YAML stdlib de `_prefiltered.yaml`), `enrich_from_tmp()` (P/E + FCF yield dos overlays `_tmp`) e `build_screener()` (universe LEFT JOIN evaluations, β/α/MoS durables do frontmatter dos reports, `_tmp` suplementa) → nova key `screener` no bundle. O `template.html` (na vault) ganha uma secção **Screener** (hub, no topo): filtros de categoria (region/sector/size/verdict/evaluated) + **range filters** (score/upside/P/E/β/α/MoS%/tech), **presets guardados em localStorage**, **export CSV**, e linhas que **deep-linkam para o report HTML** (Phase F). Top-nav ganha "Screener". Client-side vanilla-JS (mesmo padrão `__DATA__` + Grid.js). 449 testes (+10 no data layer); lógica de filtros/CSV/presets verificada num harness Node sobre o bundle real (179 linhas: round-trip de filtro, preset sobrevive reload, CSV). α/β ficam esparsos até o job diário re-correr o pool sob Phase E — mostrados com honestidade, nunca fabricados. Composite v2.2 intocado.

**v4.1 wave-2 · `--version` flag (2026-07-23)** adiciona um arg de orquestração `--version {v3, v4}` (a par de `--ticker`/`--mode`). **A última versão é SEMPRE o default** (regra dinâmica: `LATEST = VERSIONS[-1]` em `version_gate.py`, não um valor fixo). `v4` = pipeline completo; `v3` = pipeline **menos os nós overlay v4** (2.3 valuation_bands/intrinsic_value, 2.4 red_flags, 2.55 exit_plan, 2.56 alpha_beta, 2.57 watchlist, 2.58 opinion_panel, 2.59 news_sentiment, 5.7 render HTML) → cai na shape v3.1 (md-primário). Barato só para v3↔v4 porque v4 é overlay-only sobre schema 2.2 → **o composite é byte-idêntico** (o flag muda o que renderiza, nunca o score 0-10). v1/v2 antecedem o schema 2.2 (pesos/gates diferentes) e **não são alcançáveis pelo flag** — só via git tags + worktrees; o enum começa em `v3`. `version_gate.py` é a fonte única do mapa versão→nós-a-saltar; 10 testes. Composite v2.2 intocado.
