# bd-stocks-daily

A daily stock-evaluation **Claude Code skill**. Every weekday at 17:00 it picks names from a pre-filtered
quality pool, extracts ground-truth fundamentals in Python, layers LLM narrative on the deep-dive, computes
a transparent composite score, and writes tiered Obsidian reports + an HTML dashboard + an email digest.

> **Cardinal rule:** every structured number (revenue, P/E, margins, ROE, debt, prices, ROIC, EV/EBIT) comes
> **only** from Python helpers (yfinance/stockanalysis). The LLM writes *narrative* — it never sources numbers
> from filings. This boundary is the system's spine; don't cross it.
> Two documented v3.1 exceptions, each requiring source + as-of date on every figure: revenue segments
> (LLM-extracted from the official filing → `_segments/`) and macro valuation/country data (WebFetch → `_macro/`).

Schema **v2.2**. Runs via Windows Task Scheduler (`StocksDaily`, daily 17:00) → `C:\Github\.scripts\stocks-daily.bat`.

**v3.1 (2026-07-15)**: quarterly EBITDA+FCF chart with hybrid 4Q forecast (`financial_history.py`, Alpha Vantage for US listings + yfinance fallback, 80-day cache, 20-call/day AV guard); top-of-report metrics strip (`top_strip`); 3-year revenue-segments chart; 30-month relative-performance chart vs region benchmark + sector SPDR; promoted thesis/risk callouts; €1500 broker-recommendation section (composite ≥ 7.0, reuses `broker_compare.py`); daily macro section with `_macro/` cache (`macro_snapshot.py` + `prompts/macro_daily.md`).

**v4 wave-1 · Phase B (2026-07-22)**: valuation depth, overlay-only (spec rev 3 §7) — own-history P/E & P/S bands with `depth_years` + unit guards (`valuation_bands.py`, node 2.3, shared AV budget, `_valuation/` cache), FY+3 forward target (target @ date + est. return + IRR, median exit multiple, IRR sanity flag), sensitivity table with margin-bear row, and the 5-model intrinsic-value blend + margin-of-safety verdict (`intrinsic_value.py`). Additive JSON keys `valuation_bands` / `intrinsic_value`; composite untouched.

**v4 wave-1 · Phase E (2026-07-22)**: return profile + watch-list, overlay-only (spec rev 3 §10) — `alpha_beta.py` (node 2.56, ambient Python) adds α/β (3y monthly vs regional benchmark, β=cov/var, Jensen α), a CAPM realized-vs-expected line, a 1/3/5/10/15-yr price/total-return CAGR ladder, a Lynch-category return/drawdown prior, and a portfolio-fit line (portfolio α/β vs URTH from FX→EUR weighted equity holdings, cached daily in `_portfolio_riskprofile.json`); β/α are injected into `top_strip`. `watchlist.py` (node 2.57) maintains `_watchlist.csv` (quality names ≥7 held back only by price → target = fair-low), and `send_email.py` shows a red "⭐ Watch-list triggered" block + `[WATCHLIST: n]` subject tag when live ≤ target. `financial_history.py` annual cap lifted 6→20y. Additive JSON key `alpha_beta`; composite untouched.

**v4 wave-1 · Phase G (2026-07-22)**: 3-persona opinion panel, overlay-only (spec rev 3 §10b) — `second_opinion.py` (node 2.58, ambient Python) asks an **independent** model chain (Groq `llama-3.3-70b-versatile` → Gemini `gemini-2.0-flash`, via the new reusable `llm_client.py`) for three prompted personas (value/growth/contrarian), each a 0–100 conviction (50=neutral). The panel sees the evidence but **not** the composite/verdict (independence); consensus = median, divergence flagged on ≥25pt spread or gap vs composite×10. A dead persona degrades to "not available" without blocking the run. Additive JSON key `opinion_panel`; composite untouched.

**v4 wave-1 · Phase F session 1 (2026-07-23)**: HTML-primary report renderer (spec §11) — `render_report.py` (node 5.7, pure stdlib) + `report_template.html` (CSS ported from the locked `docs/v4_design/sample_report_v2.html`). Reads the report `.md` (source, frozen contract — `slim_report` regression test) + the analysis JSON → writes a self-contained, static, JS-free `{report}.html`: answer-first header with a deterministic **action verb** (verdict × mos_class × go_no_go → ACCUMULATE/BUY-DIP/HOLD/WATCH/AVOID), a 5-axis Quality/Value/Growth/Health/Mgmt snowflake (inline SVG), fair-value gauge + bear/base/bull range bar, the A/B/C/E/G cards, peer A–D grades, base64 charts ≤1.5 MB, null renders, currency from JSON. Email is untouched (styled HTML never inlined). *Session 2 (metric families + cheat-sheet glossary + index hub) closes wave 1.*

---

## What it does — the 21-node pipeline

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
| 2.6 | **Macro §8 snapshot** — indices/valuation-vs-history/country + RSP/SPY breadth & 11-sector tendencies (yfinance `macro_breadth.py`) + Buffett/M2/forward-profit; cache `_macro/{date}.md` | once per run |
| 3 | Render charts (price, 7-axis radar, peers, DCF fan, EBITDA+FCF, rel-perf 30mo, segments) | deep |
| 3.5 | **Technical score + GO/NO-GO** (for fundamentally-strong names) | deep |
| 4 | Find official reports — narrative only (no numbers) | deep |
| 5 | Write report (deep ≈2000 words / 1-min screen) | all |
| 5.5 | Auto-cascade screen→deep when verdict ≥ 7.5 (invest) | conditional |
| 5.7 | **Render HTML report (v4-F)** — self-contained static HTML primary artifact: answer-first header + action verb, 5-axis snowflake, fair-value gauge + range bar, A/B/C/E/G cards, base64 charts, **equity-vs-enterprise metric families + greyed cheat-sheet** (tooltip/`<details>`/print-column) and optional daily `index.html` hub (`--index`) (`render_report.py` + `report_template.html` + `metrics_glossary.py`) | all |
| 6 | Update `_log.csv` (v1→v2 auto-migrate) + shortlist + catalyst calendar | always |
| 7 | Regenerate dashboard + email digest | always |
| 8 | Stdout summary | always |

Numbers enter only at node 2; the LLM (2.5) and WebFetch (4) never write structured fields.

---

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
`financial_history.py` · `valuation_bands.py` + `intrinsic_value.py` (v4-B) · `red_flags.py` (v4-C) · `exit_plan.py` (v4-A) · `alpha_beta.py` + `watchlist.py` (v4-E) · `second_opinion.py` + `llm_client.py` (v4-G) · `render_report.py` + `report_template.html` + `metrics_glossary.py` (v4-F) · `macro_snapshot.py` + `macro_breadth.py` (v4-D) ·
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

# Tests (249)
uv run --with pytest pytest "C:\Users\bsdias\.claude\skills\bd-stocks-daily\tests" -q
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
