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

### R10. The bats are two divergent copies, and vmhost1's still have no lock — **M**

`C:\Github\.scripts\stocks-*.bat` (laptop) and `D:\Github\.scripts\stocks-*.bat` (vmhost1)
are **separately maintained files that have drifted**. vmhost1's copies use
`cd /d "D:\Github\BD\BD_Finance"` and `D:\Github\.scripts\run_with_timeout.ps1`; the
laptop's use the C: equivalents. So the 2026-08-17 `job_lock` additions **cannot be deployed
by copying** — a verbatim copy would break vmhost1's paths, and the machine that actually
runs the pipeline is therefore still running seven heavy jobs unserialised.

This is the ten-week frozen-bat incident (`SCHEDULING.md`) in a new form: two copies, one
edited, no mechanism to notice.

- **Partly mitigated 2026-08-17**: the 14 `job_lock.ps1` references in the laptop's bats now
  resolve via `%~dp0`, which is correct on **both** machines with no configuration, and
  `job_lock.ps1` itself was deployed to vmhost1 (hash-verified identical). The remaining
  divergence is `cd /d` and `run_with_timeout.ps1`.
- **The work**: make `run_with_timeout.ps1` `%~dp0`-relative too, move the one genuinely
  per-machine value (the BD_Finance directory) into an environment variable, then the bats
  become a single source and a push mechanism becomes possible. ~11 bats, two machines.
- **Trigger**: none; it is unscheduled only because doing it mid-session with a two-hour
  prefilter running was the wrong moment.

### R11. Fold the remaining path lists and vault constants into `bd_paths` — **M**

`analyze_ticker.py`, `financial_history.py`, `llm_client.py`, `macro_fred.py`,
`portfolio_sync.py` (DEFAULT_DB), `send_email.py`, `_run_and_save.py` and
`technical_score.py` all name `C:\Github\BD\Finance\BD_Finance` or similar. vmhost1 has no
`C:\Github` **at all**. The pipeline demonstrably works there anyway — those paths are
`sys.path` inserts and config lookups that degrade — but two of them did NOT degrade and
were live production bugs, found 2026-08-17 by running the suite on vmhost1 rather than on
the laptop:

- `technical_score.py` — Phase 3.5 raised `ModuleNotFoundError` on all five indicator
  imports, so the technical score and GO/NO-GO were **never computed on vmhost1**.
- `portfolio_sync.py` — read its gap script at import time, so `tests/test_portfolio.py`
  failed at **collection**, and a collection error aborts the whole suite. The production
  machine's tests could not be run at all.

Both are fixed, plus `run_daily.py`'s launch directory, each with its own env-var → C: → D:
resolution and a *positive* existence probe (the file actually imported, not just a
directory). That makes **three** near-identical resolution lists in one skill — deliberate
for now, because each probes a different target, but it is duplication that wants collapsing.

A **third** live failure surfaced the same evening, in a sibling skill: the weekly prefilter
summary email could never send on vmhost1 --
`ModuleNotFoundError: No module named 'api_keys_reader'` -- so a two-hour analysis succeeded
and its notification failed every Monday, in silence. Fixed and verified sending
(`{"email_sent": true}`), which makes **four** near-identical resolution lists.

Worth recording *why* the safe ones are safe: `send_email.py` carries the identical line and
works, because the daily bat `cd`s into the BD_Finance directory first. But cwd is **not** on
`sys.path` when Python runs a script by path, so whether a script survives this bug is an
accident of how it is invoked. Reasoning about which of the eight are fine is the wrong move.

- **The work**: one `bd_paths.py` beside `skills_root.py`, then convert the remaining eight.
- **Priority raised** 2026-08-17: no longer hygiene. This single pattern has now caused two
  production failures (Phase 3.5 never computing; the suite unable to collect) and one
  notification lost every week.
- **Trigger**: none; scoped with the Wave-5 path refactor, which the packaging notes already
  size at ~30 files across the family.


