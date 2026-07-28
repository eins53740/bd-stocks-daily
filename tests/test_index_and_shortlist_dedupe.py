"""
Regression tests for two silent-omission bugs found on 2026-07-28.

1. `index_reports` matched only `_<verdict>.html`, so every `_screen.html` was
   invisible in the daily hub. On a normal 1-deep + 4-screen day the hub claimed
   "1 report(s)" while five existed — a wrong count reads as a broken pipeline.

2. `build_shortlist` picked the current row per ticker with `date >`, which loses
   the Phase 5.5 cascade: a screen scoring >= 7.5 triggers a same-day deep-dive, so
   both rows share a date, `>` is False, and the first-seen (screen) row wins. The
   real log carries 12 such pairs.

Pure functions: no network.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import render_report as rr  # noqa: E402
import update_shortlist as us  # noqa: E402


FM = """---
ticker: {t}
verdict: {v}
score: {s}
mode: {m}
---
# body
"""


def write_pair(d: Path, name: str, *, ticker, verdict, score, mode):
    (d / f"{name}.html").write_text("<html></html>", encoding="utf-8")
    (d / f"{name}.md").write_text(
        FM.format(t=ticker, v=verdict, s=score, m=mode), encoding="utf-8")


# --- 1. index hub -----------------------------------------------------------

def test_screen_reports_appear_in_the_index(tmp_path):
    write_pair(tmp_path, "2026-07-28_PAYC_review", ticker="PAYC", verdict="review",
               score=6.8, mode="deep")
    write_pair(tmp_path, "2026-07-28_LR.PA_screen", ticker="LR.PA", verdict="fair",
               score=5.2, mode="screen")
    rows = rr.index_reports(tmp_path, "2026-07-28")
    assert [r["ticker"] for r in rows] == ["PAYC", "LR.PA"]  # score desc


def test_screen_verdict_comes_from_frontmatter_not_the_filename(tmp_path):
    write_pair(tmp_path, "2026-07-28_SIKA.SW_screen", ticker="SIKA.SW",
               verdict="invest", score=7.9, mode="screen")
    (row,) = rr.index_reports(tmp_path, "2026-07-28")
    assert row["verdict"] == "invest", "'screen' is a filename token, not a verdict"
    assert row["mode"] == "screen"


def test_deep_report_is_tagged_deep(tmp_path):
    write_pair(tmp_path, "2026-07-28_TSM_invest", ticker="TSM", verdict="invest",
               score=8.1, mode="deep")
    (row,) = rr.index_reports(tmp_path, "2026-07-28")
    assert row["mode"] == "deep"


def test_screen_without_a_sibling_md_still_lists(tmp_path):
    # No frontmatter to read: must not crash, and must not invent a verdict.
    (tmp_path / "2026-07-28_XYZ_screen.html").write_text("<html></html>", encoding="utf-8")
    (row,) = rr.index_reports(tmp_path, "2026-07-28")
    assert row["ticker"] == "XYZ" and row["score"] is None
    assert row["mode"] == "screen"


def test_unrelated_and_other_date_html_is_ignored(tmp_path):
    write_pair(tmp_path, "2026-07-28_OK_screen", ticker="OK", verdict="fair",
               score=5.0, mode="screen")
    (tmp_path / "dashboard.html").write_text("x", encoding="utf-8")
    (tmp_path / "index.html").write_text("x", encoding="utf-8")
    (tmp_path / "2026-07-27_OLD_invest.html").write_text("x", encoding="utf-8")
    assert [r["ticker"] for r in rr.index_reports(tmp_path, "2026-07-28")] == ["OK"]


def test_growth_reports_are_not_swept_into_the_quality_hub(tmp_path):
    # Growth uses its own verdict vocabulary (accelerate/rocket/...) and its own log.
    (tmp_path / "2026-07-28_PDD_growth_accelerate.html").write_text("x", encoding="utf-8")
    assert rr.index_reports(tmp_path, "2026-07-28") == []


def test_index_html_marks_screens_and_counts_every_report(tmp_path):
    write_pair(tmp_path, "2026-07-28_PAYC_review", ticker="PAYC", verdict="review",
               score=6.8, mode="deep")
    write_pair(tmp_path, "2026-07-28_LR.PA_screen", ticker="LR.PA", verdict="fair",
               score=5.2, mode="screen")
    html = rr.build_index_html(tmp_path, "2026-07-28", "")
    assert "2 report(s)" in html
    assert html.count("idx-tier") >= 1, "the screen must be visually distinguishable"


# --- 2. shortlist same-day cascade -----------------------------------------

def row(ticker, d, mode, score=8.0):
    return {"ticker": ticker, "date": d, "mode": mode, "score": str(score),
            "round": "1", "verdict": "invest", "gates_passed": "6", "size": "big",
            "region": "US", "sector": "Tech", "notes": ""}


def test_same_day_deep_supersedes_the_screen():
    screen, deep = row("ACN", "2026-07-28", "screen"), row("ACN", "2026-07-28", "deep")
    assert us._supersedes(deep, screen)
    assert not us._supersedes(screen, deep)


def test_screen_written_first_does_not_win_on_insertion_order():
    # The actual failure: dict insertion order decided it, because `date >` was False.
    latest = {}
    for r in (row("ACN", "2026-07-28", "screen"), row("ACN", "2026-07-28", "deep")):
        if "ACN" not in latest or us._supersedes(r, latest["ACN"]):
            latest["ACN"] = r
    assert latest["ACN"]["mode"] == "deep"


def test_a_later_screen_still_beats_an_older_deep():
    # Recency dominates; the mode tiebreak only applies within the same date.
    assert us._supersedes(row("ACN", "2026-07-28", "screen"), row("ACN", "2026-06-01", "deep"))


def test_older_deep_never_supersedes_a_newer_row():
    assert not us._supersedes(row("ACN", "2026-06-01", "deep"), row("ACN", "2026-07-28", "screen"))


def test_identical_rows_do_not_supersede_each_other():
    r = row("ACN", "2026-07-28", "deep")
    assert not us._supersedes(r, dict(r))


def test_rank_tolerates_missing_and_odd_mode_values():
    assert us._rank({"date": "2026-07-28"}) == ("2026-07-28", 0)
    assert us._rank({"date": "2026-07-28", "mode": " DEEP "}) == ("2026-07-28", 1)
    assert us._rank({}) == ("", 0)
