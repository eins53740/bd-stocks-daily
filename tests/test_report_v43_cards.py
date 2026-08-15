"""
Unit tests for the three v4.3 report cards that close the markdown-vs-HTML gap:
thesis duel, SWOT and the money-engine Sankey.

WHY these three and not "some new cards". Before v4.3 the HTML report — the artifact
that is actually delivered — had no builder for any of them, while the `.md` carried
all three. Switching delivery to HTML-only, which the plan wants, would therefore have
*silently dropped* content the reader relies on. These tests are the guarantee that it
no longer does, and that a pre-v4.2 report (no duel at all) still renders.

Fixtures are shaped from real reports on disk (MPWR, CSCO, TSM, FAE.MC), including the
awkward bits: the threats cell that opens with the word "threat", the header row whose
first cell is empty, and the mermaid block that opens with a YAML config preamble.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import render_report as rr  # noqa: E402


DUEL_MD = """### ⚔️ Bull vs Bear

| | 🐂 **BULL** | 🐻 **BEAR** |
|---|---|---|
| **Claim** | AI rack power is a structural share gain. | The AI thesis is already fully priced. |
| **Se acontecer (3–5 anos)** | Revenue ~doubles to ~$6bn. | Growth decelerates to ~10%. |
| **Depende de / Gatilho** | **NEEDS** enterprise-data growth. | **TRIGGER** a hyperscaler design loss. |

> [!success] 💚 **Thesis**: **A wide-moat compounder.**

> [!abstract] ⚖️ **MAIS PROVÁVEL: 🐻 BEAR**
> Current P/E 83.3× is the 100th percentile of a 15-year band whose median is 32.1×.
> *Leitura narrativa. **Não entra no composite** — boilerplate that should not reach the card.*

### 📊 Metrics strip
"""

# The threats cell deliberately opens with "**Valuation is the primary threat**" — the
# exact string that broke the first keyword-only parser on the real MPWR report.
SWOT_MD = """### 2.18a SWOT  *(v4 Phase C · overlay — qualitative, no score into the composite)*

| ⚠️ **Threats / Risks** *(leads · deepest)* | ✅ **Strengths** |
|---|---|
| **Valuation is the primary threat**: 83.34× P/E at the 100th percentile of a 15-year band, and every intrinsic model sits below spot. | ROIC **27.66%** vs a 13.07% cost of equity; gross margin 55.20% held through two downcycles. |
| 🔸 **Weaknesses** | 🚀 **Opportunities** |
| Net payout yield 0.44% and share count **+3.40% over 5y** — shareholders diluted while a token dividend is paid. | **AI rack power content** grows super-linearly with compute density. |