**Half of this shipped 2026-08-18** (commit `3e2702b`): `scripts/bd_paths.py` is now the single
resolver — env var, then the known roots, probing for a file that *proves* the layout, with a
stale env var **ignored rather than obeyed** so one wrong variable cannot take out ten scheduled
jobs at once. The six dead `C:\Github\BD\...` constants were converted (`analyze_ticker`,
`financial_history`, `llm_client`, `send_email`, `macro_fred` KEYS_PATH, `portfolio_sync`
DEFAULT_DB), each keeping its previous literal as the fallback so the laptop resolves
byte-identically and only vmhost1 changes behaviour. Suite: 1689 passed, 1 skipped.

Why it stayed invisible so long: `api_keys_reader()` answers a missing file with an **empty dict
and a printed warning**, never an exception. A dead BD_Finance path therefore yields no FRED key,
no Alpha Vantage key and no SMTP password while the run keeps looking healthy.

Two corrections to what this entry used to claim, both measured on 2026-08-18:

- **`C:\Github\BD` really is absent on vmhost1** — confirmed from a LOCAL context there, not over
  SSH. The distinction matters and cost a wrong first reading: a network logon cannot traverse that
  machine's junctions ("the path cannot be traversed because it contains an untrusted mount
  point"), so an SSH `Test-Path` returns False for paths a local process resolves fine. Probe via
  WSL (`arch-sim`, `/mnt/c`, `/mnt/d`) before believing either answer.
- **The ~35 `C:\BD_Obsidian` OUT_DIR constants are NOT broken.** `C:\BD_Obsidian\Personal` on
  vmhost1 is a junction to `D:\BD_Obsidian\Personal` and resolves correctly for the locally-run
  tasks — the `/mnt/c` view is the same file as the `D:` one, all 382 log files of it. Converting
  them is regression risk with no defect to fix, so it was deliberately not done.
  `bd_paths.vault_state()` exists for whoever needs it next.

**What remains**: those OUT_DIR conversions (only worth doing alongside the Wave 5 packaging move,
which changes the paths anyway), and folding `run_daily.py`'s and `technical_score.py`'s private
resolution lists into `bd_paths` so there is genuinely one copy instead of three.
**Trigger**: the Wave 5 cutover, or a third machine.

### R12. Backfill the two orphan rows on vmhost1 — **S, one command**

The defect is **diagnosed and guarded** (2026-08-18, commit `4cfbcd3`); what is left is one write
on the machine that owns the state.

The cause was measured, not assumed, from the run's own artefact timestamps on vmhost1: the
2026-08-17 13:30 run executed **fully** — node timings 13:32, financial history and valuation
bands 13:33, technical and macro 13:37, eight charts 13:40, markdown 13:52, HTML + sankey +
archive 13:53 — and then stopped. Phase 6 never wrote a row; `_log.csv`'s mtime is still
2026-08-16 23:29, verified on vmhost1's own `D:` copy and not only on the laptop mirror.

Why it still reached the inbox is the durable lesson: `send_email.py` attaches report **files** by
date glob, while the dedupe, the dashboard's All-Evaluations view and `report_history` read
`_log.csv` **rows**. The two paths never consult each other. The bat's email gate did not catch it
either — it counted 4 rows for that date, every one of them from `_growth_log.csv`. And Task
Scheduler reported result 0, which proves nothing: the action is `run_hidden.vbs`, which does not
wait.

- **Shipped**: `scripts/log_orphan_check.py` (6 tests) exits 1 when any `*_review.md` has no
  matching row, so the failover watchdog can call it; `--fix` backfills from each report's own
  front matter, idempotently, with a backup.
- **It found a second orphan on its first run**: `2026-08-13 CSCO`, deep, score 6.12. This was
  never a one-off, which is why the guard closes the class rather than the instance.
- **Left to do**: run it with `--fix` **on vmhost1** — the single writer. The laptop is a
  read-only mirror that `stocks-mirror-pull` overwrites at 09:30 and 15:30, so a fix applied there
  is discarded. Then wire the check into the 15:00 watchdog.
- **Trigger**: none.

### R13. vmhost1's task descriptions still describe the pre-migration layout — **S**

`\BD\Finance\StocksDaily`'s own Description reads `Trigger : daily 17:00` and
`Script : wscript.exe C:\Github\BD\Finance\.scripts\run_hidden.vbs ...`. The live trigger is
**13:30** and the live script is `D:\Github\.scripts\stocks-daily.bat`. Cosmetic, but it is
the first thing anyone reads in Task Scheduler when something breaks, and it points at a
path that does not exist on that machine.

