# bd-stocks-daily

A daily stock-evaluation **Claude Code skill**. Every weekday at 13:30 it picks names from a pre-filtered
quality pool, extracts ground-truth fundamentals in Python, layers LLM narrative on the deep-dive, computes
a transparent composite score, and writes tiered Obsidian reports + an HTML dashboard + an email digest.

> **Cardinal rule:** every structured number (revenue, P/E, margins, ROE, debt, prices, ROIC, EV/EBIT) comes
> **only** from Python helpers (yfinance/stockanalysis). The LLM writes *narrative* — it never sources numbers
> from filings. This boundary is the system's spine; don't cross it.
> Two documented v3.1 exceptions, each requiring source + as-of date on every figure: revenue segments
> (LLM-extracted from the official filing → `_segments/`) and macro valuation/country data (WebFetch → `_macro/`).

Schema **v2.2**. Runs via Windows Task Scheduler (`StocksDaily`, daily 13:30) → `C:\Github\.scripts\stocks-daily.bat`,
under a **30-minute wall-clock budget**: 3 tickers (1 deep + 2 screens), **1800 s timeout**, then the email. The growth
lens is a separate task (`StocksGrowth`, 12:45) so it can never delay the digest — see `docs/SCHEDULING.md`.

### Where the documentation lives

| File | Holds |
|---|---|
| `docs/CHANGELOG.md` | version history — what shipped, per version |
| `docs/ROADMAP.md` | the open backlog only — reason + trigger per item, never DONE rows |
| `docs/AUDIT_v43.md` | the v4.3 four-lens audit: findings, fixes, and what was deliberately left alone |
| `docs/SCHEDULING.md` | the ten scheduled tasks, their order, and the 30-minute budget |
| `docs/STAR_RATINGS.md` | the published bands behind the ⭐ quality ratings |
| `docs/CATEGORIES.md` | cyclical / turnaround / asset-play thresholds (`category_lens.py`) |
| `docs/ROIC_vs_ROE.md` | which return metric applies, and why (`roic_lens.py`) |
| `StocksDaily/docs/STRATEGY_GUIDE.md` | the *why* — mandate, the four metric sets and their coverage (§6, §6b–§6d, §7) |
| `StocksDaily/docs/MANUAL.md` | operator manual — running it by hand, the universe, troubleshooting |

Each `docs/*.md` above whose thresholds appear in a report is a **contract**: a test asserts
the document and the code still agree, so a threshold cannot be changed in one place only.
The heavy `Stocks*` jobs serialise through `C:\Github\.scripts\job_lock.ps1` so a Task
Scheduler catch-up burst cannot run four of them at once (incident 2026-08-15).

---

## What it does — the 22-node pipeline

| Node | Stage | Runs on |
|------|-------|---------|
| 0.5 | Thesis check (prior-pillar integrity) | re-eval only |
| 1 | Pick 1 deep + 2 screens (183-day dedupe, stale-shortlist fallback) | always |
| 1.5 | Industry-cache freshness (<90d) | deep |
| 2 | **Analyse** — 7-gate + Piotroski + Altman + DCF + peer + provisional composite | all 3 |
| 2.2 | **Financial history** — quarterly EBITDA/FCF series (AV/yfinance, `_fin_history/` cache) + hybrid 4Q forecast | deep |
| 2.3 | **Valuation depth (v4-B)** — own-history P/E & P/S bands, FY+3 forward target + IRR, sensitivity, 5-model intrinsic blend + MoS | deep |
| 2.4 | **Red-flag scanner (v4-C)** — 3-statement checks + Beneish M + earnings-quality pills → `red_flags` | deep |
| 2.5 | LLM narrative — business model, management score, growth, 3-layer risk, bear case, SWOT, revenue segments → finalize composite | deep |
| 2.55 | **Exit & thesis plan (v4-A)** — target exit P/E, profit ladder, thesis-broken trigger, yield-on-cost → `exit_plan` | deep |
| 2.56 | **Return profile (v4-E)** — α/β + CAPM + 10/15y price CAGR + Lynch prior + portfolio fit vs URTH (`alpha_beta.py`) → `alpha_beta` | deep |
| 2.57 | **Watch-list maintenance (v4-E)** — quality-name-held-back-by-price → `_watchlist.csv` (`watchlist.py`) | deep |
| 2.58 | **Opinion panel (v4-G)** — 3 independent-model personas (value/growth/contrarian) 0–100 via Groq→Gemini (`second_opinion.py` + `llm_client.py`) → `opinion_panel` | deep |
| 2.59 | **News & sentiment (v4.1-H)** — yfinance news (+1 optional NewsAPI query) → 1 LLM call → stock & market dials −1..+1 (`news_sentiment.py`) → `news_sentiment` | deep |
| 2.6 | **Macro §8 snapshot** — indices/valuation-vs-history/country + RSP/SPY breadth & 11-sector tendencies (yfinance `macro_breadth.py`) + Buffett/M2/forward-profit; cache `_macro/{date}.md` | once per run |
| 3 | Render charts (price, 7-axis radar, peers, DCF fan, EBITDA+FCF, rel-perf 30mo, segments) | deep |
| 3.5 | **Technical score + GO/NO-GO** (for fundamentally-strong names) | deep |
| 4 | Find official reports — narrative only (no numbers) | deep |
| 5 | Write report (deep ≈2000 words / 1-min screen) | all |
| 5.5 | Auto-cascade screen→deep when verdict ≥ 7.5 (invest) | conditional |
| 5.7 | **Render HTML report (v4-F)** — self-contained static HTML primary artifact: answer-first header + action verb, 5-axis snowflake, fair-value gauge + range bar, A/B/C/E/G cards, base64 charts, **equity-vs-enterprise metric families + greyed cheat-sheet** (tooltip/`<details>`/print-column) and optional daily `index.html` hub (`--index`) (`render_report.py` + `report_template.html` + `metrics_glossary.py`) | all |
| 6 | Update `_log.csv` (v1→v2 auto-migrate) + shortlist + catalyst calendar | always |
| 7 | Regenerate dashboard (incl. **v4.1-I screener** over the full pool) + email digest | always |
| 8 | Stdout summary | always |

