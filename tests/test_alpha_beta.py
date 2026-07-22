"""
Unit tests for v4 Phase E — alpha_beta.py.

Pure-function only (stdlib): no yfinance, no pandas, no network — so they run
under the lean uv venv. Live α/β + portfolio-fit are spot-checked in the
acceptance gate (§13-E), not here. Covers β=cov/var with a known slope, Jensen α,
CAPM expected return, the price-CAGR ladder (depth-gated), the Lynch prior map,
FX-free portfolio value series, benchmark resolution and the fit verdict.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import alpha_beta as ab  # noqa: E402  (module top is stdlib + markets only)


# ------------------------- benchmark_for -------------------------
def test_benchmark_for_dotted_suffix_and_default():
    m = {".AS": "^AEX", ".L": "^FTSE", ".TW": "^TWII"}
    assert ab.benchmark_for("INGA.AS", m, "^GSPC") == "^AEX"
    assert ab.benchmark_for("SHEL.L", m, "^GSPC") == "^FTSE"
    assert ab.benchmark_for("AAPL", m, "^GSPC") == "^GSPC"  # US → default


# ------------------------- returns / align -------------------------
def test_returns_by_ym_and_drop_nonpositive():
    r = ab.returns_by_ym({"2020-01": 100, "2020-02": 110, "2020-03": 99})
    assert round(r["2020-02"], 4) == 0.1
    assert round(r["2020-03"], 4) == -0.1
    # a zero close nulls the crossing periods
    r2 = ab.returns_by_ym({"2020-01": 100, "2020-02": 0, "2020-03": 120})
    assert "2020-02" not in r2 and "2020-03" not in r2


def test_align_by_key_common_only():
    a = {"x": 1, "y": 2, "z": 3}
    b = {"y": 20, "z": 30, "w": 40}
    va, vb = ab.align_by_key(a, b)
    assert va == [2, 3] and vb == [20, 30]  # sorted common keys y,z


# ------------------------- regression -------------------------
def test_regress_recovers_known_beta_and_alpha():
    # r_ticker = 1.5 * r_bench + 0.001 (perfect fit) → β=1.5, α_month=0.001, r2=1
    bench = [0.01, -0.02, 0.03, -0.01, 0.02, 0.0,
             0.015, -0.005, 0.025, -0.015, 0.005, 0.01] * 3  # 36 months
    tick = [1.5 * x + 0.001 for x in bench]
    reg = ab.regress_alpha_beta(tick, bench, rf_monthly=0.0)
    assert reg["valid"] is True and reg["n"] == 36
    assert reg["beta"] == 1.5
    assert reg["r2"] == 1.0
    assert round(reg["alpha_monthly"], 6) == 0.001
    assert round(reg["alpha_ann"], 4) == round((1.001) ** 12 - 1, 4)


def test_regress_degrades_below_min_months():
    reg = ab.regress_alpha_beta([0.01] * 10, [0.01] * 10, 0.0)
    assert reg["valid"] is False and "months" in reg["reason"]


def test_regress_zero_variance_benchmark():
    reg = ab.regress_alpha_beta([0.01] * 30, [0.02] * 30, 0.0)
    assert reg["valid"] is False and "variance" in reg["reason"]


# ------------------------- annualization / CAPM -------------------------
def test_annualize_from_returns_geometric():
    # 12 months of +1% → (1.01)^12 - 1
    assert ab.annualize_from_returns([0.01] * 12) == round(1.01 ** 12 - 1, 4)
    assert ab.annualize_from_returns([]) is None


def test_capm_expected_return_formula():
    # rf 4%, β 1.2, bench 10% → 0.04 + 1.2*(0.10-0.04) = 0.112
    assert ab.capm_expected_return(0.04, 1.2, 0.10) == 0.112
    assert ab.capm_expected_return(0.04, None, 0.10) is None


# ------------------------- price CAGR ladder -------------------------
def _monthly_10pct(years):
    n = years * 12 + 1
    f = 1.1 ** (1.0 / 12.0)
    closes = {}
    y, m = 2010, 1
    for i in range(n):
        closes[f"{y:04d}-{m:02d}"] = 100.0 * (f ** i)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return closes


def test_price_cagr_ladder_populates_10_15y_at_depth():
    l = ab.price_cagr_ladder(_monthly_10pct(15))
    for w in ("1y", "3y", "5y", "10y", "15y"):
        assert round(l[w], 3) == 0.1
    assert l["depth_years"] == 15.0
    assert "total-return" in l["basis"]


def test_price_cagr_ladder_shallow_nulls_deep_rungs():
    l = ab.price_cagr_ladder(_monthly_10pct(2))  # 25 months
    assert round(l["1y"], 3) == 0.1
    assert l["5y"] is None and l["10y"] is None and l["15y"] is None


# ------------------------- Lynch prior -------------------------
def test_lynch_prior_all_categories():
    for cat in ("fast_grower", "stalwart", "slow_grower", "cyclical", "unknown"):
        p = ab.lynch_prior(cat)
        assert p["category"] == cat and p["expected_return_band"] and p["note"]


def test_lynch_prior_unknown_fallback():
    assert ab.lynch_prior("nonsense_category")["category"] == "unknown"
    assert ab.lynch_prior(None)["category"] == "unknown"


# ------------------------- fit verdict -------------------------
def test_fit_verdict_directions():
    assert ab.fit_verdict(1.4, 1.0, 0.1) == "raises"
    assert ab.fit_verdict(0.6, 1.0, 0.1) == "dilutes"
    assert ab.fit_verdict(1.05, 1.0, 0.1) == "neutral"
    assert ab.fit_verdict(None, 1.0, 0.1) == "n/a"


# ------------------------- portfolio value series -------------------------
def test_portfolio_value_series_common_months_only():
    closes = {
        "A": {"2020-01": 10.0, "2020-02": 11.0},
        "B": {"2020-01": 5.0, "2020-02": 6.0, "2020-03": 7.0},
    }
    shares = {"A": 2.0, "B": 3.0}
    v = ab.portfolio_value_series(closes, shares)
    assert sorted(v) == ["2020-01", "2020-02"]  # 2020-03 dropped (A absent)
    assert v["2020-01"] == 2 * 10 + 3 * 5   # 35
    assert v["2020-02"] == 2 * 11 + 3 * 6   # 40


def test_portfolio_value_series_empty():
    assert ab.portfolio_value_series({}, {}) == {}
