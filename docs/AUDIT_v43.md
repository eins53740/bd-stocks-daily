# AUDIT v4.3 — four lenses over the running system

Run 2026-08-15 as v4.3 §3.1, against **live code and the on-disk corpus** (384 `_log.csv`
rows, 267 analyses with gate detail, 213 with statements, 122 cross-checkable book values,
53 with a cached annual history). Every number below was measured in this session; none is
quoted from an earlier document.

**Rule the audit worked under:** the composite is frozen at **v2.2**. A finding that would
move `scores.composite` is documented and left alone — weight recalibration is roadmap
**G1/G2**, blocked on T+6m outcome data (first possible ≈2026-10-17). Guessing new weights
to close an audit finding would be the worst outcome available.

## Scoreboard

| # | Lens | Finding | Disposition |
|---|---|---|---|
| S1 | Strategy | **Gate 7 (quick ratio > 1.5) is the binding gate at 32 % pass — and it selects against the mandate** | documented, not changed (composite) |
| S2 | Strategy | Gate 4 (ROE 5y > 5 %) passes 85 % — near-inert on a quality mandate | documented, not changed (composite) |
| S3 | Strategy | The gate-5 growth bypass fired **2 times in 267** | documented |
| D1 | Data | **R4** — Twelve Data quotes a secondary venue; the gap was logged as a yfinance error | ✅ **fixed** + 6 tests |
| D2 | Data | `_STMT_ROWS["shares"]` falls through to `"Common Stock"`, a **par value** on some filers | logged → new roadmap **R6**; mitigated in-place |
| D3 | Data | 91 of 213 cached analyses predate `statements_raw` | expected; consumers degrade |
| A1 | Analysis | **N4** — `fair_price` from a lone DCF that survived its gate by 0.30 pp | ✅ **fixed** + 11 tests |
| A2 | Analysis | **N3** — a 3-year P/E band setting a target 2.9× the price | ✅ **fixed** + 10 tests |
| A3 | Analysis | **N5** — `by_sector` peer sets still carry the full 12 % peer weight | partly closed (2.1 labels it); open |
| M1 | Metrics | Buy-5y flowchart node `B` made the P/E gate inert | ✅ verified fixed (wave 2.3) |
| M2 | Metrics | The same diagram's **thresholds** do not match the code | caveat retained; **not** rewritten — see below |
| M3 | Metrics | `lynch_category` is a residual bucket, not a test | ✅ closed by §3.5 `category_lens.py` |
| M4 | Metrics | The Buffett moat multiplier silently does not fire when ROIC is suppressed | ✅ closed by §3.6 `roic_lens.py` |
| M5 | Metrics | R1 (shortlist supersede) was already implemented | roadmap entry stale → removed in §3.4 |

---

## Lens 1 — Strategy: do the gates select what the mandate says?

Measured pass rates over **267** analyses carrying `gates_detail`:

| Gate | Threshold | Pass | Not computable |
|---|---|---|---|
| 1 — revenue CAGR 5y | ≥ 8 % | **50.6 %** | 4 % |
| 2 — valuation | P/E < 35 **or** (PEG < 2.5 **and** ROE > 20 %) | 76.0 % | 2 % |
| 3 — FCF TTM | > 0 | 79.8 % | 10 % |
| 4 — ROE 5y avg | > 5 % | **85.0 %** | 0 % |
| 5 — net margin | > 10 % (+ growth bypass) | 66.3 % | 0 % |
| 6 — D/E | < 1.0 | 74.5 % | 4 % |
| 7 — quick ratio | > 1.5 | **32.2 %** | 4 % |

Verdicts across 384 logged evaluations: `review` 194 · `fair` 111 · `reject` 43 ·
**`invest` 36 (9.4 %)**. Composite mean 5.92, median 6.17, range 1.0–8.9.

**S1 — the binding gate is a liquidity test, and it is pointed the wrong way.** Gate 7 is
the hardest gate in the ladder by a distance: two thirds of everything examined fails it.
A quick ratio above 1.5 means the company holds more than 1.5× its short-term liabilities
in near-cash. That is a *lender's* test. The Quality Compounder mandate prizes the
opposite trait — **negative working capital**, where customers pay before suppliers do:
subscription software billing annually in advance, restaurants, retailers, insurance
float. Those businesses fund themselves from the operating cycle and structurally fail
Gate 7. Because `gates_passed` contributes 3 of the 10 points of the fundamentals
sub-score, and fundamentals carry 35 % of the composite, this suppresses roughly
**0.4 composite points** for exactly the business model the mandate is hunting.

**S2 — Gate 4 is close to free.** `ROE 5y > 5 %` passes 85 %. Five percent is a bar a
mediocre business clears; on a mandate whose own moat sub-score keys the Buffett
multiplier at **ROIC > 25 %**, a 5 % ROE gate contributes almost no discrimination.

**S3 — the v2.2 growth bypass is nearly dead.** It fired twice in 267 evaluations. That is
not evidence it is wrong — it is a deliberately narrow escape hatch (rev CAGR ≥ 25 % **and**
ROIC ≥ 15 % **and** FCF/revenue improving) — but a feature at a 0.7 % hit rate should be
known to be nearly dead rather than assumed to be working.