Numbers enter only at node 2; the LLM (2.5) and WebFetch (4) never write structured fields.

---

## Charts

Two renderers, one visual system. `chart_theme.py` holds the palette and the shared axes/legend/trend helpers used by all 8 matplotlib charts. `chart_browser.py` re-renders the two charts a reader actually studies — EBITDA/FCF and relative performance — as HTML/CSS/SVG screenshotted by headless Chromium (playwright is already present for pdfgen, so no new dependency). It is fallback-first: every entry point returns `False` instead of raising, and `render_charts.py` then uses the matplotlib version, so the unattended 17:00 job cannot regress. Set `BD_CHARTS_BROWSER=0` to force matplotlib. Both renderers consume identical numbers.

**PNGs are transparent.** A static image cannot follow the reader's theme — Obsidian will not swap it — so the charts paint no background and adopt whatever page they land on (light Obsidian, dark Obsidian, a white email client, paper). Two consequences worth preserving: ink is **mid-tone**, chosen for ≥3:1 against both a light and a dark surface (~3.9:1 is the ceiling for any single colour, so AA large-text passes and AA body-text cannot on both at once); and the categorical palette is stepped into the **dark** lightness band L [0.48, 0.67], a strict subset of the light band, validated in both modes with `validate_palette.js`. Surface-coloured knockouts are gone — marker rings use `RING`, chips and label halos are border-only, since an opaque fill prints as a pale blob on a dark page.

## Scoring (composite v2.2)

`WEIGHTS_V2_DEEP` — locked, weight-neutral across v2.2:

| Factor | Weight | Notes |
|--------|-------:|-------|
| Fundamentals | 0.35 | Piotroski + 7 gates + Altman |
| Valuation | 0.20 | P/E · PEG · FCF-yield · DCF upside · **EV/EBIT** (folded inside the 0–10 cap) |
| Moat | 0.12 | ROE level/stability + margin · **Buffett opt-in: ROIC > 25% → ×1.25** |
| Peer | 0.12 | percentile vs industry peers |
| Growth durability | 0.08 | CAGR + stability + Lynch category |
| Management | 0.08 | LLM-derived (deep only); screens renormalise the other 6 (÷0.92) |
| Market context | 0.05 | VIX regime (informative, non-decisive) |

**Verdict bands:** great ≥9.0 · invest ≥7.5 · review ≥6.0 · fair ≥4.0 · reject <4.0.

**v2.2 additions:** ROIC + EV/EBIT + ROCE (Magic-Formula proxy) · Buffett moat multiplier · news-event time
decay `I(t)=I₀·e^(−λΔt)` (7-day half-life, UX freshness only) · **Gate-5 growth bypass** (the net-margin gate
is waived when revenue CAGR ≥ 25% **and** ROIC ≥ 15% **and** FCF/revenue improving YoY — records
`gate_5_bypassed` + reason).

---

## Dashboards (single-scroll cards → `_dashboard.html`)

