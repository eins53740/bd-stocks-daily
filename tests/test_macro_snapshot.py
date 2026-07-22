"""
Unit tests for macro_snapshot.py — all pure-function, network-free.

Exercises:
  * compute_changes()          — 1d/1w pct math, short-frame degradation to None.
  * parse_country_table_date() — frontmatter date extraction (present/missing/bad).
  * check()                    — freshness directive against a tmp _macro dir:
                                 empty -> missing; older file -> fallback picked;
                                 today's file -> fresh; country_table_fresh window.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from macro_snapshot import (  # noqa: E402
    check,
    compute_changes,
    parse_country_table_date,
)


# ----------------------------------------------------------------- compute_changes
def test_compute_changes_normal_series():
    # 21 closes rising by 1 each day: 100..120. last=120.
    closes = [100.0 + i for i in range(21)]
    r = compute_changes(closes)
    assert r["last"] == 120.0
    # 1d: 120 vs 119 -> +0.84%
    assert r["chg_1d_pct"] == round((120.0 / 119.0 - 1.0) * 100.0, 2)
    # 1w: 120 vs closes[-6]=115 -> +4.35%
    assert r["chg_1w_pct"] == round((120.0 / 115.0 - 1.0) * 100.0, 2)


def test_compute_changes_short_frame_no_week():
    # 5 closes -> enough for 1d, not for 1w (needs 6).
    closes = [10.0, 11.0, 12.0, 13.0, 14.0]
    r = compute_changes(closes)
    assert r["last"] == 14.0
    assert r["chg_1d_pct"] == round((14.0 / 13.0 - 1.0) * 100.0, 2)
    assert r["chg_1w_pct"] is None


def test_compute_changes_single_close_both_none():
    r = compute_changes([42.0])
    assert r["last"] == 42.0
    assert r["chg_1d_pct"] is None
    assert r["chg_1w_pct"] is None


def test_compute_changes_empty():
    r = compute_changes([])
    assert r == {"last": None, "chg_1d_pct": None, "chg_1w_pct": None}


def test_compute_changes_zero_reference_degrades_to_none():
    # prev close 0 -> 1d None rather than ZeroDivisionError; 1w still computes
    # off closes[-6]=1.0.
    closes = [1.0, 2.0, 3.0, 4.0, 0.0, 10.0]
    r = compute_changes(closes)
    assert r["last"] == 10.0
    assert r["chg_1d_pct"] is None
    assert r["chg_1w_pct"] == round((10.0 / 1.0 - 1.0) * 100.0, 2)


# ----------------------------------------------------------------- country table date
_FM_TEMPLATE = "---\ndate: 2026-07-15\ncountry_table_date: {d}\nschema_version: \"1\"\n---\n\n# body\n"


def test_parse_country_table_date_present():
    txt = _FM_TEMPLATE.format(d="2026-07-10")
    assert parse_country_table_date(txt) == date(2026, 7, 10)


def test_parse_country_table_date_missing_key():
    txt = "---\ndate: 2026-07-15\nschema_version: \"1\"\n---\n\n# body\n"
    assert parse_country_table_date(txt) is None


def test_parse_country_table_date_no_frontmatter():
    assert parse_country_table_date("# just a heading\n") is None


def test_parse_country_table_date_bad_value():
    txt = _FM_TEMPLATE.format(d="not-a-date")
    assert parse_country_table_date(txt) is None


# ----------------------------------------------------------------- check() directive
def _write_macro(out_dir: Path, d: date, country_table_date: date | None = None) -> Path:
    fm = f"---\ndate: {d.isoformat()}\n"
    if country_table_date is not None:
        fm += f"country_table_date: {country_table_date.isoformat()}\n"
    fm += "schema_version: \"1\"\n---\n\n# macro\n"
    p = out_dir / f"{d.isoformat()}.md"
    p.write_text(fm, encoding="utf-8")
    return p


def test_check_empty_dir_missing(tmp_path):
    r = check(tmp_path)
    assert r["exists"] is False
    assert r["stale"] is True
    assert r["reason"] == "missing"
    assert r["fallback_md"] is None
    assert r["fallback_age_days"] is None
    assert r["country_table_fresh"] is False
    assert r["md_path"].endswith(f"{date.today().isoformat()}.md")


def test_check_older_file_becomes_fallback(tmp_path):
    today = date.today()
    old = today - timedelta(days=3)
    older = today - timedelta(days=9)
    _write_macro(tmp_path, old)
    _write_macro(tmp_path, older)
    r = check(tmp_path)
    assert r["stale"] is True
    assert r["reason"] == "expired"
    # newest older file (3 days) wins over the 9-day one
    assert r["fallback_md"].endswith(f"{old.isoformat()}.md")
    assert r["fallback_age_days"] == 3


def test_check_todays_file_fresh(tmp_path):
    today = date.today()
    _write_macro(tmp_path, today)
    r = check(tmp_path)
    assert r["exists"] is True
    assert r["stale"] is False
    assert r["reason"] == "fresh"
    assert r["fallback_md"] is None


def test_check_country_table_fresh_within_window(tmp_path):
    today = date(2026, 7, 15)
    # newest md is 1 day old, its country_table_date is 3 days old -> fresh.
    _write_macro(tmp_path, today - timedelta(days=1), country_table_date=today - timedelta(days=3))
    r = check(tmp_path, today=today)
    assert r["country_table_fresh"] is True


def test_check_country_table_stale_outside_window(tmp_path):
    today = date(2026, 7, 15)
    _write_macro(tmp_path, today - timedelta(days=1), country_table_date=today - timedelta(days=10))
    r = check(tmp_path, today=today)
    assert r["country_table_fresh"] is False


def test_check_country_table_missing_key_not_fresh(tmp_path):
    today = date(2026, 7, 15)
    _write_macro(tmp_path, today - timedelta(days=1), country_table_date=None)
    r = check(tmp_path, today=today)
    assert r["country_table_fresh"] is False
