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

*(R2 removed 2026-08-16 — **two of its three gauges shipped** as `scripts/macro_fred.py`;
the third is now **N6** below, because it is not buildable rather than not built. §6 had
rendered "not available" for its whole life for one reason: the prompt asked an LLM to
WebFetch what a pinned API already serves. FRED M2 reads $23.16 tn, **+5.53 % YoY** with
the 3-month running hotter at **+8.72 %**; the Buffett Indicator reads **218.1 %** as of
Q1 2026. Units are read from the series metadata and converted explicitly —
`NCBEILQ027S` is published in millions and `GDP` in billions, so multiplying straight
through gives a ratio wrong by 1000× — and the ratio is taken on the latest quarter both
series cover, since the equities leg lags GDP by one. Per-gauge independent degradation
kept. See `CHANGELOG.md` v4.3.1.)*

*(R3 removed 2026-08-15 — **shipped** with v4.3 wave 4.2. `run_prefilter.py` now promotes
ANSWERED pending entrants (pass or fail) into `_universe.yaml` before wiping PENDING, so a
ticker added through `--add-ticker` survives past one Monday. Answered rather than only
passing, deliberately: the universe is the WORK LIST, not the pool, and a name that fails
this quarter may pass the next. Names that keep ERRORING are still handled by RETRY/PAUSED.
A test asserts the promotion happens before the wipe — reversed, it would promote nothing.
See `CHANGELOG.md` v4.3 wave 4.)*

