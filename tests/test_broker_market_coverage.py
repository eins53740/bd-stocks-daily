"""Invariants for the 32-market broker reference, and regressions for what it got wrong.

MEASURED 2026-08-17. brokers.yaml was extended from 11 market keys to the 32 regions the
weekly prefilter actually reports coverage for, and re-read from IBKR's published per-country
commission page and DEGIRO's Fee Schedule PDF ("Rates from: 01-01-2026"). That refresh found
three classes of error, each pinned below so it cannot come back:

  1. LOCAL CURRENCY IN A EUR FIELD. `commission_min` is defined by the schema as EUR, and
     IBKR's Asian minimums had been written into it as the local figure: HK 18.0 (HKD 18.00
     = EUR 1.98), JP 8.0 (JPY 80 = EUR 0.43), TW 15.0 (TWD 80 = EUR 2.17). IBKR's Asian cost
     was overstated 9x, 18x and 7x -- enough to hand "cheapest broker" to someone else on
     every Asian name in the pool. This is the bug worth a structural test, not a spot check.

  2. DOUBLE-COUNTED FLAT TARIFFS. leg_cost computes max(min, pct*notional) + flat_fee, so a
     flat fee written into BOTH fields is charged twice. DEGIRO Euronext Lisbon read 3.9 in
     each, billing EUR 7.80 a leg for a EUR 4.90 tariff; Trade Republic read 1.0 in each,
     EUR 2.00 a leg for a EUR 1.00 fee.

  3. UNRESEARCHED READ AS REFUSED. Absence of a market block used to mean "not offered".
     With 32 keys that turns "nobody checked Helsinki" into "IBKR does not trade Helsinki",
     which silently drops a broker from a whole region and leaves no trace of the gap.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import broker_compare as bc  # noqa: E402

DATA = bc.load_brokers_yaml(bc.YAML_PATH)
BROKERS = DATA["brokers"]
META = DATA["markets_meta"]


# --------------------------------------------------------------------------- structure

def test_market_order_and_markets_meta_agree():
    """Two lists of the same 32 keys in two files drift the moment one is edited alone."""
    assert set(bc.MARKET_ORDER) == set(META), (
        f"only in MARKET_ORDER: {sorted(set(bc.MARKET_ORDER) - set(META))} · "
        f"only in markets_meta: {sorted(set(META) - set(bc.MARKET_ORDER))}")
    assert len(bc.MARKET_ORDER) == len(set(bc.MARKET_ORDER)), "duplicate key in MARKET_ORDER"


def test_every_market_key_is_covered_for_every_broker():
    """offered + not_offered + unknown must exhaust the market list, per broker.

    This is the test that makes adding a 33rd market to markets_meta impossible without
    deciding, for each of the 12 brokers, which of the three states it falls in -- rather
    than letting it default to a silent 'not offered'.
    """
    for bid, b in BROKERS.items():
        offered = set((b.get("markets") or {}))
        no = set(bc.market_list(b, "not_offered"))
        unk = set(bc.market_list(b, "coverage_unknown"))
        assert not (offered & no), f"{bid}: {offered & no} both priced and declared absent"
        assert not (offered & unk), f"{bid}: {offered & unk} both priced and unchecked"
        assert not (no & unk), f"{bid}: {no & unk} both declared absent and unchecked"
        missing = set(META) - offered - no - unk
        assert not missing, f"{bid}: {sorted(missing)} in no state at all"


def test_support_matrix_is_tri_state_not_boolean():
    m = bc.support_matrix(BROKERS, bc.MARKET_ORDER)
    assert m["IBKR"]["PT"] is True, "a priced market must be True"
    assert m["IBKR"]["FI"] is None, "Helsinki is unchecked for IBKR -- must be None, not False"
    assert m["DEGIRO"]["TW"] is False, "DEGIRO's schedule is exhaustive: Taiwan is a real no"
    assert m["Robinhood"]["PT"] is False, "Robinhood offers no non-US market: a real no"


def test_degiros_absences_are_sourced_and_ibkrs_are_not_claimed():
    """DEGIRO publishes an exhaustive exchange list, so it is the ONE broker allowed to say
    'no'. IBKR's page simply omits some venues, which is not the same statement."""
    assert bc.market_list(BROKERS["DEGIRO"], "coverage_unknown") == []
    assert bc.market_list(BROKERS["IBKR"], "not_offered") == []
    assert set(bc.market_list(BROKERS["IBKR"], "coverage_unknown")) == {"FI", "ID"}


# ------------------------------------------------------- bug class 1: currency in EUR field

