"""
Unit tests for _log.csv round numbering and same-day supersede.

Two defects this pins down:
  * round was counted per RAW TICKER while pick_candidates counts per COMPANY, so
    evaluating 2330.TW after two TSM visits was written as round 1 while the pick
    JSON said round 3. Anything backtesting "score by round" off the log inherited
    the wrong number.
  * a manual same-day re-run APPENDED a second row, producing a duplicate card in
    that evening's digest and inflating the TODAYCOUNT the email gate reads.

No network: writes to a tmp_path copy of the log.
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import update_log as ul  # noqa: E402


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def run(monkeypatch, log_path: Path, entries: list) -> dict:
    monkeypatch.setattr(ul, "LOG", log_path)
    monkeypatch.setattr(sys, "argv", ["update_log.py", "--entries-json", json.dumps(entries)])
    out = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a))))
    assert ul.main() == 0
    return json.loads(out[-1])


def entry(ticker, date_, mode="screen", score=6.0):
    return {"ticker": ticker, "date": date_, "mode": mode, "verdict": "review",
            "score": score, "gates_passed": 4, "price_at_eval": 100.0,
            "currency": "USD", "size": "big", "notes": ""}


# ---------------------------------------------------------------- round counting

def test_round_counts_per_company_not_per_ticker_string():
    rows = [{"ticker": "TSM", "date": "2026-01-01"}, {"ticker": "TSM", "date": "2026-03-01"}]
    # The Taiwan line is the same company as the ADR -> third visit, not first.
    assert ul.round_for("2330.TW", "2026-08-03", rows) == 3
    assert ul.round_for("TSM", "2026-08-03", rows) == 3
    assert ul.round_for("UNSEEN", "2026-08-03", rows) == 1


def test_same_day_pair_is_one_visit():
    rows = [{"ticker": "AAA", "date": "2026-08-03", "mode": "screen"}]
    assert ul.round_for("AAA", "2026-08-03", rows) == 1


# ---------------------------------------------------------------- supersede

def test_plain_append_leaves_prior_rows_alone(tmp_path, monkeypatch):
    log = tmp_path / "_log.csv"
    run(monkeypatch, log, [entry("AAA", "2026-08-01")])
    res = run(monkeypatch, log, [entry("BBB", "2026-08-02")])
    assert res["superseded"] == 0
    assert [r["ticker"] for r in read(log)] == ["AAA", "BBB"]


def test_same_day_rerun_supersedes_instead_of_duplicating(tmp_path, monkeypatch):
    log = tmp_path / "_log.csv"
    run(monkeypatch, log, [entry("AAA", "2026-08-03", score=5.0)])
    res = run(monkeypatch, log, [entry("AAA", "2026-08-03", score=8.5)])
    rows = read(log)
    assert res["superseded"] == 1
    assert len(rows) == 1                      # one card in the digest, not two
    assert float(rows[0]["score"]) == 8.5      # the re-run wins
    assert rows[0]["round"] == "1"             # a re-run is not a new visit


def test_same_day_screen_then_deep_are_both_kept(tmp_path, monkeypatch):
    """The Phase 5.5 cascade is two legitimate rows -- mode is part of the key."""
    log = tmp_path / "_log.csv"
    run(monkeypatch, log, [entry("AAA", "2026-08-03", mode="screen")])
    res = run(monkeypatch, log, [entry("AAA", "2026-08-03", mode="deep")])
    assert res["superseded"] == 0
    assert [r["mode"] for r in read(log)] == ["screen", "deep"]


def test_duplicate_keys_within_one_batch_collapse(tmp_path, monkeypatch):
    """`incoming` only filters PRE-EXISTING rows, so a batch carrying the same key twice would
    otherwise write both. Last one wins, matching the supersede rule applied to history."""
    log = tmp_path / "_log.csv"
    run(monkeypatch, log, [entry("AAA", "2026-08-03", score=1.0),
                           entry("AAA", "2026-08-03", score=7.0),
                           entry("BBB", "2026-08-03")])
    rows = read(log)
    assert [r["ticker"] for r in rows] == ["AAA", "BBB"]
    assert float(rows[0]["score"]) == 7.0


def test_supersede_preserves_unrelated_history(tmp_path, monkeypatch):
    log = tmp_path / "_log.csv"
    run(monkeypatch, log, [entry("AAA", "2026-07-01")])
    run(monkeypatch, log, [entry("BBB", "2026-08-03")])
    run(monkeypatch, log, [entry("AAA", "2026-08-03", score=4.0)])
    run(monkeypatch, log, [entry("AAA", "2026-08-03", score=9.0)])
    rows = read(log)
    assert [r["ticker"] for r in rows] == ["AAA", "BBB", "AAA"]
    assert float(rows[-1]["score"]) == 9.0
    assert rows[-1]["round"] == "2"             # July visit + today = round 2
    assert not list(log.parent.glob("*.tmp"))   # atomic write left no debris