### 2.19 Veredicto final
"""


# --- section + table primitives ---------------------------------------------

class TestSectionExtraction:
    def test_a_decorated_heading_is_matched_on_its_stable_words(self):
        """Headings carry emoji, scores and italic parentheticals that the prompts vary
        freely. Anchoring on the words that never move is what survives a prompt edit."""
        chunk = rr.extract_section(SWOT_MD, r"SWOT")
        assert chunk and "Threats / Risks" in chunk

    def test_a_section_stops_at_the_next_heading_of_the_same_level(self):
        chunk = rr.extract_section(DUEL_MD, r"Bull\s*vs\s*Bear")
        assert "MAIS PROVÁVEL" in chunk
        assert "Metrics strip" not in chunk

    def test_a_deeper_subheading_does_not_end_the_section(self):
        md = "## Top\n\nbody one\n\n### Sub\n\nbody two\n\n## Next\n\nother\n"
        chunk = rr.extract_section(md, r"Top")
        assert "body two" in chunk and "other" not in chunk

    def test_a_missing_heading_returns_none(self):
        assert rr.extract_section(DUEL_MD, r"Nonexistent") is None

    def test_the_last_section_runs_to_the_end_of_the_document(self):
        assert "trailing" in rr.extract_section("### Only\n\ntrailing text\n", r"Only")


class TestTableParsing:
    def test_the_separator_row_is_dropped(self):
        rows = rr.parse_md_table("| a | b |\n|---|---|\n| 1 | 2 |\n")
        assert rows == [["a", "b"], ["1", "2"]]

    def test_an_empty_leading_header_cell_is_preserved(self):
        """The duel's header row is `| | BULL | BEAR |` — dropping the empty cell would
        shift every column left and label the bear case as bull."""
        rows = rr.parse_md_table("| | BULL | BEAR |\n|---|---|---|\n| Claim | up | down |\n")
        assert rows[0] == ["", "BULL", "BEAR"]

    def test_parsing_stops_at_the_end_of_the_first_table(self):
        rows = rr.parse_md_table("| a |\n|---|\n| 1 |\n\nprose\n\n| x |\n|---|\n| 9 |\n")
        assert rows == [["a"], ["1"]]

    def test_no_table_returns_empty(self):
        assert rr.parse_md_table("just prose") == []
        assert rr.parse_md_table("") == []


class TestInlineMarkdown:
    """The reports use single-asterisk italics freely — "*and*", "*negative*",
    "*(inferred)*" all appear in real prose — and before v4.3 the asterisks leaked
    into the HTML verbatim."""

    def test_italics_render(self):
        assert rr.md_inline("earnings quality passes with *negative* accruals") == \
            "earnings quality passes with <i>negative</i> accruals"

    def test_bold_still_wins_over_italic(self):
        assert rr.md_inline("**ROIC 27.66%**") == "<b>ROIC 27.66%</b>"

    def test_bold_inside_a_sentence_is_not_re_matched_as_italic(self):
        assert rr.md_inline("a **bold** and *italic* mix") == \
            "a <b>bold</b> and <i>italic</i> mix"

    def test_a_lone_asterisk_does_not_swallow_the_line(self):
        """A multiplication sign or a stray bullet must not turn the rest of the
        paragraph into italics."""
        assert rr.md_inline("2 * 3 = 6 and nothing else changes") == \
            "2 * 3 = 6 and nothing else changes"

    def test_a_footnote_marker_is_left_alone(self):
        assert rr.md_inline("net debt*") == "net debt*"

    def test_escaping_still_happens_first(self):
        assert "&lt;script&gt;" in rr.md_inline("<script>alert(1)</script>")


class TestCallout:
    def test_a_callout_title_and_body_are_captured(self):
        title, rest = rr.extract_callout(DUEL_MD, "abstract")
        assert "MAIS PROVÁVEL" in title
        assert rest and "100th percentile" in rest[0]

    def test_a_missing_callout_returns_none(self):
        assert rr.extract_callout("no callouts here", "abstract") is None


# --- thesis duel ------------------------------------------------------------

class TestThesisDuel:
    def test_the_table_and_the_lean_both_render(self):
        html = rr.build_thesis_duel(DUEL_MD)
        assert 'id="duel"' in html
        assert "Revenue ~doubles" in html and "hyperscaler design loss" in html
        assert "MAIS PROVÁVEL" in html and "BEAR" in html

    def test_the_lean_direction_reaches_the_css_class(self):
        """The colour is the whole point of the card at a glance — a bear lean rendered
        green would misread as agreement."""
        assert 'class="lean bear"' in rr.build_thesis_duel(DUEL_MD)
        assert 'class="lean bull"' in rr.build_thesis_duel(
            DUEL_MD.replace("🐻 BEAR**", "🐂 BULL**"))
        assert 'class="lean even"' in rr.build_thesis_duel(
            DUEL_MD.replace("🐻 BEAR**", "⚖️ EQUILIBRADO**"))

    def test_the_boilerplate_disclaimer_does_not_reach_the_card(self):
        """The italic explainer is for a reader of the raw markdown; the card has its
        own caption, so repeating it is noise."""
        html = rr.build_thesis_duel(DUEL_MD)
        assert "boilerplate that should not reach the card" not in html

    def test_bull_and_bear_columns_keep_their_sides(self):
        html = rr.build_thesis_duel(DUEL_MD)
        bull = html.index("Revenue ~doubles")
        bear = html.index("Growth decelerates")
        assert html.rindex('duel-0"', 0, bull) < bull
        assert html.rindex('duel-1"', 0, bear) < bear

    def test_a_pre_v42_report_renders_nothing_rather_than_an_empty_card(self):
        """TSM 2026-07-27 predates the duel. Re-rendering the back catalogue must not
        produce a card with a heading and no content."""
        assert rr.build_thesis_duel("### 2.1 Business model\n\nProse only.\n") == ""

    def test_a_lean_without_a_table_still_renders(self):
        only_lean = "> [!abstract] ⚖️ **MAIS PROVÁVEL: 🐂 BULL**\n> Because of the numbers.\n"
        html = rr.build_thesis_duel(only_lean)
        assert "MAIS PROVÁVEL" in html and "Because of the numbers" in html


# --- SWOT -------------------------------------------------------------------

class TestSwot:
    def test_all_four_quadrants_are_found(self):
        quads = rr.parse_swot(SWOT_MD)
        assert sorted(quads) == ["opportunity", "strength", "threat", "weakness"]

    def test_a_threats_cell_that_says_threat_is_not_mistaken_for_a_label(self):
        """The regression that motivated the length bound: MPWR's threats body opens
        '**Valuation is the primary threat**', so a keyword-only test read 900
        characters of analysis as a header and dropped the quadrant entirely."""
        quads = rr.parse_swot(SWOT_MD)
        assert "83.34" in quads["threat"]

    def test_quadrants_are_matched_by_label_not_by_position(self):
        """A model that emits Strengths first must not have them rendered as Threats."""
        swapped = SWOT_MD.replace(
            "| ⚠️ **Threats / Risks** *(leads · deepest)* | ✅ **Strengths** |",
            "| ✅ **Strengths** | ⚠️ **Threats / Risks** |")
        quads = rr.parse_swot(swapped)
        assert "83.34" in quads["strength"]      # the columns moved with their labels
        assert "ROIC" in quads["threat"]

    def test_threats_lead_the_rendered_card(self):
        """`prompts/06_swot.md` weights threats double; opening with Strengths would
        quietly invert the emphasis the analysis was written with."""
        html = rr.build_swot(SWOT_MD)
        assert html.index("Threats") < html.index("Strengths")

    def test_the_card_states_it_does_not_enter_the_composite(self):
        assert "composite" in rr.build_swot(SWOT_MD)

    def test_bold_survives_into_the_card(self):
        assert "<b>27.66%</b>" in rr.build_swot(SWOT_MD)

    def test_a_report_without_a_swot_renders_nothing(self):
        assert rr.build_swot("### 2.19 Veredicto\n\nProse.\n") == ""

    def test_a_partial_swot_renders_what_exists(self):
        partial = ("### 2.18a SWOT\n\n| ⚠️ **Threats** | ✅ **Strengths** |\n|---|---|\n"
                   "| A threat body long enough that no length bound could mistake it "
                   "for a column heading. | a strength body |\n")
        html = rr.build_swot(partial)
        assert "A threat body" in html and "Weaknesses" not in html

    def test_the_vertical_one_quadrant_per_row_layout_also_parses(self):
        """Four reports from 2026-08-05 (KLAC, ZTS, WKL.AS, 6857.T) use a one-per-row
        table instead of the 2×2 grid. A parser that only looked at the row below read
        all four as empty and silently dropped the card."""
        vertical = ("### 2.18a SWOT  *(v4 Phase C · overlay)*\n\n| | |\n|---|---|\n"
                    "| **Strengths** | Piotroski 9/9, ROIC 76.19%, operating margin 42.49%. |\n"
                    "| **Weaknesses** | Valuation sub-score 1.0/10; P/E 52.82. |\n"
                    "| **Opportunities** | Consensus revenue +33% then +16%. |\n"
                    "| **Threats / Risks** | Mean reversion to a 19.89x median. |\n")
        quads = rr.parse_swot(vertical)
        assert sorted(quads) == ["opportunity", "strength", "threat", "weakness"]
        assert "Piotroski" in quads["strength"] and "Mean reversion" in quads["threat"]


# --- Sankey -----------------------------------------------------------------

class TestSankeyCard:
    def _body(self):
        return ("### 2.1 Business model\n\n```mermaid\nsankey-beta\n\nRevenue,COGS,10\n"
                "Revenue,Gross Profit,20\n```\n")

    def test_no_diagram_costs_nothing_and_renders_nothing(self, tmp_path):
        html, used = rr.build_sankey("### 2.1\n\nprose\n", tmp_path, "X", {"date": "2026-08-15"})
        assert (html, used) == ("", 0)

    def test_a_failed_render_degrades_silently(self, monkeypatch, tmp_path):
        """The fence still sits in the collapsed appendix, so the reader loses the
        picture and never the numbers. It must not raise."""
        monkeypatch.setattr(rr.mermaid_render, "render", lambda *a, **k: False)
        assert rr.build_sankey(self._body(), tmp_path, "X", {"date": "2026-08-15"}) == ("", 0)

    def test_a_successful_render_is_embedded_and_reports_its_cost(self, monkeypatch, tmp_path):
        png = tmp_path / "IMG" / "2026-08-15_X_sankey.png"

        def fake(src, out, **kw):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"\x89PNG" + b"0" * 500)
            return True
        monkeypatch.setattr(rr.mermaid_render, "render", fake)
        html, used = rr.build_sankey(self._body(), tmp_path, "X", {"date": "2026-08-15"})
        assert used == 504 and png.exists()
        assert 'id="sankey"' in html and "data:image/png;base64," in html

    def test_an_oversized_diagram_is_dropped_rather_than_starving_the_charts(
            self, monkeypatch, tmp_path):
        def fake(src, out, **kw):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"0" * (rr.IMG_BUDGET_BYTES + 1))
            return True
        monkeypatch.setattr(rr.mermaid_render, "render", fake)
        assert rr.build_sankey(self._body(), tmp_path, "X", {"date": "2026-08-15"}) == ("", 0)

    def test_the_caption_does_not_claim_the_hues_mean_anything(self):
        """Measured: sankey-beta ignores both `cScale*` and in-diagram `nodeColors`, so
        the colour legend the prompt used to emit was describing a diagram that never
        existed. The card must not repeat that claim."""
        import inspect
        src = inspect.getsource(rr.build_sankey)
        assert "carry no meaning" in src


class TestSharedImageBudget:
    def test_charts_start_from_the_bytes_the_sankey_already_spent(self, tmp_path):
        """Without a shared allowance every new image silently multiplies the 1.5 MB
        cap the spec fixed, and the report grows past what an email client will hold."""
        img = tmp_path / "IMG"
        img.mkdir()
        big = rr.IMG_BUDGET_BYTES - 100
        (img / "2026-08-15_X_price.png").write_bytes(b"0" * big)
        fm = {"date": "2026-08-15"}
        _, dropped_alone = rr.build_charts(tmp_path / "r.md", tmp_path, "X", fm, used=0)
        _, dropped_after = rr.build_charts(tmp_path / "r.md", tmp_path, "X", fm, used=200)
        assert dropped_alone == [] and dropped_after == ["price"]


# --- the one-page cover -----------------------------------------------------

COVER_JSON = {
    "ticker": "MPWR", "company_name": "Monolithic Power Systems, Inc.", "currency": "USD",
    "verdict": "review", "price_current": 1362.55, "gates_passed": 7,
    "piotroski_fscore": 6, "altman_zscore": 63.25,
    "scores": {"composite": 6.34, "moat": 10.0},
    "fundamentals": {"market_cap": 6.696e10, "revenue_ttm": 3.274e9, "ebitda_ttm": 1.0e9,
                     "net_debt": -1.39e9, "roic_ttm": 0.2766, "roe_ttm": 0.2198,
                     "roe_5y_avg": 0.2966, "net_margin_ttm": 0.245,
                     "operating_margin_ttm": 0.31, "gross_margin_ttm": 0.552,
                     "revenue_stability_0_1": 0.95, "revenue_cagr_5y": 0.1586,
                     "eps_cagr_5y": 0.112, "pe_ratio": 83.34, "forward_pe": 39.16,
                     "ev_ebitda": 65.5, "ev_ebit": 89.98, "peg": 1.4,
                     "debt_to_equity": 0.00486, "net_debt_ebitda": -1.39, "quick_ratio": 3.53,
                     "shares_change_5y_pct": 3.4},
    "top_strip": {"fcf_margin_pct": 13.57, "fcf_yield_pct": 0.66, "beta_3y": 2.005,
                  "alpha_ann_pct": 9.23, "revenue_cagr_5y_pct": 15.86},
    "intrinsic_value": {"mos_class": "rich", "mos_pct": -101.1,
                        "capm": {"cost_of_equity": 0.1307}},
    "technical": {"go_no_go": "GO"},
    "exit_plan": {"thesis_broken_trigger": {"text": "Growth below 10% while the multiple normalises."}},
    "capital_returns": {"net_payout_yield": 0.0044, "shares_change_5y_pct": 3.4},
    "red_flags": {"income": {"subscore_0_10": 9.2}, "balance": {"subscore_0_10": 10.0},
                  "cashflow": {"subscore_0_10": 10.0}},
}

COVER_FM = {"ticker": "MPWR", "currency": "USD", "verdict": "review", "score": "6.34",
            "fair_price": "1820.0", "fair_price_basis": "consensus", "mos_class": "rich",
            "go_no_go": "GO", "bear_case_trigger": "Growth below 10% while the multiple normalises."}

COVER_BODY = ("> [!success] 💚 **Thesis**: **A wide-moat analog power specialist.**\n\n"
              "> [!danger] 🔴 **Risks**: **83.3x GAAP earnings with no valuation cushion.**\n")


class TestCover:
    def test_the_answer_comes_first(self):
        html = rr.build_cover(COVER_JSON, COVER_FM, COVER_BODY)
        assert html.index("WATCH") < html.index("Key financials")
        assert 'id="cover"' in html

    def test_every_requested_group_is_present(self):
        html = rr.build_cover(COVER_JSON, COVER_FM, COVER_BODY)
        for g in ("Scale", "Profitability", "Valuation", "Health", "Growth", "Risk / return"):
            assert g in html, g

    def test_the_headline_numbers_render(self):
        html = rr.build_cover(COVER_JSON, COVER_FM, COVER_BODY)
        for token in ("$66.96B", "83.3×", "6/9", "63.25", "7/7", "27.7%", "15.9%"):
            assert token in html, token

    def test_a_duplicated_exit_trigger_is_not_printed_twice(self):
        """`exit_plan.thesis_broken_trigger` is frequently a verbatim copy of the
        frontmatter's `bear_case_trigger`, and printing both spent a third of the answer
        band restating one sentence on the page with no room to waste."""
        html = rr.build_cover(COVER_JSON, COVER_FM, COVER_BODY)
        assert html.count("Growth below 10% while the multiple normalises") == 1
        assert "Exit trigger" not in html

    def test_a_distinct_exit_trigger_is_printed(self):
        data = {**COVER_JSON,
                "exit_plan": {"thesis_broken_trigger": {"text": "Sell if margins break 40%."}}}
        html = rr.build_cover(data, COVER_FM, COVER_BODY)
        assert "Exit trigger" in html and "margins break 40%" in html

    def test_missing_values_render_na_never_zero(self):
        """A cover printing 0.00 for a missing net-debt figure reads as a debt-free
        company — the single most expensive way for this page to be wrong."""
        html = rr.build_cover({"ticker": "X"}, {"ticker": "X"}, "")
        assert "n/a" in html
        assert "$0.00" not in html and "0.0%" not in html

    def test_a_tiny_ratio_is_not_rounded_to_zero(self):
        """MPWR's D/E is 0.005. `0.00` reads as missing data or as an exact zero, and it
        is neither."""
        html = rr.build_cover(COVER_JSON, COVER_FM, COVER_BODY)
        assert "&lt;0.01" in html or "<0.01" in html

    def test_roic_falls_back_to_roe_with_a_changed_label(self):
        """The v4.2 IC_MIN_FRACTION guard returns None for cash-rich balance sheets on
        purpose. ROE is the right metric there, and the label has to say which is shown."""
        data = {**COVER_JSON, "fundamentals": {**COVER_JSON["fundamentals"], "roic_ttm": None}}
        html = rr.build_cover(data, COVER_FM, COVER_BODY)
        assert "ROIC n/a" in html and "22.0%" in html      # the ROE value

    def test_the_gurufocus_link_appears_for_a_mapped_venue(self):
        assert "gurufocus.com/stock/MPWR" in rr.build_cover(COVER_JSON, COVER_FM, COVER_BODY)

    def test_no_link_is_emitted_for_an_unverified_venue(self):
        data, fm = {**COVER_JSON, "ticker": "LYC.AX"}, {**COVER_FM, "ticker": "LYC.AX"}
        assert "gurufocus" not in rr.build_cover(data, fm, COVER_BODY).lower()

    def test_the_stars_row_only_lists_rated_dimensions(self):
        thin = {"ticker": "X", "fundamentals": {"revenue_stability_0_1": 0.9,
                                                "gross_margin_ttm": 0.6,
                                                "revenue_cagr_5y": 0.1}}
        html = rr.build_cover(thin, {"ticker": "X"}, "")
        assert "Business model" in html and "Capital allocation" not in html

    def test_an_empty_analysis_still_produces_a_cover(self):
        """The cover is page 1 — it must render even when almost nothing loaded, because
        a missing page 1 is more alarming than a sparse one."""
        html = rr.build_cover({}, {}, "")
        assert 'id="cover"' in html and "Key financials" in html

    def test_the_prose_budget_is_advisory_not_a_truncation(self, capsys):
        """Clipping a bear trigger mid-sentence is worse than a cover that runs 1-2 lines
        long, so exceeding the measured budget logs and prints everything anyway."""
        long_fm = {**COVER_FM, "bear_case_trigger": "x" * (rr.COVER_PROSE_BUDGET_CHARS + 50)}
        html = rr.build_cover(COVER_JSON, long_fm, COVER_BODY)
        assert "x" * 100 in html
        assert "may run onto a second page" in capsys.readouterr().err


class TestCoverFormatters:
    def test_compact_money_scales(self):
        assert rr._fmt_big(6.696e10, "USD") == "$66.96B"
        assert rr._fmt_big(3.274e9, "USD") == "$3.27B"
        assert rr._fmt_big(-1.39e9, "USD") == "-$1.39B"
        assert rr._fmt_big(None, "USD") == "n/a"

    def test_multiples_are_marked_so_they_cannot_be_read_as_percentages(self):
        assert rr._fmt_x(83.34) == "83.3×"
        assert rr._fmt_x(None) == "n/a"

    def test_small_ratios_are_floored_not_rounded_away(self):
        assert rr._fmt_ratio(0.00486) == "<0.01"   # MPWR's real D/E
        assert rr._fmt_ratio(-0.00486) == "-0.01"  # sign survives the floor
        assert rr._fmt_ratio(0.0) == "0.00"        # a real zero still prints as zero
        assert rr._fmt_ratio(3.53) == "3.53"
        assert rr._fmt_ratio(None) == "n/a"

    def test_a_value_that_rounds_fine_is_left_alone(self):
        """The first version compared against a hand-derived `0.5 * 10**-decimals`
        threshold, and float representation put 0.005 on the wrong side of it — the guard
        fired for a value that rounds perfectly well. Ask the formatter, do not predict it."""
        assert rr._fmt_ratio(0.005) == "0.01"


# --- valuation methods compared (2.5) ---------------------------------------

VAL_JSON = {
    "ticker": "MPWR", "currency": "USD", "price_current": 1362.55,
    "intrinsic_value": {
        "models": {
            "two_minute_eps_growth": {"value": 911.22, "valid": True, "reason": None},
            "lynch_peg": {"value": 409.57, "valid": True, "reason": None},
            "forward_pe_target": {"value": 1243.96, "valid": True, "reason": None},
            "dcf": {"value": None, "valid": False,
                    "reason": "DCF implies -88% vs price — exceeds the 70% sanity threshold"},
            "roe_residual_income": {"value": 146.07, "valid": True, "reason": None},
        },
        "blend": {"value": 677.71, "n_valid": 4, "n_models": 5,
                  "label": "blend of 4/5 (…) — dcf excluded: DCF implies -88% vs price …"},
    },
    "valuation_bands": {"pe_band": {"current": 83.34, "median": 32.12, "depth_years": 15}},
    "consensus": {"target_median": 1820.0, "analyst_count": 13},
}


class TestValuationCompare:
    def test_every_method_gets_a_row(self):
        html = rr.build_valuation_compare(VAL_JSON)
        for label in ("Current price", "2-minute EPS growth", "Lynch PEG",
                      "Forward P/E target", "DCF", "ROE residual income",
                      "Own-history P/E band", "Consensus median", "Blend"):
            assert label in html, label

    def test_an_invalid_model_is_shown_with_its_reason_not_hidden(self):
        """"The DCF was excluded, and why" is information. A table that silently has four
        rows instead of five is not — it is the same concealment the blend already does."""
        html = rr.build_valuation_compare(VAL_JSON)
        assert "excluded" in html and "sanity threshold" in html

    def test_upside_and_downside_are_signed_and_colour_coded(self):
        html = rr.build_valuation_compare(VAL_JSON)
        assert "+34%" in html and 'vc-up' in html      # consensus above price
        assert "-89%" in html and 'vc-down' in html    # residual income below price

    def test_a_wide_spread_raises_the_banner(self):
        html = rr.build_valuation_compare(VAL_JSON)
        assert "Methods disagree materially" in html and "12.5×" in html

    def test_a_narrow_spread_still_prints_the_spread(self):
        """The reader must be able to judge a 4× themselves rather than infer "fine" from
        the absence of a banner."""
        tight = {**VAL_JSON, "intrinsic_value": {
            "models": {"lynch_peg": {"value": 1300.0, "valid": True},
                       "forward_pe_target": {"value": 1500.0, "valid": True}},
            "blend": {"value": 1400.0, "n_valid": 2, "n_models": 2}},
            "consensus": {}, "valuation_bands": {}}
        html = rr.build_valuation_compare(tight)
        assert "Methods disagree materially" not in html
        assert "Spread across valid methods" in html and "1.2×" in html

    def test_the_threshold_is_the_calibrated_one(self):
        """Measured across the 59 analysis JSONs on disk: median spread 3.37×. The plan's
        proposed 2.5× would have fired on 61 % of reports — a warning that appears on most
        reports is wallpaper. 6.0× fires on ~24 %, roughly the top quartile."""
        assert rr.VALUATION_DISPERSION_X == 6.0
        assert rr.MEDIAN_DISPERSION_X == 3.37

    def test_the_blend_row_does_not_restate_every_exclusion_reason(self):
        """The blend's own label repeats the DCF reason verbatim, which is already on the
        DCF row; two paragraphs of duplicated prose bury the number the row exists for."""
        html = rr.build_valuation_compare(VAL_JSON)
        assert "blend of 4/5 valid models" in html
        assert html.count("sanity threshold") == 1

    def test_consensus_needs_at_least_three_analysts(self):
        thin = {**VAL_JSON, "consensus": {"target_median": 1820.0, "analyst_count": 2}}
        assert "Consensus median" not in rr.build_valuation_compare(thin)

    def test_an_analysis_without_models_renders_nothing(self):
        assert rr.build_valuation_compare({"ticker": "X", "price_current": 10.0}) == ""

    def test_a_missing_price_does_not_raise(self):
        html = rr.build_valuation_compare({**VAL_JSON, "price_current": None})
        assert "Lynch PEG" in html and "—" in html


class TestFooterWatermark:
    def test_the_version_comes_from_version_py_not_a_literal(self):
        """The SKILL.md H1 drifted a whole version because a version lived in prose. This
        watermark is what makes a skipped bump visible on the face of every report."""
        import version as v
        html = rr.build_footer({}, {})
        assert f"skill v{v.version_string()}" in html

    def test_host_and_user_are_both_stamped(self):
        html = rr.build_footer({}, {})
        assert "host:" in html and "user:" in html


# --- the cumulative index (2.6) ---------------------------------------------

class TestIndexSplit:
    """`index.html` and `_index.html` were never duplicates, and that was the real bug
    behind "the index is out of date": `index.html` was a single-DATE hub overwritten every
    day, so yesterday's reports vanished from it, while the cumulative index lived at
    `_index.html` and nothing scheduled its rebuild (stale since 2026-08-06)."""

    def test_the_dated_hub_no_longer_claims_the_bookmarked_filename(self):
        import inspect
        src = inspect.getsource(rr.main)
        assert '_index_{args.index}.html' in src
        assert 'out_dir / "index.html"' not in src

    def test_a_missing_builder_is_reported_not_raised(self, tmp_path):
        """Phase 6 is the step the 2026-08-15 timeout skipped. An index refresh must not be
        able to take a run down after the reports are already on disk."""
        assert rr.refresh_cumulative_index(tmp_path) is None

    def test_a_failing_builder_is_reported_not_raised(self, tmp_path, monkeypatch):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "_build_index.py").write_text("raise SystemExit(1)", encoding="utf-8")
        assert rr.refresh_cumulative_index(tmp_path) is None

    def test_a_builder_that_hangs_is_reported_not_raised(self, tmp_path, monkeypatch):
        import subprocess
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "_build_index.py").write_text("pass", encoding="utf-8")

        def boom(*a, **k):
            raise subprocess.TimeoutExpired(cmd="py", timeout=180)
        monkeypatch.setattr(subprocess, "run", boom)
        assert rr.refresh_cumulative_index(tmp_path) is None

    def test_exit_zero_without_the_file_is_still_a_failure(self, tmp_path):
        """A builder that succeeds and writes nothing would otherwise be reported as a
        refreshed index."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "_build_index.py").write_text("pass", encoding="utf-8")
        assert rr.refresh_cumulative_index(tmp_path) is None

    def test_a_successful_build_returns_the_path(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "_build_index.py").write_text(
            "from pathlib import Path\n"
            "Path(__file__).resolve().parent.parent.joinpath('index.html')"
            ".write_text('<html>cumulative</html>', encoding='utf-8')\n",
            encoding="utf-8")
        out = rr.refresh_cumulative_index(tmp_path)
        assert out and (tmp_path / "index.html").read_text(encoding="utf-8") == "<html>cumulative</html>"


