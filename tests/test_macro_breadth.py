"""
Unit tests for macro_breadth.py — all pure-function / injected-payload, network-free.

Exercises:
  * breadth_stats()       — percentile placement, trend arrow + deadband, short/empty degradation.
  * sector_trend()        — 20d/60d MA trend, volume direction, confirms logic, insufficient-history degradation.
  * _percentile_rank()    — high/low/mid/single-element placement.
  * update_macro_json()   — additive merge is OVERLAY-ONLY (existing `metrics` byte-identical),
                            init-if-missing, and one forcibly-failed gauge still yields a
                            renderable structure (Phase D acceptance gate).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from macro_breadth import (  # noqa: E402
    _percentile_rank,
    breadth_stats,
    sector_trend,
    update_macro_json,
)


# ----------------------------------------------------------------- _percentile_rank
def test_percentile_rank_all_time_high():
    series = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _percentile_rank(series, 5.0) == 90.0  # (4 below + 0.5 equal)/5


def test_percentile_rank_all_time_low():
    series = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _percentile_rank(series, 1.0) == 10.0  # (0 below + 0.5 equal)/5


def test_percentile_rank_mid():
    series = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _percentile_rank(series, 3.0) == 50.0


def test_percentile_rank_single_and_empty():
    assert _percentile_rank([42.0], 42.0) == 50.0
    assert _percentile_rank([], 1.0) is None


# ----------------------------------------------------------------- breadth_stats
def test_breadth_stats_high_percentile_and_uptrend():
    # Rising ratio series (len > lookback): current at the top, trend up.
    series = [1.0 + i * 0.01 for i in range(40)]  # 1.00 .. 1.39
    r = breadth_stats(series, lookback=20)
    assert r["ratio_now"] == round(series[-1], 6)
    assert r["percentile"] == 98.8  # all-time high, 40-pt series: round((39+0.5)/40*100, 1)
    assert r["min"] == 1.0
    assert r["max"] == round(series[-1], 6)
    assert r["trend"] == "↑"
    assert r["depth_days"] == 40


def test_breadth_stats_downtrend():
    series = [2.0 - i * 0.01 for i in range(40)]  # falling
    r = breadth_stats(series, lookback=20)
    assert r["trend"] == "↓"
    assert r["percentile"] == 1.2  # all-time low: round((0+0.5)/40*100, 1)


def test_breadth_stats_flat_within_deadband():
    # 30 points hovering within <0.5% of each other -> flat arrow.
    series = [1.000, 1.001, 1.0005] * 10
    r = breadth_stats(series, lookback=20)
    assert r["trend"] == "→"


def test_breadth_stats_short_series_no_trend():
    # len <= lookback -> trend degrades to None, stats still computed.
    r = breadth_stats([1.0, 1.1, 1.2], lookback=20)
    assert r["trend"] is None
    assert r["ratio_now"] == 1.2
    assert r["depth_days"] == 3


def test_breadth_stats_empty_error():
    assert breadth_stats([]) == {"error": "no ratio data"}


# ----------------------------------------------------------------- sector_trend
def _rising(n: int, start: float = 100.0, step: float = 0.5) -> list[float]:
    return [start + i * step for i in range(n)]


def _falling(n: int, start: float = 200.0, step: float = 0.5) -> list[float]:
    return [start - i * step for i in range(n)]


# Volume fixtures: recent-5d mean strictly above / below the trailing 20d mean.
_RISING_VOL = [1_000.0] * 75 + [5_000.0] * 5   # recent spike -> rising vs 20d MA
_FALLING_VOL = [5_000.0] * 75 + [1_000.0] * 5  # recent drop  -> falling vs 20d MA


def test_sector_trend_uptrend_volume_confirms():
    closes = _rising(80)             # ma20 > ma60 -> uptrend
    r = sector_trend(closes, _RISING_VOL)
    assert r["trend"] == "↑"
    assert r["vol_direction"] == "rising"
    assert r["confirms"] is True


def test_sector_trend_uptrend_volume_suspect():
    closes = _rising(80)
    r = sector_trend(closes, _FALLING_VOL)
    assert r["trend"] == "↑"
    assert r["vol_direction"] == "falling"
    assert r["confirms"] is False


def test_sector_trend_downtrend_on_rising_volume_confirms():
    closes = _falling(80)            # ma20 < ma60 -> downtrend
    r = sector_trend(closes, _RISING_VOL)  # rising -> distribution confirms the down move
    assert r["trend"] == "↓"
    assert r["vol_direction"] == "rising"
    assert r["confirms"] is True


def test_sector_trend_flat_confirms_none():
    closes = [100.0] * 80            # ma20 == ma60 -> flat
    r = sector_trend(closes, _RISING_VOL)
    assert r["trend"] == "→"
    assert r["confirms"] is None     # no trend to confirm


def test_sector_trend_insufficient_history_degrades():
    # <60 closes -> trend "na"; <20 volumes -> vol_direction None; no exception.
    r = sector_trend(_rising(30), [1_000.0] * 10)
    assert r["trend"] == "na"
    assert r["vol_direction"] is None
    assert r["confirms"] is None
    assert r["ma60"] is None
    assert r["ma20"] is not None    # 30 >= 20


def test_sector_trend_empty_error():
    assert sector_trend([], []) == {"error": "no data"}


# ----------------------------------------------------------------- update_macro_json (merge)
def _seed_snapshot(out_dir: Path, d: date) -> Path:
    """Write a minimal pre-Phase-D _macro/<date>.json with a metrics block."""
    p = out_dir / f"{d.isoformat()}.json"
    p.write_text(
        json.dumps(
            {
                "date": d.isoformat(),
                "fetched_at": "2026-07-22T17:04:49",
                "metrics": {"^GSPC": {"last": 7522.2, "chg_1d_pct": 0.17, "chg_1w_pct": -0.66}},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return p


_FAKE_PAYLOAD = {
    "breadth": {"ratio_now": 0.27, "percentile": 12.0, "trend": "↓", "depth_days": 5000, "as_of": "2026-07-22"},
    "sectors": {
        "as_of": "2026-07-22",
        "market": {"symbol": "SPY", "name": "S&P 500 (overall)", "trend": "↑", "vol_direction": "rising", "confirms": True},
        "rows": [
            {"symbol": "XLK", "name": "Technology", "trend": "↑", "vol_direction": "rising", "confirms": True},
            {"symbol": "XLE", "name": "Energy", "error": "no data"},  # one forcibly-failed gauge
        ],
    },
}


def test_update_merge_is_overlay_only(tmp_path):
    d = date(2026, 7, 22)
    p = _seed_snapshot(tmp_path, d)
    before = json.loads(p.read_text(encoding="utf-8"))

    after = update_macro_json(tmp_path, today=d, payload=_FAKE_PAYLOAD)

    # Existing metrics block untouched (overlay-only); two additive keys present.
    assert after["metrics"] == before["metrics"]
    assert after["fetched_at"] == before["fetched_at"]
    assert after["breadth"] == _FAKE_PAYLOAD["breadth"]
    assert after["sectors"] == _FAKE_PAYLOAD["sectors"]
    # Persisted to disk, not just returned.
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["metrics"] == before["metrics"]
    assert on_disk["sectors"]["rows"][1]["error"] == "no data"


def test_update_initialises_when_json_missing(tmp_path):
    d = date(2026, 7, 22)
    # No pre-existing file: --update must create it rather than crash.
    after = update_macro_json(tmp_path, today=d, payload=_FAKE_PAYLOAD)
    assert after["date"] == d.isoformat()
    assert after["breadth"]["trend"] == "↓"
    assert (tmp_path / f"{d.isoformat()}.json").exists()


def test_update_tolerates_failed_gauge_still_renderable(tmp_path):
    # Acceptance gate: a breadth error + a sector error entry still merge cleanly
    # and the structure remains renderable (the good rows survive).
    d = date(2026, 7, 22)
    _seed_snapshot(tmp_path, d)
    payload = {
        "breadth": {"error": "no SPY/RSP data"},
        "sectors": _FAKE_PAYLOAD["sectors"],
    }
    after = update_macro_json(tmp_path, today=d, payload=payload)
    assert after["breadth"] == {"error": "no SPY/RSP data"}
    good = [r for r in after["sectors"]["rows"] if "error" not in r]
    assert len(good) == 1 and good[0]["symbol"] == "XLK"
    assert after["metrics"]["^GSPC"]["last"] == 7522.2  # untouched despite failures
