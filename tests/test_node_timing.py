"""node_timing must produce usable data and must never break a run.

The second property is the load-bearing one: this module is instrumentation added to a job
that already times out, so a bug in it must degrade to "no timings", never to "no digest".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import node_timing as nt  # noqa: E402


@pytest.fixture
def timings(tmp_path, monkeypatch):
    """Point the module at a temp dir and re-enable recording."""
    monkeypatch.setattr(nt, "TIMINGS_DIR", tmp_path / "_timings")
    monkeypatch.setattr(nt, "ENABLED", True)
    return tmp_path / "_timings"


# --------------------------------------------------------------- recording

def test_record_writes_one_json_line(timings):
    nt.record("2.2", 12.345, ticker="ASML.AS")
    lines = [l for l in (list(timings.glob("*.jsonl"))[0]).read_text("utf-8").splitlines() if l]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["node"] == "2.2"
    assert entry["ticker"] == "ASML.AS"
    assert entry["elapsed_s"] == 12.35  # rounded to 2dp
    assert entry["ok"] is True


def test_record_appends_rather_than_overwriting(timings):
    """Append-only is what makes a killed run keep the timings it already produced --
    the 2026-08-15 timeout lost Phase 6 and everything it would have written."""
    for i in range(5):
        nt.record(f"n{i}", i)
    assert len(nt.load()) == 5


def test_disabled_records_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "TIMINGS_DIR", tmp_path / "_timings")
    monkeypatch.setattr(nt, "ENABLED", False)
    nt.record("2.2", 1.0)
    assert nt.load() == []


def test_record_never_raises_even_on_an_unwritable_path(monkeypatch):
    """The whole point: instrumentation failure must not surface to the caller."""
    monkeypatch.setattr(nt, "TIMINGS_DIR", Path("\x00::/nonsense/cannot/exist"))
    monkeypatch.setattr(nt, "ENABLED", True)
    nt.record("2.2", 1.0)  # must not raise


# --------------------------------------------------------------- context manager

def test_timed_records_on_success(timings):
    with nt.timed("3", ticker="IBM"):
        pass
    rows = nt.load()
    assert len(rows) == 1 and rows[0]["node"] == "3" and rows[0]["ok"] is True


def test_timed_records_and_reraises_on_failure(timings):
    with pytest.raises(ValueError):
        with nt.timed("2.59"):
            raise ValueError("boom")
    rows = nt.load()
    assert len(rows) == 1
    assert rows[0]["ok"] is False, "a node that blew up must be recorded as a failure"


# --------------------------------------------------------------- summarise (pure)

def test_summarise_aggregates_and_orders_by_total_time():
    rows = [
        {"node": "2.2", "elapsed_s": 10, "ok": True},
        {"node": "2.2", "elapsed_s": 30, "ok": True},
        {"node": "3", "elapsed_s": 50, "ok": True},
    ]
    s = nt.summarise(rows)
    assert [a["node"] for a in s] == ["3", "2.2"], "biggest consumer first"
    two_two = next(a for a in s if a["node"] == "2.2")
    assert two_two["calls"] == 2
    assert two_two["total_s"] == 40
    assert two_two["mean_s"] == 20
    assert two_two["max_s"] == 30


def test_summarise_counts_failures():
    rows = [{"node": "2.5", "elapsed_s": 1, "ok": False},
            {"node": "2.5", "elapsed_s": 1, "ok": True}]
    assert nt.summarise(rows)[0]["failures"] == 1


def test_summarise_of_nothing_is_empty_not_an_error():
    assert nt.summarise([]) == []


def test_load_skips_corrupt_lines_rather_than_failing(timings):
    timings.mkdir(parents=True, exist_ok=True)
    p = nt._path_for()
    p.write_text('{"node":"2.2","elapsed_s":1,"ok":true}\nNOT JSON\n\n', encoding="utf-8")
    rows = nt.load()
    assert len(rows) == 1, "one bad line must not discard the good ones"


# --------------------------------------------------------------- CLI

def test_cli_wrapper_propagates_the_child_exit_code(timings, monkeypatch):
    monkeypatch.setattr(nt, "TIMINGS_DIR", timings)
    rc = nt.main(["--node", "9.9", "--", sys.executable, "-c", "import sys; sys.exit(7)"])
    assert rc == 7, "the wrapper must be transparent to the caller's exit code"
    rows = nt.load()
    assert rows and rows[0]["ok"] is False