# --- SWOT materiality tags (v4.3 wave 2.7) ----------------------------------

TAGGED_SWOT_MD = """### 2.18a SWOT  *(v4 Phase C · overlay)*

| ⚠️ **Threats / Risks** | ✅ **Strengths** |
|---|---|
| **MATERIAL** — Valuation at the 100th percentile (P/E 83.34)<br>*minor* — FX drag on EU revenue (inferred) | **MATERIAL** — ROIC 27.66% vs 13.07% cost of equity<br>*minor* — Long CEO tenure (inferred) |
| 🔸 **Weaknesses** | 🚀 **Opportunities** |
| *minor* — Share count +3.40% over 5y | **MATERIAL** — AI rack power content compounding (inferred) |
"""


class TestSwotItemSplitting:
    def test_items_split_on_the_literal_br(self):
        items = rr.split_swot_items("a<br>b<br>c")
        assert [t for _, t in items] == ["a", "b", "c"]

    @pytest.mark.parametrize("sep", ["<br>", "<br/>", "<br />", "<BR>"])
    def test_every_br_spelling_splits(self, sep):
        assert len(rr.split_swot_items(f"a{sep}b")) == 2

    def test_a_cell_without_a_break_is_one_item(self):
        assert len(rr.split_swot_items("one long paragraph")) == 1

    def test_empty_input_yields_nothing(self):
        assert rr.split_swot_items("") == []
        assert rr.split_swot_items(None) == []

    def test_blank_segments_are_dropped(self):
        assert len(rr.split_swot_items("a<br><br>  <br>b")) == 2

    @pytest.mark.parametrize("prefix", [
        "**MATERIAL** — ", "*MATERIAL* - ", "MATERIAL: ", "material — ",
        "__MATERIAL__ – ",
    ])
    def test_every_material_spelling_is_recognised(self, prefix):
        (mat, txt), = rr.split_swot_items(prefix + "Valuation stretched")
        assert mat == "material"
        assert txt == "Valuation stretched"

    @pytest.mark.parametrize("prefix", ["*minor* — ", "minor: ", "**minor** - "])
    def test_every_minor_spelling_is_recognised(self, prefix):
        (mat, txt), = rr.split_swot_items(prefix + "FX drag")
        assert mat == "minor"
        assert txt == "FX drag"

    def test_the_tag_is_stripped_from_the_displayed_text(self):
        (_, txt), = rr.split_swot_items("**MATERIAL** — ROIC 27.66%")
        assert "MATERIAL" not in txt

    def test_casing_of_the_item_text_survives(self):
        # _normalise_ws lowercases (it compares prose); using it here would have
        # shipped every SWOT item in lower case.
        (_, txt), = rr.split_swot_items("**MATERIAL** — ROIC vs WACC in the EU")
        assert txt == "ROIC vs WACC in the EU"

    def test_an_untagged_item_reports_no_materiality(self):
        (mat, txt), = rr.split_swot_items("Plain prose with no tag")
        assert mat is None
        assert txt == "Plain prose with no tag"

    def test_a_word_merely_containing_the_tag_is_not_a_tag(self):
        (mat, txt), = rr.split_swot_items("Materially different capital structure")
        assert mat is None
        assert txt == "Materially different capital structure"

    def test_the_tag_word_without_a_separator_is_not_a_tag(self):
        # "Material weakness in controls" is a real audit phrase, not a tag.
        (mat, txt), = rr.split_swot_items("Material weakness in controls")
        assert mat is None
        assert txt == "Material weakness in controls"


