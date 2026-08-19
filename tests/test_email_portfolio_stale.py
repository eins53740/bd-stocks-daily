"""Roadmap R22 — the stale-export warning must reach the reader, and must switch itself off.

Before this, `_portfolio_export_stale.txt` was written by the ingest bat and read by NOTHING:
the name appeared in one doc and in no `.py` at all. So a 20-day-old cost basis fed
held-detection, `exit_plan`, the buy list and every EUR weight while the digest said nothing.

The half that is easy to get wrong is the OFF switch. A warning that cannot turn itself off is
just noise with a delay, so the absent-marker and empty-marker cases are asserted as hard as the
present one, and both bodies (HTML and text/plain) are checked — the digest is a twin MIME
message and a warning in only one part is a warning half the readers never see.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import send_email  # noqa: E402


@pytest.fixture
def marker(tmp_path, monkeypatch):
    """Point the module at a marker under tmp_path. Never touch the real vault file."""
    p = tmp_path / "_portfolio_export_stale.txt"
    monkeypatch.setattr(send_email, "STALE_MARKER", p)
    return p


def test_absent_marker_renders_nothing(marker):
    assert not marker.exists()
    assert send_email.portfolio_stale_notice_html() == ""
    assert send_email.portfolio_stale_notice_text() == ""


def test_empty_marker_renders_nothing(marker):
    """A zero-byte marker is not a warning. Rendering an empty orange box would train the
    reader to ignore the box."""
    marker.write_text("", encoding="utf-8")
    assert send_email.portfolio_stale_notice_html() == ""
    assert send_email.portfolio_stale_notice_text() == ""

    marker.write_text("   \n\n  ", encoding="utf-8")
    assert send_email.portfolio_stale_notice_html() == ""
    assert send_email.portfolio_stale_notice_text() == ""


def test_present_marker_carries_the_bat_message_into_both_bodies(marker):
    """The message is the bat's own, verbatim — one source of truth for the age and the recipe."""
    msg = ("Yahoo portfolio export is 20 days old (C:\\Users\\bsdias\\Downloads\\YF\\portfolio.csv). "
           "Re-export: Yahoo Finance -> My Portfolio -> BD -> Download -> Save this portfolio as a CSV.")
    marker.write_text(msg, encoding="utf-8")

    h = send_email.portfolio_stale_notice_html()
    t = send_email.portfolio_stale_notice_text()

    assert "20 days old" in h and "20 days old" in t
    assert "stale" in h.lower() and "STALE" in t
    # the consequence, not just the fact — the reason this warning is worth a box
    assert "cost basis" in h and "cost basis" in t
    assert h.startswith("<p") and h.rstrip().endswith("</p>")


def test_marker_text_is_html_escaped(marker):
    """The marker is a file on disk carrying a path. A path with an ampersand must not break
    the digest's markup."""
    marker.write_text("export in C:\\tmp\\a&b<dir> is 99 days old", encoding="utf-8")
    h = send_email.portfolio_stale_notice_html()
    assert "a&amp;b&lt;dir&gt;" in h
    assert "<dir>" not in h


def test_unreadable_marker_never_costs_a_digest(marker, monkeypatch):
    """Same contract as run_cost_block: a freshness notice must never be able to block the mail."""
    marker.write_text("stale!", encoding="utf-8")

    def boom(*_a, **_k):
        raise OSError("disk gone")

    monkeypatch.setattr(Path, "read_text", boom)
    assert send_email.portfolio_stale_notice_html() == ""
    assert send_email.portfolio_stale_notice_text() == ""


def test_notice_sits_above_the_numbers_it_invalidates():
    """Placement is the point. A freshness warning under the cards is a footnote; the whole
    reason R22 exists is that the warning was somewhere nobody looked."""
    src = (SCRIPTS / "send_email.py").read_text(encoding="utf-8")
    body = src[src.index("html_body = f\"\"\""):]
    assert "{stale_html}" in body, "the notice is not wired into the HTML body at all"
    assert body.index("{stale_html}") < body.index("{cards_html}"), \
        "the stale-export warning must render ABOVE the cards it invalidates"
