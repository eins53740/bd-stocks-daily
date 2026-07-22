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

---

## What it does — the 14-node pipeline

| Node | Stage | Runs on |
|------|-------|---------|
| 0.5 | Thesis check (prior-pillar integrity) | re-eval only |
| 1 | Pick 1 deep + 2 screens (183-day dedupe, stale-shortlist fallback) | always |
| 1.5 | Industry-cache freshness (<90d) | deep |
| 2 | **Analyse** — 7-gate + Piotroski + Altman + DCF + peer + provisional composite | all 3 |
| 2.2 | **Financial history** — quarterly EBITDA/FCF series (AV/yfinance, `_fin_history/` cache) + hybrid 4Q forecast | deep |
| 2.5 | LLM narrative — business model, management score, growth, 3-layer risk, bear case, revenue segments → finalize composite | deep |
| 2.6 | **Macro snapshot** — indices/valuation/country cache `_macro/{date}.md` | once per run |
| 3 | Render charts (price, 7-axis radar, peers, DCF fan, EBITDA+FCF, rel-perf 30mo, segments) | deep |
| 3.5 | **Technical score + GO/NO-GO** (for fundamentally-strong names) | deep |
| 4 | Find official reports — narrative only (no numbers) | deep |
| 5 | Write report (deep ≈2000 words / 1-min screen) | all |
| 5.5 | Auto-cascade screen→deep when verdict ≥ 7.5 (invest) | conditional |
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

# Tests (135)
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