**Disposition.** All three change `gates_passed` and therefore the composite. **Nothing was
changed.** The candidate recalibrations (Gate 7 → current ratio, or > 1.0, or made a
warning rather than a gate; Gate 4 → 10–12 %) are exactly the sort of change **G1** exists
to validate against outcome data, and the first honest measurement point is ≈2026-10-17.
Recorded in `ROADMAP.md` as **G3** so the evidence is not lost.

---

## Lens 2 — Data quality

### D1 — R4: the cross-check compared the wrong venue ✅ fixed

`fetch_twelvedata_validation` **already captured** `td_exchange` and never read it. On
2026-07-30 Twelve Data answered `ADS.DE` from **XSTU (Stuttgart)** — a thin secondary
venue — with a stale €182.25 while Xetra had gapped **−18 %** on earnings. The system
recorded a 18 % divergence as a yfinance `data_quality: suspect` flag. **The reference
price was wrong, not the data being checked.**

Fix: `venue_mismatch(td_exchange, suffix)` resolves both sides to canonical venue tokens.
When they differ, the gap is recorded under `venue_notes` **and excluded from `agree`** —
it is a cross-venue observation, not a data error.

The design point worth keeping: **an unrecognised venue on either side returns `None`**
and the comparison proceeds unchanged. A guessed venue table would manufacture false
mismatches, which is the same defect wearing a different hat.

### D2 — the balance sheet's `shares` row can be a currency amount → roadmap R6

Found while building the asset-play test. `_STMT_ROWS["balance"]["shares"]` resolves
`("Share Issued", "Ordinary Shares Number", "Common Stock")` in order, and **"Common
Stock" is a par value in currency on some filers**, not a share count. Measured: across
122 reports where book value per share can be computed two ways, the two paths sit within
3× for all but five names, but a middle band of 1.7–2.9× — IBM 6.41 vs 16.44, AMAT 16.49
vs 48.75, LRCX, DE, UNP, CTAS, PG, EMR — is this fall-through, not real disagreement.

Not fixed here: the row feeds `red_flags`' balance checks, whose sub-score feeds the
financial-quality star rating, so changing the extraction silently re-rates published
reports. It needs its own change with its own before/after. **Mitigated in place**:
`category_lens` treats a >5× disagreement between the two paths as *unreliable* and
refuses to publish an asset-play claim rather than trusting either number.

### D3 — the back catalogue is thinner than the front

91 of 213 cached analyses have no `statements_raw` (added in v4 Phase C), and the four
intangibles rows added this wave exist only in analyses produced from now on. Every
consumer degrades to `n/a` with a stated reason. Expected, recorded so it is not
re-discovered as a bug.

---

## Lens 3 — Investment-analysis quality

### A1 — N4: one model outvoting four ✅ fixed

MSFT, 2026-07-30: `dcf_valid` stayed true at **−69.70 %** against a ±70 % invalidation
gate — surviving by **0.30 pp** — so the rule "DCF when valid, else consensus" published
**\$118.35** as `fair_price` against a live **\$390.54** and a 54-analyst consensus median
of **\$550**. The dashboard showed it as Fair Px and Upside.

New deterministic order in `intrinsic_value.choose_fair_price()`:
**blend** (≥3 valid models) → **blend_median** (when the models disagree ≥6.0×) →
**dcf** → **consensus** (≥3 analysts) → **omit**.

Two decisions inside that:

- **Do not simply drop the DCF.** On the 24-name sample `roe_residual_income` set the low
  in 12 cases against the DCF's 5, so excluding the DCF just relocates the artefact.
- **Under wide dispersion, the median.** The blend is a *mean*; a mean of five numbers
  spanning 40× is dominated by whichever model exploded. 6.0× is not a new threshold — it
  is the one wave 2.5 recalibrated on 59 reports for the "methods disagree materially"
  banner, so the anchor becomes robust at exactly the point the report starts warning.

Measured over 62 cached analyses: **42 blend · 13 blend_median · 5 consensus · 1 dcf ·
1 none.** MSFT's anchor moves \$118.35 → **\$303.28**. Median |anchor − price| gap: 31 %.

The anchor is now **computed in Python and copied verbatim into frontmatter**, not chosen
by the LLM from a prose rule. A structured number printed in a report belongs to a helper
(`SKILL.md:56`), and the prose rule is precisely what let the MSFT artefact through
without anything objecting.

### A2 — N3: a band that could not support the target it set ✅ fixed

adidas, 2026-07-30: a **3-year** P/E band whose *minimum* (25.44×) sat **above** the live
multiple (19.20×) and whose median reached **47.73×**, because FY2023 EPS approached zero
after the Yeezy termination. That median propagated into `justified_exit_pe`, into two of
the five intrinsic models, into a €608 forward target, and into an exit ladder whose first
trim rung was **2.9× the current price**.