class TestSwotMaterialityRendering:
    def test_tagged_items_render_as_a_list(self):
        html = rr.build_swot(TAGGED_SWOT_MD)
        assert 'class="swot-items"' in html

    def test_material_and_minor_get_distinct_classes(self):
        html = rr.build_swot(TAGGED_SWOT_MD)
        assert 'class="swot-material"' in html
        assert 'class="swot-minor"' in html

    def test_the_legend_explains_material_only_when_tags_are_present(self):
        assert "would change the verdict" in rr.build_swot(TAGGED_SWOT_MD)
        assert "would change the verdict" not in rr.build_swot(SWOT_MD)

    def test_untagged_reports_still_render_as_prose(self):
        # 40 reports on disk predate the tags; inventing one <li> per sentence
        # would fabricate a structure the analyst never wrote.
        html = rr.build_swot(SWOT_MD)
        assert html
        assert 'class="swot-items"' not in html

    def test_threats_still_lead_when_tagged(self):
        html = rr.build_swot(TAGGED_SWOT_MD)
        assert html.index("swot-threat") < html.index("swot-strength")

    def test_numbers_inside_tagged_items_keep_their_markdown(self):
        assert "<b>27.66%</b>" in rr.build_swot(
            TAGGED_SWOT_MD.replace("ROIC 27.66%", "ROIC **27.66%**"))

    def test_the_material_class_is_styled_by_the_template(self):
        css = (SCRIPTS / "report_template.html").read_text(encoding="utf-8")
        for cls in ("swot-items", "swot-material", "swot-minor"):
            assert cls in css