@pytest.mark.parametrize("bid", ["IBKR"])
def test_a_non_eur_minimum_is_the_converted_value_not_the_local_number(bid):
    """The structural guard: where a block records a local minimum and the rate used, the EUR
    field must equal local/rate. Writing HKD 18.00 into a EUR field fails this immediately."""
    checked = 0
    for mk, fee in (BROKERS[bid].get("markets") or {}).items():
        local = fee.get("commission_min_local")
        rate = fee.get("fx_rate_eur_local")
        if not local or not rate:
            continue
        ccy, _, amount = str(local).partition(" ")
        expected = float(amount) / float(rate)
        actual = float(fee.get("commission_min") or 0.0)
        assert abs(actual - expected) < 0.02, (
            f"{bid}/{mk}: commission_min is {actual} EUR but {local} at {rate} is "
            f"{expected:.2f} EUR -- the local figure was written into the EUR field")
        assert ccy != "EUR", f"{bid}/{mk}: commission_min_local should not restate EUR"
        checked += 1
    assert checked >= 15, f"only {checked} non-EUR minimums carried an auditable conversion"


def test_the_three_overstated_asian_minimums_stay_fixed():
    """Spot-check the exact numbers that were wrong, in EUR."""
    mk = BROKERS["IBKR"]["markets"]
    assert mk["HK"]["commission_min"] == pytest.approx(1.98, abs=0.02)   # was 18.0
    assert mk["JP"]["commission_min"] == pytest.approx(0.43, abs=0.02)   # was 8.0
    assert mk["TW"]["commission_min"] == pytest.approx(2.17, abs=0.02)   # was 15.0
    assert mk["TW"]["commission_pct"] == 0.08, "published Taiwan tariff is 0.08%, not 0.15%"


def test_every_eur_denominated_market_omits_the_conversion_fields():
    """A EUR venue with an FX rate attached would mean the generator mislabelled it."""
    for bid, b in BROKERS.items():
        for mk, fee in (b.get("markets") or {}).items():
            if (META.get(mk) or {}).get("currency") == "EUR":
                assert "fx_rate_eur_local" not in fee, f"{bid}/{mk}: EUR venue with an FX rate"


# --------------------------------------------------------- bug class 2: double-counted fees

def test_degiro_round_trip_matches_the_published_tariff():
    """EUR 3.90 commission + EUR 1.00 handling = 4.90 a leg = 9.80 a round trip. It read
    15.60 while the same 3.90 sat in both commission_min and flat_fee."""
    pt = BROKERS["DEGIRO"]["markets"]["PT"]
    assert bc.round_trip_cost(1500.0, pt, 0.0, False) == pytest.approx(9.80)
    ie = BROKERS["DEGIRO"]["markets"]["IE"]  # Euronext Dublin is 2.00, not 3.90
    assert bc.round_trip_cost(1500.0, ie, 0.0, False) == pytest.approx(6.00)
    us = BROKERS["DEGIRO"]["markets"]["US"]  # 1.00 + 1.00 handling
    assert bc.round_trip_cost(1500.0, us, 0.0, False) == pytest.approx(4.00)


def test_trade_republic_charges_its_one_euro_once():
    for mk in ("US", "IE", "PT"):
        fee = BROKERS["TradeRepublic"]["markets"][mk]
        assert bc.round_trip_cost(1500.0, fee, 0.0, False) == pytest.approx(2.00), (
            f"{mk}: Trade Republic bills EUR 1.00 per order, so a round trip is 2.00")


def test_per_share_markets_do_not_pretend_to_be_percentages():
    """IBKR prices US and Canadian stocks per share. At the ticket sizes compared here the
    per-order minimum is what gets paid, so commission_pct is 0 and the per-share rate is
    stated in prose -- inventing a percentage would only be right at one share price."""
    for mk in ("US", "CA"):
        fee = BROKERS["IBKR"]["markets"][mk]
        assert fee["commission_pct"] == 0.0
        assert fee.get("pricing_basis"), f"{mk}: per-share pricing must say so"
        assert "/share" in fee["other_costs"].lower(), (
            f"{mk}: the per-share rate itself must be stated, not just the basis")


# ------------------------------------------------------------------ the comparison itself

def test_every_market_in_the_pool_now_has_at_least_one_priced_broker_or_a_visible_gap():
    """The point of the refresh. Before it, 21 regions had no key, so the comparator said
    'no broker offers this' for an ASX or TSX name -- indistinguishable from 'nobody looked'."""
    bundle = bc.build_bundle(DATA)
    silent = [m["key"] for m in bundle["markets"]
              if not m["rows"] and not m["gap_note"] and not m["unchecked_brokers"]]
    assert not silent, f"markets with no rows and nothing explaining why: {silent}"
    priced = [m["key"] for m in bundle["markets"] if m["rows"]]
    assert len(priced) >= 30, f"only {len(priced)} of 32 markets have a priced broker"


def test_an_unverified_broker_still_never_reaches_a_cost_matrix():
    """Unchanged rule, re-asserted: it now has 32 chances to leak instead of 7."""
    bundle = bc.build_bundle(DATA)
    unverified = {u["id"] for u in bundle["unverified"]}
    assert unverified, "expected Bankinter/eToro to remain unverified"
    for m in bundle["markets"]:
        leaked = unverified & {r["broker"] for r in m["rows"]}
        assert not leaked, f"{m['key']}: unverified broker(s) {leaked} in the cost matrix"
