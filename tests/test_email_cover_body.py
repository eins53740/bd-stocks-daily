"""The digest body carries the cover, not the whole markdown report (v4.3 E1/E2).

MEASURED 2026-08-17 on the canonical 1-deep + 2-screen day: body 136,413 B, of which the
three inlined markdown reports were 100,989 B -- 74%. Gmail clips above ~102,400 B, so the
biggest thing in the mail was also the part being hidden, and it was the poorest rendering
of the report available: inlining markdown drops the cover, the charts, the Sankey, the SWOT
and the stars, all of which live in the .html that already travels as an attachment.

No network, no SMTP: every fixture is a file in tmp_path.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import send_email as se  # noqa: E402

COVER = (
    '<section class="cover" id="cover">'
    '<div class="cv-verb">ACCUMULATE</div>'
    '<div class="cv-tk">Heineken N.V. <span class="sub">· HEIA.AS</span></div>'
    '<div class="cv-facts"><div class="cv-fact"><div class="k">Price</div>'
    '<div class="v">&euro;73.52</div></div></div>'
    '<div class="cv-line cv-bear"><b>Risk</b> Flat topline.</div>'
    '</section>'
)

ROW = {"date": "2026-08-16", "ticker": "HEIA.AS", "mode": "deep",
       "verdict": "review", "score": "6.03", "notes": ""}


@pytest.fixture
def reports(tmp_path):
    """A rendered report with a cover, its markdown twin, and the Sankey PNG."""
    fn = se.report_filename(ROW)
    (tmp_path / f"{fn}.html").write_text(
        f"<html><body><h1>x</h1>{COVER}<section class='card' id='tldr'>t</section>"
        "</body></html>", encoding="utf-8")
    (tmp_path / f"{fn}.md").write_text("# report\n\n" + "filler paragraph. " * 4000,
                                       encoding="utf-8")
    (tmp_path / "IMG").mkdir()
    (tmp_path / "IMG" / "2026-08-16_HEIA.AS_sankey.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp_path


# --- the class-driven inliner -------------------------------------------------

def test_the_cascade_order_is_preserved():
    """`class="cv-line cv-bear"` must apply the bear colour AFTER the base rule, or the
    red border-left silently loses to the grey one it is meant to override."""
    out = se.inline_cover_styles('<div class="cv-line cv-bear">x</div>')
    style = re.search(r'style="([^"]*)"', out).group(1)
    assert style.index("border-left:3px solid #ccc") < style.index("border-left-color:#d62728")


def test_an_unknown_class_is_left_alone():
    assert se.inline_cover_styles('<div class="mystery">x</div>') == '<div class="mystery">x</div>'


def test_an_existing_style_attribute_is_not_doubled():
    """Two style= attributes on one element is invalid and clients resolve it differently."""
    src = '<div class="cv-verb" style="color:red">x</div>'
    assert se.inline_cover_styles(src) == src


def test_no_grid_reaches_the_mail():
    """Outlook renders with the Word engine, which ignores CSS grid entirely -- the reason
    the report's own stylesheet cannot simply be copied into the message."""
    assert not any("grid" in css for css in se.COVER_STYLES.values())


# --- extraction ---------------------------------------------------------------

def test_the_cover_is_extracted_and_styled(reports):
    out = se.report_cover_html(ROW, out_dir=reports)
    assert "ACCUMULATE" in out and 'style="' in out
    assert "cv-verb" in out            # class kept: it is the join key, not decoration
    assert "id='tldr'" not in out and "tldr" not in out


def test_a_missing_report_yields_nothing_not_an_apology(tmp_path):
    assert se.report_cover_html(ROW, out_dir=tmp_path) == ""


def test_a_precover_report_falls_back_to_the_markdown(tmp_path):
    """Reports rendered before wave 2.4 (2026-08-15) have no cover section. They must still
    reach the reader -- which is the only reason build_full_report_html still exists."""
    fn = se.report_filename(ROW)
    (tmp_path / f"{fn}.html").write_text("<html><body>no cover here</body></html>",
                                         encoding="utf-8")
    (tmp_path / f"{fn}.md").write_text("# old report\n\nbody text\n", encoding="utf-8")
    block = se.build_cover_block_html(ROW, out_dir=tmp_path)
    assert "old report" in block


def test_the_cover_block_is_an_order_of_magnitude_smaller(reports):
    """The whole point. The markdown fixture is deliberately ~70 KB."""
    cover_block = se.build_cover_block_html(ROW, out_dir=reports)
    full_md = se.build_full_report_html(ROW, out_dir=reports)
    assert len(cover_block) * 10 < len(full_md) or len(cover_block) < 6_000


# --- E2: the Sankey travels as an image, not as source code -------------------

def test_the_sankey_png_is_referenced_so_cid_inlining_can_find_it(reports):
    img = se.sankey_img_html(ROW, out_dir=reports)
    assert "<img" in img and "sankey.png" in img
    rewritten, imgs = se.inline_image_refs(img)
    assert [p.name for p, _cid, _sub in imgs] == ["2026-08-16_HEIA.AS_sankey.png"]
    assert "cid:" in rewritten


def test_no_sankey_png_means_no_broken_image(tmp_path):
    assert se.sankey_img_html(ROW, out_dir=tmp_path) == ""


def test_the_body_no_longer_carries_the_diagram_source(reports):
    """A ```mermaid sankey-beta fence renders as literal <pre><code> through
    python-markdown, so what used to reach the inbox was the diagram's SOURCE."""
    block = se.build_cover_block_html(ROW, out_dir=reports)
    assert "sankey-beta" not in block


# --- the plain-text twin -----------------------------------------------------

def test_the_text_cover_unescapes_entities_after_stripping_tags(reports):
    """unescape must come AFTER tag-stripping: the other order leaves `&euro;73.52` in the
    text part. Same entity mistake that once produced five phantom missing sections in a
    heading comparison."""
    txt = se.cover_text(ROW, out_dir=reports)
    assert "€73.52" in txt and "&euro;" not in txt
    assert "<" not in txt and ">" not in txt


def test_the_text_cover_keeps_the_verdict_and_the_risk(reports):
    txt = se.cover_text(ROW, out_dir=reports)
    assert "ACCUMULATE" in txt and "Flat topline" in txt
