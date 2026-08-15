"""SEC EDGAR helper — parsing, URL construction and honest degradation.

Network-free, like the rest of the suite: every test drives synthetic payloads shaped
like the real ones (verified against IBM CIK 0000051143 on 2026-08-15).

The parsing tests carry most of the weight because `filings.recent` is stored as
PARALLEL ARRAYS. Zipping those wrongly attributes one filing's date or accession to a
different filing — a bug that produces plausible-looking output and would be invisible
in a report.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import edgar  # noqa: E402


SUBMISSIONS = {
    "cik": 51143,
    "name": "INTERNATIONAL BUSINESS MACHINES CORP",
    "sicDescription": "Computer & Office Equipment",
    "exchanges": ["NYSE"],
    "fiscalYearEnd": "1231",
    "filings": {
        "recent": {
            "form":            ["8-K",        "10-Q",       "4",          "8-K",        "10-K"],
            "filingDate":      ["2026-08-14", "2026-07-23", "2026-07-20", "2026-07-22", "2026-02-25"],
            "reportDate":      ["2026-08-10", "2026-06-30", "",           "2026-07-22", "2025-12-31"],
            "accessionNumber": ["0001104659-26-097089", "0000051143-26-000078",
                                "0000051143-26-000075", "0000051143-26-000077",
                                "0000051143-26-000010"],
            "primaryDocument": ["tm2623193d1_8k.htm", "ibm-20260630.htm", "xslF345X05/doc4.xml",
                                "ibm-20260722.htm", "ibm-20251231.htm"],
            "items":           ["2.02,9.01",  "",           "",           "5.02",       ""],
        }
    },
}


class TestCikConversions:
    @pytest.mark.parametrize("raw", [51143, "51143", "CIK0000051143", "0000051143"])
    def test_pad_cik_accepts_every_form_seen_in_the_wild(self, raw):
        assert edgar.pad_cik(raw) == "CIK0000051143"

    @pytest.mark.parametrize("raw", [51143, "CIK0000051143", "0000051143"])
    def test_cik_int_strips_padding_for_archive_paths(self, raw):
        assert edgar.cik_int(raw) == "51143"

    def test_the_two_forms_are_not_interchangeable(self):
        """The JSON APIs need the padded form and Archives needs the integer.
        Swapping them 404s, which is why both conversions are explicit."""
        assert edgar.pad_cik(51143) != edgar.cik_int(51143)


class TestTickerMap:
    MAP = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 51143, "ticker": "IBM", "title": "IBM"},
    }

    def test_resolves_a_known_ticker(self):
        assert edgar.cik_from_map(self.MAP, "IBM") == "CIK0000051143"

    def test_is_case_insensitive(self):
        assert edgar.cik_from_map(self.MAP, "aapl") == "CIK0000320193"

    @pytest.mark.parametrize("bad", [None, "", "NOSUCH"])
    def test_unknown_ticker_is_none_not_a_guess(self, bad):
        assert edgar.cik_from_map(self.MAP, bad) is None

    def test_a_broken_map_does_not_raise(self):
        assert edgar.cik_from_map(None, "IBM") is None
        assert edgar.cik_from_map([], "IBM") is None


class TestFilingUrl:
    def test_the_accession_is_undashed_in_the_path_but_dashed_in_the_json(self):
        url = edgar.filing_url(51143, "0000051143-26-000078", "ibm-20260630.htm")
        assert url == ("https://www.sec.gov/Archives/edgar/data/51143/"
                       "000005114326000078/ibm-20260630.htm")
        assert "-26-" not in url.split("/data/")[1].split("/")[1]

    def test_the_cik_in_an_archive_path_is_unpadded(self):
        url = edgar.filing_url("CIK0000051143", "0000051143-26-000078", "x.htm")
        assert "/data/51143/" in url


class TestPickFilings:
    def test_columns_stay_aligned_across_the_parallel_arrays(self):
        """The core risk: form[i] must keep its own date, period and accession."""
        got = edgar.pick_filings(SUBMISSIONS)
        by_form = {f["form"]: f for f in got}
        tenq = by_form["10-Q"]
        assert tenq["filed"] == "2026-07-23"
        assert tenq["period"] == "2026-06-30"
        assert tenq["accession"] == "0000051143-26-000078"
        assert tenq["url"].endswith("ibm-20260630.htm")
        tenk = by_form["10-K"]
        assert tenk["filed"] == "2026-02-25" and tenk["period"] == "2025-12-31"

    def test_form_4_insider_noise_is_excluded(self):
        """683 of IBM's 1000 recent filings are Form 4. Including them would bury
        the three forms that carry a thesis."""
        assert all(f["form"] != "4" for f in edgar.pick_filings(SUBMISSIONS))

    def test_results_are_newest_first(self):
        dates = [f["filed"] for f in edgar.pick_filings(SUBMISSIONS)]
        assert dates == sorted(dates, reverse=True)

    def test_per_form_caps_each_form_independently(self):
        got = edgar.pick_filings(SUBMISSIONS, per_form=1)
        assert sum(1 for f in got if f["form"] == "8-K") == 1
        # ...and capping 8-Ks must not drop the sole 10-K.
        assert any(f["form"] == "10-K" for f in got)

    def test_only_requested_forms_come_back(self):
        got = edgar.pick_filings(SUBMISSIONS, forms=("10-K",))
        assert {f["form"] for f in got} == {"10-K"}

    @pytest.mark.parametrize("bad", [None, {}, {"filings": {}},
                                     {"filings": {"recent": {}}},
                                     {"filings": {"recent": {"form": []}}}])
    def test_malformed_payloads_yield_an_empty_list_not_an_exception(self, bad):
        assert edgar.pick_filings(bad) == []

    def test_a_short_column_does_not_raise_or_misalign(self):
        """Defensive: if SEC ever returns a truncated column, the rows that do exist
        must keep their own values rather than shifting up."""
        payload = json.loads(json.dumps(SUBMISSIONS))
        payload["filings"]["recent"]["reportDate"] = ["2026-08-10"]   # only one
        got = edgar.pick_filings(payload)
        # Select by filing date, not by form: there are two 8-Ks in the fixture, so
        # keying a dict on "form" silently keeps whichever came last.
        by_date = {f["filed"]: f for f in got}
        assert by_date["2026-08-14"]["period"] == "2026-08-10", "row 0 keeps its own value"
        assert by_date["2026-07-23"]["period"] is None, "no value must not borrow row 0's"
        assert by_date["2026-07-23"]["filed"] == "2026-07-23", "other columns unaffected"
        assert by_date["2026-07-23"]["accession"] == "0000051143-26-000078"


class TestEightKItems:
    def test_earnings_item_is_labelled(self):
        got = edgar.pick_filings(SUBMISSIONS, forms=("8-K",))
        earnings = [f for f in got if f["filed"] == "2026-08-14"][0]
        assert any("results of operations" in i for i in earnings["items"])

    def test_the_non_reliance_item_is_surfaced_loudly(self):
        """4.02 says previously issued financials cannot be relied upon. If this ever
        renders quietly, the report is hiding the single worst signal EDGAR carries."""
        assert edgar.describe_items("4.02") == ["4.02: PRIOR FINANCIALS NOT RELIABLE"]

    def test_unknown_codes_are_passed_through_not_dropped(self):
        assert edgar.describe_items("2.02,9.99") == [
            "2.02: results of operations (earnings release)", "9.99"]

    @pytest.mark.parametrize("raw", ["", None, ",", " , "])
    def test_empty_item_strings_yield_nothing(self, raw):
        assert edgar.describe_items(raw) == []


class TestLatestOf:
    def test_returns_the_newest_of_a_form(self):
        f = edgar.pick_filings(SUBMISSIONS)
        assert edgar.latest_of(f, "8-K")["filed"] == "2026-08-14"

    def test_missing_form_is_none(self):
        assert edgar.latest_of(edgar.pick_filings(SUBMISSIONS), "20-F") is None


class TestUsListingGate:
    @pytest.mark.parametrize("t", ["IBM", "MSFT", "BRK-B"])
    def test_bare_symbols_are_treated_as_sec_filers(self, t):
        assert edgar.is_us_listing(t) is True

    @pytest.mark.parametrize("t", ["ASML.AS", "LYC.AX", "2330.TW", "SHEL.L"])
    def test_suffixed_tickers_are_not(self, t):
        assert edgar.is_us_listing(t) is False


class TestFactsSummary:
    FACTS = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"val": 62_753_000_000, "end": "2024-12-31", "fy": 2024, "fp": "FY", "form": "10-K"},
            {"val": 62_068_000_000, "end": "2025-12-31", "fy": 2025, "fp": "FY", "form": "10-K"},
            {"val": 14_000_000_000, "end": "2025-03-31", "fy": 2025, "fp": "Q1", "form": "10-Q"},
        ]}},
        "NetIncomeLoss": {"units": {"USD": [
            {"val": 6_023_000_000, "end": "2025-12-31", "fy": 2025, "fp": "FY", "form": "10-K"},
        ]}},
    }}}

    def test_takes_the_newest_annual_figure(self):
        got = edgar.summarise_facts(self.FACTS)
        assert got["Revenues"]["value"] == 62_068_000_000
        assert got["Revenues"]["period_end"] == "2025-12-31"

    def test_quarterly_rows_are_never_mixed_into_the_annual_series(self):
        """A Q1 figure standing in for a full year understates revenue ~4x. The 10-Q
        row above is newer by nothing and smaller by a lot -- it must be ignored."""
        got = edgar.summarise_facts(self.FACTS)
        assert got["Revenues"]["value"] != 14_000_000_000

    def test_absent_tags_are_omitted_rather_than_zeroed(self):
        got = edgar.summarise_facts(self.FACTS)
        assert "Assets" not in got

    @pytest.mark.parametrize("bad", [None, {}, {"facts": {}}, {"facts": {"us-gaap": None}}])
    def test_malformed_facts_yield_an_empty_dict(self, bad):
        assert edgar.summarise_facts(bad) == {}


class TestFetchDegradation:
    def test_a_non_us_ticker_short_circuits_without_any_network_call(self, monkeypatch, tmp_path):
        def boom(*a, **k):
            raise AssertionError("no HTTP call may be made for a non-US listing")
        monkeypatch.setattr(edgar, "http_get_json", boom)
        got = edgar.fetch("ASML.AS", tmp_path)
        assert got["available"] is False
        assert "not a US listing" in got["reason"]

    def test_an_unresolvable_ticker_degrades_cleanly(self, monkeypatch, tmp_path):
        monkeypatch.setattr(edgar, "http_get_json", lambda *a, **k: {})
        got = edgar.fetch("ZZZZ", tmp_path)
        assert got["available"] is False and "CIK" in got["reason"]

    def test_a_dead_network_never_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(edgar, "http_get_json", lambda *a, **k: None)
        got = edgar.fetch("IBM", tmp_path)
        assert got["available"] is False

    def test_a_registrant_with_no_relevant_forms_is_explained_not_errored(
            self, monkeypatch, tmp_path):
        """Foreign private issuers file 20-F, not 10-K. That is a fact about the
        company, not a failure of this module."""
        payload = json.loads(json.dumps(SUBMISSIONS))
        payload["filings"]["recent"]["form"] = ["20-F", "6-K", "4", "6-K", "20-F"]
        monkeypatch.setattr(edgar, "resolve_cik", lambda t, d: "CIK0000051143")
        monkeypatch.setattr(edgar, "http_get_json", lambda *a, **k: payload)
        got = edgar.fetch("XYZ", tmp_path)
        assert got["available"] is True and got["filings"] == []
        assert "foreign private issuer" in got["note"]

    def test_facts_are_not_fetched_unless_asked(self, monkeypatch, tmp_path):
        """companyfacts is 5.6 MB and ~3 s. On a job with ~6 min of headroom it
        cannot be unconditional."""
        urls = []
        monkeypatch.setattr(edgar, "resolve_cik", lambda t, d: "CIK0000051143")

        def spy(url, *a, **k):
            urls.append(url)
            return SUBMISSIONS
        monkeypatch.setattr(edgar, "http_get_json", spy)
        edgar.fetch("IBM", tmp_path)
        assert not any("companyfacts" in u for u in urls)
        assert "xbrl_facts" not in edgar.fetch("IBM", tmp_path)


class TestCacheTtl:
    def test_a_missing_file_is_never_fresh(self, tmp_path):
        assert edgar.cache_is_fresh(tmp_path / "nope.json", 30) is False

    def test_a_new_file_is_fresh_and_an_old_one_is_not(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text("{}", encoding="utf-8")
        assert edgar.cache_is_fresh(p, 1) is True
        # 2 days later, against a 1-day TTL
        assert edgar.cache_is_fresh(p, 1, now=p.stat().st_mtime + 2 * 86400) is False

    def test_submissions_expire_far_sooner_than_facts(self):
        """A 30-day TTL on submissions would hide a brand-new 8-K for a month, which
        defeats the point of reading filings for catalysts. Deliberate departure from
        the v4.3 plan's single 30-day TTL."""
        assert edgar.SUBMISSIONS_TTL_DAYS < edgar.FACTS_TTL_DAYS
        assert edgar.SUBMISSIONS_TTL_DAYS <= 1
