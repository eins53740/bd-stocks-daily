"""
Unit tests for report_history.py — supersede rule, history block, archiver.

Regression cover for the duplication the user reported: ADBE occupying three
"Top scores" rows (8.86 / 8.66 / 8.51) and TSMC appearing as both TSM and
2330.TW. The rule under test: newest evaluation wins, older ones move to
`_archive/`, and the winner carries their record.

Filesystem tests run entirely in tmp_path. No network, no LLM.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import report_history as rh  # noqa: E402


def logrow(ticker, date, score=8.0, mode="deep", verdict="invest",
           price=100.0, ccy="USD", gates="7", notes=""):
    return {"ticker": ticker, "date": date, "score": str(score), "mode": mode,
            "verdict": verdict, "price_at_eval": str(price), "currency": ccy,
            "gates_passed": gates, "notes": notes, "round": "1"}


def write_report(root: Path, date, ticker, suffix, body=""):
    p = root / f"{date}_{ticker}_{suffix}.md"
    p.write_text(body or f"# {ticker}\n", encoding="utf-8")
    return p


# --- supersede rule ---------------------------------------------------------

def test_later_date_wins():
    assert rh.rank("2026-07-14", "deep") > rh.rank("2026-06-09", "deep")


def test_deep_beats_screen_on_the_same_day():
    # The Phase 5.5 cascade writes both; the deep is that work finished.
    assert rh.rank("2026-06-01", "deep") > rh.rank("2026-06-01", "screen")


def test_mode_is_read_from_the_filename_suffix():
    assert rh.mode_of("screen") == "screen"
    for verdict_suffix in ("invest", "review", "fair", "reject", "great"):
        assert rh.mode_of(verdict_suffix) == "deep"


# --- scanning ---------------------------------------------------------------

def test_scan_parses_tickers_containing_dots_and_dashes(tmp_path):
    write_report(tmp_path, "2026-08-05", "NOVO-B.CO", "review")
    write_report(tmp_path, "2026-07-25", "2330.TW", "invest")
    got = {r["ticker"] for r in rh.scan_reports(tmp_path)}
    assert got == {"NOVO-B.CO", "2330.TW"}


def test_scan_ignores_non_report_markdown(tmp_path):
    write_report(tmp_path, "2026-08-05", "ADBE", "invest")
    (tmp_path / "_shortlist.md").write_text("x", encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    assert len(rh.scan_reports(tmp_path)) == 1


# --- summary extraction -----------------------------------------------------

def test_extracts_thesis_line_from_a_deep_report(tmp_path):
    p = write_report(tmp_path, "2026-07-08", "ADBE", "invest", body=(
        "> [!tldr] TL;DR\n"
        "> **Veredicto**: INVEST\n"
        "> **Thesis**: Creative software **monopoly** with pricing power.\n"
        "> **Risks**: AI disruption.\n"))
    assert rh.extract_summary(p) == "Creative software monopoly with pricing power."


def test_extracts_one_liner_from_a_screen_report(tmp_path):
    p = write_report(tmp_path, "2026-04-21", "DECK", "screen", body=(
        "> [!info] Screen rápido (1 min) — 6-component score\n"
        "> 🟢 INVEST (7.72/10, 7/7 gates). HOKA + UGG operator.\n"))
    assert rh.extract_summary(p) == "🟢 INVEST (7.72/10, 7/7 gates). HOKA + UGG operator."


def test_summary_is_truncated_not_wrapped(tmp_path):
    p = write_report(tmp_path, "2026-07-08", "X", "invest",
                     body="> **Thesis**: " + "word " * 200 + "\n")
    s = rh.extract_summary(p)
    assert len(s) <= rh.MAX_SUMMARY_CHARS and s.endswith("…")


def test_unparseable_report_yields_none(tmp_path):
    p = write_report(tmp_path, "2026-04-20", "AMS.MC", "screen", body="no callout here\n")
    assert rh.extract_summary(p) is None


# --- history ----------------------------------------------------------------

def test_history_spans_every_listing_of_the_company():
    rows = [logrow("TSM", "2026-06-01", 8.49), logrow("2330.TW", "2026-07-08", 7.61),
            logrow("TSM", "2026-07-09", 8.34)]
    hist = rh.history_for("2330.TW", "2026-08-06", rows=rows, reports=[])
    assert [h["ticker"] for h in hist] == ["TSM", "2330.TW", "TSM"]


def test_history_excludes_the_current_run_and_anything_later():
    rows = [logrow("ADBE", "2026-06-09", 8.66), logrow("ADBE", "2026-07-14", 8.86),
            logrow("ADBE", "2026-09-01", 9.0)]
    hist = rh.history_for("ADBE", "2026-07-14", rows=rows, reports=[])
    assert [h["date"] for h in hist] == ["2026-06-09"]


def test_history_keeps_the_same_day_screen_that_the_deep_cascaded_from():
    rows = [logrow("PYPL", "2026-06-10", 8.52, mode="screen"),
            logrow("PYPL", "2026-06-10", 8.31, mode="deep")]
    hist = rh.history_for("PYPL", "2026-06-10", rows=rows, reports=[])
    assert [h["mode"] for h in hist] == ["screen"]


def test_history_falls_back_to_log_notes_when_the_report_has_no_thesis():
    rows = [logrow("X", "2026-06-01", notes="cheap but shrinking")]
    hist = rh.history_for("X", "2026-07-01", rows=rows, reports=[])
    assert hist[0]["summary"] == "cheap but shrinking"


def test_history_ignores_machine_tokens_in_notes():
    # notes carries `region=..;sector=..` tokens for the shortlist — not prose.
    rows = [logrow("X", "2026-06-01", notes="region=US;sector=Tech")]
    hist = rh.history_for("X", "2026-07-01", rows=rows, reports=[])
    assert hist[0]["summary"] is None


# --- trend sentence ---------------------------------------------------------

def test_trend_reports_score_delta_against_the_previous_evaluation():
    rows = [logrow("ADBE", "2026-04-20", 8.51), logrow("ADBE", "2026-06-09", 8.66)]
    hist = rh.history_for("ADBE", "2026-07-14", rows=rows, reports=[])
    s = rh.trend_sentence(hist, 8.86, "invest")
    assert "8.66 → **8.86** (+0.20)" in s
    assert "8.51–8.66" in s


def test_trend_calls_out_a_stable_verdict():
    rows = [logrow("A", "2026-01-01", verdict="invest"),
            logrow("A", "2026-03-01", verdict="invest")]
    hist = rh.history_for("A", "2026-06-01", rows=rows, reports=[])
    assert "estável" in rh.trend_sentence(hist, 8.0, "invest")


def test_trend_shows_the_verdict_chain_when_it_moved():
    rows = [logrow("A", "2026-01-01", verdict="review"),
            logrow("A", "2026-03-01", verdict="fair")]
    s = rh.trend_sentence(rh.history_for("A", "2026-06-01", rows=rows, reports=[]),
                          8.0, "invest")
    assert "review → fair → invest" in s


def test_price_delta_only_compares_within_one_currency():
    # A TWD home line and a USD ADR quote the same company 30x apart. Subtracting
    # across them would manufacture a 3000% move.
    rows = [logrow("2330.TW", "2026-05-14", price=2270.0, ccy="TWD"),
            logrow("TSM", "2026-07-09", price=442.99, ccy="USD")]
    hist = rh.history_for("2330.TW", "2026-08-06", rows=rows, reports=[])
    s = rh.trend_sentence(hist, 2400.0, "invest", current_price=2400.0,
                          current_currency="TWD")
    assert "+5.7%" in s and "2,270.00" in s
    assert "442.99" not in s


def test_trend_names_every_listing_the_company_was_seen_under():
    rows = [logrow("TSM", "2026-06-01"), logrow("2330.TW", "2026-07-08")]
    s = rh.trend_sentence(rh.history_for("2330.TW", "2026-08-06", rows=rows, reports=[]),
                          7.9, "invest")
    assert "2 cotações" in s and "TSM" in s and "2330.TW" in s


# --- rendered block ---------------------------------------------------------

def test_no_block_on_a_companys_first_evaluation():
    assert rh.render_block("NVDA", "2026-08-06", rows=[], reports=[]) == ""


def test_block_lists_newest_prior_evaluation_first():
    rows = [logrow("ADBE", "2026-04-20", 8.51), logrow("ADBE", "2026-06-09", 8.66)]
    md = rh.render_block("ADBE", "2026-07-14", 8.86, "invest", rows=rows, reports=[])
    assert md.startswith("## 5. Histórico de avaliações")
    # Compare table rows only — the trend sentence above the table also names
    # the first date ("desde 2026-04-20") and would make a whole-string index lie.
    table = [ln for ln in md.splitlines() if ln.startswith("| 2026-")]
    assert [ln.split("|")[1].strip() for ln in table] == ["2026-06-09", "2026-04-20"]


def test_block_links_to_the_archived_file_when_one_exists(tmp_path):
    p = write_report(tmp_path, "2026-06-09", "ADBE", "invest",
                     body="> **Thesis**: Still a monopoly.\n")
    reports = [{"path": p, "date": "2026-06-09", "ticker": "ADBE",
                "suffix": "invest", "mode": "deep", "company": "ADBE"}]
    md = rh.render_block("ADBE", "2026-07-14", 8.86, "invest",
                         rows=[logrow("ADBE", "2026-06-09", 8.66)], reports=reports)
    assert "[[2026-06-09_ADBE_invest]]" in md
    assert "Still a monopoly." in md


# --- archive ----------------------------------------------------------------

def test_plan_keeps_only_the_newest_report_per_company(tmp_path):
    for d in ("2026-04-20", "2026-06-09", "2026-07-14"):
        write_report(tmp_path, d, "ADBE", "invest")
    plan = rh.plan_archive(rh.scan_reports(tmp_path))
    assert {p["report"]["date"] for p in plan} == {"2026-04-20", "2026-06-09"}
    assert all(p["superseded_by"]["date"] == "2026-07-14" for p in plan)


def test_plan_collapses_across_listings_of_one_company(tmp_path):
    write_report(tmp_path, "2026-07-25", "2330.TW", "invest")
    write_report(tmp_path, "2026-07-27", "TSM", "invest")
    plan = rh.plan_archive(rh.scan_reports(tmp_path))
    assert len(plan) == 1
    assert plan[0]["report"]["ticker"] == "2330.TW"
    assert plan[0]["superseded_by"]["ticker"] == "TSM"


def test_plan_archives_the_screen_that_cascaded_into_a_same_day_deep(tmp_path):
    write_report(tmp_path, "2026-06-01", "AVGO", "screen")
    write_report(tmp_path, "2026-06-01", "AVGO", "invest")
    plan = rh.plan_archive(rh.scan_reports(tmp_path))
    assert len(plan) == 1 and plan[0]["report"]["suffix"] == "screen"


def test_growth_and_quality_reports_are_two_lenses_not_two_attempts(tmp_path):
    # /bd_stocks_daily_growth evaluates the same tickers with gate-5 bypassed by
    # design. Archiving one as "superseded" by the other would silently delete a
    # second opinion. Real pairs on disk 2026-08-05: RDDT, NET, IONQ, ADYEN.AS.
    write_report(tmp_path, "2026-05-18", "RDDT", "screen")
    write_report(tmp_path, "2026-06-10", "RDDT_growth", "rocket")
    scanned = {r["lens"]: r for r in rh.scan_reports(tmp_path)}
    assert set(scanned) == {"quality", "growth"}
    assert scanned["growth"]["ticker"] == "RDDT"   # not "RDDT_growth"
    assert rh.plan_archive(rh.scan_reports(tmp_path)) == []


def test_two_growth_reports_of_one_company_still_collapse(tmp_path):
    write_report(tmp_path, "2026-06-10", "NET_growth", "accelerate")
    write_report(tmp_path, "2026-07-31", "NET_growth", "rocket")
    plan = rh.plan_archive(rh.scan_reports(tmp_path))
    assert len(plan) == 1 and plan[0]["report"]["date"] == "2026-06-10"


def test_history_never_links_a_quality_row_to_a_growth_report(tmp_path):
    p = write_report(tmp_path, "2026-06-10", "NET_growth", "accelerate",
                     body="> **Thesis**: growth-lens take.\n")
    reports = rh.scan_reports(tmp_path)
    assert p.name in {r["path"].name for r in reports}
    hist = rh.history_for("NET", "2026-08-06",
                          rows=[logrow("NET", "2026-06-10")], reports=reports)
    assert hist[0]["link"] is None and hist[0]["summary"] is None


def test_plan_is_empty_when_every_company_has_one_report(tmp_path):
    write_report(tmp_path, "2026-08-05", "ADBE", "invest")
    write_report(tmp_path, "2026-08-05", "NVDA", "review")
    assert rh.plan_archive(rh.scan_reports(tmp_path)) == []


def test_archived_report_gets_its_image_paths_rewritten():
    src = "![Price 1Y](IMG/2026-07-08_TSM_price.png) and ![R](IMG/x.png)"
    out = rh._rewrite_img_paths(src)
    assert out.count("](../IMG/") == 2
    assert "](IMG/" not in out


def test_rewrite_leaves_other_links_alone():
    src = "[[2026-01-01_X_invest]] and [IR](https://x.com/IMG/y)"
    assert rh._rewrite_img_paths(src) == src


def test_archive_moves_md_and_html_and_leaves_the_survivor(tmp_path, monkeypatch):
    monkeypatch.setattr(rh, "OUT_DIR", tmp_path)
    old = write_report(tmp_path, "2026-06-09", "ADBE", "invest",
                       body="![p](IMG/a.png)\n")
    old.with_suffix(".html").write_text("<html></html>", encoding="utf-8")
    write_report(tmp_path, "2026-07-14", "ADBE", "invest")

    result = rh.do_archive(archive_dir=tmp_path / "_archive")

    assert result["archived"] == 1 and result["failed"] == 0
    assert not old.exists() and not old.with_suffix(".html").exists()
    assert (tmp_path / "2026-07-14_ADBE_invest.md").exists()
    moved = tmp_path / "_archive" / "2026-06-09_ADBE_invest.md"
    assert moved.exists() and "](../IMG/a.png)" in moved.read_text(encoding="utf-8")
    assert (tmp_path / "_archive" / "2026-06-09_ADBE_invest.html").exists()


def test_dry_run_touches_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(rh, "OUT_DIR", tmp_path)
    old = write_report(tmp_path, "2026-06-09", "ADBE", "invest")
    write_report(tmp_path, "2026-07-14", "ADBE", "invest")
    result = rh.do_archive(dry_run=True, archive_dir=tmp_path / "_archive")
    assert result["archived"] == 1 and old.exists()
    assert not (tmp_path / "_archive").exists()


def test_archive_never_rescans_its_own_output(tmp_path, monkeypatch):
    # _archive/ is a subdirectory; scan_reports globs the root only. If that ever
    # regressed, a second run would archive the archive.
    monkeypatch.setattr(rh, "OUT_DIR", tmp_path)
    write_report(tmp_path, "2026-06-09", "ADBE", "invest")
    write_report(tmp_path, "2026-07-14", "ADBE", "invest")
    rh.do_archive(archive_dir=tmp_path / "_archive")
    assert rh.do_archive(archive_dir=tmp_path / "_archive")["archived"] == 0


@pytest.mark.parametrize("ticker,expected", [
    ("TSM", "2330.TW"), ("2330.TW", "2330.TW"), ("NVDA", "NVDA")])
def test_company_identity_matches_the_listings_registry(ticker, expected):
    import listings
    assert listings.company_key(ticker) == expected
