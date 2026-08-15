"""
Unit tests for company_names.py and check_report_charts.py — the two helpers
added 2026-08-05 for readable shortlist labels and the chart-embedding gate.

No network. Filesystem work runs in tmp_path.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_report_charts as cg  # noqa: E402
import company_names as cn  # noqa: E402


# --- name shortening --------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Adobe Inc.", "Adobe"),
    ("Evolution AB (publ)", "Evolution"),
    ("Amadeus IT Group, S.A.", "Amadeus IT"),
    ("Wolters Kluwer N.V.", "Wolters Kluwer"),
    ("Geely Automobile Holdings Limited", "Geely Automobile"),
])
def test_legal_suffixes_are_stripped(raw, expected):
    assert cn.shorten(raw) == expected


def test_shorten_never_returns_empty():
    # A name that is nothing BUT legal noise must fall back to the original,
    # otherwise the label collapses to "TICKER ()".
    assert cn.shorten("Holdings Ltd") != ""


def test_long_names_are_truncated_with_an_ellipsis():
    s = cn.shorten("A" * 80)
    assert len(s) <= cn.MAX_NAME_CHARS and s.endswith("…")


# --- lookup -----------------------------------------------------------------

def test_label_falls_back_to_bare_ticker_when_unknown():
    assert cn.label("ZZZZ", names={}) == "ZZZZ"


def test_label_renders_ticker_and_name():
    assert cn.label("ADBE", names={"ADBE": "Adobe Inc."}) == "ADBE (Adobe)"


def test_name_resolves_across_listings_of_one_company():
    # The ADR-era report may hold a name the home line never recorded.
    assert cn.name_for("2330.TW", names={"TSM": "Taiwan Semiconductor"}) \
        == "Taiwan Semiconductor"


def test_registry_supplies_names_for_dual_listed_companies():
    reg = cn._from_registry()
    assert reg.get("2330.TW") == reg.get("TSM") == "Taiwan Semiconductor Manufacturing"


# --- building ---------------------------------------------------------------

def test_report_titles_are_parsed(tmp_path):
    (tmp_path / "2026-07-27_TSM_invest.md").write_text(
        "# TSM — Taiwan Semiconductor Manufacturing Company Limited — Score: 8.14/10 🟢 INVEST\n",
        encoding="utf-8")
    assert cn._from_report_titles(tmp_path)["TSM"].startswith("Taiwan Semiconductor")


def test_analysis_json_beats_report_title(tmp_path):
    (tmp_path / "2026-07-27_X_invest.md").write_text(
        "# X — Stale Name — Score: 8.0/10\n", encoding="utf-8")
    tmp = tmp_path / "_tmp"
    tmp.mkdir()
    (tmp / "2026-07-27_X.json").write_text(
        json.dumps({"ticker": "X", "company_name": "Fresh Name"}), encoding="utf-8")
    assert cn.build(tmp_path)["X"] == "Fresh Name"


def test_build_survives_a_corrupt_analysis_json(tmp_path):
    tmp = tmp_path / "_tmp"
    tmp.mkdir()
    (tmp / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp / "ok.json").write_text(
        json.dumps({"ticker": "Y", "company_name": "Yankee"}), encoding="utf-8")
    assert cn.build(tmp_path)["Y"] == "Yankee"


def test_archived_reports_still_supply_names(tmp_path):
    arch = tmp_path / "_archive"
    arch.mkdir()
    (arch / "2026-04-20_ADBE_invest.md").write_text(
        "# ADBE — Adobe Inc. — Score: 8.51/10\n", encoding="utf-8")
    assert cn.build(tmp_path)["ADBE"] == "Adobe Inc."


# --- chart gate -------------------------------------------------------------

def _report_with_charts(tmp_path, name, body, chart_kinds):
    (tmp_path / "IMG").mkdir(exist_ok=True)
    stem = name[: -len(".md")].rsplit("_", 1)[0]  # {date}_{ticker}
    for k in chart_kinds:
        (tmp_path / "IMG" / f"{stem}_{k}.png").write_bytes(b"\x89PNG")
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_gate_passes_when_every_chart_is_embedded(tmp_path):
    p = _report_with_charts(
        tmp_path, "2026-08-05_ZTS_review.md",
        "![Price 1Y](IMG/2026-08-05_ZTS_price.png)\n"
        "![Radar](IMG/2026-08-05_ZTS_radar.png)\n", ["price", "radar"])
    assert cg.audit_report(p)["ok"]


def test_gate_catches_a_rendered_but_unembedded_chart(tmp_path):
    # The 2026-08-05 failure: relperf rendered, report never linked it.
    p = _report_with_charts(
        tmp_path, "2026-08-05_ZTS_review.md",
        "![Price 1Y](IMG/2026-08-05_ZTS_price.png)\n", ["price", "relperf"])
    r = cg.audit_report(p)
    assert r["orphans"] == ["relperf"] and not r["ok"]


def test_gate_catches_a_broken_image_link(tmp_path):
    p = _report_with_charts(
        tmp_path, "2026-08-05_PG_fair.md",
        "![Revenue sources](IMG/2026-08-05_PG_segments.png)\n", [])
    assert cg.audit_report(p)["broken_links"] == ["segments"]


def test_fix_lines_match_the_template_captions(tmp_path):
    p = _report_with_charts(tmp_path, "2026-08-05_ZTS_review.md", "", ["relperf", "dcf"])
    lines = cg.fix_lines(p, ["relperf", "dcf"])
    assert "![Relative 2.5y](IMG/2026-08-05_ZTS_relperf.png)" in lines
    assert "![DCF](IMG/2026-08-05_ZTS_dcf.png)" in lines


def test_screens_are_exempt_from_the_gate(tmp_path):
    # Screens get the metrics strip only — no charts are expected.
    p = _report_with_charts(tmp_path, "2026-06-01_AVGO_screen.md", "no charts\n", ["price"])
    assert cg.audit_report(p)["is_screen"] is True


def test_gate_handles_tickers_with_dots(tmp_path):
    p = _report_with_charts(
        tmp_path, "2026-08-05_WKL.AS_review.md", "", ["price", "relperf"])
    assert cg.audit_report(p)["orphans"] == ["price", "relperf"]


def test_fix_inserts_orphans_at_their_template_anchors(tmp_path):
    p = _report_with_charts(
        tmp_path, "2026-08-05_ZTS_review.md",
        "### Score breakdown\n\n| c | w |\n\n### Peer ranking snapshot\n\nprose\n",
        ["radar", "peers"])
    cg.fix_report(p, dry_run=False)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[lines.index("### Score breakdown") + 2].startswith("![Radar]")
    assert lines[lines.index("### Peer ranking snapshot") + 2].startswith("![Peers]")


def test_metrics_strip_charts_land_above_section_one(tmp_path):
    # No `(Fonte: bloco top_strip` line, so they must fall back to BEFORE the §1
    # heading — a price chart printed after the deep dive is useless.
    p = _report_with_charts(
        tmp_path, "2026-08-05_ZTS_review.md",
        "| strip |\n\n## 1. Sumário executivo (5 min)\n\nbody\n", ["price", "relperf"])
    cg.fix_report(p, dry_run=False)
    text = p.read_text(encoding="utf-8")
    assert text.index("_price.png") < text.index("## 1. Sumário")
    assert text.index("_price.png") < text.index("_relperf.png")


def test_fix_removes_dead_links_but_keeps_the_prose_below(tmp_path):
    p = _report_with_charts(
        tmp_path, "2026-08-05_PG_fair.md",
        "![Revenue sources](IMG/2026-08-05_PG_segments.png)\n"
        "⚠️ **Segment data unavailable** — no cache.\n", [])
    r = cg.fix_report(p, dry_run=False)
    text = p.read_text(encoding="utf-8")
    assert "_segments.png" not in text
    assert "Segment data unavailable" in text
    assert len(r["removed"]) == 1


def test_fix_preserves_line_endings(tmp_path):
    # read_text/write_text round-tripping rewrote every terminator, turning a
    # 7-line insert into a 551-line diff.
    p = tmp_path / "2026-08-05_ZTS_review.md"
    (tmp_path / "IMG").mkdir()
    (tmp_path / "IMG" / "2026-08-05_ZTS_radar.png").write_bytes(b"\x89PNG")
    p.write_bytes(b"### Score breakdown\n\nbody\n")
    cg.fix_report(p, dry_run=False)
    assert b"\r\n" not in p.read_bytes()


def test_dry_run_writes_nothing(tmp_path):
    p = _report_with_charts(tmp_path, "2026-08-05_ZTS_review.md",
                            "### Score breakdown\n\nx\n", ["radar"])
    before = p.read_bytes()
    r = cg.fix_report(p, dry_run=True)
    assert r["changed"] and p.read_bytes() == before


def test_fix_is_idempotent(tmp_path):
    p = _report_with_charts(tmp_path, "2026-08-05_ZTS_review.md",
                            "### Score breakdown\n\nx\n", ["radar", "peers"])
    cg.fix_report(p, dry_run=False)
    first = p.read_bytes()
    second = cg.fix_report(p, dry_run=False)
    assert not second["changed"] and p.read_bytes() == first
    assert cg.audit_report(p)["ok"]


def test_fix_never_touches_a_screen(tmp_path):
    p = _report_with_charts(tmp_path, "2026-06-01_AVGO_screen.md", "body\n", ["price"])
    before = p.read_bytes()
    assert cg.fix_report(p, dry_run=False)["changed"] is False
    assert p.read_bytes() == before


def test_every_rendered_chart_kind_has_a_caption():
    # A kind with no caption still gets a fix line, but a Title-Cased guess is a
    # silent drift from the template. Keep the map in step with render_charts.
    import re
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "render_charts.py").read_text(encoding="utf-8")
    kinds = set(re.findall(r'f"\{stem\}_([a-z_]+)\.png"', src))
    missing = kinds - set(cg.CHART_CAPTIONS)
    assert not missing, f"render_charts emits {missing} with no caption in the gate"
