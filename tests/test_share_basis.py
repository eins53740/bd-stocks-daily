"""Tests for share_basis.classify() and its use in category_lens — roadmap R6.

Every ratio in the fixtures below is a REAL measurement taken from the cached corpus on
2026-08-16 (147 analyses, balance-sheet `shares` against `fundamentals.shares_out`), not an
invented number. That matters here more than usual: the roadmap's stated hypothesis for R6
— a `"Common Stock"` par value in currency — turned out to be wrong, and it was wrong
because nobody had looked at the distribution.

What the distribution actually says:
    86 within +/-5%      correct, shares outstanding
    38 in 1.05-1.5x  \\
    17 in 1.5-3.0x   /   'Share Issued' includes treasury stock
     4 above 3x          different share class, ADR ratio, depositary line
     2 below 0.95x       fiscal-year-end count, shares issued since

The band that matters is the middle one: it slips under category_lens's 5x
PB_CROSSCHECK_TOL and publishes a wrong P/B with no warning at all.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import category_lens as cl  # noqa: E402
import share_basis as sb  # noqa: E402


# --- classification, on measured ratios --------------------------------------

def test_a_matching_count_is_outstanding():
    """The median in-band name: 1.0087x."""
    got = sb.classify(1_008_700, 1_000_000)
    assert got["basis"] == sb.BASIS_OUTSTANDING
    assert got["trustworthy"] is True
    assert got["preferred_shares"] == 1_008_700


@pytest.mark.parametrize("bal,out,name", [
    (2_290_618_523, 942_134_390, "IBM 2.43x"),
    (2_004_000_000, 793_959_430, "AMAT 2.52x"),
    (1_660_600_000, 710_505_859, "MCD 2.34x"),
    (4_009_244_000, 2_328_598_978, "PG 1.72x"),
    (779_537_000, 400_169_561, "CTAS 1.95x"),
    (1_113_161_191, 594_075_498, "UNP 1.87x"),
    (1_112_576_334, 1_053_250_365, "ASSA-B 1.056x, just outside the band"),
])
def test_treasury_stock_is_recognised_and_corrected(bal, out, name):
    """These are the names the old code got silently wrong: under 3x, so the P/B
    cross-check passed them, and not outstanding, so the P/B was false."""
    got = sb.classify(bal, out)
    assert got["basis"] == sb.BASIS_ISSUED, name
    assert got["preferred_shares"] == out, name
    assert got["trustworthy"] is False, name


@pytest.mark.parametrize("bal,out,name", [
    (25_932_524_521, 5_186_474_013, "TSM — exactly the 5:1 ADR ratio"),
    (809_253_700, 106_691_000, "Roche 7.59x — voting shares vs equity certificates"),
    (6_735_612_586, 262_662_524, "SSUN.F 25.6x — a Frankfurt depositary line"),
    (4_918_452_416, 1_560_876_032, "Atlas Copco 3.15x — an A/B share structure"),
])
def test_a_class_or_ratio_mismatch_yields_no_denominator_at_all(bal, out, name):
    """Above 3x nothing is corrected, because there is nothing to correct TO — the two
    counts describe different instruments. Refuse, do not rescale."""
    got = sb.classify(bal, out)
    assert got["basis"] == sb.BASIS_CLASS_MISMATCH, name
    assert got["preferred_shares"] is None, name


@pytest.mark.parametrize("bal,out,name", [
    (594_136_852, 646_873_027, "SMCI 0.918x"),
    (935_447_000, 1_006_502_578, "LYC.AX 0.929x"),
])
def test_a_count_below_outstanding_is_staleness_not_error(bal, out, name):
    got = sb.classify(bal, out)
    assert got["basis"] == sb.BASIS_STALE, name
    assert got["preferred_shares"] == out, name


def test_the_boundary_sits_in_the_corpus_gap():
    """AMAT at 2.524 is the largest treasury case; Atlas Copco at 3.151 the smallest class
    mismatch. The corpus is empty between them, which is where the threshold belongs — not
    at a round number someone liked."""
    assert 2.524 < sb.CLASS_MISMATCH_RATIO < 3.151


def test_the_agreement_band_is_fitted_to_the_measured_span():
    """The 86 in-band names span 0.9912-1.0483. A tighter band would evict real ones."""
    assert sb.classify(991_200, 1_000_000)["basis"] == sb.BASIS_OUTSTANDING
    assert sb.classify(1_048_300, 1_000_000)["basis"] == sb.BASIS_OUTSTANDING


# --- absence, which must never be an error -----------------------------------

@pytest.mark.parametrize("bal,out", [
    (None, 1_000_000), (1_000_000, None), (None, None), (0, 1_000_000),
    (1_000_000, 0), (-5, 1_000_000), ("n/a", 1_000_000), (float("nan"), 1_000_000),
])
def test_a_missing_or_absurd_input_is_unknown_not_a_crash(bal, out):
    got = sb.classify(bal, out)
    assert got["basis"] == sb.BASIS_UNKNOWN
    assert got["trustworthy"] is False


def test_unknown_still_offers_the_best_count_available():
    """No cross-check is not the same as no data: with only one count, use it and say the
    basis is unverified."""
    assert sb.classify(None, 900)["preferred_shares"] == 900
    assert sb.classify(900, None)["preferred_shares"] == 900


# --- the helpers degrade to old behaviour ------------------------------------

def test_a_caller_with_no_basis_block_behaves_exactly_as_before():
    """Older cached analyses have no `shares_basis`. They must keep working."""
    assert sb.preferred_shares(None, fallback=123) == 123
    assert sb.preferred_shares({}, fallback=123) == 123
    assert sb.is_per_share_safe(None) is False


def test_per_share_is_safe_only_on_an_outstanding_basis():
    assert sb.is_per_share_safe(sb.classify(1_000_000, 1_000_000)) is True
    for bal, out in ((2_000_000, 1_000_000), (5_000_000, 1_000_000),
                     (900_000, 1_000_000)):
        assert sb.is_per_share_safe(sb.classify(bal, out)) is False


# --- what changes in the report ----------------------------------------------

def _analysis(bal_shares, shares_out, equity=10_000_000_000.0, price=100.0,
              book_value=None):
    a = {
        "ticker": "TEST", "currency": "USD", "price_current": price,
        "fundamentals": {"shares_out": shares_out, "book_value": book_value},
        "statements_raw": {"balance": {
            "stockholders_equity": [equity, equity],
            "shares": [bal_shares, bal_shares],
            "shares_basis": sb.classify(bal_shares, shares_out),
        }},
    }
    return a


def test_the_statement_pb_now_uses_the_outstanding_count():
    """IBM's shape: equity 10bn, 2.43bn issued, 942m outstanding, price 100.

    On the issued count BVPS is 4.37 and P/B reads 22.9x. On the outstanding count BVPS is
    10.61 and P/B reads 9.4x. The second is right, and the first was being published.
    """
    out = cl.test_asset_play(_analysis(2_290_618_523, 942_134_390))
    pb = out["metrics"]["price_to_book_from_statements"]
    assert 9.0 < pb < 10.0, pb


def test_a_class_mismatch_refuses_the_asset_play_claim():
    """TSM: the count is not corrected — there is nothing to correct TO — but the name is
    marked unreliable and no claim is made."""
    out = cl.test_asset_play(_analysis(25_932_524_521, 5_186_474_013))
    assert out["metrics"]["price_to_book_unreliable"] is True
    assert out["detected"] is None and out["confidence"] == "none"
    assert any("share class" in n for n in out["not_computable"])


def test_a_refused_name_exits_before_anything_re_derives_a_verdict():
    """The branch must RETURN, exactly as the P/B cross-check beside it does. Without the
    early exit the code below re-assigns `detected` from tangible book and the refusal is
    undone three lines later — which is what happened on the first attempt, and only the
    corpus replay showed it (TSM went None -> False)."""
    out = cl.test_asset_play(_analysis(25_932_524_521, 5_186_474_013))
    assert out["detected"] is None
    assert "price_to_tangible_book" not in out["metrics"]


def test_a_class_mismatch_is_caught_without_needing_a_5x_pb_disagreement():
    """Atlas Copco's A/B structure sits at 3.15x on the share count. The old route to
    'unreliable' was a >5x P/B disagreement, which this would not necessarily produce —
    the tolerance was a proxy for the basis, and now the basis is known directly."""
    a = _analysis(4_918_452_416, 1_560_876_032, book_value=None)
    out = cl.test_asset_play(a)
    assert out["metrics"]["price_to_book_unreliable"] is True


def test_the_basis_is_reported_on_the_card():
    out = cl.test_asset_play(_analysis(2_290_618_523, 942_134_390))
    assert out["metrics"]["shares_basis"] == sb.BASIS_ISSUED
    assert out["metrics"]["shares_basis_ratio"] == pytest.approx(2.4314, abs=1e-3)


def test_a_clean_name_reports_its_basis_without_a_ratio():
    """No ratio is printed when there is nothing to warn about — a number beside every
    clean name is noise that teaches the reader to skip the field."""
    out = cl.test_asset_play(_analysis(1_000_000_000, 1_000_000_000))
    assert out["metrics"]["shares_basis"] == sb.BASIS_OUTSTANDING
    assert "shares_basis_ratio" not in out["metrics"]


def test_an_analysis_without_the_basis_block_is_unchanged():
    """The regression that matters: 195 published reports have no `shares_basis`, and
    re-rendering one must produce what it produced before."""
    a = _analysis(1_000_000_000, 1_000_000_000)
    del a["statements_raw"]["balance"]["shares_basis"]
    out = cl.test_asset_play(a)
    assert out["metrics"].get("price_to_book_from_statements") == pytest.approx(10.0)
    assert "shares_basis" not in out["metrics"]
