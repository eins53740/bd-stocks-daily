"""Filing-text extraction — the half of "read the official documents" that metadata
alone does not deliver.

Bounded by construction: IBM's latest 10-Q measured **3.67 MB** of inline-XBRL HTML on
2026-08-15, so "fetch the filing" without a cap is neither affordable nor useful. These
tests pin the two properties that make the output trustworthy:

  * the extractor returns *prose*, not tag soup or script bodies;
  * when the requested section cannot be found it says so, rather than returning an
    arbitrary slice that would be presented to the reader as MD&A.

Network-free. `fetch_filing_text` is exercised through a stubbed transport.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import edgar  # noqa: E402


class TestStripHtml:
    def test_tags_are_removed_and_words_survive(self):
        got = edgar.strip_html("<p>Revenue <b>grew</b> 5%</p>")
        assert "Revenue" in got and "grew" in got and "<" not in got

    def test_script_and_style_bodies_are_dropped_whole(self):
        """Their contents are not prose. Leaving them in feeds an LLM javascript."""
        html = "<style>.x{color:red}</style><script>var a=1;</script><p>Real text</p>"
        got = edgar.strip_html(html)
        assert "Real text" in got
        assert "color:red" not in got and "var a" not in got

    def test_entities_are_decoded(self):
        assert "AT&T" in edgar.strip_html("<p>AT&amp;T</p>")
        assert "&nbsp;" not in edgar.strip_html("<p>a&nbsp;b</p>")

    def test_block_tags_become_line_breaks_so_rows_do_not_merge(self):
        got = edgar.strip_html("<tr><td>Alpha</td></tr><tr><td>Beta</td></tr>")
        assert "AlphaBeta" not in got.replace(" ", "")

    def test_whitespace_is_collapsed(self):
        got = edgar.strip_html("<p>a</p>\n\n\n\n     <p>b</p>")
        assert "\n\n\n" not in got

    def test_inline_xbrl_wrapping_does_not_split_words(self):
        """Modern filings wrap figures in <ix:*> tags. The words either side must not
        be glued to the number when the tags are removed."""
        html = "<p>Revenue of <ix:nonFraction>62,753</ix:nonFraction> million</p>"
        got = edgar.strip_html(html)
        assert "62,753" in got and "million" in got

    @pytest.mark.parametrize("bad", ["", None])
    def test_empty_input_is_empty_output(self, bad):
        assert edgar.strip_html(bad) == ""


class TestFindSection:
    BODY = ("TABLE OF CONTENTS\n"
            "Item 2. Management's Discussion and Analysis .... 14\n"
            "Item 3. Quantitative Disclosures .... 30\n"
            + ("filler " * 200) +
            "\nItem 2. Management's Discussion and Analysis\n"
            + ("The company reported growth in software. " * 60))

    def test_prefers_the_body_over_the_table_of_contents(self):
        """Every item heading appears twice: once in the TOC, once as the real
        section. Taking the first hit returns the contents page -- a page of dot
        leaders and page numbers -- and would look like a successful extraction."""
        got = edgar.find_section(self.BODY, ["Item 2. Management's Discussion"])
        assert got is not None
        assert "reported growth in software" in got
        assert "Item 3. Quantitative" not in got[:200]

    def test_returns_none_when_the_heading_is_absent(self):
        assert edgar.find_section(self.BODY, ["Item 9. Controls"]) is None

    def test_a_bare_toc_line_is_not_accepted_as_a_section(self):
        """A match that yields only a few hundred characters is a contents entry, not
        a section. Returning it would present a page number as MD&A."""
        tiny = "Item 7. Management's Discussion .... 22\n"
        assert edgar.find_section(tiny, ["Item 7. Management's Discussion"]) is None

    def test_headings_are_tried_in_order(self):
        text = "x" * 50 + "Item 1A. Risk Factors\n" + ("risk text. " * 80)
        got = edgar.find_section(text, ["Item 7. Management's Discussion",
                                        "Item 1A. Risk Factors"])
        assert got is not None and "risk text" in got

    def test_output_respects_max_chars(self):
        got = edgar.find_section(self.BODY, ["Item 2. Management's Discussion"],
                                 max_chars=900)
        assert got is not None and len(got) <= 900

    @pytest.mark.parametrize("bad", ["", None])
    def test_empty_text_is_none(self, bad):
        assert edgar.find_section(bad, ["Item 7"]) is None


class TestRealWorldHeadingFormats:
    """Three ways the IBM 10-Q defeated the first implementation, each measured.

    Every one of these produced output that *looked* fine -- a populated section, no
    error -- while actually handing the reader a contents page or a block of XBRL
    taxonomy URIs. They are regression tests for silent wrongness, not for crashes.
    """

    def test_a_typographic_apostrophe_still_matches_an_ascii_heading(self):
        """Filers write U+2019, not '. The first version matched neither the contents
        page nor the body and fell through to the head of the document."""
        body = ("Item 2. Management’s Discussion and Analysis\n"
                + "Revenue rose on hybrid cloud demand. " * 60)
        got = edgar.find_section(body, ["Item 2. Management's Discussion"])
        assert got is not None and "hybrid cloud" in got

    def test_irregular_whitespace_in_the_body_heading_still_matches(self):
        """IBM's body heading is 'Item 2.  MANAGEMENT'S...' (two spaces, and a line
        break); the contents page uses one. An exact-string match found only the
        contents page -- the bug that survived the apostrophe fix."""
        body = ("Item 2. Management's Discussion and Analysis .... 45\n"
                + "Item 4. Controls .... 74\n" + ("x" * 3000) +
                "\nItem 2. \n MANAGEMENT'S DISCUSSION AND ANALYSIS \n"
                + "The Management Discussion provides an overview of the business. " * 40)
        got = edgar.find_section(body, ["Item 2. Management's Discussion"])
        assert got is not None
        assert "overview of the business" in got, "must land on the body, not the TOC"
        assert ".... 45" not in got[:200]

    def test_a_contents_page_is_rejected_even_when_it_is_the_only_match(self):
        """Short lines ending in page numbers are a contents block. Returning it as
        MD&A is exactly the failure this guards."""
        toc = ("Item 7. Management's Discussion and Analysis of Financial Condition\n"
               "45\nItem 7A. Quantitative Disclosures\n70\nItem 8. Statements\n71\n"
               "Item 9. Changes\n120\nItem 9A. Controls\n121\nItem 9B. Other\n122\n")
        assert edgar.find_section(toc, ["Item 7. Management's Discussion"]) is None


class TestFirstProse:
    XBRL_HEAD = ("ibm-20260630 0000051143 --12-31 2026 Q2 false "
                 + "http://fasb.org/us-gaap/2026#CostOfRevenue " * 300)
    PROSE = "The company delivered revenue growth across its software segment. " * 60

    def test_the_inline_xbrl_context_block_is_skipped(self):
        """A modern filing opens with hidden taxonomy URIs. Measured: the naive
        'first N characters' fallback returned several pages of
        'http://fasb.org/us-gaap/2026#CostOfRevenue' as the filing narrative."""
        got = edgar.first_prose(self.XBRL_HEAD + "\n" + self.PROSE)
        assert "fasb.org" not in got[:600]
        assert "revenue growth" in got

    def test_a_clean_document_is_returned_from_the_top(self):
        got = edgar.first_prose(self.PROSE)
        assert got.startswith("The company delivered")

    def test_output_is_capped(self):
        assert len(edgar.first_prose(self.PROSE * 50, max_chars=800)) <= 800

    @pytest.mark.parametrize("bad", ["", None])
    def test_empty_input(self, bad):
        assert edgar.first_prose(bad) == ""


class TestPunctNormalisationIsLengthPreserving:
    def test_offsets_survive_normalisation(self):
        """find_section slices the normalised string, so any mapping that changed
        length would silently shift every extracted section."""
        raw = "a’b“c”d–e—f g"
        assert len(edgar._normalise_punct(raw)) == len(raw)
        assert edgar._normalise_punct(raw) == "a'b\"c\"d-e-f g"


class TestFetchFilingText:
    def _stub(self, monkeypatch, payload: bytes):
        class _Resp:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        monkeypatch.setattr(edgar.urllib.request, "urlopen", lambda *a, **k: _Resp())

    def test_extracts_the_mdna_section_when_present(self, monkeypatch):
        html = ("<html><body><p>Item 2. Management's Discussion .... 14</p>"
                + "<p>noise</p>" * 100
                + "<p>Item 2. Management's Discussion and Analysis</p>"
                + "<p>Software revenue rose on hybrid cloud demand.</p>" * 40
                + "</body></html>")
        self._stub(monkeypatch, html.encode())
        got = edgar.fetch_filing_text("http://x/f.htm")
        assert got is not None and "hybrid cloud demand" in got

    def test_falls_back_to_the_head_of_the_document(self, monkeypatch):
        """No recognisable section is not a failure -- the opening of a filing is
        still the filing. It is capped like everything else."""
        self._stub(monkeypatch, (b"<p>" + b"Opening narrative. " * 500 + b"</p>"))
        got = edgar.fetch_filing_text("http://x/f.htm", max_chars=1000)
        assert got is not None and len(got) <= 1000
        assert "Opening narrative" in got

    def test_output_is_always_capped(self, monkeypatch):
        self._stub(monkeypatch, b"<p>" + b"word " * 200_000 + b"</p>")
        got = edgar.fetch_filing_text("http://x/f.htm", max_chars=5000)
        assert len(got) <= 5000, "a 3.7 MB filing must never reach an LLM whole"

    def test_a_dead_request_returns_none_and_does_not_raise(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("connection reset")
        monkeypatch.setattr(edgar.urllib.request, "urlopen", boom)
        assert edgar.fetch_filing_text("http://x/f.htm") is None

    def test_an_empty_document_returns_none_not_an_empty_string(self, monkeypatch):
        self._stub(monkeypatch, b"<html><head></head><body></body></html>")
        assert edgar.fetch_filing_text("http://x/f.htm") is None
