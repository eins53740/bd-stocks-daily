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

### R23. Two battery settings can still block the patrimony chain — **S**

**The catch-up half shipped 2026-08-19.** `Patrimonio Monthly` had **never run once** —
`LastTaskResult 0x41303` = `SCHED_S_TASK_HAS_NOT_RUN`, `LastRunTime` still the "never" sentinel,
registered 2026-08-02 — because `StartWhenAvailable` was **absent** from its Settings and therefore
false, so a 09:00 start missed with the laptop asleep was dropped rather than caught up. Now
`true`, applied and verified by `scripts/laptop_fix_patrimonio_catchup.ps1`: day 27 preserved,
`NextRunTime` unmoved at 2026-08-27 09:00, action, principal and `Ready` state unchanged. Day 27 is
deliberate and stays — the payslip PDFs the chain parses arrive before month end.

That script had to go through the task's own XML: this is a MONTHLY task, so `Set-ScheduledTask`
refuses it, and `StartWhenAvailable` had to be **inserted** rather than flipped, into a `<Settings>`
sequence whose element order `schtasks` does not export the way the documentation suggests. The
script therefore tries candidate positions and lets `schtasks /create` validate — a wrong position
fails with the task unchanged. `before <IdleSettings>` was accepted.

**What is left is a genuine trade-off, which is why it was not flipped silently.** The same
Settings block carries:

```
<DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>
<StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>
```

- The first means the task **will not start at all** while the laptop is on battery. A 09:00
  catch-up on a workday is exactly when a laptop is likely to be unplugged, so **the fix that just
  shipped may still not produce a run** — and a fix that looks applied and does nothing is the
  silent-success shape this pipeline keeps producing.
- The second means an in-flight run is **killed** the moment the machine goes to battery. This
  chain writes `Patrimonio BD.xlsx` through Excel COM on a copy with a timestamped backup; being
  killed mid-write is worse than not running at all, so this one is arguably correct as-is.

They pull in opposite directions, and against a real cost: a full `wages → audit → report → BankBD`
run is heavy, and permitting it on battery drains it.

- **The decision needed**: allow the start on battery (flip the first, keep the second), allow both,
  or leave both and accept that this chain runs when the laptop happens to be docked on the 27th.
  A fourth option that avoids the trade-off entirely: move the trigger to an hour the machine is
  reliably plugged in.
- **The check that closes this either way**: after 2026-08-27, read `LastTaskResult` — not `State`,
  which said `Ready` for the whole time this task had never run.
- **Trigger**: the 2026-08-27 run, or a call on the battery settings.

### R20. There is still no push for `.scripts` to vmhost1 — **M**

R10 made the Stocks* bats machine-agnostic in every executable line, which is what makes a
push POSSIBLE. It does not make one exist. vmhost1 still runs its own D: copies, and today's
lock/timeout/`%~dp0` work reaches it only if someone copies it by hand.

This is the same gap that made me write a vmhost1 fixer into `C:\Github\.scripts` earlier
today -- a script for vmhost1, left in the one tree with no way to get there. Bruno caught it.
The skills tree has `stocks-skills-push.ps1` (hash-verified both ways, scheduled, and it
self-heals from the failover watchdog); `.scripts` has nothing.

- **Two options, and the cheap one is probably right**: extend `stocks-skills-push.ps1` to
  carry `.scripts/stocks-*.bat` + `_bd_env.bat` + `run_with_timeout.ps1` + `job_lock.ps1`
  (reuses a proven, already-scheduled, already-locked mechanism), or write a sibling
  `stocks-bats-push.ps1` (cannot break the skills push if it goes wrong). The first is less
  code and less schedule; the second is less blast radius.
- **Why it was not done today**: writing to vmhost1 is confirm-first here, so the end-to-end
  verification a deployment mechanism needs could not be run. Shipping an untested push is
  worse than shipping none -- a push that half-works on the machine that owns the pipeline is
  exactly the ten-week frozen-bat failure with a new mechanism.
- **Trigger**: none; it is the natural next step after R10.

### R21. Four orchestration defects the 13:30 run reported and nobody fixed — **S**

The 2026-08-18 13:30 job on vmhost1 finished cleanly (26m 15s, exit 0, digest delivered) and
its own report listed **five** defects in `run_daily.py`. Only the first was fixed that day, as
part of R11 -- and it was the fatal one (`_run_and_save.py` passing a hardcoded
`cwd=C:\Github\BD\Finance\BD_Finance` on a machine with no `C:\Github`). The other four are
still live, and all four were **re-verified against the code on 2026-08-18 at 17:00**, not
carried over on the report's word:

