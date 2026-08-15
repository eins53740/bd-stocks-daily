"""
Unit tests for star_ratings — the bands, the coverage rule, and the two properties that
make the stars trustworthy rather than decorative.

The two properties, both asserted here:

1. **Determinism.** Same JSON in, same stars out, every time. A star is a structured
   number printed in a report, so anything less would breach the ground-truth rule
   (`SKILL.md:56`) exactly as an LLM-written P/E would.
2. **Overlay-only.** `compute()` never mutates the analysis dict and never emits a
   composite or a verdict. The v2.2 composite is frozen; the stars re-express what the
   analysis found and never re-decide it.

Synthetic fixtures throughout — no network, no JSON on disk.
"""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import star_ratings as sr  # noqa: E402


def analysis(**over):
    """A complete, high-quality name — every component computable."""
    base = {
        "fundamentals": {
            "revenue_stability_0_1": 0.95, "gross_margin_ttm": 0.70,
            "revenue_cagr_5y": 0.22, "roic_ttm": 0.28, "operating_margin_ttm": 0.32,
            "net_margin_ttm": 0.25, "roe_ttm": 0.30, "roe_5y_avg": 0.28,
            "shares_change_5y_pct": -3.0,
        },
        "intrinsic_value": {"capm": {"cost_of_equity": 0.09}},
        "scores": {"moat": 9.0, "composite": 8.1},
        "piotroski_fscore": 9,
        "altman_zscore": 8.0,
        "red_flags": {"income": {"subscore_0_10": 9.5},
                      "balance": {"subscore_0_10": 10.0},
                      "cashflow": {"subscore_0_10": 9.0}},
        "capital_returns": {"net_payout_yield": 0.055, "shares_change_5y_pct": -3.0},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


# --- the band function ------------------------------------------------------

class TestBand:
    def test_the_five_steps_are_where_the_doc_says(self):
        th = (10, 20, 30, 40)
        assert [sr.band(v, th) for v in (5, 10, 25, 35, 100)] == [1, 2, 3, 4, 5]

    def test_a_boundary_value_takes_the_higher_star(self):
        """Bands are `>=`, so "ROIC > 25% is five stars" means 25.0 IS five stars. The
        alternative reads as a rounding bug to anyone checking a number by hand."""
        assert sr.band(20, (10, 20, 30, 40)) == 3

    def test_lower_is_better_inverts_the_scale(self):
        th = (-8.0, -2.0, 1.0, 5.0)
        assert sr.band(-9.0, th, higher_is_better=False) == 5   # shrinking share count
        assert sr.band(10.0, th, higher_is_better=False) == 1   # heavy dilution

    def test_missing_data_is_none_not_one_star(self):
        """One star is a judgement; None is an absence. Collapsing them would print a
        damning rating for a company whose data simply did not load."""
        assert sr.band(None, (1, 2, 3, 4)) is None
        assert sr.band("", (1, 2, 3, 4)) is None

    def test_a_boolean_is_not_a_number(self):
        assert sr.band(True, (0.2, 0.4, 0.6, 0.8)) is None

    def test_a_numeric_string_is_accepted(self):
        assert sr.band("0.30", (0.05, 0.12, 0.20, 0.30)) == 5

    def test_non_ascending_thresholds_are_a_programming_error(self):
        with pytest.raises(ValueError):
            sr.band(1, (4, 3, 2, 1))


# --- dimensions -------------------------------------------------------------

class TestDimensions:
    def test_an_excellent_company_earns_top_marks_across_the_board(self):
        res = sr.compute(analysis())
        stars = {k: v["stars"] for k, v in res["dimensions"].items()}
        assert all(s is not None and s >= 4 for s in stars.values()), stars
        assert res["overall"] >= 4.0

    def test_a_poor_company_scores_low_rather_than_na(self):
        weak = analysis(
            fundamentals={"revenue_stability_0_1": 0.3, "gross_margin_ttm": 0.10,
                          "revenue_cagr_5y": -0.05, "roic_ttm": 0.02,
                          "operating_margin_ttm": 0.01, "net_margin_ttm": 0.005,
                          "roe_ttm": 0.02, "roe_5y_avg": 0.15, "shares_change_5y_pct": 12.0},
            scores={"moat": 1.0}, piotroski_fscore=2, altman_zscore=1.1,
            red_flags={"income": {"subscore_0_10": 2.0},
                       "balance": {"subscore_0_10": 1.0},
                       "cashflow": {"subscore_0_10": 2.0}},
            capital_returns={"net_payout_yield": 0.0, "shares_change_5y_pct": 12.0})
        stars = {k: v["stars"] for k, v in sr.compute(weak)["dimensions"].items()}
        assert all(s == 1 for s in stars.values()), stars

    def test_the_roic_spread_scores_beside_the_absolute_level(self):
        """A 12% ROIC is excellent for a utility and value-destroying for a high-beta
        grower — the spread against cost of equity is what says which."""
        cheap = sr.company_economics(analysis(
            fundamentals={"roic_ttm": 0.12}, intrinsic_value={"capm": {"cost_of_equity": 0.05}}))
        dear = sr.company_economics(analysis(
            fundamentals={"roic_ttm": 0.12}, intrinsic_value={"capm": {"cost_of_equity": 0.16}}))
        assert cheap["components"]["roic_vs_cost_of_equity"] > \
            dear["components"]["roic_vs_cost_of_equity"]
        assert cheap["components"]["roic"] == dear["components"]["roic"]

    def test_missing_cost_of_equity_drops_only_that_component(self):
        data = analysis()
        del data["intrinsic_value"]
        res = sr.company_economics(data)
        assert res["components"]["roic_vs_cost_of_equity"] is None
        assert res["stars"] is not None          # 3 of 4 still clears coverage

    def test_roe_durability_is_a_ratio_not_a_difference(self):
        """A 4-point ROE drop means something different at 40% than at 8%."""
        big = sr.competitive_advantage(analysis(fundamentals={"roe_ttm": 0.36, "roe_5y_avg": 0.40}))
        small = sr.competitive_advantage(analysis(fundamentals={"roe_ttm": 0.04, "roe_5y_avg": 0.08}))
        assert big["components"]["roe_durability"] > small["components"]["roe_durability"]

    def test_a_zero_five_year_roe_does_not_divide_by_zero(self):
        res = sr.competitive_advantage(analysis(fundamentals={"roe_ttm": 0.1, "roe_5y_avg": 0.0}))
        assert res["components"]["roe_durability"] is None

    def test_retaining_at_high_roic_is_not_marked_down_for_a_low_payout(self):
        """Scoring payout alone would penalise exactly the company compounding best."""
        res = sr.capital_allocation(analysis(
            fundamentals={"roic_ttm": 0.30}, capital_returns={"net_payout_yield": 0.0,
                                                              "shares_change_5y_pct": -4.0}))
        assert res["components"]["reinvestment_return"] == 5
        assert res["stars"] >= 3

    def test_piotroski_outweighs_a_saturated_altman(self):
        """Equal weights produced a flat column on real names: 9880.HK printed four stars
        off a Piotroski of 3/9 because an Altman Z of 8.9 pinned that component at five.
        Above its own 3.0 "safe" threshold Altman carries no further information, so an
        unweighted average let one saturated ratio outvote a nine-signal composite."""
        weak_broad = sr.financial_quality({"piotroski_fscore": 3, "altman_zscore": 8.9})
        strong_broad = sr.financial_quality({"piotroski_fscore": 9, "altman_zscore": 1.9})
        assert weak_broad["stars"] < strong_broad["stars"]

    def test_buybacks_beat_dilution_on_the_share_count_component(self):
        buyer = sr.capital_allocation(analysis(capital_returns={"shares_change_5y_pct": -9.0}))
        diluter = sr.capital_allocation(analysis(capital_returns={"shares_change_5y_pct": 9.0}))
        assert buyer["components"]["share_count_trend"] == 5
        assert diluter["components"]["share_count_trend"] == 1


class TestWeighting:
    def test_weights_default_to_equal(self):
        assert sr._dimension({"a": 1, "b": 5})["avg"] == 3.0

    def test_a_weighted_component_moves_the_average_proportionally(self):
        res = sr._dimension({"a": 1, "b": 5}, weights={"a": 3.0})
        assert res["avg"] == 2.0        # (1*3 + 5*1) / 4

    def test_coverage_is_measured_in_weight_not_count(self):
        """A heavy component going missing is a bigger gap than a light one, and a
        count-based coverage would call the two identical."""
        heavy_gone = sr._dimension({"a": None, "b": 4}, weights={"a": 3.0})
        light_gone = sr._dimension({"a": 4, "b": None}, weights={"a": 3.0})
        assert heavy_gone["coverage"] < light_gone["coverage"]
        assert heavy_gone["stars"] is None      # 1 of 4 weight -> below the floor


class TestCoverage:
    def test_a_dimension_below_half_coverage_renders_na(self):
        res = sr.business_model({"fundamentals": {"gross_margin_ttm": 0.6}})
        assert res["stars"] is None and res["reason"] == "insufficient data"

    def test_an_empty_analysis_rates_nothing_and_does_not_raise(self):
        res = sr.compute({})
        assert res["rated_dimensions"] == 0
        assert all(d["stars"] is None for d in res["dimensions"].values())
        assert "overall" not in res

    def test_a_screen_without_the_red_flag_scanner_still_rates_financial_quality(self):
        """Screens carry Piotroski and Altman but no scanner. Counting the scanner's three
        sub-scores separately put them at 2-of-5 = 40 % and printed `n/a` for a dimension
        their two indicators answer perfectly well — measured on the 2026-08-15 IBM run."""
        screen = analysis(red_flags={})
        del screen["red_flags"]
        res = sr.financial_quality(screen)
        # Coverage is measured in WEIGHT: piotroski 2.0 + altman 0.5 of a 3.5 total.
        assert res["stars"] is not None and res["coverage"] == 0.71

    def test_overall_needs_at_least_three_rated_dimensions(self):
        """An "overall" resting on two dimensions reads like a summary of five."""
        thin = {"fundamentals": {"revenue_stability_0_1": 0.9, "gross_margin_ttm": 0.6,
                                 "revenue_cagr_5y": 0.1},
                "piotroski_fscore": 8, "altman_zscore": 4.0}
        res = sr.compute(thin)
        assert res["rated_dimensions"] == 2
        assert "overall" not in res


# --- the two load-bearing properties ---------------------------------------

class TestDeterminism:
    def test_the_same_input_gives_the_same_stars(self):
        data = analysis()
        assert sr.compute(data) == sr.compute(copy.deepcopy(data))

    def test_rounding_is_half_up_not_bankers(self):
        """Python rounds 3.5 to 3 and 4.5 to 4, so two companies half a star apart could
        print the same number — a surprising result to have to defend in a report."""
        assert sr._dimension({"a": 3, "b": 4})["stars"] == 4       # 3.5 -> 4
        assert sr._dimension({"a": 4, "b": 5})["stars"] == 5       # 4.5 -> 5


class TestOverlayOnly:
    def test_compute_does_not_mutate_the_analysis(self):
        data = analysis()
        before = copy.deepcopy(data)
        sr.compute(data)
        assert data == before

    def test_no_composite_or_verdict_is_emitted(self):
        res = sr.compute(analysis())
        flat = str(res)
        assert "composite" not in res and "verdict" not in res
        assert "8.1" not in flat        # the composite value never leaks in

    def test_a_broken_dimension_degrades_instead_of_ending_the_run(self, monkeypatch):
        def boom(_data):
            raise RuntimeError("kaboom")
        monkeypatch.setattr(sr, "DIMENSIONS",
                            [("business_model", "Business model", boom)] + sr.DIMENSIONS[1:])
        res = sr.compute(analysis())
        assert res["dimensions"]["business_model"]["stars"] is None
        assert "error" in res["dimensions"]["business_model"]["reason"]
        assert res["dimensions"]["financial_quality"]["stars"] is not None


class TestRendering:
    def test_stars_render_as_filled_and_empty_glyphs(self):
        assert sr.render_stars(3) == "★★★☆☆"
        assert sr.render_stars(5) == "★★★★★"

    def test_none_renders_na_not_zero_stars(self):
        assert sr.render_stars(None) == "n/a"

    def test_out_of_range_values_are_clamped(self):
        assert sr.render_stars(9) == "★★★★★"
        assert sr.render_stars(-2) == "☆☆☆☆☆"


def test_every_dimension_is_registered_in_the_dimensions_table():
    """A dimension that exists as a function but not in DIMENSIONS is invisible to the
    report — silently, and with no test failing anywhere else."""
    registered = {key for key, _label, _fn in sr.DIMENSIONS}
    assert registered == {"business_model", "company_economics", "competitive_advantage",
                          "financial_quality", "capital_allocation"}


# --- the doc IS the contract ------------------------------------------------

class TestPublishedBandsMatchTheCode:
    """`docs/STAR_RATINGS.md` says it is the contract. These tests are what make that
    sentence true rather than aspirational — a threshold changed in one place and not the
    other is exactly the drift Wave 0 spent its time removing."""

    DOC = Path(__file__).resolve().parent.parent / "docs" / "STAR_RATINGS.md"

    def _doc(self):
        assert self.DOC.exists(), f"the published bands are missing: {self.DOC}"
        # The doc uses a typographic minus (U+2212) because it is prose for a human;
        # the code uses ASCII. Normalising here keeps the doc readable without letting
        # the difference silently pass a threshold as "not published".
        return self.DOC.read_text(encoding="utf-8").replace("−", "-")

    def test_every_threshold_in_the_code_is_published(self):
        import inspect
        import re
        doc = self._doc()
        missing = []
        for key, _label, fn in sr.DIMENSIONS:
            src = inspect.getsource(fn)
            for tup in re.findall(r"\(([-\d.,\s]+)\)", src):
                nums = [n.strip() for n in tup.split(",") if n.strip()]
                if len(nums) != 4:
                    continue                       # not a threshold tuple
                for n in nums:
                    # Published as percentages for rates and as raw numbers otherwise, so
                    # accept either rendering of the same threshold.
                    val = float(n)
                    forms = {n, n.lstrip("0") or n, f"{val:g}", f"{val * 100:g}"}
                    if not any(f in doc for f in forms if f):
                        missing.append((key, n))
        assert not missing, f"thresholds in code but not in STAR_RATINGS.md: {missing}"

    def test_every_dimension_has_a_section(self):
        doc = self._doc()
        for _key, label, _fn in sr.DIMENSIONS:
            assert f"## " in doc and label.split()[0] in doc, label

    def test_the_weights_that_exist_are_published(self):
        """Only financial quality is weighted. If a second dimension gains weights and the
        doc is not updated, the published tables silently stop describing the maths."""
        import inspect
        import re
        doc = self._doc()
        for key, _label, fn in sr.DIMENSIONS:
            src = inspect.getsource(fn)
            if "weights=" not in src:
                continue
            for w in set(re.findall(r'"[a-z_]+": (\d+\.\d+)', src.split("weights=")[1])):
                assert f"**{w}**" in doc or f"| {w} " in doc, (key, w)

    def test_the_schema_version_is_stated_in_the_doc_change_procedure(self):
        assert sr.compute({})["schema"] in self._doc()
