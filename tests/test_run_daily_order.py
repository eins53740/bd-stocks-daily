"""The pipeline order is an executable contract, not prose (A1).

The 26 nodes were orchestrated entirely in SKILL.md prose. Nothing stopped a run from
skipping a node, running 2.3 before the 2.2 whose output it reads, or dying before Phase 6
with no record of how far it got -- which is what cost the 2026-08-15 digest. These tests
assert the properties that make run_daily.py a contract; each one, if it fails, is a way the
pipeline could produce a plausible report from the wrong inputs.

No subprocesses except a stub script written into tmp_path. No network.
"""
import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_daily as rd  # noqa: E402


def ns(**kw) -> argparse.Namespace:
    base = dict(date="2026-08-18", ticker=None, mode=None, mgmt_score=None,
                bear_trigger=None, prior_report=None, report=None, email=False,
                dry_run=True, json=False)
    base.update(kw)
    return argparse.Namespace(**base)


def nodes(stage: str, **kw) -> list[str]:
    """The nodes that would ACTUALLY run -- the filtered plan, not the declaration. Asserting
    against build_plan() instead would let a scoping bug pass: that is how the "later nodes
    not attempted" counter came to count run-scoped nodes it never intended to run."""
    return [s.node for s in rd.plan_for(stage, ns(**kw))[0]]


# --- the dependency order itself ---------------------------------------------

class TestOrder:
    def test_history_is_written_before_valuation_reads_it(self):
        """valuation_bands and intrinsic_value both read the file financial_history writes.
        Reversed, they would score against absent history and say nothing about it."""
        n = nodes("pre", ticker="ASML.AS", mode="deep")
        assert n.index("2.2") < n.index("2.3") < n.index("2.3b")

    def test_the_ticker_is_analysed_before_anything_overlays_it(self):
        """Every 2.x overlay writes into the _tmp JSON that node 2 creates. The macro nodes
        also start with "2." but are run-scoped, so they are absent here by construction --
        which is itself the scoping property TestScoping pins."""
        n = nodes("pre", ticker="ASML.AS", mode="deep")
        assert n.index("2") < min(n.index(x) for x in n if x.startswith("2."))

    def test_the_score_is_finalised_before_the_charts_draw_it(self):
        """render_charts and technical_score both read the composite. Drawing first would
        publish charts of a pre-management-score number."""
        n = nodes("mid", ticker="ASML.AS", mode="deep", mgmt_score=7.5,
                  bear_trigger="margin below 40%")
        assert n.index("2.5-end") < n.index("3") < n.index("3.5")

    def test_the_chart_gate_precedes_the_html_render(self):
        """5.6 is a gate: rendering first makes it an audit of something already published."""
        n = nodes("post", ticker="ASML.AS", mode="deep", report="r.md")
        assert n.index("5.6") < n.index("5.7")

    def test_the_three_stages_do_not_overlap(self):
        """A node in two stages would run twice, and the second run would overwrite the
        first with whatever the LLM had not yet supplied."""
        pre = set(nodes("pre", ticker="T", mode="deep"))
        mid = set(nodes("mid", ticker="T", mode="deep"))
        post = set(nodes("post", ticker="T", mode="deep", report="r.md"))
        assert pre & mid == set() and mid & post == set() and pre & post == set()


# --- run-scoped vs ticker-scoped ---------------------------------------------

class TestScoping:
    def test_pick_candidates_never_runs_on_a_per_ticker_call(self):
        """Three per-ticker calls re-running node 1 would choose a NEW candidate set in the
        middle of analysing the old one."""
        assert "1" not in nodes("pre", ticker="ASML.AS", mode="deep")
        assert "1" in nodes("pre")

    def test_the_macro_fetches_run_once_for_the_day(self):
        for node in ("2.6", "2.6b", "2.6c"):
            assert node in nodes("pre")
            assert node not in nodes("pre", ticker="ASML.AS", mode="deep")

    def test_the_day_closing_nodes_are_not_per_ticker(self):
        per_ticker = nodes("post", ticker="T", mode="deep", report="r.md")
        for node in ("5.7b", "6", "6b", "6c"):
            assert node not in per_ticker
            assert node in nodes("post")


# --- what may fail, and what must stop the stage ------------------------------

