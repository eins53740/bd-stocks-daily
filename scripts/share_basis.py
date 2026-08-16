"""share_basis.py — what basis is `statements_raw.balance.shares` actually on?

Roadmap **R6**, and the roadmap's own hypothesis was wrong. It blamed the `"Common Stock"`
fall-through in `_STMT_ROWS["balance"]["shares"]` for being a par value in currency. The
corpus says otherwise: measured across **147** cached analyses against
`fundamentals.shares_out`, **86 agree within ±5 %** and the other **61 are off in a
continuous spectrum from 1.05× to 25.6×** — which is not what a currency-vs-count confusion
looks like. That would be off by orders of magnitude, or not at all.

What is actually happening is three different things wearing one label:

1. **Issued includes treasury.** `"Share Issued"` is the FIRST label tried and it is the
   share count the company has ever issued, not the count outstanding today. Any company
   with decades of buybacks diverges: IBM 2.43×, AMAT 2.52×, MCD 2.34×, P&G 1.72×,
   CTAS 1.95×, UNP 1.87×. Nothing is corrupt — the number answers a different question.
2. **A different share class or quote ratio.** TSM prints exactly **5.000×**, which is the
   ADR ratio (1 ADR = 5 ordinary). Roche 7.59× is voting shares against the non-voting
   equity certificates that carry the quote. SSUN.F 25.6× is a Frankfurt depositary line.
   Ping An reports one total against a listed H-share count (2318.HK) and an A-share count
   (601318.SS) — the same balance figure, two different ratios.
3. **Staleness, in the other direction.** SMCI 0.918× and LYC.AX 0.929× are below one: the
   balance sheet is a fiscal-year-end count and shares have been issued since. That is the
   filing being old, not wrong.

Why it matters, concretely. `category_lens` cross-checks P/B from `book_value` against
P/B from equity÷shares and calls the name **unreliable** past 5×. Case 2 trips that and is
correctly refused. **Case 1 sails straight under it** — IBM's 2.43× produces a P/B that is
confidently published and wrong by a factor of two and a half, on the very metric an
asset-play claim rests on.

`red_flags.book_value_trend` is unaffected as long as the basis is STABLE, because it
compares BVPS year over year and a constant basis cancels in the ratio. That is a property
worth stating, not luck.

**This module classifies; it does not rewrite.** The extraction is untouched, so no
published composite, gate or verdict moves — which is the condition R6 was held open for.
Consumers decide what to do with the basis, and a caller that ignores it behaves exactly as
it did before.
"""
from __future__ import annotations

#: Agreement band. Measured: the 86 in-band names span 0.9912-1.0483, so ±5 % holds all of
#: them with no room to spare on either side — this is fitted to the corpus, not chosen.
AGREE_LO = 0.95
AGREE_HI = 1.05

#: Above this, the gap is too large for treasury stock and means a different share class,
#: an ADR ratio or a depositary line. The corpus is empirically EMPTY between 2.524 (AMAT)
#: and 3.151 (Atlas Copco, an A/B share structure) — the boundary sits in that gap rather
#: than at a round number someone liked.
CLASS_MISMATCH_RATIO = 3.0

BASIS_OUTSTANDING = "outstanding"
BASIS_ISSUED = "issued_with_treasury"
BASIS_CLASS_MISMATCH = "share_class_or_quote_ratio"
BASIS_STALE = "stale_or_since_issued"
BASIS_UNKNOWN = "unknown"

#: Which bases a per-share calculation may use the balance-sheet count for. The two
#: correctable ones are NOT in it: `shares_out` is the right denominator there, and it is
#: already on the analysis.
_TRUSTWORTHY = {BASIS_OUTSTANDING}


def _num(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None      # f == f filters NaN


def classify(balance_shares, shares_out) -> dict:
    """Which basis the balance-sheet share count is on, and what to divide by.

    Returns `{basis, ratio, balance_shares, shares_out, preferred_shares, trustworthy,
    note}`. `preferred_shares` is the count a per-share calculation should use, or **None**
    when no count can be trusted — never a guess. `basis` is `unknown` whenever either
    input is missing, which is the honest answer and not a failure.
    """
    bal = _num(balance_shares)
    out = _num(shares_out)

    if bal is None or bal <= 0 or out is None or out <= 0:
        return {"basis": BASIS_UNKNOWN, "ratio": None, "balance_shares": bal,
                "shares_out": out, "preferred_shares": out if (out and out > 0) else bal,
                "trustworthy": False,
                "note": "no second count to check against; basis unverified"}

    ratio = bal / out

    if AGREE_LO <= ratio <= AGREE_HI:
        return {"basis": BASIS_OUTSTANDING, "ratio": round(ratio, 4),
                "balance_shares": bal, "shares_out": out, "preferred_shares": bal,
                "trustworthy": True,
                "note": "balance-sheet count agrees with shares outstanding"}

    if ratio > CLASS_MISMATCH_RATIO:
        return {"basis": BASIS_CLASS_MISMATCH, "ratio": round(ratio, 4),
                "balance_shares": bal, "shares_out": out, "preferred_shares": None,
                "trustworthy": False,
                "note": (f"balance-sheet count is {ratio:.2f}x shares outstanding — too "
                         f"large for treasury stock, so a different share class, an ADR "
                         f"ratio or a depositary line. No per-share figure is derived "
                         f"from it.")}

    if ratio > AGREE_HI:
        return {"basis": BASIS_ISSUED, "ratio": round(ratio, 4),
                "balance_shares": bal, "shares_out": out, "preferred_shares": out,
                "trustworthy": False,
                "note": (f"balance-sheet count is {ratio:.2f}x shares outstanding — "
                         f"'Share Issued' includes treasury stock. Per-share figures use "
                         f"shares outstanding.")}

    return {"basis": BASIS_STALE, "ratio": round(ratio, 4),
            "balance_shares": bal, "shares_out": out, "preferred_shares": out,
            "trustworthy": False,
            "note": (f"balance-sheet count is {ratio:.2f}x shares outstanding — the filing "
                     f"predates shares issued since. Per-share figures use shares "
                     f"outstanding.")}


def preferred_shares(basis_block, fallback=None):
    """The denominator to use, or `fallback` when nothing is trustworthy.

    Kept as a function rather than a dict lookup so a caller that has no basis block at all
    — an older cached analysis, say — degrades to today's behaviour instead of raising.
    """
    if not isinstance(basis_block, dict):
        return fallback
    got = basis_block.get("preferred_shares")
    return got if got else fallback


def is_per_share_safe(basis_block) -> bool:
    """True only when a per-share figure from equity÷shares can be published as a fact."""
    if not isinstance(basis_block, dict):
        return False
    return basis_block.get("basis") in _TRUSTWORTHY
