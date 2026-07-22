# v4 reference sources — from Bruno's 💵 bookmark folder (2026-07-20)

Sources he actually uses, mapped to v4 phases. (Exported from Chrome `bookmarks_7_20_26.html`, folder 💵 = 48 links + "Fundamentals - Analisar Stocks" = 14.)

## Macro §8 (Phase D) — market-regime gauges he follows
- **Buffett Indicator** (Market Cap / GDP) — longtermtrends.net, currentmarketvaluation.com → ADD to §8
- **Shiller CAPE** + S&P 500 P/E / P/B / earnings / inflation-adj — multpl.com (already a macro source) → ADD CAPE + P/B
- **S&P 500 P/E TTM with ±SD bands** — gurufocus.com (matches scan p28) 
- **VIX** — FRED VIXCLS (already used); M2 → FRED M2SL (Phase D plan)
- Large-cap vs small-cap regime — longtermtrends.net
- IMF macro data — imf.org

## Valuation & fair-value visual (Phase B design north-star)
- **Jitta** — "Jitta Score" (0-10) + "Jitta Line" (fair-value line vs price over time) → our composite score + valuation band visual
- **GuruFocus** — "GF Value" predicted fair-value line + "GF Score"; **Warning Signs** panel → Phase C red-flag scanner model
- finbox.com (DCF/fair value), TIKR (multiples / 2-min model), Koyfin (tearsheets)

## Data sources for long-history metrics (yfinance is weak at these)
Needed for Phase B (10y P/E band), Phase E (α/β, 10/15y CAGR):
- **Twelve Data** — Bruno HAS an API key (twelvedata.com/account/api-keys)
- **Alpha Vantage** — API key referenced; fundamentals + FX history
- **Financial Modeling Prep (FMP)** — historical ratios/statements
- Nasdaq Data Link, OpenBB, stockrow, macrotrends, stockanalysis

## Screeners (relevant to prefilter, not report)
Finviz, Zacks, GuruFocus all-in-one, Yahoo, TipRanks (Smart Score), Graham Net-Net (gurufocus)

## AI research platforms (format/UX inspiration)
Fiscal.ai (ex-FinChat), Perplexity Finance, TipRanks, Stock Events

> Merge with the external design-research agent output before finalizing the Phase F template.

## Scope reconciliation (adversarial audit 2026-07-20)
The locked `sample_report_v2.html` intentionally shows a SUBSET of the gauges above: Macro §8 renders Buffett Indicator + CAPE/P-S + M2 only (VIX, S&P P/B, large-vs-small-cap are Phase D data, addable later); the fair-value visual is point-in-time (a Jitta-style fair-value *time-series* line is a v4.1 candidate, not in the locked template); 10/15y CAGR (Phase E) not yet a template slot. `assets/bdfinance_logo_wordmark.svg` is currently unused — the template renders the wordmark as styled text; keep the SVG as brand reference. Full audit: `AUDIT_v4spec_20260720.md`.
