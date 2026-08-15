# Plugin packaging — what landed, and the cutover that did not

v4.3 Wave 5. **The indirection shipped; the cutover did not.** That split is the whole
design: everything below runs today exactly as it ran yesterday, and the irreversible
step is a separate, reversible decision with a green run in front of it.

## Why this is the highest-blast-radius change in v4.3

**30 files** across three skills and `C:\Github\.scripts\` hard-code
`C:\Users\bsdias\.claude\skills\bd-...`. Three are worse than a path constant — they are
**runtime coupling**:

| File | Coupling |
|---|---|
| `run_prefilter.py` | **imports `analyze_ticker` in-process** — a moved module breaks the weekly pool build |
| `growth_analyze.py` | shells out to `analyze_ticker.py` by absolute path |
| `pick_earnings_review_targets.py` | imports `listings.REGISTRY` |

And **ten** live scheduled tasks run through those bats: StocksDaily, StocksGrowth,
StocksPrefilter, StocksPortfolioWeekly, StocksPortfolioMonthly, StocksEarningsPreview,
StocksEarningsReview, StocksStrategyMonthly, StocksWatchdog, Patrimonio Monthly.

`SCHEDULING.md` records what happens when a bat points at the wrong copy: **ten weeks of a
frozen job** while everyone edited the other file. A silent break, discovered late.

## What shipped

**`scripts/skills_root.py`** — one place that knows where the skills live:

1. `%BD_SKILLS_ROOT%`, if set **and the directory exists** (a stale variable is ignored,
   not obeyed — it must not be able to break ten jobs at once);
2. otherwise the parent of this file's directory, so skills that move *together* need no
   configuration;
3. otherwise the current absolute path, hard-coded.

**Step 3 is the point.** On an unconfigured machine every path resolves exactly where it
did before, which is what makes this safe to land ahead of the cutover.
`resolution_report()` prints which rule fired, so a wrong root shows up on the first run
rather than on the first failure.

The three coupling points now resolve through it, each keeping its old path as a fallback
inside a `try/except` — path resolution must never be the thing that breaks a run.

**`bd-finance/.claude-plugin/plugin.json`** (v4.3.0) and a local `marketplace.json`,
listing all eight skills. A test asserts every listed skill directory actually exists —
a manifest that names a skill nobody shipped is worse than no manifest.

## What did NOT ship, and why

| Not done | Why |
|---|---|
| Moving the skills into `bd-finance/skills/` | The move is only safe once every scheduled job has run green **from the new location**. Moving first and testing after inverts that. |
| Re-pointing the `stocks-*.bat` files | Same reason, plus these are what ten live tasks execute. |
| Re-registering any scheduled task | Persistent system configuration — needs an explicit go-ahead, not an inference. |
| Retiring the old paths | Last, and only after a full green cycle. |

## The cutover, when you want it

1. Set `BD_SKILLS_ROOT` (system-wide, so Task Scheduler sees it) to the packaged location.
2. Run `python scripts/skills_root.py` — confirm `reason` names the env var and
   `exists: true`.
3. Run the full suite: **1516 passing** at the time of writing.
4. Run each of the ten tasks **manually, from the packaged location**, and read the *logs*
   — a green Task Scheduler result proves nothing when `run_hidden.vbs` is in the chain
   (`SCHEDULING.md`).
5. Only then re-point the bats and retire the old paths.

**Never point a bat at the plugin cache.** Installed plugins live in **versioned**
directories (`...\claude-for-financial-services\equity-research\0.1.2\`), so a bat that
points there breaks on every version bump — the ten-week frozen-bat failure on a timer.
Resolve through a stable junction or `BD_SKILLS_ROOT`.

## Remaining hard-coded paths

The three runtime couplings are resolved. The rest — `OUT_DIR_DEFAULT` constants pointing
at `C:\BD_Obsidian\Personal\Finance\StocksDaily` and the `stocks-*.bat` files — are
**vault** and **launcher** paths, not skills paths. They are unaffected by packaging and
deliberately left alone: the vault does not move when the skills do.