**The fix is in two places, and the split was measured rather than reasoned.** Writing both
of N3's conditions into one usability test marked **41 of 48** cached bands unusable —
including ACN (16 years) and CSCO (14), where a single small-EPS year cannot move a median
at all. So:

1. an **earnings-collapse year is excluded from the series**, exactly as a negative-EPS
   year already was (EPS ≤ 15 % of the median |EPS|);
2. **`band_usability` applies only the depth floor** (4 clean years) to what survives;
3. `justified_exit_pe` returns `None` for an unusable band — the single funnel both
   `intrinsic_value` and the forward target read, so one guard covers both consumers, and
   both already degrade with a stated reason rather than a number.

Re-measured over 47 cached EPS histories: **44 usable · 3 unusable** (ADS.DE, ALFEN.AS,
ETOR — all 2–3 clean years), with 15 names dropping at least one collapse year. adidas is
the case the roadmap entry was written about, and it is now the case that refuses to
publish a target.

Bands still **render** when unusable, with their depth and their reason. Unusable is not
absent — the history stays visible; what it may not do is set a price.

### A3 — N5 stays open

Wave 2.1 made the peer-set tier visible and colours a sector proxy amber, so a reader can
now see when adidas is being ranked against Amazon and McDonald's. The **12 % peer weight
in the composite is unchanged**, because changing it moves the composite. Still open.

---

## Lens 4 — Metric scores and the decision flowcharts

**Composite weights, as implemented** (`WEIGHTS_V2_DEEP`): fundamentals 35 % · valuation
20 % · moat 12 % · peer 12 % · growth durability 8 % · management 8 % · market context 5 %.
`SKILL.md:75` and `:839` agree. Where management is unavailable the composite renormalises
over 0.92. **No drift found in the skill's own docs.** (An external note quoting
40/20/15/15/10/5 is the v1 weighting and is stale — corrected in the vault memory index.)

Inside `fundamentals`: Piotroski contributes 6 points, `gates_passed` 3, Altman 1. **That
is the channel through which every Lens-1 finding would reach the composite**, and the
reason none of them was acted on.

**M1 ✅ verified.** `_sources/Stocks - buy 5y.md` node `B` ("P/E < 25?") routed *both* Yes
and No to `C`, making the P/E gate inert and `Reject2` unreachable. Wave 2.3 fixed it
before rendering the PNG, so the committed image does not bake in the bug. Re-read this
session: `B -- No --> Reject2`, `B -- Yes --> C`. Correct.

**M2 — the diagram's ladder is not the implemented policy, and it was deliberately left
that way.** Three real divergences:

| Buy-5y source note | Implemented |
|---|---|
| revenue growth ≥ **10 %** | ≥ **8 %** |
| `P/E < 25` **then** `PEG < 2` (both required, sequential) | `P/E < 35` **OR** (`PEG < 2.5` **AND** `ROE > 20 %`) |
| — no node — | **Gate 3: FCF TTM > 0** |

The note is a **legacy source document** — the strategy input the system was built from,
not its specification. Rewriting its thresholds to match the code would destroy the record
of the original intent and make a later "why did we loosen the P/E gate?" unanswerable.
The caveat block added in wave 2.3 names all three divergences and points at
`STRATEGY_GUIDE.md §4` for the flowchart that tracks the code. **Recommendation:** keep it
that way; the divergences are a decision log, not a defect.

**M3 ✅ closed by §3.5.** `lynch_category()` covers 4 of Lynch's 6 categories and its
"cyclical" is the residual bucket (`5 % ≤ CAGR < 20 %` with `ROE < 10 %`) — no amplitude
test, no turnaround, no asset play. It is untouched (it feeds a scored component);
`category_lens` runs beside it and names the disagreements. See `docs/CATEGORIES.md`.

**M4 ✅ closed by §3.6.** The moat sub-score's Buffett ×1.25 multiplier keys on
`ROIC > 25 %`, and `compute_roic` deliberately returns `None` on net-cash balance sheets
(the VEEV guard). For those names — **12 of 147 measured** — the multiplier silently does
not fire. Correct behaviour, previously invisible in the report. Now stated. See
`docs/ROIC_vs_ROE.md`.

**M5 — a roadmap entry, not a defect.** R1 (shortlist supersede) was planned off
`ROADMAP.md` without checking the code; `update_shortlist._rank()` / `_supersedes()` have
been implemented since the v4.2 work Wave 0 committed. Removed from the roadmap in §3.4
rather than re-implemented.

---

## What this audit deliberately did not do

- **No weight or gate threshold was changed.** Every Lens-1 finding is real and every one
  of them would move a frozen composite. They are recorded with their measurements so that
  when G1's outcome data arrives (≈2026-10-17) the recalibration starts from evidence
  rather than from a fresh opinion.
- **No legacy source note was rewritten** to agree with the code. Divergence between the
  original strategy and the implementation is a decision log.
- **The `shares` extraction (D2) was not touched**, because it would silently re-rate 40+
  published reports through the red-flag sub-scores and the stars. It gets its own change,
  with its own before/after.
