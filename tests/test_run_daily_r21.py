"""The four orchestration defects the 2026-08-18 13:30 run reported (roadmap R21).

Each defect made a node contribute nothing while the run looked healthy, and three of the
four were invisible from the outside:

  2.5-end  finalize_score printed the finalised composite to stdout, which run_step captures
           and discards -- so `scores.management` stayed null and `composite_is_provisional`
           stayed true on the file every later node reads, and the node reported PASS.
  2.56     alpha_beta was passed a --ticker it does not declare; argparse exited 2 and the
           return profile was simply absent from deep reports.
  3.5      technical_score was NOT passed --fundamental-score, which it declares required;
           the GO/NO-GO never ran.
  2.6      macro_snapshot ran --check, a probe that writes nothing, so the macro table ran on
           whatever `metrics` happened to be on disk -- and on 2026-08-19 that was none.

TestArgumentContract is the general one: it validates every node's argument list against the
target script's own argparse declarations, so 2.56 and 3.5 could not have survived a test
run. The other classes pin the specific behaviours.

No network. The one place that would fetch is monkeypatched.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import finalize_score  # noqa: E402
import macro_snapshot  # noqa: E402
import run_daily as rd  # noqa: E402


def ns(**kw) -> argparse.Namespace:
    base = dict(date="2026-08-18", ticker=None, mode=None, mgmt_score=None,
                bear_trigger=None, prior_report=None, report=None, email=False,
                fundamental_score=None, dry_run=True, json=False)
    base.update(kw)
    return argparse.Namespace(**base)


def step(stage: str, node: str, **kw):
    for s in rd.build_plan(stage, ns(**kw)):
        if s.node == node:
            return s
    raise AssertionError(f"node {node} absent from the {stage} plan")


# --- the general contract: a node's arguments must be ones the script accepts -------------

def declared_flags(script: Path) -> tuple[set[str], set[str]]:
    """(every --flag the script declares, the subset declared required=True).

    Read from the source with ast rather than by running the script: --help would prove the
    script starts, not that a flag exists, and running 26 scripts to check spelling is a
    price a test should not pay.
    """
    import ast
    tree = ast.parse(script.read_text(encoding="utf-8"))
    flags: set[str] = set()
    required: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        names = [a.value for a in node.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)
                 and a.value.startswith("--")]
        if not names:
            continue
        flags.update(names)
        for kw in node.keywords:
            if kw.arg == "required" and isinstance(kw.value, ast.Constant) and kw.value.value:
                required.update(names)
    return flags, required


ALL_STEPS = [(stage, s)
             for stage in ("pre", "mid", "post")
             for s in rd.build_plan(stage, ns(ticker="ASML.AS", mode="deep", mgmt_score=7.5,
                                             bear_trigger="x", fundamental_score=8.6,
                                             report="r.md", prior_report="p.md", email=True))]
ALL_IDS = [f"{stage}-{s.node}" for stage, s in ALL_STEPS]


class TestArgumentContract:
    @pytest.mark.parametrize("stage,s", ALL_STEPS, ids=ALL_IDS)
    def test_every_flag_passed_is_a_flag_the_script_declares(self, stage, s):
        """Node 2.56 passed --ticker to a script that has never declared it. argparse exits 2,
        so the node FAILED on every deep run -- and because it is not `required`, the stage
        carried on and the report simply had no return profile."""
        flags, _ = declared_flags(SCRIPTS / s.script)
        unknown = {a for a in s.args if a.startswith("--")} - flags
        assert not unknown, f"{s.script} does not declare {sorted(unknown)}"

    @pytest.mark.parametrize("stage,s", ALL_STEPS, ids=ALL_IDS)
    def test_every_required_flag_is_supplied(self, stage, s):
        """Node 3.5 omitted --fundamental-score, which technical_score declares required=True.
        Same outcome as above, on the node that produces the GO/NO-GO."""
        _, required = declared_flags(SCRIPTS / s.script)
        passed = {a for a in s.args if a.startswith("--")}
        assert not (required - passed), (
            f"{s.script} requires {sorted(required - passed)}; "
            f"node {s.node} passes {sorted(passed)}")


# --- 0.5: the fifth defect, found by the contract test above -----------------------------

class TestThesisCheckWasNeverWired:
    """Not in R21's list of four: the contract test found it. Node 0.5 passed a
    `--prior-report` thesis_check.py has never declared and omitted the `--current-json` it
    declares required, so the thesis-drift check exited 2 on every re-evaluation. SKILL.md
    carried the same wrong flag, so no path ever ran it."""

    def args(self):
        return step("pre", "0.5", ticker="T", mode="deep", prior_report="prior.md").args

    def test_it_is_given_todays_analysis_json(self):
        a = self.args()
        assert "--current-json" in a and "--prior-report" not in a

    def test_it_runs_after_the_node_that_writes_that_json(self):
        """It cannot run "before any new analysis" as SKILL.md claimed -- it compares TODAY's
        numbers against the prior _log.csv row, and node 2 writes them."""
        n = [s.node for s in rd.plan_for("pre", ns(ticker="T", mode="deep",
                                                   prior_report="prior.md"))[0]]
        assert n.index("2") < n.index("0.5")

    def test_round_one_still_skips_it(self):
        runnable, skipped = rd.plan_for("pre", ns(ticker="T", mode="deep", prior_report=None))
        assert "0.5" not in [s.node for s in runnable]
        assert any(r["node"] == "0.5" for r in skipped)


# --- 2.5-end: the finalised score must reach the disk ------------------------------------

class TestFinalizeScorePersists:
    def json_file(self, tmp_path: Path) -> Path:
        p = tmp_path / "2026-08-18_T.json"
        p.write_text(json.dumps({
            "ticker": "T", "mode": "deep", "verdict": "review",
            "scores": {"fundamentals": 8.0, "valuation": 6.0, "moat": 7.0, "peer": 5.0,
                       "growth_durability": 6.0, "market_context": 5.5, "management": None,
                       "composite": 6.5, "composite_is_provisional": True},
        }), encoding="utf-8")
        return p

    def run(self, argv: list[str]) -> int:
        old = sys.argv
        sys.argv = ["finalize_score.py", *argv]
        try:
            return finalize_score.main()
        finally:
            sys.argv = old

    def test_update_writes_the_management_score_to_the_file(self, tmp_path, capsys):
        p = self.json_file(tmp_path)
        assert self.run(["--json-path", str(p), "--mgmt-score", "8.5", "--update"]) == 0
        capsys.readouterr()
        after = json.loads(p.read_text(encoding="utf-8"))
        assert after["management_score"] == 8.5
        assert after["scores"]["management"] == 8.5
        assert after["scores"]["composite_is_provisional"] is False

    def test_without_update_the_file_is_untouched(self, tmp_path, capsys):
        """The old behaviour, kept deliberately: SKILL.md's manual path redirects stdout, and
        a script that writes whether or not it was asked to is its own surprise."""
        p = self.json_file(tmp_path)
        before = p.read_text(encoding="utf-8")
        assert self.run(["--json-path", str(p), "--mgmt-score", "8.5"]) == 0
        capsys.readouterr()
        assert p.read_text(encoding="utf-8") == before

    def test_update_without_a_path_refuses_instead_of_pretending(self, capsys):
        """--update reading stdin has nowhere to write. Exiting 0 would be the R21 defect with
        a flag on it."""
        rc = self.run(["--mgmt-score", "8.5", "--update"])
        capsys.readouterr()
        assert rc == 2

    def test_the_runner_asks_for_the_write(self):
        assert "--update" in step("mid", "2.5-end", ticker="T", mode="deep",
                                  mgmt_score=7.5).args


# --- 3.5: the gate input comes from the JSON, not from a human ---------------------------

class TestFundamentalsScoreIsRead:
    def write(self, tmp_path: Path, scores: dict | None) -> Path:
        p = tmp_path / "2026-08-18_T.json"
        body: dict = {"ticker": "T"}
        if scores is not None:
            body["scores"] = scores
        p.write_text(json.dumps(body), encoding="utf-8")
        return p

    def test_it_is_read_off_the_analysis_json(self, tmp_path):
        assert rd._fundamentals_score(str(self.write(tmp_path, {"fundamentals": 8.64}))) == 8.64

    @pytest.mark.parametrize("bad", ["missing-file", "no-scores", "no-key", "unparseable"])
    def test_an_unreadable_score_is_none_not_a_guess(self, tmp_path, bad):
        """Every failure returns None so node 3.5 becomes a stated skip. A default of 0.0 would
        print "gate not met" -- naming a reason that was never measured."""
        if bad == "missing-file":
            p = tmp_path / "nope.json"
        elif bad == "no-scores":
            p = self.write(tmp_path, None)
        elif bad == "no-key":
            p = self.write(tmp_path, {"composite": 6.5})
        else:
            p = tmp_path / "bad.json"
            p.write_text("{not json", encoding="utf-8")
        assert rd._fundamentals_score(str(p)) is None

    def test_the_node_carries_the_value_it_read(self):
        s = step("mid", "3.5", ticker="T", mode="deep", mgmt_score=7.5, fundamental_score=8.64)
        assert "--fundamental-score" in s.args
        assert s.args[s.args.index("--fundamental-score") + 1] == "8.64"

    def test_no_score_means_a_stated_skip_not_an_argparse_death(self):
        runnable, skipped = rd.plan_for("mid", ns(ticker="T", mode="deep", mgmt_score=7.5,
                                                  bear_trigger="x", fundamental_score=None))
        assert "3.5" not in [s.node for s in runnable]
        rec = next(r for r in skipped if r["node"] == "3.5")
        assert "fundamental-score" in rec["detail"]


class TestNeedsDoesNotConfuseZeroWithMissing:
    """`not value` was the test, so a real 0.0 read as "the caller forgot the flag"."""

    @pytest.mark.parametrize("value", [0.0, 0, 6.5, "x", True])
    def test_a_real_value_is_present(self, value):
        assert rd._absent(value) is False

    @pytest.mark.parametrize("value", [None, "", False])
    def test_only_these_are_missing(self, value):
        assert rd._absent(value) is True

    def test_a_zero_mgmt_score_still_runs_the_node(self):
        runnable, _ = rd.plan_for("mid", ns(ticker="T", mode="deep", mgmt_score=0.0,
                                            bear_trigger="x", fundamental_score=8.0))
        assert "2.5-end" in [s.node for s in runnable]


# --- 2.6: the macro data must be fetched, and fetching must not delete the overlays -------

class TestMacroSnapshot:
    def test_the_runner_fetches_rather_than_asking_about_freshness(self):
        s = step("pre", "2.6")
        assert "--fetch" in s.args and "--check" not in s.args

    def test_fetch_preserves_the_breadth_and_regime_overlays(self, tmp_path, monkeypatch):
        """The clobber that made this node's position load-bearing: fetch() wrote a fresh
        three-key payload, so a fetch landing after macro_breadth/macro_fred deleted their
        work. Measured 2026-08-19: `_macro/2026-08-19.json` held breadth+sectors+regime and
        NO metrics -- the mirror image, and the reason the runner was left on --check."""
        monkeypatch.setattr(macro_snapshot, "fetch_metrics",
                            lambda tickers: {"^GSPC": {"last": 1.0}})
        p = tmp_path / "2026-08-18.json"
        p.write_text(json.dumps({"date": "2026-08-18", "breadth": {"rsp_spy": 0.9},
                                 "sectors": {"XLK": 1.2}, "regime": {"m2_yoy_pct": 5.5}}),
                     encoding="utf-8")

        macro_snapshot.fetch(tmp_path, today=date(2026, 8, 18))

        after = json.loads(p.read_text(encoding="utf-8"))
        assert after["metrics"] == {"^GSPC": {"last": 1.0}}
        assert after["breadth"] == {"rsp_spy": 0.9}
        assert after["sectors"] == {"XLK": 1.2}
        assert after["regime"] == {"m2_yoy_pct": 5.5}
        assert after["fetched_at"]

    def test_fetch_still_creates_the_file_when_there_is_nothing_to_merge(self, tmp_path,
                                                                        monkeypatch):
        monkeypatch.setattr(macro_snapshot, "fetch_metrics",
                            lambda tickers: {"^VIX": {"last": 14.0}})
        out = macro_snapshot.fetch(tmp_path, today=date(2026, 8, 18))
        assert out["metrics"] == {"^VIX": {"last": 14.0}}
        assert (tmp_path / "2026-08-18.json").exists()

    def test_a_corrupt_file_is_reinitialised_rather_than_crashing_the_run(self, tmp_path,
                                                                         monkeypatch):
        monkeypatch.setattr(macro_snapshot, "fetch_metrics",
                            lambda tickers: {"^VIX": {"last": 14.0}})
        p = tmp_path / "2026-08-18.json"
        p.write_text("{ truncated", encoding="utf-8")
        out = macro_snapshot.fetch(tmp_path, today=date(2026, 8, 18))
        assert out["metrics"] == {"^VIX": {"last": 14.0}}


# --- the suite must not write into the operational timings log ---------------------------

def test_timings_are_disabled_for_the_whole_suite():
    """`run_step` records a timing on every call, and `node_timing.record` writes to the REAL
    StocksDaily/_timings/<today>.jsonl. The order-contract tests call run_step with stub steps
    named "A" and "X", so every test run was injecting fake nodes into production data --
    measured 2026-08-19: 12 rows on 08-17, 54 on 08-18 (the WHOLE file) and 21 on 08-19, so the
    timing report was partly measuring the test runner. `tests/conftest.py` sets BD_TIMINGS=0,
    which node_timing reads at import time.

    This assertion lives in a collected test file on purpose: it was written in conftest.py
    first, where pytest does not collect it, so it passed by never running -- the same silent
    shape as the four defects above it.
    """
    import node_timing
    assert node_timing.ENABLED is False, (
        "node_timing is live under test: it will append stub nodes to the real "
        f"{node_timing.TIMINGS_DIR}"
    )