# ===================================================================
# wave 3.5 / 3.6 — the category & return-metric lens card
# ===================================================================
CAT_BLOCK = {
    "schema": "category_lens/1",
    "primary": "cyclical",
    "detected": ["cyclical"],
    "lynch_category": "stalwart",
    "agrees_with_lynch": False,
    "disagreement_note": "at peak earnings a cyclical shows high ROE",
    "peak_earnings_warning": True,
    "flags": {
        "cyclical": {"detected": True, "confidence": "moderate",
                     "evidence": ["1 completed cycle(s) in 9y, deepest 90%",
                                  "LATE-CYCLE: margin sits in the top 17%"],
                     "metrics": {}, "not_computable": [], "secular_decline": False},
        "turnaround": {"detected": False, "confidence": "high", "evidence": [],
                       "metrics": {}, "not_computable": []},
        "asset_play": {"detected": False, "confidence": "high", "evidence": [],
                       "metrics": {}, "not_computable": []},
    },
}

ROIC_BLOCK = {
    "schema": "roic_lens/1",
    "roic": 0.078, "roe": 0.081, "roce": 0.063,
    "roic_ex_goodwill": None, "rote": None,
    "preferred_metric": "roic", "preferred_reason": "ROIC is leverage-neutral",
    "roic_vs_wacc": {"roic": 0.078, "wacc": 0.170, "spread": -0.092,
                     "verdict": "destroys value", "note": "below its cost of capital"},
    "leverage_manufactured_roe": {"flagged": False, "note": None},
    "buffett_multiplier": {"fires": False, "gate": 0.25, "note": None},
    "capital_intensity": {}, "notes": [],
}


