# ⭐ Star ratings — the published bands

Five quality dimensions, 1–5 stars each, computed by `scripts/star_ratings.py`.

**This file is the contract.** A star scale with no published thresholds is not comparable
across companies, which is the entire reason the stars exist — "is this a 4-star balance
sheet?" has to mean the same thing for IBM and for Lynas. Every threshold below is the one
in the code; change one and change the other, or this document stops being true.

## Three rules that constrain the whole design

1. **100 % deterministic Python. No LLM residual, ever.** A star printed in a report is a
   structured number, so an LLM-set star breaks the ground-truth rule (`SKILL.md:56`)
   exactly as an LLM-set P/E would. Either a dimension is computed from the bands below, or
   it renders `n/a`. There is no third option.
2. **Overlay-only.** Stars never enter `scores.composite` (frozen at v2.2) and never change
   the verdict. They re-express what the analysis already found; they do not re-decide it.
3. **Absence is not a low score.** A missing input yields `None`, never 1 star — printing a
   damning rating for a company whose data simply failed to load is worse than printing
   nothing.

## How a star is produced

- Each **component** maps its value through four ascending cut points → 1…5. Bands are
  `>=`, so a value sitting exactly on a boundary takes the **higher** star.
- A **dimension** averages its computable components and rounds **half up** (3.5 → 4).
  Python's default banker's rounding would send 3.5 → 3 and 4.5 → 4, printing the same
  star for two companies half a star apart.
- Components are **equally weighted unless a weight column says otherwise**. Only one
  dimension (financial quality) uses weights, and the reason is stated there.
- A dimension needs **≥ 50 % of its component weight** computable, otherwise `n/a`.
  Coverage is measured in weight, not count, so a heavy component going missing registers
  as the bigger gap it is.
- **Overall** is the mean of the dimensions that earned a star, and is omitted unless at
  least **three** did — an overall resting on two dimensions reads like a summary of five.

## Honest proxies — stated, not hidden

Two things the request asks about cannot be measured from a numbers JSON, and are scored on
named proxies instead. They are named here because a star whose provenance is unstated is
indistinguishable from a guess:

| Wanted | Proxy actually used | Why it is defensible | What it is not |
|---|---|---|---|
| Revenue **recurrence** | `revenue_stability_0_1` — smoothness of the 5-year revenue series | A revenue line that does not lurch is evidence of repeat business | Not a disclosed subscription/ARR figure |
| **Pricing power** | `gross_margin_ttm` | Sustained gross margin is the clearest financial trace of pricing power | Not a read of contract terms or price lists |
| **Reinvestment quality** | `roic_ttm` | Return earned on capital already deployed is the best available guide to the return on the next unit | Not an incremental (ROIIC) measure |

---

## 1. Business model

*Revenue quality, unit economics, pricing power.*

| Component | Field | ★1 | ★2 | ★3 | ★4 | ★5 |
|---|---|---|---|---|---|---|
| Revenue stability | `revenue_stability_0_1` | < 0.55 | ≥ 0.55 | ≥ 0.70 | ≥ 0.82 | ≥ 0.92 |
| Gross margin | `gross_margin_ttm` | < 20 % | ≥ 20 % | ≥ 35 % | ≥ 50 % | ≥ 65 % |
| Revenue growth | `revenue_cagr_5y` | < 2 % | ≥ 2 % | ≥ 6 % | ≥ 12 % | ≥ 20 % |

## 2. Company economics

*Return on capital, margin structure, and whether returns clear their own cost.*

| Component | Field | ★1 | ★2 | ★3 | ★4 | ★5 |
|---|---|---|---|---|---|---|
| ROIC | `roic_ttm` | < 8 % | ≥ 8 % | ≥ 12 % | ≥ 18 % | ≥ 25 % |
| ROIC − cost of equity | `roic_ttm` − `intrinsic_value.capm.cost_of_equity` | < −2 pp | ≥ −2 pp | ≥ +2 pp | ≥ +7 pp | ≥ +14 pp |
| Operating margin | `operating_margin_ttm` | < 5 % | ≥ 5 % | ≥ 12 % | ≥ 20 % | ≥ 30 % |
| Net margin | `net_margin_ttm` | < 4 % | ≥ 4 % | ≥ 9 % | ≥ 15 % | ≥ 22 % |

**Why the spread sits beside the level, not instead of it.** A 12 % ROIC is excellent for a
utility and value-destroying for a high-beta grower. The absolute level answers "is this a
good business?"; the spread answers "is it creating value at *its* cost of capital?" Both
are worth a star. Cost of equity comes from the CAPM block `intrinsic_value.py` already
computes — no new maths, no new fetch.

**ROIC is deliberately `None` for cash-rich balance sheets** (the v4.2 `IC_MIN_FRACTION`
guard). Those names lose two of four components here and fall back on margins, which is the
correct treatment — see `ROIC_vs_ROE.md` when Wave 3.6 lands.

## 3. Competitive advantage

*Moat: the analysis' own moat sub-score, plus whether the returns behind it held.*

| Component | Field | ★1 | ★2 | ★3 | ★4 | ★5 |
|---|---|---|---|---|---|---|
| Moat sub-score | `scores.moat` (0–10) | < 2.0 | ≥ 2.0 | ≥ 4.0 | ≥ 6.5 | ≥ 8.5 |
| ROIC level | `roic_ttm` | < 8 % | ≥ 8 % | ≥ 12 % | ≥ 18 % | ≥ 25 % |
| ROE durability | `roe_ttm / roe_5y_avg` | < 0.55 | ≥ 0.55 | ≥ 0.75 | ≥ 0.92 | ≥ 1.05 |