Rendered by `build_dashboard.py` (stdlib-only, so it regenerates even when market APIs are down). Each card
reads precomputed JSON / report frontmatter — the dashboard computes nothing.

- **Overview** — shortlist, composite scores, verdicts.
- **Technical** — GO/NO-GO, entry zone, ATR-based stop, for fundamentally-strong names.
- **Portfolio** — held positions from BankBD (read-only) with a Hold / Buy-More / Sell engine + cited triggers.
- **Thesis** — pillar × status × conviction (FS2 framework) + Buy/Hold/Sell from stored narratives.
- **Broker** — cost-by-market comparison across 9 brokers with per-market recommendations.

---

## Data architecture

- **Primary:** yfinance (all fundamentals + prices), global incl. EU/Asia small-cap.
- **3-layer validation:** Layer 0 internal consistency → Layer 1 external cross-check (FMP US / Twelve Data EU /
  Stooq non-US price — *Stooq CSV currently JS/proof-of-work-gated, degrades to L0+L2*) → Layer 2 price self-heal.
- **Global markets:** US · EU · TW/CN/HK/IN/KR/JP — values reported in **local currency + EUR**, with
  accounting-standard caveats (IFRS / US-GAAP / JP-GAAP / China-GAAP) surfaced in `data_warnings`.

---

## Scripts

`analyze_ticker.py` (engine + scoring + validation) · `finalize_score.py` · `pick_candidates.py` ·
`financial_history.py` · `valuation_bands.py` + `intrinsic_value.py` (v4-B) · `red_flags.py` (v4-C) · `exit_plan.py` (v4-A) · `alpha_beta.py` + `watchlist.py` (v4-E) · `second_opinion.py` + `llm_client.py` (v4-G) · `news_sentiment.py` (v4.1-H) · `version_gate.py` (v4.1 `--version`) · `render_report.py` + `report_template.html` + `metrics_glossary.py` (v4-F) · `macro_snapshot.py` + `macro_breadth.py` (v4-D) ·
`technical_score.py` · `portfolio_sync.py` + `portfolio_dashboard.py` · `thesis_dashboard.py` ·
`broker_compare.py` (+ `brokers.yaml`) · `markets.py` · `render_charts.py` · `update_log.py` ·
`update_shortlist.py` · `build_dashboard.py` · `send_email.py` · `find_reports.py` · `get_narrative.py` ·
`ensure_industry_cache.py` · `thesis_check.py` · `peers.json`.

Prompts: `prompts/01_business_model.md` … `05_bear_case.md`, `industry_*.md`, `_style_rules.md`.

---

## Run & test

```bash
# Runtime env is the BD_Finance uv venv (yfinance, pandas, etc.)
cd C:\Github\BD\Finance\BD_Finance

# Analyse a ticker
uv run python "C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\analyze_ticker.py" --ticker ASML.AS --mode deep

# Regenerate the dashboard
uv run python "...\scripts\build_dashboard.py"

# Tests (1840: 1839 pass + 1 opt-in Chromium skip, as of v4.3.5)
# --with-requirements, NOT --with pytest: `uv run --with pytest` builds an env holding
# pytest and nothing else, so it CANNOT COLLECT 13 of the test files (matplotlib,
# yfinance, yaml, pandas, numpy). Every count published before 2026-08-18 came from a
# different command than the documented one -- roadmap B7.
uv run --with-requirements requirements-dev.txt pytest tests -q
# ...or, faster, against the system interpreter the pipeline itself uses:
python -m pytest tests -q
```

Or invoke the whole pipeline as a Claude Code skill: **`/bd-stocks-daily`**.

**Outputs** land in `C:\BD_Obsidian\Personal\Finance\StocksDaily\` (`_prefiltered.yaml`, `_universe.yaml`,
`_log.csv`, `_shortlist.md`, `_dashboard.html`, `docs/`, reports `YYYY-MM-DD_TICKER_*.md`).

---

## Related

- **`/bd_stocks_daily_growth`** — parallel growth-lens sibling skill (Rule of 40, NRR, runway; Gate-5 bypassed by design).
- **`/bd-stocks-prefilter`** — weekly (Mon 14:00) quality sweep that builds `_prefiltered.yaml`.
- Design docs: `StocksDaily\docs\` (`AUDIT_v3`, `SCORING_REVIEW_v3`, `DATA_INFRA_REVIEW_v3`, `MARKET_COVERAGE_v3`, `STRATEGY_GUIDE`, `MANUAL`).

*Personal project. Market data is best-effort; reference fee/coverage data needs periodic manual refresh. Not investment advice.*
