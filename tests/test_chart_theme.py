"""
Unit tests for chart_theme.py and the styling contracts render_charts.py relies on.

These lock the properties that make the charts readable — the palette is the
validated set in fixed order, bars stay thin, fractional axes read as
percentages — plus a smoke render of every offline chart so a styling change
cannot silently start raising.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import chart_theme as th  # noqa: E402


# --- palette ----------------------------------------------------------------

def test_palette_is_the_validated_set_in_fixed_order():
    # Order is the CVD-safety mechanism, not cosmetic — a reshuffle invalidates
    # the adjacent-pair separation the palette was validated on. These are the
    # 2026-07-28 steps, re-stepped into the DARK lightness band so one palette
    # validates on both surfaces (required once the PNGs went transparent).
    assert th.SERIES == [
        "#2a78d6", "#e6642f", "#12ab77", "#c98000",
        "#d46992", "#008300", "#594cba", "#e34948",
    ]


def test_every_slot_sits_inside_the_dark_lightness_band():
    """The dark band [0.48, 0.67] is a strict subset of light's [0.43, 0.77], so
    staying inside it is what lets a single transparent PNG read on either page.
    Recomputed here rather than trusted: an eyeballed hex tweak would silently
    break the property the whole transparency decision rests on."""
    import math

    def oklch_L(hexc):
        h = hexc.lstrip("#")
        def lin(c):
            c /= 255
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = (lin(int(h[i:i + 2], 16)) for i in (0, 2, 4))
        l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
        m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
        s_ = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
        c = [v ** (1 / 3) if v > 0 else -((-v) ** (1 / 3)) for v in (l, m, s_)]
        return 0.2104542553 * c[0] + 0.7936177850 * c[1] - 0.0040720468 * c[2]

    for hexc in th.SERIES:
        L = oklch_L(hexc)
        assert 0.48 <= L <= 0.67, f"{hexc} L={L:.3f} outside the dark band"


def test_ink_steps_clear_three_to_one_on_both_surfaces():
    """The point of the mid-tone ink: legible on a light page AND a dark one."""
    def lum(hexc):
        h = hexc.lstrip("#")
        def lin(c):
            c /= 255
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = (lin(int(h[i:i + 2], 16)) for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def ratio(a, b):
        la, lb = lum(a), lum(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    for name in ("INK", "INK_SECONDARY", "INK_MUTED", "AXIS", "RING"):
        col = getattr(th, name)
        light, dark = ratio(col, "#fcfcfb"), ratio(col, "#1e1e1e")
        assert min(light, dark) >= 3.0,             f"{name} {col}: light {light:.2f}, dark {dark:.2f} — below 3:1 on one surface"


def test_named_slots_point_at_the_first_three_series():
    assert th.PRIMARY == th.SERIES[0]
    assert th.ACCENT == th.SERIES[1]
    assert th.AQUA == th.SERIES[2]


def test_status_colours_are_disjoint_from_series_colours():
    # A status colour must never be mistakable for "series N".
    assert not {th.GOOD, th.WARNING, th.CRITICAL} & set(th.SERIES)


def test_every_colour_is_a_full_length_hex():
    for name, value in vars(th).items():
        if name.isupper() and isinstance(value, str) and value.startswith("#"):
            assert len(value) == 7, f"{name}={value}"


# --- bar width cap ----------------------------------------------------------

def test_cap_bar_width_clamps_a_wide_bar_over_few_categories():
    fig, ax = plt.subplots()
    # 0.62 over 3 categories would render as a slab; the cap pulls it in.
    assert th.cap_bar_width(ax, 0.62, 3) == pytest.approx(0.135)
    plt.close(fig)


def test_cap_bar_width_leaves_an_already_thin_bar_alone():
    fig, ax = plt.subplots()
    assert th.cap_bar_width(ax, 0.05, 40) == pytest.approx(0.05)
    plt.close(fig)


def test_cap_bar_width_scales_with_category_count():
    fig, ax = plt.subplots()
    narrow = th.cap_bar_width(ax, 10.0, 3)
    wide = th.cap_bar_width(ax, 10.0, 30)
    assert wide > narrow
    plt.close(fig)


def test_cap_bar_width_survives_garbage_input():
    fig, ax = plt.subplots()
    assert th.cap_bar_width(ax, 0.5, None) == 0.5  # type: ignore[arg-type]
    plt.close(fig)


# --- axes chrome ------------------------------------------------------------

def test_style_axes_drops_the_top_and_right_spines():
    fig, ax = plt.subplots()
    th.style_axes(ax, title="t", ylabel="y")
    assert not ax.spines["top"].get_visible()
    assert not ax.spines["right"].get_visible()
    assert ax.spines["left"].get_visible()
    plt.close(fig)


def test_style_axes_sets_title_left_aligned():
    fig, ax = plt.subplots()
    th.style_axes(ax, title="My title")
    assert ax.get_title(loc="left") == "My title"
    assert ax.get_title(loc="center") == ""
    plt.close(fig)


def test_subtitle_is_rendered_as_its_own_text():
    fig, ax = plt.subplots()
    th.style_axes(ax, title="T", subtitle="the subtitle")
    assert any("the subtitle" == t.get_text() for t in ax.texts)
    plt.close(fig)


def test_percent_axis_formats_fractions_as_percentages():
    fig, ax = plt.subplots()
    ax.set_xlim(0, 0.4)
    th.percent_axis(ax, "x")
    assert "%" in ax.xaxis.get_major_formatter()(0.25, None)
    plt.close(fig)


def test_marker_kwargs_carry_a_neutral_ring_not_a_surface_knockout():
    # A surface-coloured ring was a knockout: it only worked because the PNG had a
    # light background painted in. On a transparent PNG over a dark page it became a
    # pale blob, so the ring is now a dual-surface neutral.
    kw = th.marker_kwargs(th.PRIMARY)
    assert kw["markeredgecolor"] == th.RING
    assert kw["markeredgecolor"] != th.SURFACE
    assert kw["markeredgewidth"] > 0
    assert kw["markerfacecolor"] == th.PRIMARY


def test_apply_theme_is_idempotent():
    th.apply_theme()
    first = matplotlib.rcParams["axes.titlelocation"]
    th.apply_theme()
    assert matplotlib.rcParams["axes.titlelocation"] == first == "left"


def test_theme_grid_is_solid_not_dashed():
    th.apply_theme()
    assert matplotlib.rcParams["grid.linestyle"] == "-"


def test_save_writes_a_png(tmp_path):
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    out = tmp_path / "x.png"
    th.save(fig, out)
    assert out.is_file() and out.stat().st_size > 0


# --- smoke renders (offline charts only) ------------------------------------

@pytest.fixture(scope="module")
def rc():
    import render_charts
    return render_charts


SCORES = {
    "fundamentals": 8.2, "valuation": 4.1, "moat": 8.8, "peer": 6.5,
    "growth_durability": 7.0, "management": 8.0, "market_context": 5.5,
    "composite": 7.1,
}


def test_radar_renders(rc, tmp_path):
    out = tmp_path / "radar.png"
    assert rc.chart_radar(SCORES, "TEST", out) is True
    assert out.stat().st_size > 0


def test_radar_still_refuses_incomplete_scores(rc, tmp_path):
    # The pre-existing guard must survive the restyle: a misleading near-zero
    # radar is worse than no chart.
    assert rc.chart_radar({"composite": 5.0}, "TEST", tmp_path / "r.png") is False


def test_dcf_renders(rc, tmp_path):
    out = tmp_path / "dcf.png"
    assert rc.chart_dcf("TEST", 245.0, 289.0, "USD", out) is True
    assert out.stat().st_size > 0


def test_dcf_skips_without_inputs(rc, tmp_path):
    assert rc.chart_dcf("TEST", None, 289.0, "USD", tmp_path / "d.png") is False


def test_peers_renders_with_metrics(rc, tmp_path):
    peer_info = {
        "industry": "Widgets",
        "peer_tickers": ["AAA", "BBB"],
        "peer_metrics": {
            "TEST": {"pe": 24.1, "ev_ebitda": 14.2, "peg": 2.1,
                     "roe": 0.263, "net_margin": 0.114, "fcf_yield": 0.052},
            "AAA": {"pe": 22.4, "ev_ebitda": 13.1, "peg": None,
                    "roe": 0.298, "net_margin": 0.168, "fcf_yield": 0.045},
            "BBB": {"pe": 16.8, "ev_ebitda": 10.4, "peg": 1.7,
                    "roe": 0.151, "net_margin": 0.113, "fcf_yield": 0.061},
        },
        "rankings": {"pe": {"BBB": 1, "AAA": 2, "TEST": 3}},
    }
    out = tmp_path / "peers.png"
    assert rc.chart_peers("TEST", peer_info, out) is True
    assert out.stat().st_size > 0


def test_peers_placeholder_still_renders(rc, tmp_path):
    out = tmp_path / "peers_empty.png"
    assert rc.chart_peers("TEST", {"industry": "Widgets", "peer_tickers": []}, out) is True
    assert out.stat().st_size > 0


def _fin_history() -> dict:
    return {
        "ticker": "TEST",
        "source": "test",
        "currency": "USD",
        "quarters_available": 4,
        "series": {
            "labels": ["2025Q1", "2025Q2", "2025Q3", "2025Q4"],
            "ebitda": [1e9, 1.1e9, 1.2e9, 1.15e9],
            "fcf": [0.8e9, 0.9e9, 1.0e9, 0.95e9],
        },
        "annual": {
            "labels": ["FY2023", "FY2024", "FY2025"],
            "ebitda": [3.8e9, 4.1e9, 4.5e9],
            "fcf": [3.0e9, 3.3e9, 3.6e9],
            "net_income": [2.5e9, 2.8e9, 3.1e9],
        },
        "forecast": {
            "labels": ["2026Q1", "2026Q2"],
            "ebitda": [1.25e9, 1.3e9],
            "fcf": [1.05e9, 1.1e9],
            "basis": "trend_extrapolation_no_consensus",
        },
    }


def test_ebitda_fcf_renders_with_annual_and_forecast(rc, tmp_path):
    out = tmp_path / "ef.png"
    assert rc.chart_ebitda_fcf(_fin_history(), out) is True
    assert out.stat().st_size > 0


def test_ebitda_fcf_rejects_empty_series(rc, tmp_path):
    assert rc.chart_ebitda_fcf({"series": {"labels": [], "ebitda": [], "fcf": []}},
                               tmp_path / "e.png") is False


def test_ni_pe_renders(rc, tmp_path):
    bands = {"pe_band": {"series": [{"year": y, "pe": p} for y, p in
                                    ((2023, 21.0), (2024, 24.5), (2025, 22.1))]}}
    out = tmp_path / "nipe.png"
    assert rc.chart_net_income_vs_pe(_fin_history(), bands, "TEST", out) is True
    assert out.stat().st_size > 0


def test_ni_pe_skips_without_pe_series(rc, tmp_path):
    assert rc.chart_net_income_vs_pe(_fin_history(), {"pe_band": {"series": []}},
                                     "TEST", tmp_path / "n.png") is False


def test_segments_renders_and_folds_the_tail_into_other(rc, tmp_path):
    segments = {
        "fiscal_years": ["FY2023", "FY2024", "FY2025"],
        "currency": "USD",
        "segments": [
            {"name": f"Seg{i}", "values": [1e9 * (9 - i), 1.1e9 * (9 - i), 1.2e9 * (9 - i)]}
            for i in range(7)  # 7 segments -> top 5 + Other, never a 9th hue
        ],
    }
    out = tmp_path / "seg.png"
    assert rc.chart_revenue_segments(segments, out) is True
    assert out.stat().st_size > 0


def test_segments_rejects_invalid_input(rc, tmp_path):
    assert rc.chart_revenue_segments({"fiscal_years": ["a"], "segments": []},
                                     tmp_path / "s.png") is False


def test_validate_segments_accepts_a_good_payload(rc):
    good = {
        "fiscal_years": ["FY2023", "FY2024", "FY2025"],
        "segments": [{"name": "A", "values": [1, 2, None]}],
    }
    assert rc.validate_segments(good) == []


# --- legibility layer (2026-07-28) ------------------------------------------
# The theme gained four helpers whose whole purpose is to stop things printing on
# top of each other. A collision is invisible to a smoke test that only asserts
# "the PNG is non-empty", so assert the geometry instead.

def test_trailing_avg_is_right_aligned_and_waits_for_a_full_window():
    import chart_theme as th
    got = th.trailing_avg([1, 2, 3, 4, 8], window=4)
    assert got[:3] == [None, None, None]
    assert got[3] == 2.5            # (1+2+3+4)/4
    assert got[4] == 4.25           # (2+3+4+8)/4


def test_trailing_avg_suppresses_windows_containing_none_or_nan():
    import math
    import chart_theme as th
    assert th.trailing_avg([1, None, 3, 4, 5], window=4)[3] is None
    assert th.trailing_avg([1, math.nan, 3, 4, 5], window=4)[3] is None


def test_trailing_avg_on_a_series_shorter_than_the_window():
    import chart_theme as th
    assert th.trailing_avg([1, 2], window=4) == [None, None]
    assert th.trailing_avg([], window=4) == []


def test_legend_above_places_the_legend_outside_the_axes():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import chart_theme as th
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="s")
    leg = th.legend_above(ax)
    # y >= 1 in axes coordinates means "above the plot area", which is the point.
    assert leg.get_bbox_to_anchor().y0 >= 1.0
    assert leg.get_frame_on() is False
    plt.close(fig)


def test_legend_above_accepts_explicit_handles_for_a_twin_axis():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import chart_theme as th
    fig, ax = plt.subplots()
    a, = ax.plot([0, 1], [0, 1], label="left")
    ax2 = ax.twinx()
    b, = ax2.plot([0, 1], [1, 0], label="right")
    leg = th.legend_above(ax, ncol=2, handles=[a, b], labels=["left", "right"])
    assert [t.get_text() for t in leg.get_texts()] == ["left", "right"]
    plt.close(fig)


def test_legend_row_lifts_the_title_clear_of_the_legend_strip():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import chart_theme as th

    def rendered_title_gap(**kw):
        """Vertical gap in pixels between the top of the axes and the title
        baseline. `title.get_position()` is always (0, 1.0) — the pad is applied at
        draw time — so the geometry has to be measured after a draw."""
        fig, ax = plt.subplots(figsize=(6, 4), dpi=100)
        th.style_axes(ax, title="T", subtitle="S", **kw)
        fig.canvas.draw()
        gap = (ax.title.get_window_extent().y0
               - ax.get_window_extent().y1)
        plt.close(fig)
        return gap

    assert rendered_title_gap(legend_row=True) > rendered_title_gap() + 10, \
        "the reserved legend row must push the title clear by roughly its height"


def test_legend_row_also_lifts_the_subtitle():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import chart_theme as th

    def subtitle_y(**kw):
        fig, ax = plt.subplots()
        th.style_axes(ax, title="T", subtitle="S", **kw)
        y = [t.get_position()[1] for t in ax.texts if t.get_text() == "S"][0]
        plt.close(fig)
        return y

    assert subtitle_y(legend_row=True) > subtitle_y()


def test_value_chip_is_border_only_so_it_reads_on_any_background():
    # Was a surface-filled box, which only worked because the PNG painted a light
    # background. Transparent PNGs made that fill a pale blob on a dark page.
    fig, ax = plt.subplots()
    ann = th.value_chip(ax, 1, 2, "3.5B", th.PRIMARY)
    assert ann.get_text() == "3.5B"
    assert ann.get_bbox_patch().get_facecolor()[3] == 0, "no fill"
    assert ann.get_bbox_patch().get_edgecolor()[:3] == \
        matplotlib.colors.to_rgb(th.PRIMARY)
    plt.close(fig)


def test_value_chip_can_be_offset_left_of_a_reference_line():
    # Border-only means whatever is behind shows through, so callers next to the
    # forecast rule must be able to move the chip clear of it.
    fig, ax = plt.subplots()
    left = th.value_chip(ax, 1, 2, "x", th.PRIMARY, dx=-46)
    right = th.value_chip(ax, 1, 2, "x", th.PRIMARY)
    assert left.xyann[0] < 0 < right.xyann[0]
    plt.close(fig)


def test_theme_paints_no_background():
    th.apply_theme()
    for key in ("figure.facecolor", "axes.facecolor", "savefig.facecolor"):
        assert matplotlib.rcParams[key] in ("none", (0, 0, 0, 0)), \
            f"{key} must be transparent, or dark-page reading breaks"


def test_saved_png_carries_an_alpha_channel(tmp_path):
    """The end-to-end guarantee: whatever the theme says, the file on disk must
    actually be transparent, or none of the dual-surface work reaches the reader."""
    from PIL import Image
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    out = tmp_path / "alpha.png"
    th.save(fig, out)
    im = Image.open(out)
    # The guarantee is TRANSPARENCY, not a particular storage mode. Since 2026-08-03 save() also
    # palette-quantises, so the file is legitimately "P" with a tRNS array instead of "RGBA".
    # Asserting the mode string would test the encoder; asserting clear pixels tests the promise.
    assert im.mode == "RGBA" or (im.mode == "P" and "transparency" in im.info), \
        f"PNG must be able to carry alpha, got mode={im.mode} info={sorted(im.info)}"
    assert im.convert("RGBA").getpixel((0, 0))[3] == 0, "corner pixel must be clear"


def test_quantised_png_is_smaller_but_keeps_its_transparency(tmp_path):
    """Palette quantisation must never be paid for with a solid background.

    17% of a real chart's pixels are partially transparent (antialiased strokes over nothing), so a
    quantiser that drops alpha -- which is what every Pillow method except FASTOCTREE does -- would
    put a box behind every chart while still looking fine in a thumbnail.
    """
    from PIL import Image
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.set_title("a title with text to antialias")
    out = tmp_path / "q.png"
    th.save(fig, out)

    rgba = Image.open(out).convert("RGBA")
    alpha = rgba.split()[-1].histogram()
    assert alpha[0] > 0, "quantised chart lost its transparent background entirely"
    assert sum(alpha[1:255]) > 0, "quantised chart lost every partially-transparent (AA) pixel"


def test_quantisation_can_be_disabled(tmp_path, monkeypatch):
    """The escape hatch must actually produce a truecolour PNG, so a visual regression can be
    ruled out in one line rather than by reverting the module."""
    from PIL import Image
    monkeypatch.setattr(th, "QUANTIZE_COLORS", 0)
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    out = tmp_path / "noq.png"
    th.save(fig, out)
    assert Image.open(out).mode == "RGBA"


def test_figure_title_reserves_the_top_margin():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import chart_theme as th
    fig, _ = plt.subplots(2, 1)
    th.figure_title(fig, "Title", "Subtitle", top=0.84)
    assert fig.subplotpars.top == 0.84
    assert [t.get_text() for t in fig.texts] == ["Title", "Subtitle"]
    plt.close(fig)


def test_figure_title_without_a_subtitle_draws_only_the_title():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import chart_theme as th
    fig, _ = plt.subplots()
    th.figure_title(fig, "Only")
    assert [t.get_text() for t in fig.texts] == ["Only"]
    plt.close(fig)