class TestRequiredness:
    def test_the_nodes_every_later_node_reads_are_required(self):
        req = {s.node for s in rd.build_plan("pre", ns(ticker="T", mode="deep"))
               if s.required}
        assert {"1", "2", "2.2"} <= req

    def test_an_overlay_node_is_never_required(self):
        """A missing red-flag or lens card costs one section. Marking it required would turn
        a cosmetic gap into a lost digest."""
        opt = {s.node: s.required
               for s in rd.build_plan("pre", ns(ticker="T", mode="deep"))}
        assert opt["2.4"] is False and opt["2.4b"] is False and opt["1.5"] is False

    def test_a_required_node_skipped_for_a_missing_argument_is_an_error(self, capsys):
        """`mid` without --mgmt-score used to print a tidy SKIP line, do nothing at all and
        exit 0 -- a misinvocation that read as a clean stage."""
        rc = rd.main(["mid", "--date", "2026-08-18", "--ticker", "IBM",
                      "--mode", "screen", "--dry-run"])
        out = capsys.readouterr()
        assert rc == 1
        assert "MISINVOKED" in out.err and "mgmt-score" in out.err

    def test_a_deep_only_skip_is_still_just_a_skip(self, capsys):
        """A screen has no charts to draw; node 3 is required AND deep-only, and that
        combination must not turn every screen into a failure."""
        rc = rd.main(["mid", "--date", "2026-08-18", "--ticker", "IBM", "--mode", "screen",
                      "--mgmt-score", "7.5", "--dry-run"])
        assert rc == 0
        assert "MISINVOKED" not in capsys.readouterr().err

    def test_a_required_failure_stops_the_stage_and_says_so(self, tmp_path, monkeypatch,
                                                            capsys):
        """The silent version of this is the 2026-08-15 failure: the run stopped before
        Phase 6 and nothing in the output said which nodes never ran."""
        boom = tmp_path / "boom.py"
        boom.write_text("import sys; sys.exit(3)", encoding="utf-8")
        monkeypatch.setattr(rd, "SCRIPTS", tmp_path)
        monkeypatch.setattr(rd, "build_plan", lambda st, a: [
            rd.Step("A", "explodes", "boom.py", required=True, per_ticker=False),
            rd.Step("B", "never runs", "boom.py", per_ticker=False),
        ])
        rc = rd.main(["pre", "--date", "2026-08-18"])
        out = capsys.readouterr()
        assert rc == 1
        assert "[FAIL]" in out.out and "never runs" not in out.out
        assert "not attempted" in out.err


# --- the email is opt-in even in the finalisation stage -----------------------

def test_the_digest_is_never_sent_by_default():
    """The one irreversible act in the pipeline. The send-once ledger is a backstop, not a
    licence to make every re-run of a finalisation step a delivery decision."""
    assert "7" not in nodes("post")
    assert "7" in nodes("post", email=True)
    assert {s.node: s.needs for s in rd.build_plan("post", ns())}["7"] == ("email",)


# --- the runner never raises --------------------------------------------------

def test_a_missing_script_is_a_fail_not_a_traceback(tmp_path, monkeypatch):
    monkeypatch.setattr(rd, "SCRIPTS", tmp_path)
    state, detail = rd.run_step(rd.Step("X", "gone", "nope.py"), dry_run=False)
    assert state == "FAIL" and detail


def test_dry_run_executes_nothing(tmp_path, monkeypatch):
    marker = tmp_path / "ran.txt"
    script = tmp_path / "writes.py"
    script.write_text(f"open(r'{marker}', 'w').write('x')", encoding="utf-8")
    monkeypatch.setattr(rd, "SCRIPTS", tmp_path)
    state, _ = rd.run_step(rd.Step("X", "writes", "writes.py"), dry_run=True)
    assert state == "PLAN" and not marker.exists()


def test_a_step_that_passes_reports_pass(tmp_path, monkeypatch):
    script = tmp_path / "ok.py"
    script.write_text("print('fine')", encoding="utf-8")
    monkeypatch.setattr(rd, "SCRIPTS", tmp_path)
    state, _ = rd.run_step(rd.Step("X", "ok", "ok.py"), dry_run=False)
    assert state == "PASS"


def test_broken_timing_instrumentation_cannot_break_a_step(tmp_path, monkeypatch):
    """Instrumentation that can fail a run is worse than no instrumentation."""
    script = tmp_path / "ok.py"
    script.write_text("print('fine')", encoding="utf-8")
    monkeypatch.setattr(rd, "SCRIPTS", tmp_path)
    monkeypatch.setattr(rd.node_timing, "record",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    assert rd.run_step(rd.Step("X", "ok", "ok.py"), dry_run=False)[0] == "PASS"


def test_a_flag_with_an_empty_value_is_dropped_as_a_PAIR():
    """Dropping only the empty string left the flag behind, so `["--a", "", "--b", "v"]`
    became `--a --b v` and argparse bound "--b" as the VALUE of --a. The `needs` gate should
    keep empties out of here, but a runner that mis-binds arguments when its guard fails is
    not a contract."""
    assert rd._clean_args(["--a", "", "--b", "v"]) == ["--b", "v"]
    assert rd._clean_args(["--a", "x", "--b", ""]) == ["--a", "x"]
    assert rd._clean_args(["--only-flag", "--b", "v"]) == ["--only-flag", "--b", "v"]
    assert rd._clean_args(["pos.json", "--update"]) == ["pos.json", "--update"]


@pytest.mark.parametrize("stage", ["pre", "mid", "post"])
def test_every_step_names_a_script_that_exists(stage):
    """A typo'd module name is a node that silently never contributes."""
    scripts = Path(rd.SCRIPTS)
    for step in rd.build_plan(stage, ns(ticker="T", mode="deep", report="r.md",
                                        mgmt_score=7.0, bear_trigger="x",
                                        prior_report="p.md")):
        assert (scripts / step.script).exists(), f"{stage}/{step.node}: {step.script}"
