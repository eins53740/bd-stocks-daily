"""
Tests for the browser chart renderer (option C).

The property that matters here is NOT that Chromium produces a pretty PNG — it is
that the daily job cannot regress when Chromium is unavailable. Every entry point
must return False rather than raise, so render_charts falls back to matplotlib.
These tests therefore concentrate on the failure and disable paths, plus the pure
helpers. The one test that really launches a browser is opt-in via BD_TEST_BROWSER=1
so the suite stays fast and works on a machine with no Chromium.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import chart_browser as cb  # noqa: E402


FIN = {
    "ticker": "ACN", "currency": "USD", "source": "test", "quarters_available": 8,
    "series": {
        "labels": [f"202{y}Q{q}" for y in (3, 4) for q in (1, 2, 3, 4)],
        "ebitda": [1e9 + i * 1e8 for i in range(8)],
        "fcf": [0.9e9 + i * 1e8 for i in range(8)],
        "revenue": [5e9 + i * 1e8 for i in range(8)],
    },
    "forecast": {"labels": ["2025Q1", "2025Q2"], "ebitda": [2e9, 2.1e9],
                 "fcf": [1.9e9, 2.0e9], "basis": "consensus_revenue_x_trailing_margin"},
}

RELPERF = {
    "ticker": "ACN", "subtitle": "s",
    "series": [{"key": "ticker", "sym": "ACN", "points": [[1_700_000_000_000, 100.0],
                                                          [1_800_000_000_000, 120.0]]}],
    "notes": ["note"],
}


# --- the kill switch --------------------------------------------------------

def test_disabled_by_env_returns_false_without_touching_chromium(tmp_path, monkeypatch):
    monkeypatch.setenv("BD_CHARTS_BROWSER", "0")
    # If this tried to launch a browser the test would be slow; assert no file too.
    out = tmp_path / "a.png"
    assert cb.render_ebitda_fcf(FIN, out) is False
    assert cb.render_relperf(RELPERF, out) is False
    assert not out.exists()


@pytest.mark.parametrize("val", ["0", "false", "no", "FALSE", " no "])
def test_enabled_recognises_the_off_spellings(monkeypatch, val):
    monkeypatch.setenv("BD_CHARTS_BROWSER", val)
    assert cb.enabled() is False


@pytest.mark.parametrize("val", ["1", "yes", "true", ""])
def test_enabled_defaults_to_on(monkeypatch, val):
    monkeypatch.setenv("BD_CHARTS_BROWSER", val)
    assert cb.enabled() is True


def test_enabled_when_env_is_absent(monkeypatch):
    monkeypatch.delenv("BD_CHARTS_BROWSER", raising=False)
    assert cb.enabled() is True


# --- degradation, never exceptions ------------------------------------------

def test_a_broken_screenshot_returns_false_not_an_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("BD_CHARTS_BROWSER", "1")
    monkeypatch.setattr(cb, "_screenshot",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no chromium")))
    assert cb.render_ebitda_fcf(FIN, tmp_path / "a.png") is False
    assert cb.render_relperf(RELPERF, tmp_path / "b.png") is False


def test_screenshot_swallows_a_launch_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "_shell", lambda *a, **k: "<html></html>")
    import builtins
    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name.startswith("playwright"):
            raise ImportError("playwright missing")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    assert cb._screenshot("<html></html>", tmp_path / "x.png", 100, 100) is False


def test_screenshot_cleans_up_its_temp_html(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "_shell", lambda *a, **k: "<html></html>")
    out = tmp_path / "x.png"
    cb._screenshot("<html></html>", out, 50, 50)  # will fail or succeed; either way:
    assert not out.with_suffix(".tmp.html").exists()


@pytest.mark.parametrize("bad", [None, {}, {"series": {}}, {"series": {"labels": []}}])
def test_empty_or_missing_input_returns_false(tmp_path, monkeypatch, bad):
    monkeypatch.setenv("BD_CHARTS_BROWSER", "1")
    assert cb.render_ebitda_fcf(bad, tmp_path / "a.png") is False


def test_relperf_with_no_usable_series_returns_false(tmp_path, monkeypatch):
    monkeypatch.setenv("BD_CHARTS_BROWSER", "1")
    assert cb.render_relperf({"series": []}, tmp_path / "a.png") is False
    assert cb.render_relperf({"series": [{"key": "ticker", "points": []}]},
                             tmp_path / "a.png") is False


def test_a_ragged_forecast_block_is_dropped_not_fatal(tmp_path, monkeypatch):
    """Guard against a half-written cache: labels and values out of step must not
    index-error, they must simply render without a forecast."""
    monkeypatch.setenv("BD_CHARTS_BROWSER", "1")
    captured = {}
    def _cap(html, *a, **k):
        captured["html"] = html
        return True

    monkeypatch.setattr(cb, "_screenshot", _cap)
    fin = {**FIN, "forecast": {"labels": ["2025Q1", "2025Q2"], "ebitda": [1e9],
                               "fcf": [1e9, 2e9]}}
    assert cb.render_ebitda_fcf(fin, tmp_path / "a.png") is True
    assert "FORECAST" not in captured["html"]


# --- pure helpers -----------------------------------------------------------

def test_money_scales_and_keeps_a_sign():
    assert cb._money(2.5e9) == "2.5B"
    assert cb._money(-2.5e9) == "-2.5B"
    assert cb._money(3.4e6) == "3M"
    assert cb._money(1.2e12) == "1.2T"
    assert cb._money(950) == "950"


def test_nice_ticks_span_the_range_and_stay_inside_it():
    ticks = cb._nice_ticks(0, 3.9e9)
    assert ticks and all(0 <= t <= 3.9e9 for t in ticks)
    assert ticks == sorted(ticks)


def test_nice_ticks_on_a_degenerate_range():
    assert cb._nice_ticks(5, 5) == [5]
    assert cb._nice_ticks(5, 1) == [1]


def test_negative_fcf_renders_a_zero_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("BD_CHARTS_BROWSER", "1")
    captured = {}
    def _cap(html, *a, **k):
        captured["html"] = html
        return True

    monkeypatch.setattr(cb, "_screenshot", _cap)
    fin = {**FIN, "series": {**FIN["series"], "fcf": [-1e9] * 8}, "forecast": {}}
    assert cb.render_ebitda_fcf(fin, tmp_path / "a.png") is True
    assert 'class="zero"' in captured["html"], "a series crossing zero needs the baseline"


def test_html_is_escaped_enough_to_stay_well_formed(tmp_path, monkeypatch):
    monkeypatch.setenv("BD_CHARTS_BROWSER", "1")
    captured = {}
    def _cap(html, *a, **k):
        captured["html"] = html
        return True

    monkeypatch.setattr(cb, "_screenshot", _cap)
    cb.render_ebitda_fcf(FIN, tmp_path / "a.png")
    html = captured["html"]
    assert html.count("<svg") == html.count("</svg>") == 1
    assert "&amp;" in html, "the title's ampersand must be an entity"


# --- the real thing, opt-in ------------------------------------------------

@pytest.mark.skipif(os.environ.get("BD_TEST_BROWSER") != "1",
                    reason="set BD_TEST_BROWSER=1 to exercise a real Chromium launch")
def test_real_chromium_writes_a_png(tmp_path, monkeypatch):
    monkeypatch.setenv("BD_CHARTS_BROWSER", "1")
    out = tmp_path / "real.png"
    assert cb.render_ebitda_fcf(FIN, out) is True
    assert out.stat().st_size > 5000
