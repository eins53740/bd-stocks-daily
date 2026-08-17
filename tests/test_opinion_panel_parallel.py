"""The 3-persona panel asks its three questions concurrently (A2, 2026-08-17).

The personas are independent by design -- same evidence prompt, different system message,
none of them sees another's answer (spec 10b, "nao eco"). They were nonetheless run in a
plain `for` loop, so three independent network round-trips were serialised on the 30-minute
critical path.

Safe HERE and not elsewhere: the panel talks to Groq/Gemini, and a refused call surfaces as
an unavailable card. yfinance -- which SKILL.md's "Phase 2, sequential" rule and the
2026-08-15 incident are actually about -- answers a throttled request with an EMPTY FRAME
that looks like success. These tests pin both the concurrency and the ordering it must not
cost us.

llm_client is replaced wholesale: no network, no API keys.
"""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import second_opinion as so  # noqa: E402

EVIDENCE = {"ticker": "TEST", "top_strip": {"pe": 20}}


class _Recorder:
    """Stands in for llm_client.complete_json; records concurrency and answers per persona."""

    def __init__(self, delay=0.10):
        self.delay = delay
        self.live = 0
        self.peak = 0
        self.seen: list[str] = []
        self._lk = threading.Lock()

    def complete_json(self, prompt, system, keys=None):
        with self._lk:
            self.live += 1
            self.peak = max(self.peak, self.live)
            self.seen.append(system)
        time.sleep(self.delay)
        with self._lk:
            self.live -= 1
        # Conviction encodes which persona asked, so ordering is checkable downstream.
        idx = next(i for i, p in enumerate(so.PERSONAS) if p["system"] == system)
        return {"ok": True, "data": {"verdict": "hold", "conviction_0_100": 10 * (idx + 1),
                                     "one_liner": f"persona {idx}"}}


@pytest.fixture
def rec(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(so.llm_client, "complete_json", r.complete_json)
    return r


def test_all_three_personas_are_in_flight_together(rec):
    cards = so.run_panel(EVIDENCE)
    assert len(cards) == len(so.PERSONAS) == 3
    assert rec.peak == 3, f"personas still serialised (peak in-flight = {rec.peak})"


def test_the_wall_clock_is_one_call_not_three(monkeypatch):
    r = _Recorder(delay=0.25)
    monkeypatch.setattr(so.llm_client, "complete_json", r.complete_json)
    started = time.time()
    so.run_panel(EVIDENCE)
    elapsed = time.time() - started
    assert elapsed < 0.25 * 2, f"took {elapsed:.2f}s for 3x0.25s calls -- not concurrent"


def test_the_card_order_is_the_persona_order_not_the_completion_order(monkeypatch):
    """executor.map yields in INPUT order. If it did not, the panel would be shuffled
    differently on every run: the card list IS the report's persona order, and consensus()
    indexes into it. Slowest-first makes completion order the reverse of input order."""
    delays = {p["system"]: d for p, d in zip(so.PERSONAS, (0.30, 0.15, 0.01))}

    def slow(prompt, system, keys=None):
        time.sleep(delays[system])
        idx = next(i for i, p in enumerate(so.PERSONAS) if p["system"] == system)
        return {"ok": True, "data": {"verdict": "hold", "conviction_0_100": 10 * (idx + 1),
                                     "one_liner": f"persona {idx}"}}

    monkeypatch.setattr(so.llm_client, "complete_json", slow)
    cards = so.run_panel(EVIDENCE)
    assert [c["name"] for c in cards] == [p["name"] for p in so.PERSONAS]
    assert [c["conviction_0_100"] for c in cards] == [10, 20, 30]


def test_one_dead_persona_does_not_take_the_panel_down(monkeypatch):
    """A dead persona was already meant to render `available: false` without blocking the
    others; concurrency must not have quietly turned it into a raised exception."""
    def flaky(prompt, system, keys=None):
        if system == so.PERSONAS[1]["system"]:
            raise RuntimeError("provider down")
        return {"ok": True, "data": {"verdict": "hold", "conviction_0_100": 55,
                                     "one_liner": "ok"}}

    monkeypatch.setattr(so.llm_client, "complete_json", flaky)
    cards = so.run_panel(EVIDENCE)
    assert len(cards) == 3
    assert [c.get("available") for c in cards] == [True, False, True]


def test_setting_the_worker_count_to_one_serialises_again(monkeypatch):
    """The escape hatch has to actually work -- it is what a provider refusing concurrent
    requests would be fixed with, at 13:30, without a code change."""
    r = _Recorder()
    monkeypatch.setattr(so.llm_client, "complete_json", r.complete_json)
    monkeypatch.setattr(so, "PANEL_MAX_WORKERS", 1)
    cards = so.run_panel(EVIDENCE)
    assert r.peak == 1
    assert [c["name"] for c in cards] == [p["name"] for p in so.PERSONAS]


def test_a_zero_or_negative_worker_count_still_runs_the_panel(monkeypatch):
    """max(1, ...) -- a misconfigured 0 must degrade to serial, never to an empty panel."""
    r = _Recorder()
    monkeypatch.setattr(so.llm_client, "complete_json", r.complete_json)
    monkeypatch.setattr(so, "PANEL_MAX_WORKERS", 0)
    assert len(so.run_panel(EVIDENCE)) == 3
