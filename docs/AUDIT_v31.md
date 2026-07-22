# Audit report — v3.1 upgrade (2026-07-15)

Item 8 of the v3.1 request: audit the finished work, fix anything incorrect, buggy, inconsistent or false. This file records what was checked, what was found, and what was fixed.

## Scope delivered (items 1-7)

| # | Feature | Delivered by |
|---|---------|--------------|
| 1 | Quarterly EBITDA + FCF chart (top of deep report) | `scripts/financial_history.py` + `chart_ebitda_fcf` (render_charts) + Phase 2.2 |
| 1.1 | 4-quarter hybrid forecast | forecast block in `financial_history.py` (consensus revenue × trailing median margin; trend fallback; suppression <4Q) |
| 2 | Top metrics strip | `top_strip` block in `analyze_ticker.py` + template strip (deep + screen) |
| 3 | Revenue-sources chart, 3 FYs | `_segments/{TICKER}.json` (LLM extraction, Phase 2.5 step 7b — documented ground-truth exception) + `chart_revenue_segments` |
| 4 | €1500 broker recommendation (composite ≥ 7.0) | existing `broker_compare.py --small 1500` + §2.19 + suffix→MARKET_KEY table |
| 5 | Promoted thesis/risk callouts | `[!success]`/`[!danger]` blocks after TL;DR — parser labels `**Thesis**:`/`**Risks**:` preserved |
| 6 | 30-month relative-performance chart | `chart_relperf` + extended `BENCH_BY_SUFFIX` (22 suffixes, live-verified) + `SECTOR_ETF` map |
| 7 | Daily macro section (§4) | `scripts/macro_snapshot.py` + `prompts/macro_daily.md` + `_macro/` daily cache + Phase 2.6 |

## Verification performed

1. **Test suite**: 188 passed (final run, after the A2 fix) — includes 47 new tests (financial_history 23, macro_snapshot 15, segments schema 9, bench-map assertion). Note: the A2 fix persists a small additive `_forecast_inputs` block in the fin-history JSON (underscore-prefixed; render_charts ignores it).
2. **Dry-run, US path (NVDA)**: analyze → financial_history → render_charts into `_dry/`. Alpha Vantage delivered **40 quarters + 6 annual years**; AV budget counter at 2/20 after the run; cache-hit re-run confirmed zero network.
3. **Dry-run, non-US path (2330.TW)**: yfinance fallback delivered 6 quarters + 5 annual years (TWD); forecast basis `consensus_revenue_x_trailing_margin`; `top_strip` **13/13 filled**; all 6 applicable charts rendered (segments = designed skip, no `_segments` JSON yet); relperf correctly used **^TWII** + XLK with the "US sector ETF" footnote. Charts visually inspected — correct.
4. **Macro**: `--check` directive correct on empty/missing/fresh states (15 unit tests); live `--fetch` returned all 13 tickers; `_macro/2026-07-15.md` exists with per-figure sources (multpl/FactSet/Trading Economics) — tonight's run will correctly treat it as fresh.
5. **Parser regression (the adversarial-review BLOCKER)**: `build_dashboard.py` regenerated both dashboards; thesis/risk extraction confirmed intact (labels preserved in template).
6. **Broker JSON**: `--small 1500 --out` emits `markets[]` rows with `key/rows/recommendation` — matches the §2.19 instructions exactly.

## Defects found during audit → fixed

| # | Defect | Fix |
|---|--------|-----|
| A1 | `render_charts.py` resolved `_fin_history/` and `_segments/` strictly beside the IMG output dir, so `--output-dir _dry/IMG` (dry-run) silently skipped the EBITDA/segments charts even when production cache existed | Fallback lookup to the production StocksDaily root when the beside-IMG path is missing (2 lines) |
| A2 | `financial_history.py` returned the **cached forecast verbatim on cache hits** — with an 80-day TTL, a forecast (and its basis) could be a quarter stale even when a fresh `--analysis-json` consensus was supplied | On cache hit with `--analysis-json`, the forecast is recomputed from the cached series + fresh consensus (pure computation, no network) and the cache's forecast block is refreshed; `fetched_at` untouched. New regression test |
| A3 | NVDA dry-run produced a mostly-null `top_strip` (6/45 fund fields), `sector: null`, composite 3.65/reject | **Not a code defect** — Yahoo quoteSummary returned transient 404s during the run (verified in stderr). The new code degraded correctly: None-safe strip, honest trend-basis label. Same-day MSFT and 2330.TW runs produced fully-populated strips. No fix needed; noted so a future reader doesn't chase it |

## Consistency checks on SKILL.md / README

- Pipeline count updated 12 → 14 nodes in both files; no stale references remain (grep clean).
- Section numbering: §2.19 and §4 don't collide (previous max was §2.18 / §3).
- `schema_version` stays "2.2" — scoring weights are untouched by v3.1; the new frontmatter keys are additive.
- Ground-truth rule now lists exactly two documented exceptions (segments, macro), both requiring source + as-of date per figure.
- Deviations accepted from implementers: `.LS` benchmark corrected to `PSI20.LS` (^PSI20 is delisted on Yahoo; previous ^STOXX50E mapping was wrong region granularity); yfinance capex sign handled by addition (yfinance reports negative outflows); AV annual reports parsed for free (same 2 calls).

## Known limitations (by design, stated in reports)

- 10-year quarterly depth is only achievable for US listings (Alpha Vantage). Non-US tickers get ~5-6 quarters + annual FY bars; the chart title always states the real depth and source.
- Forecast is a **derived estimate** (consensus revenue × trailing median margin), never analyst EBITDA/FCF guidance — labelled on the chart.
- S&P 500 EV/EBITDA has no reliably free source; today's macro file correctly shows "not available" rather than an estimate.
- Segment data is LLM-extracted from official filings — the single structured-number exception, always labelled with the source URL.
- Email inline-image test deferred to the next scheduled run: `inline_image_refs` is filename-agnostic (generic `IMG/` cid rewrite), and re-sending today's digest out-of-band would duplicate the 17:00 email. Check tomorrow's digest renders the 3 new PNGs.

---
*Analysis written by Claude Fable 5 · bsdias©2026*
