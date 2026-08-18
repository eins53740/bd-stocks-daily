"""Tests for log_orphan_check.py -- the "delivered but unlogged" guard (roadmap R12)."""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location("log_orphan_check", SCRIPTS / "log_orphan_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load()

HEADERS = ["ticker", "date", "round", "mode", "verdict", "score", "gates_passed",
           "price_at_eval", "currency", "size", "notes", "management_score",
           "management_flag", "bear_case_trigger"]

REPORT = """---
tags: [stocks, evaluation, finance]
ticker: {tic}
date: {date}
round: 2
mode: deep
verdict: review
score: 7.25
gates_passed: 5
price_at_eval: 57.65
currency: EUR
size: small_growth
management_score: 7.5
management_flag: false
bear_case_trigger: "If X then the thesis is broken."
---

# body
"""


def _state(tmp_path: Path, logged: list[tuple[str, str]], reports: list[tuple[str, str]]) -> Path:
    root = tmp_path / "StocksDaily"
    root.mkdir()
    with (root / "_log.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADERS)
        w.writeheader()
        for tic, date in logged:
            w.writerow({**{h: "" for h in HEADERS}, "ticker": tic, "date": date, "round": "1"})
    for tic, date in reports:
        (root / f"{date}_{tic}_review.md").write_text(REPORT.format(tic=tic, date=date), encoding="utf-8")
    return root


@pytest.fixture()
def patched(tmp_path, monkeypatch):
    def _make(logged, reports):
        root = _state(tmp_path, logged, reports)
        monkeypatch.setattr(MOD, "_CANDIDATES", (root,))
        return root
    return _make


def test_frontmatter_of_a_real_report(tmp_path):
    p = tmp_path / "2026-08-17_ROVI.MC_review.md"
    p.write_text(REPORT.format(tic="ROVI.MC", date="2026-08-17"), encoding="utf-8")
    fm = MOD.frontmatter(p)
    assert fm["ticker"] == "ROVI.MC"
    assert fm["date"] == "2026-08-17"
    assert fm["bear_case_trigger"] == "If X then the thesis is broken."   # quotes stripped
    assert "tags" in fm and fm["tags"] == "[stocks, evaluation, finance]"  # not parsed, just carried


def test_clean_state_exits_zero(patched, capsys):
    patched([("ROVI.MC", "2026-08-17")], [("ROVI.MC", "2026-08-17")])
    sys.argv = ["log_orphan_check.py"]
    assert MOD.main() == 0
    assert "ORPHANS  : none" in capsys.readouterr().out


def test_orphan_is_detected_and_exit_is_nonzero(patched, capsys):
    patched([], [("ROVI.MC", "2026-08-17")])
    sys.argv = ["log_orphan_check.py"]
    assert MOD.main() == 1, "an unlogged report must fail the check, so a watchdog can see it"
    out = capsys.readouterr().out
    assert "ORPHANS  : 1" in out and "ROVI.MC" in out


def test_fix_appends_the_row_from_the_front_matter(patched):
    root = patched([], [("ROVI.MC", "2026-08-17")])
    sys.argv = ["log_orphan_check.py", "--fix"]
    assert MOD.main() == 0
    rows = list(csv.DictReader((root / "_log.csv").open(newline="", encoding="utf-8")))
    assert len(rows) == 1
    r = rows[0]
    assert (r["ticker"], r["date"], r["verdict"], r["score"]) == ("ROVI.MC", "2026-08-17", "review", "7.25")
    assert r["management_flag"] == "False", "flag must be CSV-canonical, not the YAML 'false'"
    assert "R12" in r["notes"], "the row must say why it exists"
    assert (root / "_log.csv.pre-orphan-fix").exists(), "a write to the source of truth needs a backup"


def test_fix_is_idempotent(patched):
    root = patched([], [("ROVI.MC", "2026-08-17")])
    sys.argv = ["log_orphan_check.py", "--fix"]
    MOD.main()
    MOD.main()
    rows = list(csv.DictReader((root / "_log.csv").open(newline="", encoding="utf-8")))
    assert len(rows) == 1, "re-running must not duplicate the row"


def test_since_filter_excludes_older_reports(patched, capsys):
    patched([], [("OLD", "2026-01-05"), ("ROVI.MC", "2026-08-17")])
    sys.argv = ["log_orphan_check.py", "--since", "2026-08-01"]
    assert MOD.main() == 1
    out = capsys.readouterr().out
    assert "ROVI.MC" in out and "OLD" not in out


def test_describe_root_names_the_machine():
    r"""R12 follow-up: the line used to print C:\ on BOTH machines (vmhost1 has a junction),
    which is the one thing a single-writer tool must not be silent about."""
    import socket
    out = MOD.describe_root(Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily"))
    assert socket.gethostname() in out
    assert "StocksDaily" in out


def test_describe_root_flags_a_junction(tmp_path):
    real = tmp_path / "real"
    real.mkdir()

    # A plain directory resolves to itself -> no junction annotation.
    assert "junction" not in MOD.describe_root(real)

    # A path whose resolve() lands elsewhere must say so AND show the target, because the
    # target is the answer to "which machine did I just write to".
    class Redirected(type(real)):
        def resolve(self, strict=False):
            return real

    out = MOD.describe_root(Redirected(tmp_path / "link"))
    assert "junction" in out and str(real) in out
