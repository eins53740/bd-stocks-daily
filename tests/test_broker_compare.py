"""
Phase-8 unit tests for the broker cost comparator.

All pure-function, network-free. Exercises:
  * leg_cost() / round_trip_cost() — commission min/cap + flat + FX math on
    known inputs (hand-computed expected values).
  * fx_applies()                   — base-vs-market currency.
  * brokers_for_market()           — market-exclusion logic (a PT-only broker
    must NOT appear in a Taiwan listing).
  * recommend()                    — small-vs-large recommendation flip.
  * load_brokers_yaml()            — the real brokers.yaml parses + the curated
    exclusions hold (Robinhood US-only; Banco* absent from Asia).
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from broker_compare import (  # noqa: E402
    MARKET_ORDER,
    brokers_for_market,
    build_bundle,
    cost_matrix_for_market,
    fx_applies,
    leg_cost,
    load_brokers_yaml,
    recommend,
    round_trip_cost,
)

YAML_PATH = SCRIPTS / "brokers.yaml"


# ----------------------------------------------------------------- leg_cost math
def test_leg_cost_percentage_dominates():
    # 0.10% of 25,000 = 25.00; above the 1.25 min; no flat; no FX.
    mf = {"commission_pct": 0.10, "commission_min": 1.25, "commission_max": None, "flat_fee": 0.0}
    assert leg_cost(25_000, mf, fx_fee_pct=0.0, fx_applies=False) == 25.0


def test_leg_cost_minimum_floors_small_ticket():
    # 0.10% of 1,000 = 1.00 < min 1.25 -> commission floored to 1.25.
    mf = {"commission_pct": 0.10, "commission_min": 1.25, "commission_max": None, "flat_fee": 0.0}
    assert leg_cost(1_000, mf, fx_fee_pct=0.0, fx_applies=False) == 1.25


def test_leg_cost_cap_applies():
    # 1% of 25,000 = 250, capped at 1.00.
    mf = {"commission_pct": 1.0, "commission_min": 1.0, "commission_max": 1.0, "flat_fee": 0.0}
    assert leg_cost(25_000, mf, fx_fee_pct=0.0, fx_applies=False) == 1.0


def test_leg_cost_flat_plus_fx():
    # commission 0 (pct 0, min 0) + flat 1.0 + FX 0.25% of 1,000 = 2.50 -> 3.50.
    mf = {"commission_pct": 0.0, "commission_min": 0.0, "commission_max": 1.0, "flat_fee": 1.0}
    assert leg_cost(1_000, mf, fx_fee_pct=0.25, fx_applies=True) == 3.5


def test_fx_not_applied_when_disabled():
    mf = {"commission_pct": 0.0, "commission_min": 0.0, "commission_max": 1.0, "flat_fee": 1.0}
    # same block, fx_applies False -> just the flat 1.0.
    assert leg_cost(1_000, mf, fx_fee_pct=0.25, fx_applies=False) == 1.0


def test_round_trip_is_two_legs():
    mf = {"commission_pct": 0.0, "commission_min": 2.0, "commission_max": None, "flat_fee": 0.0}
    assert round_trip_cost(1_000, mf, 0.0, False) == 4.0


# ----------------------------------------------------------------- fx_applies
def test_fx_applies_currency_mismatch():
    assert fx_applies("USD", "EUR") is True
    assert fx_applies("EUR", "EUR") is False
    assert fx_applies("eur", "EUR") is False  # case-insensitive


# --------------------------------------------------- market-exclusion logic
def _toy_brokers() -> dict:
    """PT-only broker vs a global broker — to assert exclusion."""
    return {
        "PTOnly": {
            "name": "PT Only Bank", "base_currency": "EUR", "fx_fee_pct": 0.5,
            "markets": {
                "PT": {"commission_pct": 0.30, "commission_min": 6.0, "commission_max": None, "flat_fee": 0.0},
            },
        },
        "Global": {
            "name": "Global Broker", "base_currency": "EUR", "fx_fee_pct": 0.03,
            "markets": {
                "PT": {"commission_pct": 0.05, "commission_min": 1.25, "commission_max": None, "flat_fee": 0.0},
                "TW": {"commission_pct": 0.15, "commission_min": 15.0, "commission_max": None, "flat_fee": 0.0},
            },
        },
    }


def test_market_exclusion_pt_only_absent_from_taiwan():
    b = _toy_brokers()
    tw = brokers_for_market(b, "TW")
    assert "Global" in tw
    assert "PTOnly" not in tw  # the PT-only broker must NOT surface for Taiwan
    pt = brokers_for_market(b, "PT")
    assert set(pt) == {"PTOnly", "Global"}


def test_cost_matrix_excludes_unsupported_broker():
    b = _toy_brokers()
    rows = cost_matrix_for_market(b, "TW", "TWD", 1_000, 25_000)
    ids = {r["broker"] for r in rows}
    assert ids == {"Global"}  # PTOnly excluded


def test_recommend_empty_when_no_broker():
    assert recommend([]) == {}


# --------------------------------------------------- small-vs-large flip
def test_recommendation_flip_small_vs_large():
    """One broker is cheap on tiny tickets (flat fee, low %), another is cheap
    on large tickets (% capped). The small-trader pick and the large-holder
    pick must differ."""
    brokers = {
        # 0.50% no min: small = 0.5%*1000 = 5/leg -> 10.00 (wins small);
        # large = 0.5%*25000 = 125/leg -> 250.00 (loses large).
        "PctCheapSmall": {
            "name": "Pct Cheap Small", "base_currency": "EUR", "fx_fee_pct": 0.0,
            "markets": {"US": {"commission_pct": 0.50, "commission_min": 0.0,
                               "commission_max": None, "flat_fee": 0.0}},
        },
        # EUR 8 flat/leg: small = 16.00 (loses small);
        # large = 16.00 (wins large vs 250).
        "FlatCheapLarge": {
            "name": "Flat Cheap Large", "base_currency": "EUR", "fx_fee_pct": 0.0,
            "markets": {"US": {"commission_pct": 0.0, "commission_min": 0.0,
                               "commission_max": None, "flat_fee": 8.0}},
        },
    }
    rows = cost_matrix_for_market(brokers, "US", "EUR", 1_000, 25_000)
    rec = recommend(rows)
    assert rec["small_frequent_trader"]["broker"] == "PctCheapSmall"
    assert rec["large_buy_and_hold"]["broker"] == "FlatCheapLarge"
    # sanity: they genuinely differ (the flip)
    assert rec["small_frequent_trader"]["broker"] != rec["large_buy_and_hold"]["broker"]


# --------------------------------------------------- real brokers.yaml
def test_yaml_parses_nine_brokers():
    data = load_brokers_yaml(YAML_PATH)
    brokers = data["brokers"]
    assert len(brokers) == 9
    expected = {"IBKR", "DEGIRO", "TradeRepublic", "Robinhood", "Revolut",
                "XTB", "BancoBIG", "BancoCTT", "BancoBEST"}
    assert set(brokers) == expected


def test_robinhood_is_us_only():
    data = load_brokers_yaml(YAML_PATH)
    for mk in MARKET_ORDER:
        applicable = brokers_for_market(data["brokers"], mk)
        if mk == "US":
            assert "Robinhood" in applicable
        else:
            assert "Robinhood" not in applicable, f"Robinhood should not trade {mk}"


def test_banco_brokers_absent_from_asia():
    data = load_brokers_yaml(YAML_PATH)
    asia = ["TW", "HK", "JP", "CN_SZ"]
    for mk in asia:
        applicable = set(brokers_for_market(data["brokers"], mk))
        assert not (applicable & {"BancoBIG", "BancoCTT", "BancoBEST"}), \
            f"No Banco* broker should trade {mk}; got {applicable}"


def test_build_bundle_shape_and_recommendations():
    data = load_brokers_yaml(YAML_PATH)
    bundle = build_bundle(data)
    assert bundle["n_brokers"] == 9
    assert len(bundle["markets"]) == len(MARKET_ORDER)
    us = next(m for m in bundle["markets"] if m["key"] == "US")
    # every applicable broker on US should have a recommendation
    assert us["recommendation"]
    assert us["recommendation"]["small_frequent_trader"]["broker"]
    # Taiwan: only the global brokers (IBKR) — exclusions held
    tw = next(m for m in bundle["markets"] if m["key"] == "TW")
    tw_ids = {r["broker"] for r in tw["rows"]}
    assert "IBKR" in tw_ids
    assert not (tw_ids & {"Robinhood", "BancoBIG", "BancoCTT", "BancoBEST",
                          "TradeRepublic", "Revolut", "XTB", "DEGIRO"})
