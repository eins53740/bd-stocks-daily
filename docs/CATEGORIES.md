# Investment categories — cyclical, turnaround, asset play

Doctrine and published thresholds for `scripts/category_lens.py`. **This file is the
contract**: every cut point below is the one in the code, and `tests/test_category_lens.py`
pins the behaviour. A classifier with unpublished thresholds is not reproducible.

## TL;DR — five sentences

1. `lynch_category()` covers **4 of Lynch's 6** categories, and its "cyclical" is a
   **residual bucket**, not a test — whatever falls through `5 % ≤ CAGR < 20 %` with
   `ROE < 10 %`.
2. The expensive error is the other direction: **a cyclical at peak earnings is labelled
   `stalwart`**, shows record margins and a low trailing P/E, and sails through Gate 2.
3. `category_lens` tests **earnings amplitude across a cycle**, a **loss-to-profit
   inflection**, and **price vs tangible book** — three tests, from data already on disk.
4. It is a **lens, not a mandate change**: the mandate stays Quality Compounder, the
   composite is untouched, and an asset play is *recognised and explained*, never *bought*.
5. It never claims a **realisation catalyst** — that is not derivable from a numbers JSON,
   and inferring one from a low multiple is how a value trap gets bought.

## Why a second classifier instead of fixing the first

`analyze_ticker.lynch_category()` is eight lines and feeds the **Growth-durability
sub-score** and the Lynch return/drawdown prior in `alpha_beta.py`. Changing it would move
`scores.composite`, frozen at v2.2, which v4.3 may not do. So the classification ships as
an additive `category_lens` key **alongside** `lynch_category`, and where the two disagree
the block says so in words rather than quietly overwriting one.

---

## 1. Cyclical

**A cycle has amplitude, duration, and a return.** All three are tested, because each was
added after a corpus run produced a false positive without it.

| Requirement | Threshold | Constant |
|---|---|---|
| history depth | ≥ 6 annual years of **positive** EBITDA | `CYC_MIN_YEARS` |
| a down leg opens an episode | fall ≥ 20 % from the running peak | `CYC_FALL_LEG` |
| …at a meaningful scale | episode peak ≥ 5 % of the series maximum | `CYC_PEAK_FLOOR_FRAC` |
| …sustained, not a write-down | ≥ 2 **consecutive** years below the fall threshold | `CYC_FALL_YEARS` |
| …and it came back | ≥ 50 % of the fall regained | `CYC_RECOVERY` |
| detection | ≥ 1 completed cycle with fall ≥ 30 % | `CYC_DRAWDOWN` |
| high confidence | ≥ 2 completed cycles, or margin range ≥ 10 pp | `CYC_STRONG_AMPLITUDE_PP` |
| late-cycle warning | current EBITDA margin in the top 20 % of its own range | `CYC_PEAK_PERCENTILE` |

Sector base rates (Energy, Basic Materials, Consumer Cyclical, Industrials, Real Estate)
are recorded as **supporting evidence only, never decisive** — "Industrials" contains both
a steel mill and a payroll processor.

### Three corrections the corpus forced

- **Loss years break the arithmetic.** `(peak − v) / peak` is unbounded once `v` goes
  negative: AMD's twenty-year EBITDA history contains six loss years and produced a **319 %
  drawdown** and five phantom cycles. The test now confines itself to the longest
  contiguous run of positive EBITDA and **names the window it used**. The loss years are
  not noise — they are the turnaround test's evidence.
- **A one-year plunge is a write-down, not a cycle.** P&G's FY2019 EBITDA fell to 9.4bn
  between 16.7 and 19.3 — the Gillette impairment — and was counted as a completed 54 %
  cycle. Requiring elapsed time from the peak did *not* fix it (P&G's peak sat eleven years
  earlier, so a one-year plunge inherited a decade of slow drift). Requiring **consecutive**
  years below the threshold does: P&G has two such years in twenty and they are four years
  apart, while AMD's FY2022 and FY2023 sit side by side.
- **A fall that never returns is a secular decline.** IBM's EBITDA fell 74 % across the
  Kyndryl spin-off and the mainframe-to-software transition and was called cyclical at
  *high* confidence. It is now reported as `secular_decline` — a different and genuinely
  useful fact, and disqualifying for the cyclical read, because mid-cycle earnings are
  meaningless when there is no cycle to be mid of.

### Judge a cyclical on

| Use | Not |
|---|---|
| **mid-cycle EPS** | TTM EPS |
| EV/EBITDA against its **own** cycle range | the sector median today |
| capacity utilisation, inventory turns | revenue growth |
| net debt/EBITDA **at the trough** | net debt/EBITDA today |

**Red flags:** a **low P/E at the peak** (the classic trap), rising inventories, margins at
a cycle high. The default yardstick fails because a peak-earnings cyclical scores *cheap*
on trailing P/E and passes Gate 2.

