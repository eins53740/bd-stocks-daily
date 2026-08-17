# Scheduling & the 30-minute budget

How the `Stocks*` jobs are wired, why they are wired that way, and what breaks when
they are not. Set 2026-07-31 after three consecutive days of late-or-missing digests.

## The tasks

All live in Task Scheduler folder **`\BD\Finance\`**. `Get-ScheduledTask` and
`Set-ScheduledTask` need `-TaskPath '\BD\Finance\'` — without it you get a misleading
"cannot find the file specified".

| Task | Time | Bat | Timeout | Sends email? |
|---|---|---|---|---|
| `StocksGrowth` | **12:45** | `stocks-growth.bat` | 1500 s (25 min) | **No** — guarded |
| `StocksDaily` | **13:30** | `stocks-daily.bat` | **1800 s (30 min)** | **Yes** — the only sender |
| `StocksPrefilter` | **Mon 14:30** | `stocks-prefilter.bat` | 2 h | No |
| `StocksWatchdog` | 14:15 | `stocks-watchdog.bat` | — | No |
| `StocksEarningsPreview` | 06:00 | `stocks-earnings-preview.bat` | 1800 s | Yes (own) |
| `StocksEarningsReview` | 07:30 | `stocks-earnings-review.bat` | 2700 s | No — by design |
| `StocksPortfolioWeekly` | Mon 08:30 | `stocks-portfolio-ingest.bat` | — | No |

All times verified against the live triggers with
`Get-ScheduledTask -TaskPath '\BD\Finance\'` on 2026-08-15 — **read the tasks, not this
table, when they disagree.** Two drifts were corrected here on that date: the prefilter was
documented as `16:45` (it is **Mon 14:30**, and `bd-stocks-prefilter/SKILL.md` separately
claimed 14:00), and `StocksDaily`'s timeout was documented as 1500 s while
`stocks-daily.bat:83` has passed `-TimeoutSeconds 1800` since 2026-07-31.
| `StocksPortfolioWeekly` | Mon 08:30 | `stocks-portfolio-ingest.bat` | — | No |

Order matters in both directions:

- **Growth before daily.** `send_email.py` renders its Growth section from
  `_growth_log.csv` rows dated today. StocksGrowth finishing ~13:10 means those rows are
  already on disk when StocksDaily emails at ~13:52 — one digest, both lenses, nothing
  dropped. If growth ran *after* the daily job its rows would miss that day's digest
  entirely.
- **Prefilter after both.** It was at 16:45 with the daily job at 17:00 and the 15-minute
  gap was never enough: the prefilter takes 21–41 min with `--max-workers 4` and saturates
  yfinance. On **2026-07-31** the daily run's every ticker 429'd — PKO BP came back
  `1.33/10, reject, 0/7 gates` with every fundamental `None`, and `analyze_ticker.py`
  exits 0 while printing that, so it would have been written as a real verdict. The daily
  job now runs 3 h ahead of the prefilter and consumes the *previous* day's pool, which is
  by design: the pool is a slow-moving artefact, the 429 was not survivable.

## The 30-minute budget

**Requirement:** the digest is in the inbox within 30 minutes of the 13:30 trigger.

Three things buy it, and all three are load-bearing:

1. **Growth off the critical path** (its own task). It was the long pole: 19 min on a good
   day, over 45 on a bad one, sitting between the quality run and the email.
2. **3 tickers, not 5** — `pick_candidates.N_SCREENS = 2`. At 5 tickers the quality run
   measured 28, 32 and 32 min on three consecutive days.
3. **25-minute timeout** in the bat, leaving ~4 min for the email step.

> **Do not tighten the timeout without cutting tickers to match.** Phase 6
> (`update_log.py`) writes `_log.csv` only at the *very end* of the pipeline, so a run
> killed mid-flight leaves **zero rows for today** — and the gate at the bottom of
> `stocks-daily.bat` then skips the email. Cutting the cap alone converts "late digest"
> into "no digest", which is strictly worse than the problem it solves.

## Why the digest went missing on 2026-07-30

Worth reading before touching `run_with_timeout.ps1` or the log redirects. A four-link
chain, each link individually plausible:

1. The growth run overran its 45-min ceiling, so the wrapper timed out and ran
   `taskkill /PID <child> /T /F`.
2. `taskkill` printed `ERROR: The process with PID … could not be terminated` to
   **stderr**. This is usually *benign* — it mostly means a descendant had already exited
   (`Reason: There is no running instance of the task`).
3. But the wrapper ran under `$ErrorActionPreference = 'Stop'`, and Windows PowerShell 5.1
   promotes native stderr to a **terminating** `NativeCommandError`. The script **aborted
   mid-kill**: the fallback `$proc.Kill()` never ran, `exit 124` never ran (it returned 1,
   so the caller's `==124` branch never fired), and the main `claude -p` **survived** —
   it went on to print its summary at **21:37**, three hours and twenty minutes later.
4. The survivor still held the **log file handle**. `cmd` opens redirections *before*
   running a command, so `python send_email.py … >> "%LOGFILE%"` could not open its
   redirect and **was never executed**. Not "ran and failed to log" — never ran.

Two fixes, kept independent on purpose:

- `run_with_timeout.ps1` drops `$ErrorActionPreference` to `Continue` around the
  `taskkill` call, snapshots the process tree *before* killing (the parent's death
  destroys the `ParentProcessId` links), then **verifies** each PID is gone and escalates
  to `Stop-Process -Force`, and always exits 124.
- The bats no longer route their critical steps through the handle a child inherited.
  `stocks-daily.bat` writes the email step to `%EMAILLOG%`; `stocks-growth.bat` writes its
  status lines to `%STATUSLOG%`. A handle nothing else has touched cannot be held hostage.
  Belt and braces: the email is the one step whose failure the user actually notices.

Verified 2026-07-31 by reproducing the timeout with a 25–30 s copy of the bat: before the
fix, exit 1 + a `claude` orphan alive 5 minutes later + an unappendable log; after, exit
124, no survivors, and the status lines land.

## Growth-skill cadence — decision note (v4.3 §4.4, 2026-08-15)

**Question**: `StocksGrowth` runs daily at 12:45. Keep it daily, or drop to 2–3×/week given
the hyper-growth pool is 46 names?

**Recommendation: keep it daily for now, and revisit when the first pass closes.**

The measurement that decides it — `_growth_log.csv`, 2026-06-09 → 2026-08-14:

| | |
|---|---|
| runs | 15 distinct days |
| names evaluated | **71**, and **zero repeats** |
| per run | 3–4 (one 23-name backfill day) |
| pool | **46** names tagged `hyper_growth` in `_prefiltered.yaml`; **178** in the raw `_universe.yaml` |

**Zero repeats in 71 evaluations is the whole answer.** The job is still on its *first pass*
through the hyper-growth slice — it has never yet re-evaluated a name, so the dedupe window
has not begun to bind. First-pass discovery is the highest-value phase of this skill's life,
and cutting the cadence now would slow the only thing it is currently doing.

At 3–4 names per run and ~5 runs a week, the 46-name prefiltered pool covers in ~2.5 weeks;
the job has evidently been drawing from the wider 178-name universe slice, which takes
~9–12 weeks. **The trigger to revisit is the first repeat appearing in `_growth_log.csv`** —
at that point the job is re-evaluating rather than discovering, and 2–3×/week delivers the
same coverage for 40–60 % of the cost.

**What does *not* argue for cutting it**: the 2026-08-15 collision with `StocksDaily`. That
was a missed-task catch-up burst running both jobs in the same minute, and it is fixed
properly by `job_lock.ps1` (wave 0). Reducing the cadence to dodge a race would have been
treating the symptom.

**Cost note**: the growth job never emails (guarded) and finishes ~16 min, well inside its
1500 s ceiling, so it does not compete with the digest for the 30-minute budget as long as
the lock holds the ordering.

*Owner's call recorded: keep daily. Re-open when `_growth_log.csv` shows its first repeated
ticker.*


## Wednesday is the token day — decision note (2026-08-17)

Bruno's **Claude weekly quota resets on Wednesday**, so by Wednesday the remainder is
use-it-or-lose-it. Standing rule: a **weekly or monthly** job that spends Claude tokens
belongs on a Wednesday. Daily jobs are not movable and dominate the weekly spend anyway.

**First question, always: does the job actually spend tokens?** Only a bat that invokes
`claude -p` does. Checked task by task on 2026-08-17:

| Job | Spends tokens? | Day |
|---|---|---|
| `StocksMonitor` | yes | **moved Fri 18:00 → Wed 18:00** |
| `ClaudeConfigSync` (vmhost1, biweekly 01:00) | yes | **moved Mon → Wed** |
| `WikiReadNow` | yes (`--max-budget-usd 25`) | already Wed 13:00 |
| `StocksPortfolioMonthly` · `StocksStrategyMonthly` | yes (15 / 30 USD) | already land on Wednesdays |
| **`StocksPrefilter`** | **NO** | stays **Mon 14:30** |
| `StocksPortfolioWeekly` (ingest) · `StocksSkillsPush` · `StocksMirrorPull` · watchdogs | no | unchanged |

**`StocksPrefilter` is the one worth spelling out**, because it is the job most likely to be
proposed for the move: since the prefilter rework it runs `python run_prefilter.py` under
`run_with_timeout`, not `claude -p`, so moving it saves nothing — and it would cost something.
Monday is deliberate: the pool it writes has to serve the whole week, and a Wednesday refresh
would leave Monday and Tuesday screening against a seven-day-old pool.

**Two Monday jobs were deliberately NOT moved**, because their day carries meaning and a
silent move would break what they are for:
- **`BD Claude Weekly`** (Mon 10:00) is a retrospective of *the past week*. Running it
  mid-week changes the window it reports on.
- **`Claude-SprintReview-UNS-OT`** (Mon 09:20, biweekly) is tied to a sprint boundary and a
  meeting, not to a token budget.

**Bonus from moving `ClaudeConfigSync`**, and the reason it was the easy one: it is the job
that installed a **pre-v4.3 skill** on vmhost1 at 01:00 on 2026-08-17 (49 scripts instead of
61). `StocksSkillsPush` repairs that drift, but it runs Wed 09:44 — so a Monday 01:00 sync left
vmhost1 running regressed code for ~2.5 days and two daily runs. At Wednesday 01:00 the repair
follows **8 h 43 m later the same morning**.

**Gotcha**: `Set-ScheduledTask` needs `-TaskPath` (these live at `\BD\Finance\` and `\BD\Claude\`)
or it fails with a misleading *"The system cannot find the file specified"*. And edit the
existing trigger object in place rather than building a new one with
`New-ScheduledTaskTrigger` — a rebuilt trigger silently drops `WeeksInterval`, turning a
biweekly job into a weekly one.


## Traps

- **`run_hidden.vbs` launches the bat non-waiting** (`.Run(..., 0, False)`), so wscript
  exits within a second. The task therefore reports `LastTaskResult 0` almost immediately,
  its `ExecutionTimeLimit` **never applies to the bat**, and `MultipleInstances IgnoreNew`
  cannot block an overlapping run either. `run_with_timeout.ps1` is the only real ceiling
  the job has. A green task result says nothing about whether the digest went out — read
  the log.
- **One copy per bat.** Until 2026-07-29 the tasks pointed at duplicates under
  `C:\Github\BD\Finance\.scripts\`, frozen since 2026-05-14, so ten weeks of edits to the
  `C:\Github\.scripts\` copies did nothing. If you clone a bat, re-point the task.
- **`%ERRORLEVEL%` inside a parenthesised `if (…) else (…)` block** is expanded when the
  block is *parsed*, not when the command runs — so `set X=%ERRORLEVEL%` there captures a
  stale value. Both bats use `goto` labels instead. Same class of bug as needing
  `setlocal enabledelayedexpansion` for a `for /f` variable inside a block.
- **Never end a `claude -p` run with a question** — see the Headless rule in `SKILL.md`.
  On 2026-07-28 a run finished its work at 17:50, asked "send the email?", and blocked the
  bat for 13.7 hours.
