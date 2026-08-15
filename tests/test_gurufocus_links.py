"""
Unit tests for `markets.gurufocus_url` — the v4.3 deep link.

**The load-bearing rule is that an unverified venue gets NO link.** GuruFocus namespaces a
symbol as `{PREFIX}:{SYMBOL}` and the prefix is *not* the Yahoo suffix, nor reliably the
ISO 10383 MIC: Paris is `XPAR` (a MIC) but London is `LSE`, Tokyo `TSE`, Hong Kong `HKSE`,
Milan `MIL` and Taipei `TPE` — none of which are. Deriving prefixes from the MIC list
would have shipped six broken links into reports the user acts on.

Every mapping asserted here was read off GuruFocus's own pages on 2026-08-15 (breadcrumb
and peer-compare strips) and at least one generated URL per family was opened live.
Network-free: these tests check the string builder, not GuruFocus.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import markets as m  # noqa: E402


BASE = "https://www.gurufocus.com/stock/"


class TestVerifiedVenues:
    def test_us_symbols_are_bare(self):
        """No NAS-vs-NYSE decision is needed after all: gurufocus.com/stock/IBM resolves,
        which removes the one part of this feature that was not derivable from the ticker."""
        assert m.gurufocus_url("IBM") == BASE + "IBM/summary"
        assert m.gurufocus_url("MPWR") == BASE + "MPWR/summary"

    def test_a_us_class_share_is_not_treated_as_a_venue(self):
        """BRK.B's `.B` is a share class, not an exchange — `suffix_of` already knows,
        and the link must not become `B:BRK`."""
        assert m.gurufocus_url("BRK.B") == BASE + "BRK.B/summary"

    def test_the_european_prefixes(self):
        cases = {"SAP.DE": "XTER:SAP", "ASML.AS": "XAMS:ASML", "MC.PA": "XPAR:MC",
                 "ITX.MC": "XMAD:ITX", "RACE.MI": "MIL:RACE", "NESN.SW": "XSWX:NESN",
                 "SHEL.L": "LSE:SHEL"}
        for ticker, path in cases.items():
            assert m.gurufocus_url(ticker) == f"{BASE}{path}/summary", ticker

    def test_the_asian_prefixes(self):
        cases = {"7203.T": "TSE:7203", "2330.TW": "TPE:2330", "600655.SS": "SHSE:600655",
                 "002371.SZ": "SZSE:002371", "INFY.NS": "NSE:INFY", "543278.BO": "BOM:543278"}
        for ticker, path in cases.items():
            assert m.gurufocus_url(ticker) == f"{BASE}{path}/summary", ticker

    def test_london_is_lse_not_xlon(self):
        assert "XLON" not in m.gurufocus_url("SHEL.L")

    def test_tokyo_is_tse_not_xtks(self):
        assert "XTKS" not in m.gurufocus_url("7203.T")

    def test_milan_is_mil_not_xmil(self):
        assert m.gurufocus_url("RACE.MI").count("MIL") == 1
        assert "XMIL" not in m.gurufocus_url("RACE.MI")


class TestHongKongPadding:
    """Yahoo's own padding varies (`0700.HK`, `1929.HK`); GuruFocus always uses five
    digits. Verified live: `HKSE:00700` is Tencent."""

    def test_a_four_digit_code_is_padded_to_five(self):
        assert m.gurufocus_url("0700.HK") == BASE + "HKSE:00700/summary"
        assert m.gurufocus_url("1929.HK") == BASE + "HKSE:01929/summary"

    def test_an_already_five_digit_code_is_untouched(self):
        assert m.gurufocus_url("09880.HK") == BASE + "HKSE:09880/summary"

    def test_a_non_numeric_hk_symbol_is_not_padded(self):
        assert m.gurufocus_url("ABC.HK") == BASE + "HKSE:ABC/summary"


class TestUnverifiedVenuesGetNoLink:
    """This is the discipline the whole feature rests on. These venues are NOT
    unsupported by GuruFocus — they are unverified, and a guessed prefix produces a 404
    inside a report the user acts on."""

    def test_copenhagen_is_absent_because_both_url_forms_failed_live(self):
        """GuruFocus displays Novo Nordisk as `CSE:NOVO B`, but `CSE:NOVO%20B` and
        `CSE:NOVO-B` both land on an empty search page. Whatever it routes on is not the
        string it shows, so `.CO` gets nothing."""
        assert m.gurufocus_url("NOVO-B.CO") is None

    def test_the_unmapped_venues_return_none(self):
        for t in ["EVO.ST", "EQNR.OL", "NOKIA.HE", "JMT.LS", "RYA.IR", "UCB.BR",
                  "OMV.VI", "005930.KS", "SHOP.TO", "LYC.AX", "D05.SI", "WEGE3.SA",
                  "2222.SR", "AMX.MX", "TLKM.JK", "OTP.BD", "SSUN.F"]:
            assert m.gurufocus_url(t) is None, t

    def test_a_brand_new_suffix_fails_closed(self):
        assert m.gurufocus_url("FOO.ZZ") is None


class TestInputHandling:
    def test_empty_and_non_string_input_is_none(self):
        for bad in ("", None, 123, [], {}):
            assert m.gurufocus_url(bad) is None

    def test_a_lowercase_ticker_is_normalised(self):
        assert m.gurufocus_url("sap.de") == BASE + "XTER:SAP/summary"

    def test_surrounding_whitespace_is_stripped(self):
        assert m.gurufocus_url("  IBM  ".strip()) == BASE + "IBM/summary"

    def test_the_colon_is_not_percent_encoded(self):
        """`%3A` in the path sends GuruFocus to its search page instead of the stock —
        which is exactly how the Copenhagen attempt failed."""
        assert "%3A" not in m.gurufocus_url("SAP.DE")

    def test_the_scheme_is_always_https(self):
        """The plain `http` form redirects, and a redirect inside an emailed report is
        one more thing that can be rewritten or stripped in transit."""
        assert m.gurufocus_url("IBM").startswith("https://")


def test_every_mapped_suffix_is_a_market_the_system_knows():
    """A GuruFocus prefix for a suffix `_SUFFIX_META` has never heard of would mean the
    two tables disagree about which markets exist — the same class of drift the v4.3
    market-coverage test exists to stop."""
    unknown = [s for s in m._GURUFOCUS_PREFIX if s and s not in m._SUFFIX_META]
    assert not unknown, f"GuruFocus prefixes for unmapped suffixes: {unknown}"