- **Shipped 2026-08-18**: `vmhost1-fix-finance-task-descriptions.ps1`, values measured on
  vmhost1 that day rather than copied from a doc. StocksPrefilter lied too (claimed
  `daily 16:45 ... has drifted; review`; real: **weekly Monday 14:30**), and
  StocksPortfolioWeekly and StocksStrategyMonthly carried **no description at all** — so a task
  disabled ON PURPOSE, because the laptop owns both (verified Ready there, Disabled here), reads
  exactly like one someone switched off and forgot.
- **Left to do**: run `pwsh -File D:\Github\.scripts\vmhost1-fix-finance-task-descriptions.ps1`
  on vmhost1. Descriptions only; no trigger, action or principal touched; idempotent; a
  COMPUTERNAME guard makes it refuse to run anywhere else (verified: exits 2 on the laptop).
- **Trigger**: none.

### R14. Evaluate OpenBB as a second data spine — macro first, fundamentals second — **M**

Requested 2026-08-17. OpenBB is a **Python platform with a CLI on top** that normalises many
providers behind one interface (`obb.equity.*`, `obb.economy.*`, `obb.fixedincome.*`). Free
tier, open source.

**The premise that has to be corrected before any work starts**: OpenBB is an *aggregator*,
not a data source. It does not own numbers. On the free tier its equity fundamentals still
resolve to yfinance and FMP-free, which means it does **not** by itself solve **N0**
(non-US depth) any more than the Alpha Vantage key pool did in wave 1.0 — that failure came
from assuming a wrapper changes the underlying entitlement. Judge it on what it *does* add.

**Where it plainly wins — macro, and it closes a gap this roadmap already carries.** Wave 4.1
specified portfolio benchmarks against **PT HICP inflation**, the **PT OT-10y** and the
**UST-10y**, and had to record "yfinance has neither; no source ⇒ the row renders
not-available". OpenBB's `economy` and `fixedincome` modules reach FRED, EconDB, IMF, OECD,
the World Bank and the ECB, which is exactly those three series plus policy rates, yield
curves, unemployment, PMI and debt/GDP. `api_key_fred` already exists.

**Ranked by leverage, highest first:**

| # | Use | Why it is worth it |
|---|---|---|
| 1 | **Macro country dashboards** — GDP, CPI/HICP, unemployment, policy rate, 10y yield, PMI, debt/GDP, FX, per country the portfolio is exposed to | The one genuinely new capability. Feeds the requested macro skill and the `MarketCtx` weight (0.05 of the composite) which is today the thinnest-sourced input in the score |
| 2 | **Unblock 4.1's three benchmark rows** | Named, citable series instead of a blank row |
| 3 | **Risk-free rate and yield curve for the DCF** | `intrinsic_value.py` CAPM needs `rf`; sourcing it from FRED/ECB per currency beats one number that ages |
| 4 | **Cross-check layer on yfinance** | A second independent read of the same figure is exactly what the 3-layer validation stack wants; the 2026-08-15 `ADS.DE` incident was a *reference price* being wrong, not the data |
| 5 | Earnings calendar / estimates | Overlaps what the two earnings skills already do — check before building |

**Constraints to respect, from this skill's own history:**
- **Python API in-process, not the CLI.** A subprocess parsing human-formatted CLI output is
  the fragile pattern; `obb.*` returns typed objects. The ground-truth rule is satisfied
  either way — these are numbers from a Python helper — but only the API is deterministic.
- **Budget.** The 13:30 job runs at 22-24 min of a 30-min ceiling. Any macro call ships
  **opt-in**, cached by content hash, exactly like every wave 1-2 addition.
- **Dependency weight.** `openbb` pulls a large tree. Install it in its own venv and call it
  from there, or take only the provider packages actually needed — do not add it to the
  daily job's import path on a whim.
- **Macro is one of the two documented LLM-narrative exceptions.** Structured macro series
  arriving from OpenBB would make that exception *narrower*, not wider: the numbers become
  ground truth and the LLM keeps only the commentary. Worth saying so in `SKILL.md` when it
  lands.

- **First step, cheap and decisive**: one venv, `obb.economy.cpi` and
  `obb.fixedincome.government.treasury_rates` for PT/US, and confirm the free tier returns
  the three series 4.1 needs. That answers "is this worth wiring in" in under an hour.
