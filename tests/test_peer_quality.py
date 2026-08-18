"""N5: is the peer set actually a peer set?

The adidas fixture is the real audit case -- ranked against Amazon, McDonald's, Home Depot,
Starbucks and Nike because yfinance could not resolve a footwear industry set, with the
resulting 7.33/10 carrying the full 12% peer weight and nothing marking it a sector proxy.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze_ticker as at  # noqa: E402

ADIDAS = {
    "ADS.DE": {"industry": "Footwear & Accessories", "sector": "Consumer Cyclical"},
    "NKE": {"industry": "Footwear & Accessories", "sector": "Consumer Cyclical"},
    "AMZN": {"industry": "Internet Retail", "sector": "Consumer Cyclical"},
    "MCD": {"industry": "Restaurants", "sector": "Consumer Cyclical"},
    "HD": {"industry": "Home Improvement Retail", "sector": "Consumer Cyclical"},
    "SBUX": {"industry": "Restaurants", "sector": "Consumer Cyclical"},
}


def test_the_adidas_case_is_flagged_untrustworthy():
    q = at.peer_set_quality("Footwear & Accessories", "by_sector", ADIDAS, "ADS.DE")
    assert q["trustworthy"] is False
    assert q["n_same_industry"] == 1 and q["n_industry_known"] == 5
    assert q["same_industry_pct"] == 0.2
    assert "SECTOR PROXY, NOT PEERS" in q["note"]
    assert "Restaurants" in q["note"], "names what it was actually compared against"


def test_the_target_is_not_counted_as_its_own_peer():
    q = at.peer_set_quality("Footwear & Accessories", "by_sector", ADIDAS, "ADS.DE")
    assert q["n_peers"] == 5, "six entries, one of them the target"


def test_a_sector_set_that_happens_to_be_peers_is_usable():
    peers = {"X": {"industry": "Footwear & Accessories"},
             "NKE": {"industry": "Footwear & Accessories"},
             "PUM.DE": {"industry": "Footwear & Accessories"},
             "MCD": {"industry": "Restaurants"}}
    q = at.peer_set_quality("Footwear & Accessories", "by_sector", peers, "X")
    assert q["trustworthy"] is True
    assert q["same_industry_pct"] == 1.0 or q["same_industry_pct"] >= 0.5


def test_curated_and_industry_sets_are_trustworthy_by_construction():
    for src in ("by_ticker", "by_industry"):
        q = at.peer_set_quality("Footwear & Accessories", src, ADIDAS, "ADS.DE")
        assert q["trustworthy"] is True
        assert "not a sector proxy" in q["note"]


def test_none_keeps_its_existing_honesty():
    q = at.peer_set_quality("Anything", "none", {}, "X")
    assert q["trustworthy"] is False
    assert "neutral 5.0 placeholder" in q["note"]


def test_unknown_industries_are_unverified_not_assumed_good():
    peers = {"X": {}, "A": {}, "B": {}}
    q = at.peer_set_quality("Footwear & Accessories", "by_sector", peers, "X")
    assert q["trustworthy"] is False
    assert q["same_industry_pct"] is None
    assert "could not be checked" in q["note"]


def test_the_sub_score_is_deliberately_not_damped():
    """Damping would move the composite for a large share of names and make today's scores
    incomparable with every score already logged. That is a G1 recalibration decision."""
    src = (Path(__file__).resolve().parents[1] / "scripts" / "analyze_ticker.py").read_text(encoding="utf-8")
    i = src.index("def peer_set_quality")
    body = src[i:i + 3000]
    assert "does NOT damp" in body, "the deliberate omission has to be written down"
    assert "peer_score = " not in body and "score_0_10\"] =" not in body
