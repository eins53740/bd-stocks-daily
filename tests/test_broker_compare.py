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

import pytest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import broker_compare as bc  # noqa: E402
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
def test_yaml_parses_every_broker_including_the_unverified_ones():
    data = load_brokers_yaml(YAML_PATH)
    brokers = data["brokers"]
    # v4.3 wave 4.5 added Bankinter, eToro and Trading 212 as schema-only entrants.
    # Trading 212 was verified against its own help centre on 2026-08-16 and now carries
    # real tariffs; the other two stay excluded from every cost matrix by
    # `verified: false` — see test_unverified_brokers_never_enter_a_cost_matrix.
    assert len(brokers) == 12
    assert sum(1 for b in brokers.values() if b.get("verified") is False) == 2
    expected = {"IBKR", "DEGIRO", "TradeRepublic", "Robinhood", "Revolut",
                "XTB", "BancoBIG", "BancoCTT", "BancoBEST",
                "Bankinter", "eToro", "Trading212"}
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
    assert bundle["n_brokers"] == 12
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


# ===================================================================
# v4.3 wave 4.5 — the new brokers, markets and structural dimensions
# ===================================================================
class TestWave45:
    @pytest.fixture(scope="class")
    def bundle(self):
        return bc.build_bundle(load_brokers_yaml(YAML_PATH))

    def test_unverified_brokers_never_enter_a_cost_matrix(self, bundle):
        """A broker with unconfirmed tariffs and an empty fee map would win every
        'cheapest' row on numbers nobody checked — the worst failure available in a file
        used to decide where to place real money."""
        unverified = {u["id"] for u in bundle["unverified"]}
        assert unverified == {"Bankinter", "eToro"}
        for market in bundle["markets"]:
            assert not (unverified & {r["broker"] for r in market["rows"]})

    def test_trading212_earned_its_way_into_the_matrices(self, bundle):
        """Verified 2026-08-16 against Trading 212's own help centre — commission Free,
        FX 0.15%, custody Free, stated verbatim. The gate is the SOURCE, not the age of
        the entry: it moved because a primary page was read, and Bankinter did not
        because its tariff PDF refuses automated fetch."""
        t212 = bundle["broker_profiles"]["Trading212"]
        assert t212["verified"] is True
        assert t212["fx_fee_pct"] == 0.15
        appearing = {m["key"] for m in bundle["markets"]
                     if "Trading212" in {r["broker"] for r in m["rows"]}}
        assert {"US", "PT", "NL", "FR", "DE", "UK"} <= appearing

    def test_trading212_is_absent_from_asia_rather_than_free_there(self, bundle):
        """It offers no Asian venue. An empty `markets` entry would have read as zero
        cost and won every Asian row outright."""
        for mk in ("TW", "HK", "JP", "CN_SZ"):
            market = next(m for m in bundle["markets"] if m["key"] == mk)
            assert "Trading212" not in {r["broker"] for r in market["rows"]}

    def test_a_zero_commission_broker_still_carries_its_real_cost(self, bundle):
        """Zero commission is not zero cost: on a foreign-currency trade the 0.15% FX
        conversion IS the price, and a comparator that reported 0.00 would be wrong in
        the one direction that matters."""
        us = next(m for m in bundle["markets"] if m["key"] == "US")
        row = next(r for r in us["rows"] if r["broker"] == "Trading212")
        assert row["fx_applies"] is True
        assert row["small"] > 0 and row["large"] > 0, row

    def test_a_zero_commission_broker_really_is_free_in_its_own_currency(self, bundle):
        """The mirror of the test above, and the reason the FX number matters: on
        Euronext Lisbon there is no conversion, so the cost genuinely is zero. If both
        rows read the same, the comparator is not modelling FX at all."""
        pt = next(m for m in bundle["markets"] if m["key"] == "PT")
        row = next(r for r in pt["rows"] if r["broker"] == "Trading212")
        assert row["fx_applies"] is False
        assert row["small"] == 0.0 and row["large"] == 0.0, row

    def test_an_unverified_broker_says_what_is_missing(self, bundle):
        for u in bundle["unverified"]:
            assert u["pending_verification"], f"{u['id']} claims nothing to verify"

    def test_the_four_eu_venues_exist_as_market_keys(self, bundle):
        keys = {m["key"] for m in bundle["markets"]}
        assert {"NL", "FR", "DE", "UK"} <= keys

    def test_an_empty_market_is_reported_as_a_gap_not_as_no_brokers(self, bundle):
        for market in bundle["markets"]:
            if market["n_brokers"] == 0:
                assert market["gap_note"] and "verified tariff" in market["gap_note"]
            else:
                assert market["gap_note"] is None

    def test_structural_fields_are_reported_for_every_broker(self, bundle):
        for bid, prof in bundle["broker_profiles"].items():
            for field in bc.STRUCTURAL_FIELDS:
                assert field in prof, f"{bid} missing {field}"

    def test_cash_protection_distinguishes_a_deposit_from_client_money(self, bundle):
        """The EUR 100k question turns on WHICH mechanism holds the cash, and the two
        differ sharply between a bank and a broker."""
        bank = bundle["broker_profiles"]["Bankinter"]["cash_protection_100k"]
        broker = bundle["broker_profiles"]["eToro"]["cash_protection_100k"]
        assert bank["protected"] is True and bank["mechanism"] == "deposit guarantee"
        assert broker["protected"] is False
        assert "not a bank deposit" in broker["note"].lower()

    def test_investor_compensation_names_its_scheme(self, bundle):
        for bid in ("Bankinter", "eToro", "Trading212"):
            ic = bundle["broker_profiles"][bid]["investor_compensation"]
            assert ic["scheme"] and ic["cover_eur"] and ic["as_of"]

    def test_the_requested_trade_sizes_are_declared(self):
        assert bc.TRADE_SIZES_EUR == [500.0, 1500.0, 2000.0]

    def test_the_bundle_explains_the_structural_fields(self, bundle):
        assert "deposit guarantee" in bundle["structural_note"]
        assert "not tariffs" in bundle["structural_note"]