- **Trigger**: none; item 1 is wanted for the macro skill and is independent of the rest.

---
### R15. Corrections found in the narrative never reach the JSON — **S, highest data-integrity value open**

Found by the adversarial audit of `2026-08-17_ROVI.MC` (ReadNow 0319, 2026-08-18). The report's
prose is exemplary: it names three vendor-data defects and corrects each one. The **machine
artefact does not**. `_tmp/2026-08-17_ROVI.MC.json` still carries:

| Key | Served | Real | How the real value is known |
|---|---|---|---|
| `operating_margin_ttm` | 0.0942 | **0.227** | quarterly Operating Income sum over TTM revenue |
| `ebitda_ttm` | 175.96M | **272.80M** | 175.96M is TTM **EBIT**; the quarterly EBITDA rows sum to 272.8M, matching `_fin_history` exactly |
| `ev_ebitda` | 16.82 | **10.85** | follows from the row above |

…while `data_quality: "ok"`, `corrected_fields: []`, `consistency_issues: []`. The Layer-0
consistency gate caught neither corruption, and **the corrupt EV/EBITDA already scored the peer
rank (5 of 6) inside the composite** at 12% weight. Any consumer of the JSON — dashboard cards,
the screener, future parsers — is served known-false numbers under a green stamp.

Measured against the governing principle (false data is worse than no data) this is the most
valuable open item in the file. It is not that a number was wrong: it is that **the system's own
correction is unreachable by anything except a human reading prose.**

- **The work**: a Layer-0 cross-check of `ebitda_ttm` against the quarterly EBITDA sum and of
  `operating_margin_ttm` against statement-derived operating income — both series are already
  persisted. On mismatch: write the derived value, name the key in `corrected_fields`, set
  `data_quality: suspect`. No new fetch is needed.
- **Trigger**: none.

### R16. The one-off detector reads annual `unusual_items` only — **S**

`red_flags.py:148` reads the **annual** statement snapshot, so ROVI's €62.4M Q2-2026 gain —
**33.7% of TTM net income, 2.2x the 15% threshold** — printed a pass at "0.4%". The narrative
caught it and quantified it correctly everywhere (normalized EPS 2.597, P/E 22.20, ROE 19.99%,
all independently reproduced by the audit), but the deterministic scanner that exists for exactly
this did not. Diligence is not a control.

- **The work**: read `unusual_items` / `special_income_charges` from the quarterly statements too,
  and compare the TTM sum against TTM net income.
- **Trigger**: none.

### R17. The report asserts side effects it never performed — **S**

The same report states twice that ROVI is *"already in `_watchlist.csv`"*. It is not: that file's
mtime is 2026-08-10 and it holds five rows, none of them ROVI. A reader waiting on the promised
€50.82 entry alert would never get one.

This is the most serious *class* the audit found — not a wrong number but a **stated action that
did not happen** — and it is invisible to every numeric check, because there is no number in it.

- **The work**: either have the phase actually write the row, or forbid the prompt from claiming a
  side effect at all and let a deterministic step report what was written. The second is the safer
  shape: the LLM should describe state, never assert changes to it.
- **Trigger**: none.

### R18. Three labelling defects in one report — **S**

All from the 2026-08-18 audit. Individually cosmetic; jointly they are how a careful reader stops
trusting labels.

- **Two RSIs under one name.** `analyze_ticker.py:1454` computes **Cutler** RSI (rolling mean) ->
  32.6 in the JSON; `technical_score.py` uses BD_Finance's **Wilder** RSI -> 48.7 in the report.
  Both were recomputed and both are internally correct — they are different indicators wearing one
  label, and 32.6 (near-oversold) versus 48.7 ("neutral") is not a rounding difference. Wilder is
  the defensible one to print; one pipeline should not own two.
- **Mixed margin-of-safety denominators.** The headline -13.4% is `(fair-price)/fair`; the
  corrected "~-27%" in 2.11d is `(fair-price)/price`. On the model's own convention the corrected
  figure is **-37.4%**, so the mix understates the deterioration.
- **The history table mislabels the prior verdict** as WATCH where `_log.csv` records `review`.
- **Trigger**: none.


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
