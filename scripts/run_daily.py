r"""run_daily.py -- the deterministic phases of the daily pipeline, in a fixed order.

WHY THIS EXISTS (A1)
  The 26-node pipeline was orchestrated entirely in SKILL.md prose: a numbered list of
  "run this, then run that". Prose is not an executable contract. Nothing stopped a run
  from skipping a node, running 2.3 before 2.2 (valuation_bands reads what
  financial_history writes), or -- the failure that actually cost a digest on 2026-08-15 --
  dying before Phase 6 with no record of how far it got. The order matters and it now
  lives in a table a program reads.

WHAT IT DOES *NOT* DO
  It does not write narrative, and it never calls a model. The LLM owns ~6 phases (industry
  cache refresh, 2.5 qualitative, 2.58 panel, 4 narrative, 5 report prose) and this script
  brackets them: `pre` runs everything the narrative needs, `mid` runs everything the
  narrative feeds, `post` runs everything the written report feeds. Between stages the
  skill does its own work; the stages simply refuse to let the deterministic parts happen
  out of order.

  This is deliberately NOT a single `--all` entry point. The model has to sit in the middle
  of the pipeline -- a one-shot runner would have to either call a model (crossing the
  ground-truth boundary) or skip the qualitative pass entirely.

STAGES (each is idempotent; re-running one repeats its writes, it never doubles them)
  pre    0.5 thesis_check . 1 pick_candidates . 2 analyze_ticker . 2.2 financial_history
         . 2.2b reconcile_ttm
         . 2.3 valuation_bands + intrinsic_value . 2.4 red_flags . 2.4b category+roic lens
         . 1.5 edgar . 2.6 macro (once per run)
  mid    2.5-end finalize_score . 2.55 exit_plan . 2.56 alpha_beta . 2.57 watchlist
         . 2.59 news_sentiment . 3 render_charts . 3.5 technical_score
  post   5.6 check_report_charts . 5.7 render_report + index . 6 update_log
         + update_shortlist + report_history --archive + build_dashboard . 7 send_email

USAGE -- WITHOUT --ticker a stage runs only its once-per-run nodes; WITH --ticker only its
per-ticker nodes. The two are mutually exclusive on purpose: otherwise three per-ticker
calls would re-run pick_candidates three times, choosing new candidates mid-analysis.

  python run_daily.py pre  --date 2026-08-18                      # opens the day
  python run_daily.py pre  --date 2026-08-18 --ticker ASML.AS --mode deep
  python run_daily.py mid  --date 2026-08-18 --ticker ASML.AS --mode deep --mgmt-score 7.5
  python run_daily.py post --date 2026-08-18 --ticker ASML.AS --mode deep \
                           --report "...\2026-08-18_ASML.AS_review.md"
  python run_daily.py post --date 2026-08-18                      # closes the day
  python run_daily.py pre  --date 2026-08-18 --dry-run            # print the plan only

EXIT CODES
  0  every step that ran either passed or was skipped for a stated reason
  1  a REQUIRED step failed (the stage stops there -- a later node would read a file the
     failed one never wrote)
  2  bad arguments
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

try:
    import node_timing
except Exception:  # pragma: no cover - instrumentation must never block the pipeline
    node_timing = None

OUT_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")

# The working directory every node is launched from -- it is where api_keys.txt is found.
# RESOLVED, not hardcoded: vmhost1 has no C:\Github at all (its repos live on D:), and with a
# single C: constant here subprocess.run() failed on EVERY step there, making this orchestrator
# a no-op on the one machine that actually runs the pipeline. Caught by run_daily's own tests
# executing on vmhost1, which is the entire reason for running the suite on both machines.
# Order matches scripts/skills_root.py: explicit env var, then the known roots.
_CWD_CANDIDATES = (
    Path(os.environ["BD_FINANCE_DIR"]) if os.environ.get("BD_FINANCE_DIR") else None,
    Path(r"C:\Github\BD\Finance\BD_Finance"),
    Path(r"D:\Github\BD\BD_Finance"),
)
CWD = next((p for p in _CWD_CANDIDATES if p and p.is_dir()),
           Path(r"C:\Github\BD\Finance\BD_Finance"))

# `required` is the whole point of the table: it says which failures make the REST of the
# stage meaningless. valuation_bands reads the file financial_history writes, so 2.2 failing
# means 2.3 would silently score against missing history -- stop instead. An overlay node
# (red_flags, the lenses, news) failing costs one card, so the run continues without it.
# This column is the difference between "the pipeline degraded" and "the pipeline lied".


@dataclass
class Step:
    node: str                       # the SKILL.md phase number, for node_timing
    name: str                       # human label
    script: str                     # module in scripts/
    args: list[str] = field(default_factory=list)
    required: bool = False
    per_ticker: bool = True         # False = once per run, whatever the ticker count
    deep_only: bool = False
    needs: tuple[str, ...] = ()     # argparse dests that must be present, else SKIP


def _tmp_json(date: str, ticker: str) -> str:
    return str(OUT_DIR / "_tmp" / f"{date}_{ticker}.json")


def build_plan(stage: str, a: argparse.Namespace) -> list[Step]:
    """The order. Read this top to bottom -- it IS the pipeline contract."""
    tj = _tmp_json(a.date, a.ticker) if a.ticker else ""
    if stage == "pre":
        return [
            Step("0.5", "thesis check (round > 1 only)", "thesis_check.py",
                 ["--ticker", a.ticker or "", "--prior-report", a.prior_report or ""],
                 needs=("ticker", "prior_report")),
            Step("1", "pick candidates", "pick_candidates.py", [],
                 required=True, per_ticker=False),
            Step("2.6", "macro snapshot", "macro_snapshot.py", ["--check"],
                 per_ticker=False),
            Step("2.6b", "macro breadth", "macro_breadth.py", ["--update"],
                 per_ticker=False),
            Step("2.6c", "macro regime (FRED)", "macro_fred.py", ["--update"],
                 per_ticker=False),
            Step("2", "analyse ticker", "_run_and_save.py",
                 ["--ticker", a.ticker or "", "--mode", a.mode or "screen",
                  "--date", a.date],
                 required=True, needs=("ticker",)),
            Step("2.2", "financial history", "financial_history.py",
                 ["--ticker", a.ticker or "", "--analysis-json", tj],
                 required=True, needs=("ticker",)),
            # 2.2b must come AFTER 2.2: the quarterly series it reconciles against is
            # written by financial_history, and node 2 (analyze_ticker) runs before that,
            # so analyze_ticker's own Layer-0 gate structurally cannot see it. Roadmap R15.
            Step("2.2b", "reconcile TTM aggregates", "reconcile_ttm.py",
                 ["--analysis-json", tj, "--update"],
                 required=True, needs=("ticker",)),
            Step("2.3", "valuation bands", "valuation_bands.py",
                 ["--ticker", a.ticker or "", "--analysis-json", tj, "--update"],
                 deep_only=True, needs=("ticker",)),
            Step("2.3b", "intrinsic value", "intrinsic_value.py",
                 ["--analysis-json", tj, "--update"],
                 deep_only=True, needs=("ticker",)),
            Step("2.4", "red flags + Beneish", "red_flags.py",
                 ["--ticker", a.ticker or "", "--analysis-json", tj, "--update"],
                 deep_only=True, needs=("ticker",)),
            Step("2.4b", "category lens", "category_lens.py", [tj, "--update"],
                 deep_only=True, needs=("ticker",)),
            Step("2.4c", "ROIC lens", "roic_lens.py", [tj, "--update"],
                 deep_only=True, needs=("ticker",)),
            Step("1.5", "EDGAR filings", "edgar.py",
                 ["--ticker", a.ticker or "", "--out-dir", str(OUT_DIR)],
                 needs=("ticker",)),
        ]
    if stage == "mid":
        return [
            Step("2.5-end", "finalize score", "finalize_score.py",
                 ["--json-path", tj, "--mgmt-score", str(a.mgmt_score)],
                 required=True, needs=("ticker", "mgmt_score")),
            Step("2.55", "exit & thesis plan", "exit_plan.py",
                 ["--ticker", a.ticker or "", "--analysis-json", tj, "--update",
                  "--bear-trigger", a.bear_trigger or ""],
                 deep_only=True, needs=("ticker", "bear_trigger")),
            Step("2.56", "return profile (alpha/beta)", "alpha_beta.py",
                 ["--ticker", a.ticker or "", "--analysis-json", tj, "--update"],
                 deep_only=True, needs=("ticker",)),
            Step("2.57", "watch-list maintenance", "watchlist.py",
                 ["--analysis-json", tj, "--update"],
                 deep_only=True, needs=("ticker",)),
            Step("2.59", "news & market sentiment", "news_sentiment.py",
                 ["--ticker", a.ticker or "", "--analysis-json", tj, "--update"],
                 deep_only=True, needs=("ticker",)),
            Step("3", "render charts", "render_charts.py",
                 ["--ticker", a.ticker or "", "--analysis-json", tj],
                 required=True, deep_only=True, needs=("ticker",)),
            Step("3.5", "technical score & GO/NO-GO", "technical_score.py",
                 ["--ticker", a.ticker or "", "--analysis-json", tj],
                 deep_only=True, needs=("ticker",)),
        ]
    if stage == "post":
        return [
            Step("5.6", "chart gate", "check_report_charts.py",
                 ["--report", a.report or ""],
                 required=True, needs=("report",)),
            Step("5.7", "render HTML report", "render_report.py",
                 ["--md", a.report or "", "--analysis-json", tj,
                  "--out-dir", str(OUT_DIR)],
                 required=True, needs=("report", "ticker")),
            Step("5.7b", "rebuild index", "render_report.py",
                 ["--index", a.date, "--out-dir", str(OUT_DIR)],
                 per_ticker=False),
            Step("6", "update shortlist", "update_shortlist.py", [], per_ticker=False),
            Step("6b", "archive report history", "report_history.py", ["--archive"],
                 per_ticker=False),
            Step("6c", "rebuild dashboard", "build_dashboard.py", [], per_ticker=False),
            # Phase 7 is opt-in even here. The digest is the one irreversible act in the
            # pipeline -- send_email.py has a send-once ledger, but a runner that mails by
            # default turns every re-run of a finalisation step into a delivery decision.
            Step("7", "email digest", "send_email.py", ["--date", a.date],
                 per_ticker=False, needs=("email",)),
        ]
    raise ValueError(stage)


def plan_for(stage: str, a: argparse.Namespace) -> tuple[list[Step], list[dict]]:
    """(steps that will run, SKIP records) -- the plan AFTER scoping.

    Split out from build_plan because two callers need the filtered view and disagreeing
    about it is a silent bug: the "later nodes not attempted" message was counting the
    UNFILTERED plan, so it over-reported how much a required failure had cost.
    """
    runnable: list[Step] = []
    skipped: list[dict] = []
    for step in build_plan(stage, a):
        # Ticker-scoped and run-scoped steps are mutually exclusive on one invocation, and
        # the switch is the presence of --ticker. Without that, `pre --ticker A` followed by
        # `pre --ticker B` would re-run pick_candidates and the three macro fetches once per
        # ticker -- picking a fresh candidate set in the middle of analysing the old one.
        if step.per_ticker != bool(a.ticker):
            continue
        if step.deep_only and a.mode != "deep":
            skipped.append({"node": step.node, "name": step.name,
                            "state": "SKIP", "detail": "deep-only phase"})
            continue
        missing = [n for n in step.needs if not getattr(a, n, None)]
        if missing:
            # A REQUIRED step skipped for want of an argument is not a skip, it is a
            # misinvocation: `mid` without --mgmt-score would print a tidy SKIP line, do
            # nothing at all, and exit 0. A deep-only skip is different and stays a skip --
            # a screen legitimately has no charts to draw.
            skipped.append({"node": step.node, "name": step.name,
                            "state": "MISS" if step.required else "SKIP",
                            "detail": f"needs --{missing[0].replace('_', '-')}"})
            continue
        runnable.append(step)
    return runnable, skipped


def _clean_args(args: list[str]) -> list[str]:
    """Drop a flag together with its empty value.

    Filtering only the empty string left the flag behind, so `["--a", "", "--b", "v"]`
    became `--a --b v` and argparse bound "--b" as the value of --a. The `needs` gate should
    keep empties out of here, but a runner that silently mis-binds arguments when it fails is
    not a contract.
    """
    out: list[str] = []
    i = 0
    while i < len(args):
        cur = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else None
        if cur.startswith("--") and nxt is not None and nxt == "":
            i += 2
            continue
        if cur == "":
            i += 1
            continue
        out.append(cur)
        i += 1
    return out


def run_step(step: Step, dry_run: bool) -> tuple[str, str]:
    """('PASS'|'FAIL', detail). Never raises."""
    cmd = [sys.executable, str(SCRIPTS / step.script), *_clean_args(step.args)]
    if dry_run:
        return "PLAN", " ".join(cmd[1:])
    started = time.time()
    try:
        p = subprocess.run(cmd, cwd=str(CWD), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
    except (subprocess.TimeoutExpired, OSError) as exc:
        _record(step, time.time() - started, note=type(exc).__name__)
        return "FAIL", f"{type(exc).__name__}: {exc}"
    _record(step, time.time() - started, note=f"rc={p.returncode}")
    if p.returncode != 0:
        tail = ((p.stderr or "") + (p.stdout or "")).strip()[-400:]
        return "FAIL", f"rc={p.returncode} {tail}"
    return "PASS", f"{time.time() - started:.1f}s"


def _record(step: Step, elapsed: float, note: str) -> None:
    """Timings are instrumentation: a broken recorder must not break a run."""
    if node_timing is None:
        return
    try:
        node_timing.record(step.node, elapsed, note=note)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["pre", "mid", "post"])
    ap.add_argument("--date", required=True)
    ap.add_argument("--ticker")
    ap.add_argument("--mode", choices=["deep", "screen"])
    ap.add_argument("--mgmt-score", type=float, help="mid: the Phase 2.5 management score")
    ap.add_argument("--bear-trigger", help="mid: the bear-case trigger sentence")
    ap.add_argument("--prior-report", help="pre: prior report path, enables Phase 0.5")
    ap.add_argument("--report", help="post: the written .md report path")
    ap.add_argument("--email", action="store_true", help="post: also send the digest")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, execute nothing")
    ap.add_argument("--json", action="store_true", help="machine-readable result on stdout")
    a = ap.parse_args(argv)

    runnable, skipped = plan_for(a.stage, a)
    results: list[dict] = list(skipped)
    ran = 0
    stopped = False

    for step in runnable:
        state, detail = run_step(step, a.dry_run)
        ran += 1
        results.append({"node": step.node, "name": step.name,
                        "state": state, "detail": detail})
        if state == "FAIL" and step.required and not a.dry_run:
            stopped = True
            break

    width = max((len(r["name"]) for r in results), default=10)
    for r in results:
        print(f"  [{r['state']:<4}] {r['node']:<8} {r['name']:<{width}}  {r['detail']}")
    if stopped:
        # Named explicitly, and counted against the FILTERED plan. A required node failed, so
        # the nodes after it were never attempted, and silence here would read as "the stage
        # finished" -- which is precisely how the 2026-08-15 run looked from the outside.
        print(f"\nSTOPPED: required node {results[-1]['node']} failed; "
              f"{len(runnable) - ran} later node(s) not attempted", file=sys.stderr)
    missing = [r for r in results if r["state"] == "MISS"]
    if missing:
        print("\nMISINVOKED: required node(s) " +
              ", ".join(r["node"] for r in missing) +
              " could not run for want of an argument -- " +
              "; ".join(r["detail"] for r in missing), file=sys.stderr)
    if a.json:
        print(json.dumps({"stage": a.stage, "date": a.date, "ticker": a.ticker,
                          "stopped": stopped, "misinvoked": bool(missing),
                          "steps": results}, ensure_ascii=False))
    return 1 if (stopped or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
