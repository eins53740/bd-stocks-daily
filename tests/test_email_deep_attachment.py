"""
Unit tests for deep_report_attachments() and its two notice builders.

Delivery decision "a + b" (v4.3): the digest keeps everything it inlined AND carries
the deep report's rendered HTML as a real attachment, because a `file://` link to the
laptop is dead on the phone where this digest is actually read.

Three properties are worth a test and are exactly the ones that would fail silently:
  1. only the DEEP row is attached — three 1.5 MB screens would get the mail refused;
  2. a missing HTML degrades to nothing, never to a raised exception inside main();
  3. the reader is TOLD, in both MIME parts — an unannounced attachment goes unopened.

Pure functions: no SMTP, no network. OUT_DIR is passed in, so nothing here depends on
which reports happen to exist in the vault today.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import send_email as se  # noqa: E402


def row(ticker="IBM", mode="deep", verdict="fair", date="2026-08-15"):
    return {"ticker": ticker, "mode": mode, "verdict": verdict, "date": date,
            "score": 5.85}


@pytest.fixture()
def out(tmp_path):
    """A tmp OUT_DIR holding one deep and one screen HTML."""
    (tmp_path / "2026-08-15_IBM_fair.html").write_bytes(b"<html>deep</html>")
    (tmp_path / "2026-08-15_MP_screen.html").write_bytes(b"<html>screen</html>")
    return tmp_path


# --- what gets attached ------------------------------------------------------

def test_the_deep_row_is_attached(out):
    picked = se.deep_report_attachments([row()], out_dir=out)
    assert [name for _p, name in picked] == ["2026-08-15_IBM_fair.html"]


def test_screens_are_never_attached(out):
    picked = se.deep_report_attachments(
        [row("MP", mode="screen", verdict="reject")], out_dir=out)
    assert picked == []


def test_a_screen_alongside_a_deep_leaves_only_the_deep(out):
    picked = se.deep_report_attachments(
        [row("MP", mode="screen"), row()], out_dir=out)
    assert [name for _p, name in picked] == ["2026-08-15_IBM_fair.html"]


def test_mode_matching_is_case_and_whitespace_insensitive(out):
    picked = se.deep_report_attachments([row() | {"mode": " Deep "}], out_dir=out)
    assert len(picked) == 1


def test_the_deep_filename_uses_the_verdict_not_the_word_screen(out):
    """report_filename()'s rule: screens use 'screen', deep uses the verdict. If that
    ever inverts, the attachment silently stops being found."""
    path, _name = se.deep_report_attachments([row()], out_dir=out)[0]
    assert path.name.endswith("_fair.html")


# --- degradation, which must never raise -------------------------------------

def test_a_missing_html_yields_nothing_and_does_not_raise(out):
    assert se.deep_report_attachments(
        [row("NOPE", verdict="invest")], out_dir=out) == []


def test_no_rows_at_all(out):
    assert se.deep_report_attachments([], out_dir=out) == []
    assert se.deep_report_attachments(None, out_dir=out) == []


def test_a_row_with_no_mode_key_is_not_treated_as_deep(out):
    r = row()
    del r["mode"]
    assert se.deep_report_attachments([r], out_dir=out) == []


def test_a_file_over_budget_is_skipped_rather_than_sent(out):
    assert se.deep_report_attachments([row()], out_dir=out, budget=1) == []


def test_the_budget_is_cumulative_across_rows(out):
    """Two deep rows, a budget that fits exactly one: the second is dropped, not the
    first, and the mail still goes out."""
    (out / "2026-08-15_MSFT_invest.html").write_bytes(b"x" * 100)
    rows = [row(), row("MSFT", verdict="invest")]
    picked = se.deep_report_attachments(rows, out_dir=out, budget=50)
    assert [name for _p, name in picked] == ["2026-08-15_IBM_fair.html"]


# --- the reader has to be told -----------------------------------------------

def test_notice_names_the_file_in_html():
    out_html = se.attachment_notice_html(["2026-08-15_IBM_fair.html"])
    assert "2026-08-15_IBM_fair.html" in out_html
    assert "Attached" in out_html


def test_notice_names_the_file_in_text():
    assert "2026-08-15_IBM_fair.html" in se.attachment_notice_text(
        ["2026-08-15_IBM_fair.html"])


def test_no_attachment_means_no_notice_in_either_part():
    """A promise of an attachment that is not there is worse than saying nothing."""
    assert se.attachment_notice_html([]) == ""
    assert se.attachment_notice_text([]) == ""


def test_notice_escapes_html_in_a_filename():
    assert "<script>" not in se.attachment_notice_html(["<script>x</script>.html"])
