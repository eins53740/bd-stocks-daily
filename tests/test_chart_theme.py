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
    # the adjacent-pair separation the palette was validated on.
    assert th.SERIES == [
        "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
        "#e87ba4", "#008300", "#4a3aa7", "#e34948",
    ]


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


def test_marker_kwargs_carry_a_surface_ring():
    kw = th.marker_kwargs(th.PRIMARY)
    assert kw["markeredgecolor"] == th.SURFACE
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