| Node | Defect | Verified how | Shape |
|---|---|---|---|
| **2.5-end** | `finalize_score.py` prints the finalised composite to **stdout** and the runner throws it away | `finalize_score.py:67` is `print(json.dumps(result...))` -- there is no write path; `run_daily.py:269` captures stdout and, on `rc == 0`, **returns without reading it** | **SILENT** -- the node reports PASS while the management score never lands and the composite stays provisional |
| **2.56** | passes `--ticker` to `alpha_beta.py`, which does not accept it | `alpha_beta.py:451-454` declares only `--analysis-json`, `--out-dir`, `--update` | Loud: argparse exits 2, so the return profile is simply absent |
| **3.5** | omits `--fundamental-score`, which is **required** | `technical_score.py:531` -- `required=True`, no default | Loud: the GO/NO-GO never runs |
| **2.6** | runs `macro_snapshot.py --check` and never `--fetch` | `run_daily.py:118` passes `["--check"]`; `macro_snapshot.py:217-218` are mutually exclusive modes and only `--fetch` writes | Half-silent: freshness is *asserted* on a file nothing in this path refreshes |

**2.5-end is the one that matters, and it is the third instance of one shape.** R15 (corrections
computed in prose, never written to the JSON) and R17 (a side effect announced but never
performed) were the same defect: a helper that knows the answer, a channel that drops it, and a
green status either way. That is now a named pattern, not three coincidences -- see
`feedback_silent_success_antipatterns`.

- **The fix is small and the risk is in the wiring, not the logic**: give `finalize_score.py`
  an `--update` that writes back through the same path `exit_plan`/`alpha_beta`/`watchlist`
  already use (do not invent a fourth), drop the bad flag at 2.56, thread the fundamentals
  score into 3.5 from the JSON already on disk, and decide deliberately whether 2.6 should
  fetch in the scheduled path or whether the prefilter/macro job owns that (a second
  `--fetch` is known to clobber the merged breadth+sectors overlay, so this one is a
  **decision**, not a typo).
- **Why it was not done on 2026-08-18**: the 1-16 pass was scoped to the roadmap items the user
  ordered, and these arrived from a run report rather than from the roadmap. Listing them here
  is what makes them ordinary work instead of a memory.
- **Trigger**: none.

### R14. OpenBB — evaluation DONE, Phase 1 awaiting a go/no-go — **M**

**The evaluation this item asked for is complete**: ReadNow 0315
(`0315-openbb-exploration-08-17-39ab82`), 2026-08-17, with a working venv, confirmed endpoints
and measured values. What is left is a decision, not research.

**Verdict: adopt narrowly, for macro only.** OpenBB's value is OECD + EconDB/Eurostat + ECB
breadth, which FRED alone does not give. Replacing `macro_fred.py` is explicitly out of scope --
for series we already fetch directly from FRED, OpenBB only adds a dependency.

Half of 0315's value is what it measured as BROKEN, and those negatives must survive into any
implementation: `fixedincome.government.treasury_rates` and `economy.money_measures` do not
exist in this version; `economy.cpi` accepts only `fred`/`oecd`; **Portugal is absent** from
both the EconDB yield-curve list and the composite leading indicator (Spain, France, Germany
and Italy are present); `economy.indicators` requires `frequency`; and `openbb-core` plus
providers is NOT enough -- the router extensions and `openbb.build()` are required.

**Two traps that gate adoption, both already named in 0315:**
- **Units.** CPI comes back as a DECIMAL (`0.021854`), not a percentage. Same class as the
  Buffett-Indicator factor-of-1000 that `macro_fred.py` documents. Any new module must ASSERT
  its units, not assume them.
- **stderr at shutdown.** OpenBB's `atexit` handler emits `RuntimeError: can't create new
  thread at interpreter shutdown` plus an un-awaited `ClientSession.close`. Harmless to the
  result, but it goes to **stderr** -- and this family has already lost a digest to exactly
  that: the 2026-07-29 `taskkill`/stderr/`EAP=Stop` chain leaked a log handle and silently
  deleted the email. Anything wrapping OpenBB must not treat stderr as failure.

**The country list is derived, not chosen** (measured 2026-08-18 from `_log.csv`, 385 rows /
295 distinct tickers, and from `_portfolio_holdings.yaml`):

| Tier | Countries | Share of evaluations |
|---|---|---|
| Must have | United States | 55.1% |
| Then | Hong Kong 4.7 · Netherlands 3.9 · Germany 3.4 · France 3.1 · South Korea 2.9 · United Kingdom 2.9 · Sweden 2.6 · Taiwan 2.3 | ~26% |
| Then | China 2.1 · Japan 2.1 · Spain 1.8 · Portugal 1.6 · India 1.6 | ~9% |

Those 14 cover ~88% of everything ever evaluated. The portfolio itself is narrower still --
US 8 of 12 holdings, Netherlands 2, Taiwan 1, Portugal 1 -- so a Phase 1 that starts with the
top tier plus the four portfolio countries is defensible on its own evidence. **Portugal is the
one that OpenBB cannot serve well** (absent from the yield-curve and CLI lists), which is worth
knowing before it is promised.

- **Left to do**: Bruno's go/no-go on 0315's Phase 1 (`country_macro.py`, isolated venv,
  24h cache, units asserted, fixtures-only tests, ~2-3h). Phases 2 and 3 follow only after the
  timing harness proves Phase 1 fits; Phase 3 changes valuations (`rf` per currency in the DCF)
  so it ships alone with a measured before/after.
- **Trigger**: that decision.

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
