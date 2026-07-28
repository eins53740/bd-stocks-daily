"""
Unit tests for the Obsidian-syntax email renderer in send_email.py.

Covers the two constructs python-markdown does not know and that therefore used
to reach the inbox as literal source text — wikilinks and callouts — plus the
run attribution line. Pure functions only: no network, no SMTP.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import send_email as se  # noqa: E402


# --- wikilinks ---------------------------------------------------------------

def test_wikilink_with_label_uses_label_as_anchor_text():
    out = se.wikilinks_to_html("see [[_macro/2026-07-27|Full macro snapshot]] now")
    assert "[[" not in out
    assert ">Full macro snapshot</a>" in out
    assert "file=Personal/Finance/StocksDaily/_macro/2026-07-27.md" in out


def test_wikilink_without_label_falls_back_to_last_path_segment():
    out = se.wikilinks_to_html("[[_industry/semiconductors]]")
    assert ">semiconductors</a>" in out
    assert "file=Personal/Finance/StocksDaily/_industry/semiconductors.md" in out


def test_wikilink_to_sibling_report():
    out = se.wikilinks_to_html("[[2026-07-09_TSM_invest|2026-07-09 (8.34)]]")
    assert ">2026-07-09 (8.34)</a>" in out
    assert "file=Personal/Finance/StocksDaily/2026-07-09_TSM_invest.md" in out


def test_multiple_wikilinks_on_one_line_all_convert():
    out = se.wikilinks_to_html("[[a|A]] · [[b|B]] · [[c]]")
    assert out.count("<a href=") == 3
    assert "[[" not in out


def test_wikilink_heading_anchor_is_encoded_not_dropped():
    out = se.wikilinks_to_html("[[_industry/semiconductors#Moat|moat]]")
    assert "semiconductors.md%23Moat" in out


def test_label_is_html_escaped():
    out = se.wikilinks_to_html("[[x|a <b> & c]]")
    assert "&lt;b&gt;" in out and "&amp;" in out


def test_empty_target_left_untouched():
    assert se.wikilinks_to_html("[[]]") == "[[]]"


def test_text_without_wikilinks_is_unchanged():
    assert se.wikilinks_to_html("plain text, no links") == "plain text, no links"


# --- callouts ---------------------------------------------------------------

def test_single_line_callout_becomes_styled_div():
    out = se.render_markdown_html("> [!warning] Auto-generated. Not advice.")
    assert "[!warning]" not in out
    assert "#d97706" in out            # amber accent
    assert "Auto-generated" in out
    assert out.count("<div") >= 1


def test_multiline_callout_keeps_body_lines():
    md = "> [!tldr] TL;DR\n> line one\n> line two"
    out = se.render_markdown_html(md)
    assert "[!tldr]" not in out
    assert "line one" in out and "line two" in out
    assert "#0891b2" in out            # cyan accent for tldr


def test_callout_type_drives_colour():
    danger = se.render_markdown_html("> [!danger] boom")
    success = se.render_markdown_html("> [!success] yay")
    assert "#dc2626" in danger
    assert "#059669" in success


def test_unknown_callout_type_degrades_to_neutral_not_literal():
    out = se.render_markdown_html("> [!mysterytype] something")
    assert "[!mysterytype]" not in out
    assert "#64748b" in out            # neutral accent
    assert "something" in out


def test_callout_body_markdown_is_rendered():
    out = se.render_markdown_html("> [!info] head\n> **bold** body")
    assert "<strong>bold</strong>" in out


def test_wikilink_inside_callout_is_linked():
    out = se.render_markdown_html("> [!info] prior [[2026-07-09_TSM_invest|Jul 9]]")
    assert "[[" not in out
    assert ">Jul 9</a>" in out


def test_callout_div_is_not_nested_in_a_paragraph():
    out = se.render_markdown_html("> [!info] head")
    assert "<p><div" not in out


def test_callout_and_following_paragraph_both_render():
    out = se.render_markdown_html("> [!info] head\n\nA normal paragraph.")
    assert "head" in out
    assert "<p>A normal paragraph.</p>" in out


def test_plain_blockquote_stays_a_blockquote():
    out = se.render_markdown_html("> just a quote")
    assert "<blockquote>" in out


def test_frontmatter_is_stripped_before_rendering():
    out = se.render_markdown_html("---\nticker: TSM\n---\n\n# Title")
    assert "ticker: TSM" not in out
    assert "<h1>Title</h1>" in out


# --- attribution ------------------------------------------------------------

def test_attribution_names_model_owner_and_host():
    line = se.attribution_text()
    assert "Claude Opus 5 (1M context)" in line
    assert "bsdias©2026" in line
    assert re.search(r"host: \S+", line)


def test_run_host_is_never_empty():
    assert se.run_host()


def test_attribution_appears_in_html_and_text_bodies():
    rows = [{
        "ticker": "TSM", "date": "2026-07-27", "round": "3", "mode": "deep",
        "verdict": "invest", "score": "8.14", "gates_passed": "7",
        "price_at_eval": "395.09", "currency": "USD", "size": "big", "notes": "n",
    }]
    _subject, html_body, text_body = se.build_email(rows, "2026-07-27")
    assert "Claude Opus 5 (1M context)" in html_body
    assert "Claude Opus 5 (1M context)" in text_body
    assert "bsdias©2026" in html_body and "bsdias©2026" in text_body
