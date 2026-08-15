# ROIC vs ROE — which return metric applies, and what it is saying

Doctrine for `scripts/roic_lens.py`. **This file is the contract**: every threshold below is
the one in the code, and `tests/test_roic_lens.py` asserts the pairing. Change one, change
the other, or this document stops being true.

## TL;DR — the five sentences that matter

1. **Use both.** ROE is the return to *equity holders* and is inflated by leverage; ROIC is
   the return on *all* invested capital and is leverage-neutral.
2. **A high ROE with high debt and a low ROIC is a financing artefact, not a moat** — the
   system flags it at `ROE > 20 %` **and** `D/E > 1.0` **and** `ROIC < 12 %`.
3. **ROIC vs WACC is the economic test.** Below its cost of capital, a business destroys
   value as it grows. No cost of equity in the JSON → no WACC, never an assumed one.
4. **For banks and insurers ROIC is meaningless** — debt is raw material, not financing.
   ROE, and ROTE where tangible equity is derivable.
5. **ROIC is deliberately `None` on net-cash balance sheets**, and the Buffett moat
   multiplier then silently does not fire. Correct, previously invisible, now stated.

---

## 1. What each metric answers

| | ROE | ROIC |
|---|---|---|
| Numerator | net income | NOPAT = EBIT × (1 − effective tax) |
| Denominator | shareholders' equity | total debt + equity − cash |
| Answers | "what did *my* capital earn?" | "what does the *business* earn?" |
| Sensitive to leverage | **yes** — buybacks and debt raise it mechanically | no |
| Sensitive to acquisitions | mildly | **yes** — goodwill sits in invested capital |

Neither is a substitute for the other. ROE is the shareholder's number; ROIC is the
business's. The failure mode this doctrine exists to prevent is quoting the first and
calling it evidence of the second.

## 2. Leverage-manufactured ROE — the flag

`roic_lens.leverage_manufactured_roe` fires only when **all three** hold:

| Condition | Threshold | Constant |
|---|---|---|
| ROE is high | `> 20 %` | `LEV_ROE_MIN` |
| the balance sheet is levered | `D/E > 1.0` | `LEV_DE_MIN` |
| the business does not earn it | `ROIC < 12 %` | `LEV_ROIC_MAX` |

All three, because any one alone is unremarkable: a 28 % ROE on a 19 % ROIC is a good
business, a 2.1× D/E with a 19 % ROIC is a good business that borrows, and a 12 % ROE on
2.1× debt is simply mediocre.

It is **not a veto** and it does **not** touch the composite. It is the sentence a reader
needs before treating a high ROE as evidence of quality. `D/E` is already stored as a ratio
(`analyze_ticker` divides yfinance's percentage by 100), so `1.0` means one-to-one.

Measured on the corpus: three names flagged out of 147 with usable statements — IQVIA,
Volvo B and Waste Management, each a genuinely levered structure carrying a modest ROIC.

## 3. ROIC vs WACC — the economic-value test

```
WACC = ke · E/(D+E) + kd · (1 − t) · D/(D+E)
```

| Input | Source | Refusal condition |
|---|---|---|
| `ke` cost of equity | `intrinsic_value.capm.cost_of_equity` (CAPM, already computed) | absent → **no WACC** |
| `kd` cost of debt | interest expense ÷ **average** gross debt | outside 0–25 % → refused |
| `t` effective tax | `1 − net income / pretax income`, clamped `[0, 0.35]` | falls back to 21 % |
| weights | market cap vs gross debt | no market cap → no WACC |

Verdict band, `WACC_MARGIN = 2 pp`:

| Spread (ROIC − WACC) | Verdict |
|---|---|
| `> +2 pp` | creates value |
| `−2 pp … +2 pp` | marginal |
| `< −2 pp` | **destroys value as it grows** |

Three deliberate choices:

- **Average debt, not year-end.** A company that refinanced mid-year carries a year-end
  debt figure the interest never applied to.
- **The same tax clamp as `compute_roic`.** One company must not carry two different
  effective tax rates in one report.
- **No cost of equity ⇒ no WACC.** Assuming one would put an invented discount rate behind
  a value-creation verdict — the exact failure roadmap **N4** records for the DCF (MSFT's
  `fair_price` of \$118.35 against a live \$390.54).

## 4. Capital intensity, goodwill, and which ROIC is being quoted

For asset-light names ROIC is distorted twice: invested capital is small, and for
acquisitive companies most of what remains is goodwill.

| Signal | Threshold | Constant |
|---|---|---|
| asset-light | net PP&E / total assets `< 15 %` | `ASSET_LIGHT_PPE_SHARE` |
| goodwill-heavy | (goodwill + intangibles) / equity `> 30 %` | `GOODWILL_HEAVY_SHARE` |

Where both are derivable the block quotes **ROIC** and **ROIC ex-goodwill** side by side:

- **with goodwill** = the return on what was *paid* for the businesses,
- **ex-goodwill** = the return on how they *operate*.

They answer different questions and a serial acquirer's are far apart. When removing
intangibles drives invested capital to zero or below, ex-goodwill renders `None` — that is
the same divide-by-almost-zero territory rule 5 exists for.

The intangibles rows (`goodwill`, `intangibles`, `goodwill_and_intangibles`,
`net_tangible_assets`) were added to `analyze_ticker._STMT_ROWS` in v4.3 wave 3. They are
read from the balance frame already in memory — no fetch, no API call. The **combined** row
wins when present, so an acquisitive balance sheet's largest line is never counted twice.

## 5. When ROIC is deliberately `None`

`analyze_ticker.compute_roic` returns `None` once invested capital falls below
`IC_MIN_FRACTION = 5 %` of the gross capital base — the net-cash case. VEEV held cash of
7.31bn against equity of 7.28bn and printed **ROIC 13,671 %**, which tripped the >25 %
Buffett moat opt-in on a company earning ROE 13.9 % and ROCE 12.5 %.

Two consequences, the second previously undocumented:

1. `roic_lens.preferred_metric` falls back to **ROE**, and says why in the report.
2. The **Buffett moat multiplier (×1.25) is keyed on ROIC > 25 %**, so for these names it
   **silently does not fire**. That is the correct outcome — the input is an artefact — but
   until now nothing in the report said so. `buffett_multiplier.note` now does.

Measured on the corpus: 12 of 147 names carry a suppressed ROIC, VEEV among them.

## 6. Financials — the sector exception

For banks and insurers, debt is **raw material**, not financing: "invested capital" has no
operating meaning and ROIC is not the right instrument. The lens routes them to **ROE**, or
**ROTE** (net income / tangible equity) where the intangibles rows make tangible equity
derivable — the sharper metric for banks carrying acquired goodwill.

Detection is sector-first (`Financial Services`) with an industry-substring fallback
(`bank`, `insurance`, `capital markets`, `asset management`, `credit services`, `mortgage`),
because yfinance files exchanges and asset managers inconsistently. 22 of 147 corpus names
route this way.

`INGA.AS` is in the portfolio today, so this is a live case and not a hypothetical.

## 7. What this does **not** do

- It does not change `scores.composite` (frozen at v2.2), any gate, or the verdict.
- It does not recompute ROIC or ROE — it reads what `analyze_ticker` already produced and
  says which one applies and what it means.
- It does not recalibrate the moat sub-score's Buffett multiplier. That is a weight change,
  which is roadmap **G1/G2** territory and blocked on backtest data (≈2026-10-17).
