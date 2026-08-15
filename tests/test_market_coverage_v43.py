"""Market coverage v4.3 — the suffix tables must agree with each other.

WHY THIS FILE EXISTS
  Two tables describe the same set of exchanges and drifted apart unnoticed:

    markets._SUFFIX_META            keys WITHOUT a dot   ("AX")
    technical_score.BENCH_BY_SUFFIX keys WITH a dot      (".AX")

  Because the key formats differ, adding a market to one and forgetting the other
  is easy and silent. It had already happened in BOTH directions before v4.3:
  `.AX` had a benchmark (^AXJO) but no metadata -- so Lynas was charted against the
  right index while being priced in the wrong currency -- and `.F`/`.JP` had
  metadata but no benchmark.

  200 of the universe's 1,720 tickers are .AX. The cost of this drift was not
  theoretical.

The consistency test below is the point of the file: it fails the moment a future
market is added to one table only.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import markets  # noqa: E402
import technical_score  # noqa: E402


def _bench_suffixes():
    """BENCH_BY_SUFFIX keys, normalised to the dot-less form _SUFFIX_META uses."""
    return {k.lstrip(".") for k in technical_score.BENCH_BY_SUFFIX}


class TestTheTwoTablesAgree:
    def test_every_mapped_market_has_a_benchmark(self):
        missing = sorted(set(markets._SUFFIX_META) - _bench_suffixes())
        assert not missing, (
            f"suffixes with metadata but no benchmark: {missing} — they would be "
            f"charted against the default (US) index while priced in local currency")

    def test_every_benchmarked_market_has_metadata(self):
        missing = sorted(_bench_suffixes() - set(markets._SUFFIX_META))
        assert not missing, (
            f"suffixes with a benchmark but no metadata: {missing} — they resolve to "
            f"INTL/USD, which breaks to_eur() and region_of() (this is exactly what "
            f"'.AX' did to 200 tickers before v4.3)")

    def test_the_key_formats_are_still_different_so_the_check_stays_necessary(self):
        """If someone ever unifies the formats this test documents why the
        normalisation above exists. It is not redundant while this holds."""
        assert any(k.startswith(".") for k in technical_score.BENCH_BY_SUFFIX)
        assert not any(k.startswith(".") for k in markets._SUFFIX_META)


class TestNewlyMappedMarkets:
    """Every suffix that was live in _universe.yaml while resolving to INTL/USD."""

    @pytest.mark.parametrize("ticker,region,currency", [
        ("LYC.AX", "AU", "AUD"),        # 200 tickers -- the big one
        ("D05.SI", "SG", "SGD"),        # 30
        ("WEGE3.SA", "BR", "BRL"),      # Brazil
        ("2222.SR", "SAU", "SAR"),      # Saudi Aramco
        ("WALMEX.MX", "MX", "MXN"),
        ("TOI.V", "CA", "CAD"),
        ("BBCA.JK", "ID", "IDR"),
        ("OTP.BD", "HU", "HUF"),
    ])
    def test_resolves_to_the_right_region_and_currency(self, ticker, region, currency):
        meta = markets.market_meta(ticker)
        assert meta["known"] is True, f"{ticker} still falls through to INTL/USD"
        assert meta["region"] == region
        assert meta["currency"] == currency

    def test_sa_is_brazil_and_sr_is_saudi_not_the_other_way_round(self):
        """The single most damaging way to get this table wrong. The universe holds
        both (WEGE3/RENT3/RADL3.SA and 2222/1120.SR), so a transposition would
        silently misprice three Brazilian names in SAR."""
        assert markets.currency_of("WEGE3.SA") == "BRL"
        assert markets.currency_of("2222.SR") == "SAR"
        assert markets.market_meta("WEGE3.SA")["region"] != \
               markets.market_meta("2222.SR")["region"]

    def test_no_new_market_silently_kept_the_intl_fallback(self):
        for t in ["LYC.AX", "D05.SI", "WEGE3.SA", "2222.SR", "WALMEX.MX",
                  "TOI.V", "BBCA.JK", "OTP.BD"]:
            assert markets.market_meta(t)["region"] != "INTL", t


class TestTradabilityTier:
    """'IBKR Europe to buy, Yahoo to monitor' is a union with a distinction. A venue
    that cannot be bought must not be presented as buyable."""

    @pytest.mark.parametrize("ticker", ["LYC.AX", "D05.SI", "WALMEX.MX", "TOI.V",
                                        "ASML.AS", "IBM", "SHEL.L"])
    def test_tradable_venues(self, ticker):
        assert markets.is_tradable(ticker) is True
        assert markets.tradability(ticker) == "tradable"

    @pytest.mark.parametrize("ticker", ["WEGE3.SA", "2222.SR", "BBCA.JK", "OTP.BD"])
    def test_monitor_only_venues(self, ticker):
        assert markets.is_tradable(ticker) is False
        assert markets.tradability(ticker) == "monitor_only"

    def test_an_unknown_suffix_is_never_reported_as_tradable(self):
        """Fail closed. Implying an unresolved market can be bought is worse than
        admitting it is unknown."""
        assert markets.is_tradable("FOO.ZZZ") is False
        assert markets.tradability("FOO.ZZZ") == "unknown"

    def test_monitor_only_names_carry_an_explicit_caveat(self):
        cav = " ".join(markets.market_caveats("2222.SR"))
        assert "MONITOR-ONLY" in cav
        assert "not reachable" in cav

    def test_tradable_names_carry_no_tradability_caveat(self):
        assert not any("MONITOR-ONLY" in c for c in markets.market_caveats("ASML.AS"))


class TestThinSecondaryVenues:
    """Roadmap R4: ADS.DE resolved to Stuttgart, returned a stale price while Xetra
    had gapped -18%, and the divergence was recorded as a yfinance error when the
    REFERENCE was what was wrong."""

    @pytest.mark.parametrize("ticker", ["SSUN.F", "XYZ.HA", "TOI.V"])
    def test_thin_venues_warn_about_stale_quotes(self, ticker):
        cav = " ".join(markets.market_caveats(ticker))
        assert "thin secondary listing" in cav
        assert "REFERENCE problem" in cav

    def test_frankfurt_and_hanover_keep_the_correct_currency(self):
        """They are real German venues -- EUR is right. The risk is thinness and
        duplicate identity, not currency, so they stay mapped and are warned about."""
        for t in ("SSUN.F", "XYZ.HA"):
            assert markets.currency_of(t) == "EUR"
            assert markets.market_meta(t)["region"] == "DE"

    def test_the_german_secondary_venue_benchmarks_against_the_dax(self):
        assert technical_score.BENCH_BY_SUFFIX[".F"] == "^GDAXI"
        assert technical_score.BENCH_BY_SUFFIX[".HA"] == "^GDAXI"

    def test_identity_of_a_known_gdr_is_handled_by_listings_not_by_this_table(self):
        """SSUN.F is Samsung's Frankfurt GDR. The dedupe must come from the listing
        registry, so the analysis runs on 005930.KS rather than on a thin wrapper."""
        import listings
        assert listings.company_key("SSUN.F") == listings.company_key("005930.KS")


class TestAustraliaIsTheHeadlineCase:
    def test_lynas_no_longer_resolves_to_intl_usd(self):
        """Measured on 2026-08-15 before the fix:
            {'region':'INTL','currency':'USD','exchange':'unknown (AX)','known':False}
        which broke FX conversion, region routing and the accounting caveat."""
        meta = markets.market_meta("LYC.AX")
        assert (meta["region"], meta["currency"], meta["known"]) == ("AU", "AUD", True)
        assert "unknown" not in meta["exchange"]

    def test_the_half_yearly_reporting_caveat_is_stated(self):
        """The measured reason LYC.AX produces no quarterly financial history: ASX
        issuers report half-yearly. The report must explain that rather than look
        like a fetch failure."""
        cav = " ".join(markets.market_caveats("LYC.AX"))
        assert "HALF-YEARLY" in cav

    def test_australia_keeps_its_own_index(self):
        assert technical_score.BENCH_BY_SUFFIX[".AX"] == "^AXJO"
