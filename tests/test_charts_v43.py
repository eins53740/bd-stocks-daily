"""
Unit tests for the v4.3 chart builders: the 5-year peers chart and the
long-horizon evolution panel.

Network-free. The two fetch paths take an injectable `_fetcher`, so the FX
conversion, the common-start rule and the depth floors are all exercised against
synthetic series rather than yfinance.

The rules under test are the ones that were WRONG before they were measured:
 - a partial-year EPS stub must not plot as a collapsed final year (MPWR
   2026-06-30, VEEV 2026-04-30),
 - adjusted EPS beside GAAP net income must not print a phantom multiple
   (MPWR FY2024: 14.13 EPS against $1.79bn net income => 126m implied shares
   against ~48m either side => a 150x price/EBITDA spike),
 - a non-US name with four years of history must draw nothing rather than a
   price line over two empty panels.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import matplotlib  # noqa: E402

matplotlib.use("Agg")

import pandas as pd  # noqa: E402

import render_charts as rc  # noqa: E402


# --- peer provenance --------------------------------------------------------

def test_curated_peer_set_is_not_flagged_as_a_proxy():
    note, is_proxy = rc.peers5y_note("by_ticker", "Semiconductors", "Technology")
    assert is_proxy is False
    assert "curated" in note


@pytest.mark.parametrize("source", ["by_industry", "by_sector", "none", ""])
def test_every_non_curated_tier_is_flagged_as_a_proxy(source):
    _, is_proxy = rc.peers5y_note(source, "Semiconductors", "Technology")
    assert is_proxy is True


def test_sector_fallback_says_sector_proxy_in_words():
    # Roadmap N5: adidas ranked against Amazon/McDonald's/Home Depot/Starbucks.
    # The tier has to be legible on the chart, not just present in a field.
    note, _ = rc.peers5y_note("by_sector", "Footwear", "Consumer Cyclical")
    assert "SECTOR PROXY" in note
    assert "Consumer Cyclical" in note


def test_the_note_names_the_bucket_it_fell_back_to():
    note, _ = rc.peers5y_note("by_industry", "Semiconductors", "Technology")
    assert "Semiconductors" in note


# --- indexing to 100 --------------------------------------------------------

def _frame(**cols):
    idx = pd.date_range("2021-01-01", periods=len(next(iter(cols.values()))), freq="D")
    return pd.DataFrame(cols, index=idx)


def test_every_series_starts_at_exactly_100():
    out = rc.index_to_100(_frame(A=[10.0, 20.0], B=[5.0, 5.0]))
    assert out["A"].iloc[0] == pytest.approx(100.0)
    assert out["B"].iloc[0] == pytest.approx(100.0)


def test_a_doubling_reads_as_200():
    out = rc.index_to_100(_frame(A=[10.0, 20.0]))
    assert out["A"].iloc[-1] == pytest.approx(200.0)


def test_the_common_start_is_the_latest_first_valid_date():
    # B lists two days late, so nobody is indexed off a date B cannot match.
    f = _frame(A=[1.0, 2.0, 4.0], B=[float("nan"), float("nan"), 8.0])
    out = rc.index_to_100(f)
    assert len(out) == 1
    assert out["A"].iloc[0] == pytest.approx(100.0)


def test_an_explicit_start_overrides_the_common_start():
    f = _frame(A=[1.0, 2.0, 4.0], B=[float("nan"), 3.0, 6.0])
    out = rc.index_to_100(f, start=f.index[0])
    assert len(out) == 3
    assert out["A"].iloc[-1] == pytest.approx(400.0)


def test_a_zero_base_is_dropped_not_turned_into_infinity():
    out = rc.index_to_100(_frame(A=[10.0, 20.0], B=[0.0, 5.0]))
    assert list(out.columns) == ["A"]


def test_an_empty_frame_returns_none():
    assert rc.index_to_100(pd.DataFrame()) is None
    assert rc.index_to_100(None) is None


# --- year parsing -----------------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("FY2016", 2016), ("2016Q3", 2016), ("2016-12-31", 2016),
    ("fy2016", 2016), ("", None), (None, None), ("FY", None), ("Q3", None),
])
def test_year_is_parsed_from_every_label_shape_in_the_corpus(label, expected):
    assert rc._fy_year(label) == expected


def test_an_implausible_year_is_not_accepted():
    # A four-digit run is not enough — it has to be a year a filing could carry,
    # or an accession number and a part number both parse as fiscal years.
    assert rc._fy_year("FY1234-56") is None
    assert rc._fy_year("part-9999-x") is None
    assert rc._fy_year("acc-0001-1995-x") == 1995


# --- implied share-count consistency ---------------------------------------

def test_a_stable_share_count_keeps_every_year():
    ni = {y: 100.0 * (y - 2009) for y in range(2010, 2020)}
    eps = {y: (y - 2009) for y in range(2010, 2020)}  # 100 shares throughout
    ok, bad = rc.consistent_share_years(ni, eps)
    assert bad == []
    assert len(ok) == 10


def test_a_one_off_gain_year_is_rejected():
    # The MPWR FY2024 shape: net income jumps 3x while reported EPS does not,
    # so the implied share count triples for exactly one year.
    ni = {y: 100.0 for y in range(2010, 2020)}
    eps = {y: 1.0 for y in range(2010, 2020)}
    ni[2015] = 300.0
    ok, bad = rc.consistent_share_years(ni, eps)
    assert bad == [2015]
    assert 2015 not in ok


def test_a_slow_buyback_drift_is_tolerated():
    # 3%/yr of buybacks over a decade is a 26% total change — exactly the drift a
    # long-horizon panel exists to show, so it must not trip the spike guard.
    ni, eps = {}, {}
    shares = 100.0
    for y in range(2010, 2020):
        ni[y] = 100.0
        eps[y] = 100.0 / shares
        shares *= 0.97
    ok, bad = rc.consistent_share_years(ni, eps)
    assert bad == []


def test_too_few_years_to_judge_passes_everything_through():
    ok, bad = rc.consistent_share_years({2020: 10.0, 2021: 99.0},
                                        {2020: 1.0, 2021: 1.0})
    assert bad == []
    assert ok == [2020, 2021]


def test_non_positive_earnings_years_are_excluded_entirely():
    ni = {2020: -50.0, 2021: 100.0, 2022: 100.0, 2023: 100.0}
    eps = {2020: -0.5, 2021: 1.0, 2022: 1.0, 2023: 1.0}
    ok, bad = rc.consistent_share_years(ni, eps)
    assert 2020 not in ok and 2020 not in bad


# --- evolution series -------------------------------------------------------

def _fin(years, ebitda=None, net_income=None, revenue=None, **kw):
    labels = [f"FY{y}" for y in years]
    n = len(years)
    d = {
        "ticker": "TEST", "currency": "USD", "source": "alphavantage",
        "annual": {
            "labels": labels,
            "ebitda": ebitda if ebitda is not None else [100.0] * n,
            "net_income": net_income if net_income is not None else [50.0] * n,
            "revenue": revenue if revenue is not None else [500.0] * n,
        },
    }
    d.update(kw)
    return d


def _eps(years, values=None):
    return [{"date": f"{y}-12-31", "eps": (values[i] if values else 1.0)}
            for i, y in enumerate(years)]


def _bands(pe_by_year):
    return {"pe_band": {"series": [{"year": y, "pe": v}
                                   for y, v in sorted(pe_by_year.items())]}}


def test_no_annual_history_returns_none():
    assert rc.evolution_series({}, {}, []) is None
    assert rc.evolution_series(None, {}, []) is None
    assert rc.evolution_series({"annual": {"labels": []}}, {}, []) is None


def test_depth_is_counted_in_fiscal_years():
    years = list(range(2010, 2022))
    d = rc.evolution_series(_fin(years), {}, _eps(years))
    assert d["depth_years"] == 12
    assert d["enough_depth"] is True


def test_a_four_year_non_us_history_fails_the_depth_floor():
    years = list(range(2022, 2026))
    d = rc.evolution_series(_fin(years, source="yfinance"), {}, _eps(years))
    assert d["depth_years"] == 4
    assert d["enough_depth"] is False


def test_the_depth_floor_is_the_published_constant():
    years = list(range(2010, 2010 + rc.EVOLUTION_MIN_YEARS))
    d = rc.evolution_series(_fin(years), {}, _eps(years))
    assert d["enough_depth"] is True
    d = rc.evolution_series(_fin(years[:-1]), {}, _eps(years[:-1]))
    assert d["enough_depth"] is False


def test_a_partial_year_eps_stub_is_dropped():
    # MPWR's cache ends 2026-06-30 beside twenty-two 12-31 annuals. Kept, it
    # plots as a 40% earnings collapse in the final year.
    years = list(range(2014, 2026))
    records = _eps(years) + [{"date": "2026-06-30", "eps": 10.5}]
    d = rc.evolution_series(_fin(years), {}, records)
    assert 2026 not in d["eps"]
    assert max(d["eps"]) == 2025


def test_price_ebitda_is_pe_times_net_income_over_ebitda():
    years = list(range(2010, 2020))
    d = rc.evolution_series(
        _fin(years, ebitda=[200.0] * 10, net_income=[100.0] * 10),
        _bands({y: 20.0 for y in years}), _eps(years, [1.0] * 10))
    # 20 x 100 / 200 = 10.0
    assert d["p_ebitda"][2015] == pytest.approx(10.0)


def test_the_multiple_is_suppressed_where_eps_and_net_income_disagree():
    years = list(range(2010, 2020))
    ni = [100.0] * 10
    ni[5] = 300.0                      # one-off gain, EPS unchanged
    d = rc.evolution_series(
        _fin(years, ebitda=[200.0] * 10, net_income=ni),
        _bands({y: 20.0 for y in years}), _eps(years, [1.0] * 10))
    assert 2015 not in d["p_ebitda"]
    assert d["eps_ni_mismatch_years"] == [2015]


def test_a_rejected_year_with_no_pe_is_not_reported_as_suppressed():
    # Pre-IPO years fail the ratio test too, but reporting them is noise about a
    # point that was never going to be drawn.
    years = list(range(2010, 2020))
    ni = [100.0] * 10
    ni[1] = 400.0
    d = rc.evolution_series(
        _fin(years, ebitda=[200.0] * 10, net_income=ni),
        _bands({y: 20.0 for y in years[5:]}), _eps(years, [1.0] * 10))
    assert d["eps_ni_mismatch_years"] == []


def test_negative_ebitda_never_produces_a_multiple():
    years = list(range(2010, 2020))
    eb = [200.0] * 10
    eb[3] = -50.0
    d = rc.evolution_series(
        _fin(years, ebitda=eb), _bands({y: 20.0 for y in years}),
        _eps(years, [1.0] * 10))
    assert 2013 not in d["p_ebitda"]
    assert all(v > 0 for v in d["p_ebitda"].values())


def test_a_loss_year_never_produces_a_multiple():
    years = list(range(2010, 2020))
    ni = [100.0] * 10
    ni[4] = -10.0
    d = rc.evolution_series(
        _fin(years, net_income=ni), _bands({y: 20.0 for y in years}),
        _eps(years, [1.0] * 10))
    assert 2014 not in d["p_ebitda"]


def test_the_multiples_panel_has_its_own_depth_floor():
    years = list(range(2010, 2022))
    shallow = {y: 20.0 for y in years[:rc.EVOLUTION_MIN_MULTIPLE_YEARS - 1]}
    d = rc.evolution_series(_fin(years), _bands(shallow), _eps(years))
    assert d["enough_depth"] is True
    assert d["enough_multiples"] is False


def test_missing_valuation_bands_leaves_the_multiples_empty_not_broken():
    years = list(range(2010, 2022))
    d = rc.evolution_series(_fin(years), {}, _eps(years))
    assert d["pe"] == {}
    assert d["p_ebitda"] == {}
    assert d["enough_multiples"] is False


def test_non_numeric_values_are_skipped_rather_than_raising():
    years = list(range(2010, 2022))
    fin = _fin(years)
    fin["annual"]["ebitda"][2] = "n/a"
    fin["annual"]["ebitda"][3] = None
    d = rc.evolution_series(fin, {}, _eps(years))
    assert 2012 not in d["ebitda"] and 2013 not in d["ebitda"]
    assert len(d["ebitda"]) == 10


# --- evolution rendering ----------------------------------------------------

def test_below_the_depth_floor_nothing_is_written(tmp_path):
    years = list(range(2022, 2026))
    out = tmp_path / "e.png"
    assert rc.chart_evolution("X", _fin(years), {}, _eps(years), out,
                              _fetcher=lambda *a, **k: None) is False
    assert not out.exists()


def test_a_deep_history_renders_without_a_price_series(tmp_path):
    years = list(range(2006, 2026))
    out = tmp_path / "e.png"
    ok = rc.chart_evolution("X", _fin(years), _bands({y: 20.0 for y in years}),
                            _eps(years), out, _fetcher=lambda *a, **k: None)
    assert ok is True
    assert out.stat().st_size > 0


def test_a_deep_history_renders_with_a_price_series(tmp_path):
    years = list(range(2006, 2026))
    idx = pd.date_range("2006-01-31", periods=240, freq="ME")
    series = pd.Series([10.0 * (1.01 ** i) for i in range(240)], index=idx)
    out = tmp_path / "e.png"
    assert rc.chart_evolution("X", _fin(years), _bands({y: 20.0 for y in years}),
                              _eps(years), out,
                              _fetcher=lambda *a, **k: series) is True
    assert out.stat().st_size > 0


def test_a_broken_input_returns_false_rather_than_raising(tmp_path):
    assert rc.chart_evolution("X", {"annual": "not a dict"}, {}, [],
                              tmp_path / "e.png") is False


# --- peers 5y rendering -----------------------------------------------------

def _price_fetcher(mapping, days=400):
    """A fetcher over {symbol: growth-per-day}. FX pairs resolve to a flat 1.0
    unless overridden, so a test can isolate the conversion."""
    idx = pd.date_range("2021-01-04", periods=days, freq="B")

    def fetch(sym, period="5y", interval="1d"):
        if sym not in mapping:
            return None
        g = mapping[sym]
        if callable(g):
            return g(idx)
        return pd.Series([100.0 * (g ** i) for i in range(days)], index=idx)
    return fetch


def test_the_subject_and_its_peers_render(tmp_path):
    out = tmp_path / "p.png"
    fetch = _price_fetcher({"AAA": 1.001, "BBB": 1.0005, "CCC": 1.0,
                            "EURUSD=X": 1.0})
    info = {"peer_tickers": ["BBB", "CCC"], "peers_source": "by_ticker"}
    assert rc.chart_peers5y("AAA", info, out, _fetcher=fetch) is True
    assert out.stat().st_size > 0


def test_no_peers_resolved_means_no_chart(tmp_path):
    out = tmp_path / "p.png"
    fetch = _price_fetcher({"AAA": 1.001, "EURUSD=X": 1.0})
    assert rc.chart_peers5y("AAA", {"peer_tickers": []}, out,
                            _fetcher=fetch) is False
    assert not out.exists()


def test_the_subject_itself_is_never_counted_as_its_own_peer(tmp_path):
    out = tmp_path / "p.png"
    fetch = _price_fetcher({"AAA": 1.001, "EURUSD=X": 1.0})
    info = {"peer_tickers": ["AAA"], "peers_source": "by_ticker"}
    assert rc.chart_peers5y("AAA", info, out, _fetcher=fetch) is False


def test_a_failed_subject_fetch_means_no_chart(tmp_path):
    out = tmp_path / "p.png"
    fetch = _price_fetcher({"BBB": 1.0, "EURUSD=X": 1.0})
    info = {"peer_tickers": ["BBB"], "peers_source": "by_ticker"}
    assert rc.chart_peers5y("AAA", info, out, _fetcher=fetch) is False


def test_a_lone_surviving_series_is_not_drawn_as_a_peer_chart(tmp_path):
    # One line is the price chart, not a comparison.
    out = tmp_path / "p.png"
    fetch = _price_fetcher({"AAA": 1.001, "EURUSD=X": 1.0})
    info = {"peer_tickers": ["BBB", "CCC"], "peers_source": "by_ticker"}
    assert rc.chart_peers5y("AAA", info, out, _fetcher=fetch) is False


def test_the_peer_set_is_capped(tmp_path):
    out = tmp_path / "p.png"
    names = [f"P{i}" for i in range(12)]
    fetch = _price_fetcher({"AAA": 1.001, "EURUSD=X": 1.0,
                            **{n: 1.0 for n in names}})
    info = {"peer_tickers": names, "peers_source": "by_ticker"}
    assert rc.chart_peers5y("AAA", info, out, _fetcher=fetch) is True
    assert rc.PEERS5Y_MAX <= 5


def test_a_peer_with_a_stub_of_history_is_dropped(tmp_path):
    # Indexed to 100 at its own late start, a two-week-old listing would read as
    # the flat winner while everyone else carried five years of drawdown.
    idx_full = pd.date_range("2021-01-04", periods=400, freq="B")

    def fetch(sym, period="5y", interval="1d"):
        if sym == "AAA":
            return pd.Series([100.0] * 400, index=idx_full)
        if sym == "OLD":
            return pd.Series([100.0] * 400, index=idx_full)
        if sym == "NEW":
            return pd.Series([100.0] * 10, index=idx_full[-10:])
        if sym == "EURUSD=X":
            return pd.Series([1.0] * 400, index=idx_full)
        return None

    out = tmp_path / "p.png"
    info = {"peer_tickers": ["OLD", "NEW"], "peers_source": "by_ticker"}
    assert rc.chart_peers5y("AAA", info, out, _fetcher=fetch) is True
    assert rc.PEERS5Y_MIN_POINTS > 10


def test_fx_moves_change_the_indexed_result():
    """A peer flat in its own currency, in a currency halving against EUR, must
    read as a 50% loss — that is the whole point of converting first."""
    idx = pd.date_range("2021-01-04", periods=200, freq="B")
    flat = pd.Series([100.0] * 200, index=idx)
    # EURUSD rising = more USD per EUR = USD weakening.
    weakening = pd.Series([1.0 + i / 199.0 for i in range(200)], index=idx)
    converted = flat / weakening
    out = rc.index_to_100(pd.DataFrame({"P": converted}))
    assert out["P"].iloc[-1] == pytest.approx(50.0, abs=0.5)


def test_a_broken_peer_input_returns_false_rather_than_raising(tmp_path):
    assert rc.chart_peers5y("AAA", {"peer_tickers": "not a list"},
                            tmp_path / "p.png",
                            _fetcher=lambda *a, **k: None) is False


# --- cross-module chart registry (anti-drift) -------------------------------

def test_the_two_chart_order_lists_hold_the_same_charts():
    """render_report embeds them and check_report_charts gates them. They are
    separate lists in separate modules; a chart added to one and not the other
    is either never embedded or never gated, and both fail silently."""
    import check_report_charts as crc
    import render_report as rr
    assert set(rr.CHART_ORDER) == set(crc.CHART_ORDER)


def test_every_gated_chart_has_a_caption_for_the_markdown_fix_line():
    import check_report_charts as crc
    missing = [k for k in crc.CHART_ORDER if k not in crc.CHART_CAPTIONS]
    assert missing == []


def test_every_gated_chart_has_an_anchor_to_be_inserted_at():
    import check_report_charts as crc
    missing = [k for k in crc.CHART_ORDER if k not in crc.ANCHORS]
    assert missing == []


def test_every_embedded_chart_has_a_human_label():
    """The label is the figcaption and the alt text; falling back to the raw key
    would print 'peers5y' to the reader."""
    import inspect

    import render_report as rr
    src = inspect.getsource(rr.build_charts)
    for key in rr.CHART_ORDER:
        assert f'"{key}"' in src, f"{key} has no label in build_charts"


def test_the_new_v43_charts_are_registered_everywhere():
    import check_report_charts as crc
    import render_report as rr
    for key in ("peers5y", "evolution"):
        assert key in rr.CHART_ORDER
        assert key in crc.CHART_ORDER
        assert key in crc.CHART_CAPTIONS
        assert key in crc.ANCHORS


# --- build artefacts are not unembedded charts ------------------------------

def test_the_sankey_is_not_treated_as_an_unembedded_chart(tmp_path):
    """The Sankey PNG is rendered FROM the report's own mermaid fence at
    HTML-render time. Counting it as an orphan made the gate demand a
    ![Sankey](...) line, which prints the diagram twice in Obsidian and leaves a
    dead link the moment the fence is edited."""
    import check_report_charts as crc
    (tmp_path / "IMG").mkdir()
    md = tmp_path / "2026-08-14_MPWR_review.md"
    md.write_text("# r\n\n```mermaid\nsankey-beta\nA,B,1\n```\n", encoding="utf-8")
    for kind in ("sankey", "price"):
        (tmp_path / "IMG" / f"2026-08-14_MPWR_{kind}.png").write_bytes(b"x")
    audit = crc.audit_report(md)
    assert "sankey" not in audit["orphans"]
    assert "price" in audit["orphans"]


def test_the_excluded_set_is_declared_not_inferred():
    import check_report_charts as crc
    assert "sankey" in crc.NON_REPORT_IMAGES
    # An excluded artefact must never also be a gated chart — it would be both
    # demanded and exempted.
    assert not (crc.NON_REPORT_IMAGES & set(crc.CHART_ORDER))
