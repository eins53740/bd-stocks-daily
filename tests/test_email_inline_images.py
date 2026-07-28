"""
Unit tests for inline_image_refs() in send_email.py.

The digest embeds report charts as `<img src="IMG/....png">`. Mail clients will not
fetch local paths, so every local reference has to become a `cid:` URI backed by a
multipart/related attachment. The v3.1 audit deferred this check to "tomorrow's
digest" and it was never turned into a test — so a regression here would silently
ship a digest of broken-image icons, which nobody notices until they open the mail.

Pure function: no network, no SMTP. OUT_DIR is monkeypatched to a tmp dir so the
tests never depend on which PNGs happen to exist in the Obsidian vault.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import send_email as se  # noqa: E402

CID_RE = re.compile(r"cid:(img-[0-9a-f]{32}@stocksdaily)")


@pytest.fixture()
def img_dir(tmp_path, monkeypatch):
    """A tmp OUT_DIR containing IMG/a.png and IMG/b.jpg."""
    img = tmp_path / "IMG"
    img.mkdir()
    (img / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (img / "b.jpg").write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr(se, "OUT_DIR", tmp_path)
    return img


# --- the happy path ----------------------------------------------------------

def test_local_png_becomes_a_cid_reference_with_an_attachment(img_dir):
    html, atts = se.inline_image_refs('<img src="IMG/a.png" alt="chart">')
    assert 'src="cid:' in html
    assert "IMG/a.png" not in html
    assert len(atts) == 1
    path, cid, subtype = atts[0]
    assert path.name == "a.png"
    assert subtype == "png"
    # The cid in the html must be the one we are attaching, or the client shows nothing.
    assert CID_RE.search(html).group(1) == cid


def test_alt_and_other_attributes_survive_the_rewrite(img_dir):
    html, _ = se.inline_image_refs('<img class="c" src="IMG/a.png" alt="EBITDA & FCF">')
    assert 'class="c"' in html
    assert 'alt="EBITDA & FCF"' in html


def test_mime_subtype_follows_the_extension(img_dir):
    _, atts = se.inline_image_refs('<img src="IMG/b.jpg">')
    assert atts[0][2] == "jpeg"


def test_single_quoted_src_is_handled(img_dir):
    html, atts = se.inline_image_refs("<img src='IMG/a.png'>")
    assert len(atts) == 1
    assert "cid:" in html


# --- what must be left alone -------------------------------------------------

@pytest.mark.parametrize("src", [
    "https://example.com/x.png",
    "http://example.com/x.png",
    "cid:already@somewhere",
    "data:image/png;base64,iVBOR",
])
def test_non_local_sources_are_untouched(img_dir, src):
    original = f'<img src="{src}">'
    html, atts = se.inline_image_refs(original)
    assert html == original
    assert atts == []


def test_missing_file_is_left_as_is_so_alt_text_degrades_gracefully(img_dir):
    original = '<img src="IMG/nope.png" alt="fallback">'
    html, atts = se.inline_image_refs(original)
    assert html == original
    assert atts == []


def test_scheme_matching_is_case_insensitive(img_dir):
    original = '<img src="HTTPS://example.com/x.png">'
    html, atts = se.inline_image_refs(original)
    assert html == original
    assert atts == []


# --- dedupe & multiplicity ---------------------------------------------------

def test_the_same_image_twice_attaches_once_and_shares_one_cid(img_dir):
    html, atts = se.inline_image_refs(
        '<img src="IMG/a.png"><p>x</p><img src="IMG/a.png">')
    assert len(atts) == 1, "duplicate attachment would double the message size"
    cids = CID_RE.findall(html)
    assert len(cids) == 2 and cids[0] == cids[1]


def test_distinct_images_get_distinct_cids(img_dir):
    html, atts = se.inline_image_refs('<img src="IMG/a.png"><img src="IMG/b.jpg">')
    assert len(atts) == 2
    cids = CID_RE.findall(html)
    assert len(set(cids)) == 2
    assert {c for _, c, _ in atts} == set(cids)


def test_mixed_local_and_remote_in_one_body(img_dir):
    html, atts = se.inline_image_refs(
        '<img src="IMG/a.png"><img src="https://x/y.png"><img src="IMG/b.jpg">')
    assert len(atts) == 2
    assert 'src="https://x/y.png"' in html


# --- degenerate input --------------------------------------------------------

def test_body_without_images_is_returned_unchanged(img_dir):
    body = "<p>no charts today</p>"
    html, atts = se.inline_image_refs(body)
    assert html == body
    assert atts == []


def test_empty_body(img_dir):
    assert se.inline_image_refs("") == ("", [])


def test_every_returned_path_exists_and_is_a_file(img_dir):
    _, atts = se.inline_image_refs('<img src="IMG/a.png"><img src="IMG/b.jpg">')
    assert atts and all(p.is_file() for p, _, _ in atts)