class TestLensCard:
    def test_no_blocks_no_card(self):
        assert rr.build_lens({}) == ""

    def test_either_block_alone_renders(self):
        assert rr.build_lens({"category_lens": CAT_BLOCK})
        assert rr.build_lens({"roic_lens": ROIC_BLOCK})

    def test_an_errored_block_is_skipped_not_rendered(self):
        assert rr.build_lens({"category_lens": {"error": "boom"},
                              "roic_lens": {"error": "boom"}}) == ""

    def test_percentages_are_scaled_from_fractions(self):
        """roic_lens stores 0.078; fmt_pct prints a percent. Missing this printed
        'ROIC 0.1% vs WACC 0.2%' on a company earning 7.8% against 17.0%."""
        html = rr.build_lens({"roic_lens": ROIC_BLOCK})
        assert "7.8%" in html and "17.0%" in html
        assert "0.1%" not in html

    def test_the_late_cycle_warning_gets_its_own_row(self):
        html = rr.build_lens({"category_lens": CAT_BLOCK})
        assert "LATE-CYCLE" in html
        assert "mid-cycle EPS" in html

    def test_the_warning_line_is_not_repeated_inside_the_evidence(self):
        html = rr.build_lens({"category_lens": CAT_BLOCK})
        assert html.count("LATE-CYCLE") == 1

    def test_evidence_is_clipped_on_a_word_boundary(self):
        long_ev = dict(CAT_BLOCK)
        long_ev["flags"] = dict(CAT_BLOCK["flags"])
        long_ev["flags"]["cyclical"] = {**CAT_BLOCK["flags"]["cyclical"],
                                        "evidence": ["word " * 200]}
        html = rr.build_lens({"category_lens": long_ev})
        assert "…" in html
        assert "wor…" not in html

    def test_the_disagreement_with_lynch_is_shown(self):
        html = rr.build_lens({"category_lens": CAT_BLOCK})
        assert "lynch_category" in html and "peak earnings" in html

    def test_a_secular_decline_is_flagged_separately_from_a_cycle(self):
        block = json.loads(json.dumps(CAT_BLOCK))
        block["primary"] = None
        block["flags"]["cyclical"] = {"detected": False, "confidence": "high",
                                      "evidence": [], "metrics": {},
                                      "not_computable": [], "secular_decline": True}
        html = rr.build_lens({"category_lens": block})
        assert "SECULAR" in html and "a decline, not a cycle" in html

    def test_no_category_says_the_default_lens_applies(self):
        block = json.loads(json.dumps(CAT_BLOCK))
        block.update(primary=None, detected=[], peak_earnings_warning=False,
                     disagreement_note=None)
        block["flags"]["cyclical"]["detected"] = False
        html = rr.build_lens({"category_lens": block})
        assert "DEFAULT LENS" in html
        assert "Quality Compounder yardsticks apply as written" in html

    def test_the_leverage_flag_is_surfaced_when_it_fires(self):
        block = json.loads(json.dumps(ROIC_BLOCK))
        block["leverage_manufactured_roe"] = {
            "flagged": True, "note": "ROE 28.0% rests on 2.10x debt/equity"}
        html = rr.build_lens({"roic_lens": block})
        assert "LEVERAGED ROE" in html and "2.10x" in html

    def test_the_silently_unfired_buffett_multiplier_reaches_the_reader(self):
        block = json.loads(json.dumps(ROIC_BLOCK))
        block["buffett_multiplier"]["note"] = "silently does not fire"
        assert "silently does not fire" in rr.build_lens({"roic_lens": block})

    def test_the_card_states_it_is_overlay_only(self):
        html = rr.build_lens({"category_lens": CAT_BLOCK, "roic_lens": ROIC_BLOCK})
        assert "not enter the composite" in html or "Neither block enters the composite" in html
        assert "docs/CATEGORIES.md" in html and "docs/ROIC_vs_ROE.md" in html

    def test_the_card_is_in_the_nav_and_in_the_assembly(self):
        assert ("lens", "Category lens") in rr.NAV_ITEMS
        import inspect
        assert "build_lens" in inspect.getsource(rr.render)