*(R6 removed 2026-08-16 — **shipped** as `scripts/share_basis.py`, and the entry's own
hypothesis was wrong. It blamed the `"Common Stock"` fall-through for being a par value in
currency. Measured against `fundamentals.shares_out` across **147** analyses: 86 agree
within ±5 % and the other 61 are off in a **continuous spectrum from 1.05× to 25.6×**,
which is not what a currency-vs-count confusion looks like. Three distinct causes wore one
label — `"Share Issued"` including treasury stock (IBM 2.43×, AMAT 2.52×, P&G 1.72×), a
different share class or quote ratio (TSM exactly 5.000× = the ADR ratio, Roche 7.59×,
Samsung's Frankfurt line 25.6×), and stale filings below 1× (SMCI 0.918×). The extraction
is **unchanged**, so no composite moved; the basis is classified into an additive
`shares_basis` block and consumers act on it. Measured before/after over the corpus: **58
statement-P/B corrections** (IBM 16.44 → 6.76, AMAT 48.75 → 19.32, KLAC 115.53 → 53.67)
and **2 names newly refused** — Roche and Atlas Copco, whose basis mismatch cleared the 5×
P/B tolerance untouched. See `CHANGELOG.md`.)*

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

*(R8 removed 2026-08-17 — **shipped, and it was worse than the entry said**. R8 named
`bd-stocks-monitor` as "the only skill not under version control". An audit of all eight found
**five**: `bd-stocks-prefilter`, `bd-stocks-portfolio`, `bd-stocks-earnings-review`,
`bd-strategy-monthly` and the `bd-finance` plugin wrapper — while `bd-stocks-monitor` had in
fact been given a repo in the meantime. The entry was written from memory of one directory
rather than from a sweep, which is why it undercounted by four.
The blocker it recorded is also resolved: the packaging question ("one repo per skill vs one
`bd-finance` repo for all eight") is now settled as **one repo per skill**, with `bd-finance`
holding only `.claude-plugin/`. All five were initialised with `bd-stocks-daily`'s
`.gitignore` verbatim, key guard included, and each first commit records the working state
unedited so the NEXT diff means something. Verified no secrets in any of them before staging.
The immediate cost of the gap, for the record: the Y1 throttle fix — a suspected 429 must
never advance the pause counter — went into production on vmhost1 **uncommittable**, because
`bd-stocks-prefilter` had nothing to commit to. See `CHANGELOG.md`.)*

*(R13 removed 2026-08-19 — **shipped, both halves, verified off both machines.** Laptop:
three owned tasks that had no description at all now carry 1255 / 923 / 914 chars, states
unchanged, `NextRunTime` unmoved. vmhost1: the fourth landed through the XML fallback — `desc=381`,
still `Disabled`, `logon=S4U` — alongside the three written 2026-08-18. Shipped
`scripts/_task_description_engine.ps1` as the single write path for both host scripts, plus
`laptop_fix_task_descriptions.ps1`.

Three findings worth keeping. **(1)** The root cause first written here was wrong: it blamed an
empty `<Months>` list, and after an XML round-trip `<Months>` holds all twelve months while
`Set-ScheduledTask` still refuses. The real mechanism is that `Get-ScheduledTask` returns a
monthly `CalendarTrigger` as the **base** `MSFT_TaskTrigger` with no month, no day-of-month and no
week — the schedule is absent from the object — so the error is Windows refusing to write back a
trigger that lost its schedule on the way out. It cannot round-trip a monthly task on this build
at all, on either machine, which makes this the *same* defect R19 dodged rather than a cousin.
**(2)** vmhost1 has **no real PowerShell 7** — only the Store execution alias, which refuses to
launch non-interactively; over ssh it says "Access is denied" and wrapped in `cmd /c` it fails
**silently, exiting 0 with no output**. The RUN line now says `powershell.exe`. **(3)** The XML
route COMPLETES a degenerate trigger with Windows defaults: vmhost1's task exported no
`<DaysOfMonth>` and now carries `<Day>1</Day>`. That is a trigger change made by a fixer that
promised descriptions only — harmless here (the task is disabled, the laptop owns the job, and a
trigger with no day could never have fired correctly) but recorded in the engine header as a
pre-flight check. See `CHANGELOG.md`.)*

*(R22 removed 2026-08-19 — **shipped, decisions taken.** (a) `send_email.py` gained
`portfolio_stale_notice_html/text`, rendered **above** the cards they invalidate; until then
`_portfolio_export_stale.txt` was written by the ingest bat and read by **nothing** — the name
appeared in one doc and in no `.py` — so a 20-day-old cost basis fed held-detection, `exit_plan`,
the buy list and every EUR weight in silence. Self-clearing (the bat deletes the marker on a fresh
run) and it cannot cost a digest (any read failure returns `""`, same contract as
`run_cost_block`). It also prints the date the marker was flagged, which is how the live render
exposed the marker itself going stale — it said 18 days when the truth was 20. 6 new tests;
**1756 passed, 1 skipped**. (b) The export is **ad-hoc**, so the weekly ingest stays and an
unchanged CSV reporting `added/removed/changed: none` is documented as NORMAL. (c)
**Wednesday 12:30** is the decision — in `SCHEDULING.md`, both task descriptions, the vault memory,
and vmhost1's copy via `vmhost1_align_portfolio_weekly_trigger.ps1` (the cmdlet is safe there
*because* a weekly trigger has a real CIM class and round-trips, unlike the monthly ones). Two
side-findings fixed on the way: an orphan `StocksPortfolioWeekly` row left dangling outside the
`SCHEDULING.md` table made the file state the wrong time twice, and the `0x1` failure was not a
live defect — the export sits in the `YF` subfolder and the search path was widened the same
morning. The `StartWhenAvailable` catch-up that landed the 08-10 and 08-17 runs on Mondays is
recorded as a false signal: **a Monday run is not evidence of a Monday trigger.** See
`CHANGELOG.md`.)*

*(R23 removed 2026-08-19 — **decided and applied.** Owner's call: **allow the START on battery,
keep the stop.** `DisallowStartIfOnBatteries` is now `false` on `\BD\Finance\Patrimonio Monthly`
(`laptop_allow_patrimonio_on_battery.ps1`, verified: day 27 kept, `StartWhenAvailable` kept,
`Ready` kept, action and principal unchanged). `StopIfGoingOnBatteries` stays **true** on purpose —
the two settings look symmetric and are not: one decides whether work begins, the other can
interrupt work already in flight, and this chain writes `Patrimonio BD.xlsx` through Excel COM on a
copy with a timestamped backup, where a write killed half-way is worse than a run that never
happened. Together with the catch-up fix earlier the same day, the task had **never run once** since
registration on 2026-08-02 (`LastTaskResult 0x41303` = `SCHED_S_TASK_HAS_NOT_RUN`) and now has both
a catch-up and permission to take it.

**The remaining item is an observation, not work**: after **2026-08-27**, read `LastTaskResult` —
**not** `State`, which read `Ready` throughout the entire period this task had never executed.
`0x41303` means it still has not run; `0` means it did.

**One thing this exposed that was bigger than R23.** Reviewing what else starts unattended showed
**four enabled tasks firing at exactly 09:00** — this one, `StocksStrategyMonthly`,
`SyncSapEnv-To-vmhost1`, `Deslocacoes-Subsidio-Mensal` — three more at exactly 13:00, and **~30 of
the ~33 enabled `\BD\` tasks carrying `StartWhenAvailable=true` with no `RandomDelay` at all**. A
slot missed while the laptop sleeps fires as catch-up on the next wake, so a late logon started the
whole missed morning at once: the 2026-08-15 incident (growth and daily both stamped `_1336`, both
at their ceilings, digest lost) generalised from two tasks to twenty, and `job_lock.ps1` only ever
protected the Stocks pair. 27 tasks now carry a `RandomDelay` spread across 5–25 minutes
(`laptop_stagger_task_starts.ps1`, idempotent, delays derived from a hash of the task path so
re-running does not reshuffle thirty schedules). Three excluded with reasons. **`RandomDelay` is
NOT a minimum** — Windows draws from zero to the value — and a hard floor is not expressible on a
calendar trigger at all, so what this buys is de-correlation, which is the actual cause. The
verification had to read the **XML**, not `$task.Triggers[].RandomDelay`: a monthly CalendarTrigger
comes back as the base `MSFT_TaskTrigger` with no such property, so the CIM read called seven
writes that had plainly succeeded a failure. See `CHANGELOG.md`.)*

*(R20 removed 2026-08-19 — **shipped and verified against vmhost1, which is the half that had
been impossible.** `stocks-skills-push.ps1` now carries **two sets under one lock**: the finance
skills as before, and the 13 launchers in `.scripts` (`_bd_env.bat`, `run_with_timeout.ps1`,
`job_lock.ps1`, ten `stocks-*.bat`) to `D:\Github\.scripts` — a different DRIVE, hence a second
root pair rather than one loop. Extending the proven, already-scheduled, already-locked mechanism
rather than writing a sibling, per the entry's own preference.

**The gap it closed, measured rather than asserted.** Before the push vmhost1 held **10 of the 13
files, and 8 of those 10 differed**; `_bd_env.bat`, `stocks-monitor.bat` and
`stocks-failover-watchdog.bat` were **absent entirely**. Diffing `stocks-daily.bat` showed the
divergence was exactly R10's work missing: vmhost1 still ran the **pre-R10** copy with hardcoded
`D:\Github\.scripts\job_lock.ps1`, `D:\...\run_with_timeout.ps1` and
`cd /d "D:\Github\BD\BD_Finance"`, against the laptop's `%~dp0`-relative, `_bd_env.bat`-probing
version. So the machine that has run the pipeline since the 2026-08-17 cutover was running
launchers three weeks behind the ones being edited.

**One hard dependency was checked BEFORE pushing, not after.** The new bats `call
"%~dp0_bd_env.bat"` and `exit /b 9` if `BDF` does not resolve — and that file was one of the three
missing. Pushing the bats without it would have killed the 13:30 job outright. Verified on vmhost1
first that `_bd_env.bat`'s probe target exists (`D:\Github\BD\BD_Finance\config\api_keys.txt`,
present) and that its FIRST candidate cannot win by accident (`/mnt/c/Github` exists there but is
**empty**, so the C: branch is absent and the D: branch is taken). After the push,
`_bd_env.bat` was executed on vmhost1 and returned **rc=0**.

**Two deliberate differences from the skills set.** (1) **No orphan deletion.** The skills tree is
meant to be a byte-for-byte replica, so an extra file there is drift; `D:\Github\.scripts` is
vmhost1's own script directory, holding its lock state and whatever else that machine legitimately
needs, and deleting "extras" would delete files the laptop has no opinion about. (2)
**`job_lock.ps1` is the one file that can break the push while the push holds its lock**, so the
remote copy is backed up before extraction and the RELEASE is used as the test: if releasing fails,
the backup is restored and released instead, loudly. A stuck global lock blocks every Stocks job on
the machine that runs the pipeline. On the live run the release succeeded with the pushed copy,
which is what proves it good.

Both manifests verified after the push: skills `544AAD98025B88D1`, `.scripts`
`5AC51FEF2DBF2F1D`, exit 0. `-SkillsOnly` added for the case where only set 1 is wanted. See
`CHANGELOG.md`.)*

### R14. OpenBB — five questions to settle before any code — **M**

**The evaluation asked for is done** (ReadNow 0315, `0315-openbb-exploration-08-17-39ab82`,
2026-08-17: working venv, confirmed endpoints, measured values). What is open is no longer
research — it is a **discussion**, and the owner named its agenda on 2026-08-19. **The scope also
widened**: 0315 concluded *"adopt narrowly, for macro only"*, and the ask is now macro **and**
company evaluation. That is not a bigger version of the same decision, it is a second decision
with its own evidence requirement, so the questions are split accordingly.

**Q1 — What do we actually gain?** What 0315 measured: OECD + EconDB/Eurostat + ECB breadth that
FRED alone does not serve. What it did **not** establish is any gain on the company side, because
it never looked there. The honest position going in: for series we already pull straight from FRED,
OpenBB adds a dependency and nothing else — `macro_fred.py` already reads M2 (`M2SL`) and the
Buffett Indicator (`NCBEILQ027S`÷`GDP`) with units asserted. So Q1 has a measured answer for macro
and **no answer at all** for companies.

**Q2 — What is it an alternative to, next to yfinance?** The question that decides whether this is
worth real effort. yfinance is the spine of this whole system and its known holes are specific:
non-US fundamentals depth (~4-5 quarters via the fallback), an EPS series gated to US outright
(`valuation_bands.py:451`, `if suffix == ""`), no quarterly P/E anywhere, and a throttle that
returns 429 in bursts. Alpha Vantage cannot fix any of it — its fundamentals endpoints are
**US-listed only at every tier**, and the free cap is **per-IP** (measured, roadmap R5 WON'T DO),
so more keys buy nothing. **If OpenBB's free providers reach non-US fundamentals, it addresses the
gap that closed N0 as WON'T DO** — that, and not the macro breadth, would be the real prize. It is
unmeasured. Measuring it is cheap: pick five names already in the universe across `.AS`, `.L`,
`.TW`, `.HK`, `.SA`, pull income statement + cash flow + EPS history, and diff against what
yfinance and the reports already hold.

**Q3 — Does it run as a CLI, and does it drop into our scripts?** Partly answered and the partial
answer is a warning. 0315 established that `openbb-core` plus providers is **not enough** — the
router extensions and `openbb.build()` are required, which is a build step, not an import. What is
unmeasured is whether a CLI invocation exists that a `.bat` or a helper can shell out to the way
every other ground-truth helper does. This matters more than it looks: **the ground-truth rule
(`SKILL.md:56`) means numbers must come from a Python helper**, so OpenBB has to sit behind a
helper with a JSON contract, in an **isolated venv** — it pulls a large dependency tree and this
system's daily job cannot afford a dependency conflict with yfinance, pandas or matplotlib.

**Q4 — What data, and at what quality?** 0315's negatives are half its value and they must survive
into any implementation: `fixedincome.government.treasury_rates` and `economy.money_measures` **do
not exist** in this version; `economy.cpi` accepts only `fred`/`oecd`; `economy.indicators` requires
`frequency`; and **Portugal is absent** from both the EconDB yield-curve list and the composite
leading indicator, while Spain, France, Germany and Italy are present. Two quality traps, both
named in 0315: **CPI returns a DECIMAL (`0.021854`), not a percent** — the same class as the
Buffett-Indicator factor-of-1000 — so any module must **assert** its units rather than assume them;
and OpenBB's `atexit` handler emits `RuntimeError: can't create new thread at interpreter shutdown`
plus an un-awaited `ClientSession.close` **to stderr**, which this family has already lost a digest
to (the 2026-07-29 `taskkill`/stderr/`EAP=Stop` chain), so nothing wrapping it may treat stderr as
failure.

**Q5 — Is the free tier enough?** Unmeasured, and the question that can kill the whole item.
OpenBB is an aggregator: its ceilings are its **providers'** ceilings, so "free tier" is not one
number but one per provider, and several of the useful ones (FMP, Intrinio, Polygon, Benzinga) are
key-gated with their own caps. The AV lesson applies directly — a cap that turns out to be per-IP
rather than per-key changes the answer completely, and it was only found by burning a key on
purpose. **Any go decision needs the per-provider cap measured the same way**, for the specific
endpoints we would depend on, before code is written against them.

**The country list is derived, not chosen** (measured 2026-08-18 from `_log.csv`, 385 rows / 295
distinct tickers, plus `_portfolio_holdings.yaml`):

| Tier | Countries | Share of evaluations |
|---|---|---|
| Must have | United States | 55.1% |
| Then | Hong Kong 4.7 · Netherlands 3.9 · Germany 3.4 · France 3.1 · South Korea 2.9 · United Kingdom 2.9 · Sweden 2.6 · Taiwan 2.3 | ~26% |
| Then | China 2.1 · Japan 2.1 · Spain 1.8 · Portugal 1.6 · India 1.6 | ~9% |

Those 14 cover ~88% of everything ever evaluated; the portfolio is narrower still (US 8 of 12,
Netherlands 2, Taiwan 1, Portugal 1). **Portugal is the one OpenBB serves worst** — worth knowing
before it is promised, since it is the home market.

- **Left to do**: settle Q1-Q5 in conversation. Q2 and Q5 are the two that need **new measurement**
  before they can be answered honestly (a five-ticker non-US fundamentals diff, and a per-provider
  cap probe); Q1, Q3 and Q4 have partial answers from 0315 already. Only then Phase 1
  (`country_macro.py`, isolated venv, 24h cache, units asserted, fixtures-only tests, ~2-3 h).
  Phases 2 and 3 follow only if the timing harness says Phase 1 fits, and Phase 3 changes
  valuations (`rf` per currency in the DCF) so it ships alone with a measured before/after.
- **Trigger**: that conversation.

*(R19 removed 2026-08-19 — **shipped, both halves**. The bat gained `job_lock`, a 2700 s
ceiling and a VERDICT line on every exit path (installed 16:13 on 2026-08-18, verified by
running the real control flow with the claude and mail calls stubbed). The half that needed a
human — dropping `Repetition PT1H/PT2H` from a MONTHLY trigger — landed the same evening and was
verified from the task itself: `Repeat: Every: Disabled`, `Days: Second WED` intact,
`Next Run Time 2026-09-09 09:00`, and `<ScheduleByMonthDayOfWeek>` / `<Week>2</Week>` /
`<Wednesday />` all present after the round-trip. That round-trip was the whole risk, which is
why `laptop_fix_strategy_monthly_trigger.ps1` goes through the task's own XML instead of
`Set-ScheduledTask`: the ScheduledTasks cmdlets do not model a CalendarTrigger well, and a
monthly job that starts firing on the wrong day is a worse defect than the repetition it was
meant to fix. That judgement was vindicated within the hour — see R13, where the same cmdlet
refused to write at all. Two facts the XML corrected about the incident: MultipleInstancesPolicy
was ALREADY `IgnoreNew`, so only the first of the three starts ran and Windows refused the other
two (hence `0x800710E0`); and `StartWhenAvailable=true` is what produced the 10:24 catch-up after
the 10:17 boot — left alone deliberately, since a monthly refresh that silently skips a month is
worse than one that runs late. See `CHANGELOG.md`.)*

## Next — AGREED-DEFERRED

*(N3 and N4 removed 2026-08-16 — both **shipped** in v4.3 §3.1 and their evidence lives in
`AUDIT_v43.md` A2 and A1 and in `CHANGELOG.md` v4.3. They had been left in place with
SHIPPED banners "to remove at the next prune"; this is that prune. N3: an
earnings-collapse year is excluded from the P/E series and a 4-clean-year depth floor
applies to what survives — 44 usable, 3 unusable. N4: `choose_fair_price()` is the
deterministic anchor, blend → blend_median → dcf → consensus → omit, moving MSFT
$118.35 → $303.28.)*

### N6. Index-level forward-profit horizons (§7) — **BLOCKED ON A SOURCE, not on work**

Split out of R2 on 2026-08-16 when the other two gauges shipped. §7 of `_macro/<date>.md`
asks for S&P 500 forward earnings at 3m / 6m / 1Y / 2Y / 3Y. It says "not available", and
that is now a **recorded finding rather than an open task**.

- **Why**: forward earnings estimates are a licensed product — FactSet, LSEG, S&P — and
  no free, pinnable API publishes them. FRED has no forward-earnings series.
- **Why not scrape**: a page that reprints someone's licensed consensus is not a pinned
  source. It changes layout without notice, it carries no as-of you can trust, and the
  whole point of R2 was to stop sourcing numbers from pages.
- **Trigger**: a paid data subscription, or a free provider that publishes consensus
  estimates under a stable API. Neither exists today.
- Per-ticker forward earnings are **unaffected** — those come from the analyst consensus
  already on each analysis, and Phase B's forward target uses them. This is index-level
  only.

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
| B4 | Four yfinance names with no FCF series at all | **S** | `0175.HK, CMO.MC, FLOW.AS, INGA.AS` — thin non-US statements where FCF genuinely is not published. Correct degradation today. Its stated trigger was "only worth revisiting if a second source is added", and **2026-08-18 answered that negatively**: N0 closed WON'T DO because FinancialReports serves filing documents, not structured statements. There is no known FREE second source for non-US fundamentals, so this stays as-is until a paid provider is on the table — it is not waiting on work. |
| B5 | `patrimonio positions` cannot write a disposal | **M** | By design: the holdings file records what is held, never a sale price, date or commission, and inventing one puts a fabricated capital gain in a tax-relevant sheet. Live case 2026-08-16: DOMO sits open on row 27 with no matching holding. Closing it needs those three inputs from a broker statement, which is a different importer. |
| B6 | Only **9 free rows** remain in the `Accoes (BD)` formula block | **S** | Lots live on rows 3–36 and `H37` is `=SUMIFS(H3:H36,N3:N36,"")`. Rows 28–36 are free; the tenth new lot has nowhere to go that the invested total can see. Extending the block means extending the SUMIFS and copying the six per-row formulas down — deliberate work, not something a writer should do on the fly. |

---

## Won't do — decided against

### N0. FinancialReports / financialfilings.com as the non-US fundamentals source — WON'T DO

Probed 2026-08-18. **Both stated reasons for wanting it are false**, and neither depends on
pricing, so the conclusion holds however the free tier turns out.

The entry existed because it was "the only credible free source of European filings and new
listings", and because non-US depth is the one thing Alpha Vantage structurally cannot give
(its statement endpoints are US-listed only). The API's own documentation says:

| What we needed | What the API has |
|---|---|
| structured income statement / balance sheet / cash flow for non-US names | **Nothing.** It returns filing DOCUMENTS and metadata; `/filings/{id}/markdown/` returns plain text |
| a European IPO / new-listings feed | **No such endpoint.** The full surface is `/companies/`, `/filings/`, `/isic-*`, reference data (`/filing-types/`, `/sources/`, `/languages/`, `/countries/`) and `/watchlist/`. The daily IPO index is a WEBSITE feature |

Getting EBITDA/FCF/EPS series out of it would mean **an LLM reading a filing** -- which is the
exact ground-truth violation the system forbids everywhere except the two documented
exceptions. Adopting it would not add a data source; it would add a third exception.

Two corrections to what this entry used to claim:
- **"500 free credits/month" is stale.** The rebranded site now says "Paid, for builders", and
  neither the marketing site nor `docs.financialreports.eu` discloses a free tier or a
  per-tier rate limit. The docs show "50/second or 5/minute" as *examples only*.
- Coverage did grow -- **85,633 companies / 36.3M filings / 57 markets**, against the 69,647
  companies recorded here. It is the only figure that improved, and it is about filings, not
  fundamentals.

Worth knowing for a different purpose: there is a free official **MCP server**
(`github.com/financial-reports/financial-reports-mcp-server`) that bridges the same API. As a
research tool for reading a specific European filing in conversation, that is genuinely useful
and costs nothing. As a pipeline data source it inherits every limit above.

**So non-US fundamental depth remains unsolved, and now has no known free answer.** The honest
position: yfinance's ~5-6 quarters is the ceiling for non-US names, the evolution panel's depth
floor (v4.3 wave 2.2) already refuses to draw a band it cannot support, and the next real step
is a paid provider -- not another free probe.


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