## 2. Turnaround

| Requirement | Threshold | Constant |
|---|---|---|
| history depth | ≥ 4 annual years of net income or FCF | `TURN_MIN_YEARS` |
| the loss is recent | within 5 years of the latest observation | `TURN_LOOKBACK` |
| the latest year is positive | — | — |
| **there was profit before the loss** | ≥ 1 positive year preceding it | — |
| survival: Altman Z | `< 1.8` downgrades confidence | `TURN_ALTMAN_DISTRESS` |
| survival: current ratio | `< 1.0` downgrades | `TURN_CURRENT_RATIO_MIN` |
| survival: net debt/EBITDA | `> 4.0×` downgrades | `TURN_NETDEBT_EBITDA_MAX` |

**First profitability is not a turnaround.** PLTR — losses from IPO to 2022, profitable
since — was flagged beside adidas, whose FY2023 loss followed two decades of profit. One
recovered a *known* earnings power; the other reached an *unknown* one for the first time.
The difference decides what you underwrite, so the record must contain profit **before** the
loss.

**Survival before recovery.** Gates 1 / 4 / 5 (growth, ROE, margin) reject every turnaround
by construction, so the question a report must answer is not "is it growing" but "does it
get there": liquidity runway, covenant headroom, Altman Z, the FCF inflection, the debt
maturity wall. Detected turnarounds on a distressed balance sheet are downgraded to
*moderate* with the risks listed — never hidden.

**Red flags:** dilution risk, going-concern language, cash burn against runway.

## 3. Asset play

| Requirement | Threshold | Constant |
|---|---|---|
| discount to book | `P/B ≤ 1.0` strong, `≤ 1.3` moderate | `ASSET_PB_STRONG` / `_MODERATE` |
| confirmed on tangible book | `P/TB ≤ 1.5` | `ASSET_PTB_MAX` |
| the two book paths agree | ratio `≤ 5×` | `PB_CROSSCHECK_TOL` |
| the number is a valuation at all | `P/B ≥ 0.05` | `PB_PLAUSIBLE_MIN` |

**Tangible book is the confirmation.** A P/B of 0.9 on a balance sheet that is mostly
goodwill is not an asset play — it is an impairment waiting to be booked.

### Two unit errors this test refuses to publish

- **Pence.** RIO.L quoted at 7927 **GBp** against a book value of 28.31 **GBP** printed a
  P/B of **280×**. Every London name would have been dismissed for the wrong reason.
  `markets.normalize_gbx` is applied before dividing.
- **Share class and reporting currency.** BRK-B printed **0.001×** book (a B-share quote
  against an A-share book value) and TSM **82×** (a USD ADR against TWD book). The lens
  cross-checks `book_value` against equity/shares from the balance sheet and, when the two
  break by more than 5×, reports **unreliable** instead of a number. The tolerance is set
  from the corpus: across 122 cross-checkable reports the ratio is under 3 for all but five
  names, and the 1.7–2.9 middle band is the balance extractor's `shares` row falling
  through to `"Common Stock"` — a par value on some filers rather than a share count
  (recorded as an audit finding).

**The catalyst is never claimed.** `catalyst` is always `null` with a stated reason: a
permanent holding-company discount and an imminent break-up look identical in a numbers
JSON. **Red flags:** a value trap with no catalyst, governance blocking realisation, a
perpetual holding-company discount. Earnings-based valuation is the wrong instrument here
entirely.

## 4. Precedence, disagreement, and what the block means

When more than one test fires, `PRECEDENCE = cyclical → turnaround → asset_play`. A
cyclical **at the trough** also looks like a turnaround (losses, then recovery); cyclical
wins that tie because the recovery is the cycle doing its job, not management fixing
anything. All detected categories are listed in `detected`, not just the primary.

Disagreement with `lynch_category` is stated in words. The one case that must not be
overstated: when the amplitude test **could not run** (no annual history cached),
`agrees_with_lynch` is `null` and the note says the test could not run — *not* that it found
no cycle.

### Corpus base rates (53 names with both an analysis JSON and a cached annual history)

| Outcome | Count |
|---|---|
| none of the three (the default Quality Compounder lens) | 39 |
| turnaround | 8 |
| cyclical | 5 |
| asset play | 1 |
| secular decline (not a category — a separate warning) | 4 |
| late-cycle peak-earnings warning | 4 |

## 5. What this does **not** do

- It does not change `scores.composite`, the gates, `lynch_category`, or the verdict.
- It does not make asset plays or turnarounds buy candidates — `STRATEGY_GUIDE.md` rejects
  Deep Value and Net-Nets as incompatible with the mandate, and that stands.
- It does not apply category-specific weights. That is roadmap **G2**, blocked on the
  **G1** backtest until ≈2026-10-17.