`scores.moat` is rescaled rather than re-derived: it is already a judgement made under
published rules, and computing a second, differently-shaped moat number would leave the
report arguing with itself.

Durability is a **ratio, not a difference** — a 4-point ROE drop means something different
at 40 % than at 8 %. A wide moat score sitting on decaying ROE is exactly the case this
component exists to surface.

## 4. Financial quality

*Piotroski, Altman and the red-flag scanner — three co-equal sources.*

| Component | Field | Weight | ★1 | ★2 | ★3 | ★4 | ★5 |
|---|---|---|---|---|---|---|---|
| Piotroski F-score | `piotroski_fscore` (0–9) | **2.0** | < 3 | ≥ 3 | ≥ 5 | ≥ 7 | ≥ 8 |
| Altman Z | `altman_zscore` | **0.5** | < 1.8 | ≥ 1.8 | ≥ 2.7 | ≥ 3.5 | ≥ 5.0 |
| Statement quality | mean of `red_flags.{income,balance,cashflow}.subscore_0_10` | 1.0 | < 3.0 | ≥ 3.0 | ≥ 5.5 | ≥ 7.5 | ≥ 9.0 |

Altman's cut points are the published grey-zone ones (< 1.8 distress, > 3.0 safe) stretched
to five steps.

**Why this is the only weighted dimension.** Equal weights produced a *flat column* on real
names: 9880.HK printed four stars off a Piotroski of 3/9, because an Altman Z of 8.9 pinned
that component at five. That is Altman behaving as designed — above its own 3.0 "safe"
threshold it carries **no further information**, so every solvent company maxes it, and an
unweighted average let one saturated ratio outvote a nine-signal composite. Piotroski
aggregates nine tests across all three statements; Altman is a single solvency score.

**The scanner counts as ONE component, not three.** Counting its sub-scores separately
over-weighted a single source and put screens over a coverage cliff: a screen has Piotroski
and Altman but no scanner, so it scored 2/5 = 40 % and printed `n/a` for a dimension its two
indicators answer perfectly well. Measured on the 2026-08-15 IBM run.

## 5. Capital allocation

*What management does with the cash — the Borja v2.1 fields, already computed.*

| Component | Field | ★1 | ★2 | ★3 | ★4 | ★5 |
|---|---|---|---|---|---|---|
| Net payout yield | `capital_returns.net_payout_yield` | < 0.5 % | ≥ 0.5 % | ≥ 2 % | ≥ 4 % | ≥ 6 % |
| Share count 5y *(lower is better)* | `shares_change_5y_pct` | ≥ +5 % | ≥ +1 % | ≥ −2 % | ≥ −8 % | < −8 % |
| Reinvestment return | `roic_ttm` | < 8 % | ≥ 8 % | ≥ 12 % | ≥ 18 % | ≥ 25 % |

**Why reinvestment return is here.** Scoring payout alone would mark down exactly the
company compounding best: a business retaining earnings at 25 % ROIC is allocating capital
well with a 0 % payout, and a 6 % payout funded by debt is not.

---

## Calibration on real names (2026-08)

Run at the bands above. Included so the scale can be judged against companies rather than
against itself.

| | MPWR | CSCO | IBM *(screen)* | 9880.HK | SHA0.DE |
|---|---|---|---|---|---|
| Business model | ★★★★☆ | ★★★★☆ | ★★★★☆ | ★★★★☆ | ★★★☆☆ |
| Company economics | ★★★★★ | ★★★★☆ | ★★★☆☆ | ★☆☆☆☆ | ★☆☆☆☆ |
| Competitive advantage | ★★★★☆ | ★★★★☆ | ★★★★☆ | ★☆☆☆☆ | ★☆☆☆☆ |
| Financial quality | ★★★★☆ | ★★★★★ | ★★★★☆ | ★★★☆☆ | ★★★☆☆ |
| Capital allocation | ★★★☆☆ | ★★★☆☆ | ★★★☆☆ | ★★☆☆☆ | ★★☆☆☆ |
| **Overall** | **4.0** | **4.0** | **3.6** | **2.2** | **2.0** |

Three things to read off this table rather than take on trust:

- **The scale discriminates.** Wide-moat compounders land at 4.0 and weak names at 2.0, and
  the dimensions do not all move together — MPWR is 5★ on economics and 3★ on capital
  allocation, which is the correct reading of $8M of buybacks against a *rising* share count.
- **A high composite does not buy a high star.** MPWR scores 4★ on financial quality, not
  5★, because its Piotroski is 6/9 despite a fortress balance sheet. The stars read the
  inputs, not the verdict.
- **Coverage is reported, not hidden.** SHA0.DE rates financial quality on Piotroski alone
  (57 % coverage, weighted) and the card prints that percentage beside the stars. Below
  50 % the dimension renders `n/a` instead — absence and a low score never look the same.

## Changing a band

The stars are comparable over time only if the bands are stable, so a change is a **version
event**, not a tweak:

1. Change the threshold in `star_ratings.py` **and** in the table above.
2. Bump `schema` in `compute()` (`star_ratings_v1` → `v2`) so old JSONs are distinguishable.
3. Re-run the calibration table above and paste the new numbers — if the ranking of those
   five names changes, say why in `CHANGELOG.md`.
4. Note it in `CHANGELOG.md`. Stars printed under different bands are not comparable, and
   nothing in the report will say so unless you do.
