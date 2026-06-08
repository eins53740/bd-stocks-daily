---
name: bd-stocks-daily
description: Daily stock evaluation — picks 3 tickers (1 deep + 2 screens) from the pre-filtered pool, applies Quality Compounder 7-gates, Piotroski/Altman, peer comparison, management quality score (LLM), industry context (cached per sector), 3-layer risk audit, bear case, computes 0-10 composite score (v2 weights), and writes tiered reports (5min TL;DR / 30min deep) to C:\BD_Obsidian\Personal\Finance\StocksDaily\. Run via Task Scheduler daily 17:00.
argument-hint: "[--ticker TICKER] [--mode deep|screen] [--dry-run] — optional overrides for manual runs"
---

# Daily Stock Evaluation (v2)

Avaliação diária automática de 3 acções (1 deep-dive + 2 screens) do pool pré-filtrado, com score 0-10, peer comparison, market timing, **management quality**, **industry context**, **3-layer risk audit** e **bear case**, layout tiered (5 min TL;DR / 30 min deep).

**Horizonte**: 1-5 anos (quality compounders, não day-trade).
**Output**: `C:\BD_Obsidian\Personal\Finance\StocksDaily\`
**Disclaimer obrigatório** em cada relatório e email: 🤖 Auto-generated. Not investment advice. Verify all figures before acting.

## Ground-truth rule (CRITICAL)

**Números estruturados (revenue, P/E, margins, ROE, debt, prices) — SEMPRE de Python helpers (yfinance/stockanalysis).** Nunca extrair números de 10-K / 10-Q via WebFetch. LLM só compõe narrativa (tese, riscos, guidance management, management quality score qualitativo). Se precisares de um número, chama o helper. Qualquer secção qualitativa (§2.1, 2.3, 2.7, 2.11, 2.12, 2.14) deve citar números a partir da JSON da Phase 2 — **nunca inventar**.

## Composite score v2 (weights)

| Componente                                            | Peso   | Fonte                  |
| ----------------------------------------------------- | ------ | ---------------------- |
| Fundamentals (Piotroski + gates + Altman)             | 35%    | Python                 |
| Valuation (P/E + PEG + FCF yield + DCF upside)        | 20%    | Python                 |
| Moat (ROE consistency + margin stability)             | 12%    | Python                 |
| Peer ranking                                          | 12%    | Python + LLM narrative |
| Growth Durability (CAGR + stability + Lynch category) | 8%     | Python                 |
| **Management Quality**                                | **8%** | **LLM (Phase 2.5)**    |
| Market Context (VIX / FGI)                            | 5%     | Python                 |

- **Deep mode**: runs all 7 components. `analyze_ticker.py` emits a provisional composite with `mgmt=5.0` (neutral); `finalize_score.py` recomputes after the LLM Phase 2.5 supplies the real Management Quality score.
- **Screen mode**: no management LLM call. The 6 Python components are renormalised (each weight ÷ 0.92) so they sum to 100%. No `finalize_score.py` call.
- **Management flag**: if `management_score < 7.0` and `mode == deep`, frontmatter `management_flag: true` and report shows a "PROCEED WITH CAUTION" banner. **No auto-demotion of verdict** — composite + flag are surfaced, user decides.

## Style rules (apply to every LLM call in Phase 2.5 and 1.5 refresh)

Every qualitative LLM call must append the block from `skills\bd-stocks-daily\prompts\_style_rules.md`:

- UK English
- Short paragraphs (max 4 sentences)
- No fluff, no hedging without evidence
- Label inferred claims `(inferred)` or `(assumption — evidence gap)`
- Numbers come from the JSON. If not in JSON, say "not available"
- Include AI disruption callout when relevant
- Separate Operator lens (execution) from Investor lens (profit pools, moats)

## Paths (absolutos, obrigatórios)

```
SKILL_DIR      = C:\Users\bsdias\.claude\skills\bd-stocks-daily
SCRIPTS        = C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts
PROMPTS        = C:\Users\bsdias\.claude\skills\bd-stocks-daily\prompts
OUT_DIR        = C:\BD_Obsidian\Personal\Finance\StocksDaily
IND_CACHE      = C:\BD_Obsidian\Personal\Finance\StocksDaily\_industry
BD_FINANCE     = C:\Github\BD\Finance\BD_Finance
PYTHON         = python   (system Python; BD_Finance has its own env but we use system)
LOG_FILE       = C:\Github\.scripts\logs\stocks-daily_<timestamp>.log  (set by .bat wrapper)
```

Change directory to `BD_FINANCE` for yfinance + SMTP helpers to find their config:

```bash
cd /d "C:\Github\BD\Finance\BD_Finance"
```

## Prompt library

Located at `%PROMPTS%\`. Each prompt has `{COMPANY}`, `{TICKER}`, `{NUMBERS_JSON}`, and context-specific placeholders. Read the file, substitute placeholders, run the prompt with the `_style_rules.md` block appended.

Source-framework lineage (the two reference docs at `OneDrive/Ambiente de Trabalho/AI Stocks - ChatGPT GPT/`):

| File                             | Source framework                                               | Purpose                                                                      | Feeds deep-dive section  |
| -------------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------- | ------------------------ |
| `_style_rules.md`                | `ai_industry_analysis_framework.md` "Recommended Enhancements" | Shared style appendix (UK English, AI disruption lens, Operator vs Investor) | Every call               |
| `01_business_model.md`           | `5_step_system.md` Step 1                                      | Money engine (how it makes money)                                            | §2.1                     |
| `02_management_quality.md`       | `5_step_system.md` Step 2                                      | X/10 score + verdict (feeds composite)                                       | §2.3                     |
| `03a_growth_decomposition.md`    | `5_step_system.md` Step 3 Part A                               | Volume/price/M&A; structural vs temporary                                    | §2.7 part A              |
| `03b_constraints.md`             | `5_step_system.md` Step 3 Part B                               | Theory of Constraints bottleneck                                             | §2.7 part B              |
| `03c_growth_assumption_check.md` | `5_step_system.md` Step 3 Part C                               | Supported / Weakly / Not supported                                           | §2.7 part C              |
| `04_risk_audit.md`               | `5_step_system.md` Step 4                                      | 3 layers + leading indicators                                                | §2.11                    |
| `05_bear_case.md`                | `5_step_system.md` Step 5                                      | "If X happens, thesis is broken."                                            | §2.12                    |
| `industry_macro.md`              | `ai_industry_analysis_framework.md` Step 1                     | Market, value chain, players, disruption                                     | `_industry/<slug>.md` §1 |
| `industry_customer.md`           | `ai_industry_analysis_framework.md` Step 2                     | Buyer journey, switching costs                                               | `_industry/<slug>.md` §2 |
| `industry_architecture.md`       | `ai_industry_analysis_framework.md` Step 3                     | Winning models, moats, top-15 KPIs                                           | `_industry/<slug>.md` §3 |

`ai_industry_analysis_framework.md` Step 4 ("Synthesize with NotebookLM") is intentionally not wired in — that step is an external-tool synthesis, not something the skill can automate.

For the full theoretical context (PT-PT/EN bilingual), see `C:\BD_Obsidian\Personal\Finance\StocksDaily\docs\STRATEGY_GUIDE.md` — comprehensive synthesis of TIKR + Modelo Integrado + 5_step_system frameworks with `IN-USE` / `PLANNED` / `SKIPPED` tags per technique and a roadmap.

## Workflow (executar por esta ordem exacta)

### Phase 0.5 — Thesis check (only when `round > 1`)

Skipped on `round == 1`. For re-evaluations (round 2+), `pick_candidates.py` already loads the prior report; before any new analysis runs, verify whether the previous thesis is still intact.

```bash
python "%SCRIPTS%\thesis_check.py" --ticker {ticker} --prior-report {path_to_prior_md}
```

Output JSON:

```json
{
  "ticker": "ASML.AS",
  "prior_date": "2026-02-12",
  "prior_score": 8.7,
  "prior_bear_trigger": "If ASML loses EUV monopoly to a credible competitor within 3 years",
  "pillars": [
    {"name": "ROE > 30%", "prior": 0.48, "now": 0.46, "status": "intact"},
    {"name": "Revenue 5y CAGR > 8%", "prior": 0.18, "now": 0.07, "status": "weakened"},
    {"name": "Net margin > 25%", "prior": 0.28, "now": 0.31, "status": "intact"}
  ],
  "overall_status": "weakened",
  "summary": "2 of 3 pillars intact; revenue growth deceleration is the watch item."
}
```

Status values: `intact` / `weakened` / `broken`. **Surface the status in the TL;DR** as `Thesis status (round {N}): {emoji} {overall_status}`. If `broken`, the report gets a 🚨 banner at the top and §2.15 (Bear case) opens with the broken pillar.

The script reads the prior `_log.csv` row and prior report frontmatter for the comparison baseline; no LLM call.

### Phase 1 — Pick today's candidates

```bash
python "%SCRIPTS%\pick_candidates.py"
```

Output JSON:

```json
{
  "date": "2026-04-17",
  "deep": {"ticker": "ASML.AS", "size": "big", "region": "NL", "sector": "Semiconductors", "round": 1},
  "screens": [
    {"ticker": "CELH", "size": "small_growth", "region": "US", ...},
    {"ticker": "JMT.LS", "size": "big", "region": "PT", ...}
  ]
}
```

If any ticker has `round > 1`, the report gets a `🔁 Reavaliação #N` badge at the top and a link back to the prior evaluation.

**Pool-exhausted fallback**: when the regular pool is empty (every prefiltered ticker is within the 183-day dedupe window), `pick_candidates.py` falls back to re-evaluating the stalest ticker from `_log.csv` instead of exiting empty. The user wants a deep-dive in the inbox every day, so the cascade is:

1. Stalest active shortlist (`score >= 7.5`, age `>= 14d`, `round < 5`)
2. Stalest any-verdict (age `>= 14d`, `round < 5`)
3. Empty exit (only on a fresh install with no log)

The output JSON gains `fallback_mode: true` and `fallback_reason`. The TL;DR adds a `🔁 Fallback re-eval — pool was exhausted` banner. Screens stay empty in fallback mode — one deep dive is enough for the daily email.

### Phase 1.5 — Industry cache check (deep only)

```bash
python "%SCRIPTS%\ensure_industry_cache.py" --sector "{deep.sector}"
```

Emits a JSON directive `{slug, path, exists, stale, reason, age_days, generated_at}`:

- `stale: false` → cache is fresh (≤90 days). Phase 2.5 embeds the ~400-word snapshot and moves on.
- `stale: true` (reason `missing` or `expired`) → Phase 2.5 refresh path kicks in: run the 3 industry prompts (`industry_macro.md`, `industry_customer.md`, `industry_architecture.md`) via LLM with WebFetch for trade reports / filings, then write the full output to `{path}` with frontmatter:

```yaml
---
sector: {Sector}
slug: {slug}
generated_at: {today ISO}
schema_version: "2.1"
sources: [url1, url2, ...]
---
```

Screens do NOT trigger industry cache checks.

### Phase 2 — Analyse each ticker (sequential, to avoid yfinance rate limits)

For **each** of the 3 tickers (deep first, then 2 screens):

```bash
python "%SCRIPTS%\analyze_ticker.py" --ticker ASML.AS --mode deep
```

**After each analyse call, check these flags in the JSON output:**

- `earnings_today: true` → material event risk within hours. For the **deep** ticker, pick a replacement manually from `_prefiltered.yaml` (same `size` bucket, not in the 183-day dedupe window per `_log.csv`) and re-run `analyze_ticker.py` on it; do NOT re-run `pick_candidates.py` — it's date-seeded and will return the same ticker. For a **screen** ticker, annotate the screen report with an explicit "⚠️ Earnings today" banner and keep going (cheaper to note than to re-pick).
- `dcf_valid: false` → **do not quote `dcf_intrinsic` as a price target anywhere in the narrative.** The `dcf_reason` field explains why the model can't be trusted (negative FCF, TTM/annual divergence, or |upside|>70% sanity trip). Section 2.9 should reference the reason verbatim and mark the intrinsic as "not meaningful".
- `score_details.peer_info.peers_source` → `by_ticker` means a precise sub-industry peer set was used; `by_industry` means yfinance's industry bucket; `by_sector` is a coarse fallback; `none` means no peers and the peer score is a neutral 5.0 placeholder. Mention the source in §2.10 so the reader can calibrate trust in the ranking.
- `fundamentals.revenue_cagr_basis` → `5y_financials` / `4y_financials` / `3y_financials` / `3y_income_stmt` / `1y_yoy_fallback` / `unavailable`. v2.1+ tolerates NaN years and short series. When basis is `1y_yoy_fallback`, mention it in §2.9 (Growth decomposition) so the reader knows the CAGR is a single-year proxy, not a multi-year trend.
- `data_quality` → `ok` / `corrected` / `suspect` (3 validation layers).
  - **`corrected`** → Layer 2 self-healed a stale `info` price using `history()`'s last close (and recomputed `market_cap`). Read `corrected_fields` for what changed — the numbers in the JSON are already the FIXED ones, safe to use. This auto-fixes the CMO.MC €8.49→€38 class. Add a small "ℹ️ price auto-corrected from history()" note.
  - **`suspect`** → Layer 0 found an UNFIXABLE inconsistency. **DO NOT trust the raw numbers** — read `consistency_issues` and `cross_validation.divergences`, cross-check the affected fields against the official filing before quoting, and add a "⚠️ data-quality: suspect" note. This catches the distorted-margin/PE class (e.g. SEM.LS P/E 50 vs margin 31%).
  - `cross_validation.error` containing "no coverage" just means FMP free can't validate this ticker (EU exchanges) — Layers 0+2 cover it. Note: no free quote API (FMP/Polygon/Finnhub free, Stooq) covers Iberian small-caps; Layers 0+2 (pure yfinance) are the protection there.

v2 output JSON (the ground truth — USE THESE NUMBERS):

```json
{
  "ticker": "ASML.AS",
  "mode": "deep",
  "schema_version": "2.1",
  "weights": { "fundamentals": 0.35, "valuation": 0.20, "moat": 0.12, "peer": 0.12, "growth_durability": 0.08, "management": 0.08, "market_context": 0.05 },
  "fetched_at": "...",
  "company_name": "ASML Holding NV",
  "sector": "Technology",
  "industry": "Semiconductor Equipment & Materials",
  "currency": "EUR",
  "price_current": 842.1,
  "fundamentals": { "revenue_ttm": 27.5e9, "pe_ratio": 29.1, "peg": 1.8, "roe_5y_avg": 0.48, ... },
  "technical": {...},
  "piotroski_fscore": 8, "altman_zscore": 6.4,
  "gates_passed": 7, "gates_detail": {...},
  "lynch_category": "stalwart",
  "dcf_intrinsic": 920, "dcf_upside_pct": 0.09,
  "vix": 18.3, "earnings_date_next": "2026-04-24",
  "scores": {
    "fundamentals": 9.2, "valuation": 7.5, "moat": 9.0, "peer": 9.5,
    "growth_durability": 8.5, "market_context": 6.0,
    "management": null,           // filled by finalize_score.py (deep) or stays null (screen)
    "composite": 8.10,            // provisional for deep (mgmt=5.0); final for screen
    "composite_is_provisional": true
  },
  "management_score": null, "management_flag": false,
  "verdict": "invest",
  "data_source": "yfinance",
  "data_warnings": []
}
```

### Phase 2.5 — Qualitative LLM pass (deep only)

Runs in Claude's orchestration context. Skipped entirely for screens.

1. **Refresh industry cache if stale** (from Phase 1.5 directive). Substitute `{INDUSTRY}` = `deep.sector`. Run `industry_macro.md` first → use output as `{MACRO_OUTPUT}` for `industry_customer.md` → use both as context for `industry_architecture.md`. Write the combined result to `_industry/<slug>.md` with the frontmatter above. Use WebFetch over 3-5 credible sources (trade association reports, consulting-firm industry overviews, SEC filings for the sector's top-3 players).

2. **Business model** — run `01_business_model.md` with `{ANNUAL_NARRATIVE}` from Phase 4's WebFetch. Output → §2.1.

3. **Management quality** — run `02_management_quality.md`. Parse the line `Management Quality Score: X.X/10` → that's `mgmt_score`. The rest of the output → §2.3.

4. **Growth decomposition & constraints** — run `03a_growth_decomposition.md`, then `03b_constraints.md` with 03a's output, then `03c_growth_assumption_check.md`. Combined output → §2.9.

5. **3-Layer Risk Audit** — run `04_risk_audit.md`. Output → §2.13.

6. **Consensus color** (Borja #18) — 1 short paragraph reconciling the deep-dive verdict with the `consensus` JSON block (recommendation key, target mean/range, EPS/revenue estimates). Skip entirely if `analyst_count < 3`. Output → §2.14.

7. **Bear case** — derive `{BULL_THESIS}` from §2.1 + §2.9 + TL;DR thesis line; run `05_bear_case.md`. Parse the FINAL LINE `If {X} happens, the thesis is broken.` → `bear_case_trigger`. Full output → §2.15.

8. **Finalise composite**:
   
   ```bash
   python "%SCRIPTS%\finalize_score.py" --json-path {analyze_json_path} --mgmt-score {mgmt_score}
   ```
   
   Use the returned JSON for Phase 5. Sets `management_score`, `management_flag`, recomputes `scores.composite` and `verdict`.
   
   **Then write `finalize_score.py` stdout to `%OUT_DIR%\_tmp\{date}_{ticker}.json` (overwrite Phase 2's intermediate).** Phase 3 (`render_charts.py`) reads from this file via `--analysis-json`. Without this step, the radar PNG will be skipped (validation gate) and the report loses its score breakdown.

If any Phase 2.5 step fails, log a warning and continue with what you have — the report degrades gracefully (missing section + `(assumption — evidence gap)` note), it does not abort.

### Phase 3 — Render charts (deep only)

**Pre-condition (CRITICAL):** the analysis JSON for this ticker MUST have been written to `%OUT_DIR%\_tmp\{date}_{ticker}.json` first, with all 7 score components populated. For deep mode, this means writing the `finalize_score.py` stdout (Phase 2.5 step 7) to that file. For screens, write Phase 2's stdout. **Without this file, render_charts will validate-skip the radar chart and the report will lose its score-breakdown PNG.** A canonical `--analysis-json` argument prevents the silent-empty-stdin bug that produced misleading 0/10 radars.

Filename rule: dots in tickers are kept (`JMT.LS` → `2026-04-30_JMT.LS.json`); only `/` and `\` are sanitised. Already handled by `safe_ticker_filename()`.

```bash
python "%SCRIPTS%\render_charts.py" --ticker ASML.AS --analysis-json "%OUT_DIR%\_tmp\2026-04-30_ASML.AS.json"
```

For **dry-run** add `--output-dir "%OUT_DIR%\_dry\IMG"` so charts land beside the dry report instead of in the production `IMG/` folder:

```bash
python "%SCRIPTS%\render_charts.py" --ticker NVDA --analysis-json "%OUT_DIR%\_dry\_tmp\2026-05-14_NVDA.json" --output-dir "%OUT_DIR%\_dry\IMG"
```

`render_charts.py` now logs provenance to stderr (input source, byte count, score keys, peer-metrics count) and **refuses to draw the radar** when `scores` lacks at least 5 of 6 non-management components plus `composite`. The peers chart distinguishes "peers identified but metrics not fetched" from "no peers configured" so the placeholder no longer misleads.

Produz em `OUT_DIR\IMG\`:

- `YYYY-MM-DD_TICKER_price.png` — preço 1Y + SMA50/200 + volume
- `YYYY-MM-DD_TICKER_radar.png` — radar 7 eixos (Fundamentals, Valuation, Moat, Peer, Growth, Management, Market)
- `YYYY-MM-DD_TICKER_peers.png` — bar chart vs 3-5 peers
- `YYYY-MM-DD_TICKER_dcf.png` — DCF fan chart bear/base/bull

Screens não chamam este script.

### Phase 4 — Find official reports (narrative-only WebFetch OK here)

```bash
python "%SCRIPTS%\find_reports.py" --ticker ASML.AS
```

Output JSON com URLs oficiais:

```json
{
  "annual_url": "...",
  "annual_date": "2026-02-12",
  "quarterly_url": "...",
  "quarterly_date": "2026-04-15",
  "ir_page_url": "..."
}
```

Para **deep-dive**: depois disto usa WebFetch sobre `annual_url` e `quarterly_url` para extrair **narrativa** (tese management, strategic priorities, riscos materiais, guidance). Os textos fetched aqui alimentam `{ANNUAL_NARRATIVE}` e `{QUARTERLY_NARRATIVE}` em Phase 2.5. **Não** extraias números daí — os números já vêm da Phase 2.

**v2.1 narrative fallback** — SEC EDGAR routinely returns 403 to WebFetch (rate-limit / UA gate) and other filing aggregators are inconsistent. Before WebFetch attempts, run:

```bash
python "%SCRIPTS%\get_narrative.py" --ticker NVDA --max-news 5
```

Returns a JSON dict with `business_summary` (yfinance `longBusinessSummary`, ~1500 chars MD&A-equivalent), `recent_news` (yfinance `Ticker.news`), `ir_url`, `stockanalysis_fundamentals_url`, and a `narrative_quality` grade (`good` / `partial` / `degraded`). Use the combined `business_summary + recent_news` content as the `{ANNUAL_NARRATIVE}` substitution. If quality is `good` or `partial`, you can skip WebFetch entirely. If `degraded`, then try WebFetch on `annual_url` / `ir_page_url` from `find_reports.py` (avoid SEC EDGAR direct URLs — they 403). Degraded final state → §2.7 / §2.8 carry the `⚠️ Official report narrative unavailable` note and Phase 2.5 prompts label inferred claims accordingly.

### Phase 5 — Write the report

**Nome do ficheiro**: `{date}_{ticker}_{verdict}.md` (deep) ou `{date}_{ticker}_screen.md` (screens).
`verdict` ∈ {`great` ≥9.0, `invest` 7.5-8.9, `review` 6.0-7.4, `fair` 4.0-5.9, `reject` <4.0}.

**Frontmatter v2** (lowercase, sem emojis, sem espaços):

```yaml
---
tags: [stocks, evaluation, finance]
ticker: ASML.AS
exchange: AEX
region: NL
sector: Semiconductors
size: big
date: 2026-04-17
round: 1
mode: deep            # deep | screen
verdict: invest       # great | invest | review | fair | reject
score: 8.7
gates_passed: 7
piotroski_fscore: 8
altman_zscore: 6.4
price_at_eval: 842.1
currency: EUR
earnings_date_next: 2026-04-24
manual_reviewed: false
management_score: 8.5          # null for screens
management_flag: false         # true only if <7.0 and mode==deep
industry_cache_date: 2026-04-17
industry_cache_slug: semiconductors
bear_case_trigger: "If ASML loses EUV monopoly to a credible competitor within 3 years"
schema_version: "2.1"
---
```

#### Deep-dive body (obrigatório)

```md
# {TICKER} — {Company name} — Score: {score}/10 {emoji} {verdict_label}

> [!warning] 🤖 Auto-generated. Not investment advice. Verify all figures before acting.

{If management_flag: insert banner}
> [!danger] ⚠️ PROCEED WITH CAUTION — Management Quality {mgmt_score}/10 (<7). See §2.3.

> [!tldr] ⚡ TL;DR (leitura 2 minutos)
> **Veredicto**: {emoji} {verdict_label} ({score}/10, {gates_passed}/7 gates, Piotroski {fscore}/9, Mgmt {mgmt_score}/10)
> **Thesis**: {1-line bull case}
> **Risks**: {2-3 key risks}
> **Bear trigger**: {bear_case_trigger}
> **Action**: {explicit next step}
> **Earnings watch**: próximos earnings em {earnings_date_next}

![Price 1Y](IMG/{date}_{ticker}_price.png)

## 1. Sumário executivo (5 min)
### Score breakdown
![Radar](IMG/{date}_{ticker}_radar.png)
| Componente | Peso | Score | Contributo |
|------------|------|-------|------------|
| Fundamentals | 35% | {X}/10 | {0.35*X} |
| Valuation    | 20% | {X}/10 | ... |
| Moat         | 12% | ... | ... |
| Peer Ranking | 12% | ... | ... |
| Growth Durability | 8% | ... | ... |
| Management Quality | 8% | {X}/10 | ... |
| Market Context | 5% | ... | ... |
| **Total**    | 100% | — | **{composite_score}/10** |

### Quality Compounder 7-Gate checklist
- {✅/❌/⚠️} Gate 1 — Revenue growth 5y CAGR ≥ 8%: **{value}%**
- {✅/❌/⚠️} Gate 2 — P/E < 35 OR (PEG < 2.5 AND ROE > 20%): **P/E {pe}, PEG {peg}, ROE {roe}%**
- ... (todos os 7 gates)

### Market timing context
- VIX: **{vix}** → {regime} ({interpretation 1 linha})
- Fear & Greed Index: **{fgi}/100** → {label}
- Verdict: **{GOOD|NEUTRAL|BAD}** (componente 5% — informativo, não bloqueia)

### Peer ranking snapshot
![Peers](IMG/{date}_{ticker}_peers.png)

## 2. Deep dive (30 min)

### 2.1 Business model — money engine
({300-500 palavras a partir de prompts\01_business_model.md})

**Money-flow Sankey** (obrigatório, no fim de §2.1) — Mermaid `sankey-beta` com Revenue → COGS / Gross Profit → R&D / SG&A / Other OpEx / Operating Income → Interest & Tax / Net Income → Dividends / Buybacks / Retained Earnings. Valores TTM em milhões da moeda de reporte (arredondar à centena). Sub-linhas em falta (e.g. R&D não disclosed) ficam marcadas `(not disclosed)` e o ramo é omitido — nunca inventar. Caption de uma linha após o diagrama, do tipo *"Cada euro de receita transforma-se em ~X% de net income; o maior dreno é {bucket} ({Y}%)."* Ver template completo em `prompts\01_business_model.md`.

### 2.2 Industry snapshot ({sector})
({~400 palavras extraídas/resumidas a partir de `_industry/<slug>.md` — macro + moats + AI disruption. Linka para o ficheiro completo.})
📂 Full industry analysis: [[_industry/{slug}]]

### 2.3 Management quality — {mgmt_score}/10
{If <7: PROCEED WITH CAUTION banner here too}
({Paragraph-verdict a partir de prompts\02_management_quality.md})

### 2.4 Estrutura acionista (Borja #4)
(Pulled from `shareholder_structure` JSON block — pure yfinance, no LLM narrative.)

| Métrica | Valor |
|---|---|
| Insider ownership | {insider_pct}% |
| Institutional ownership | {institutional_pct}% |
| Float shares | {float_shares:,} |
| Shares outstanding | {shares_out:,} |

**Top 5 institutional holders**
| Holder | Shares | % held | Value |
|---|---|---|---|
| ... | ... | ... | ... |

**Recent insider transactions** (last 5): bullet list of `{insider} ({position}) — {transaction} {shares:,} sh on {date}`.

**Takeaway** (1 line): high insider ownership = skin in the game; institutional concentration > 90% can dampen rallies on bad news.

### 2.5 Capital returns & shareholder yield (Borja #13–14)
(From `capital_returns` JSON block.)

| Métrica | TTM | Notes |
|---|---|---|
| Dividend yield | {dividend_yield}% | |
| Payout ratio | {payout_ratio}% | <50% = safe; >80% = thin cushion |
| Dividends paid | {dividends_paid_ttm:,} | |
| Buybacks | {buybacks_ttm:,} | |
| Stock issuance | {issuance_ttm:,} | |
| **Net payout yield** | **{net_payout_yield}%** | (div + buybacks − issuance) / mkt cap |
| 5y share-count delta | {shares_change_5y_pct}% | negative = buybacks; positive = dilution |

**Reading the net payout yield** (Borja's signature metric): >5% = aggressive return of capital; 2-5% = healthy; <2% = reinvestment-focused or weak; negative = net dilution.

### 2.6 Fundamentals detalhados (ordem Borja #6–#14)
| Bloco | Métrica | TTM | 5y CAGR / média | Notes |
|---|---|---|---|---|
| #6  | Market cap | {market_cap:,} | — | |
| #6  | Shares outstanding | {shares_out:,} | Δ5y {shares_change_5y_pct}% | |
| #7  | Revenue | {revenue_ttm:,} | {rev_cagr_5y}% CAGR | |
| #7  | **P/S** | {ps_ratio}x | — | |
| #8  | **EBITDA** | {ebitda_ttm:,} | — | |
| #8  | **EV/EBITDA** | {ev_ebitda}x | — | |
| #9  | Net income | {net_income:,} | — | |
| #9  | P/E (trailing) | {pe_ratio}x | — | |
| #9  | PEG | {peg}x | — | |
| #10 | Gross margin | {gross_margin_ttm}% | — | |
| #10 | Operating margin | {operating_margin_ttm}% | — | |
| #10 | Net margin | {net_margin_ttm}% | {net_margin_5y_avg}% avg | |
| #11 | ROE | {roe_ttm}% | {roe_5y_avg}% avg | |
| #11 | **ROCE** | {roce_ttm}% | — | |
| #11 | **ROIC** | {roic_ttm}% | — | |
| #12 | Total debt | {total_debt:,} | — | |
| #12 | **Net debt** | {net_debt:,} | total_debt − total_cash | |
| #12 | **Net debt / EBITDA** | {net_debt_ebitda}x | <2x = comfortable; >4x = stretched |
| #12 | D/E | {debt_to_equity}x | — | |
| #12 | Quick ratio | {quick_ratio}x | — | |
| #13 | Dividend yield | {dividend_yield}% | payout {payout_ratio}% | see §2.5 |
| #14 | **Net payout yield** | {net_payout_yield}% | — | see §2.5 |
| —   | FCF | {fcf_ttm:,} | FCF yield {fcf_yield}% | |

### 2.7 Wrap-up Annual Report {year}
**Link**: [{annual_url}]({annual_url}) — publicado {annual_date}
({Narrativa do management discussion — tese de crescimento, strategic priorities, capital allocation. NÃO repete números, esses estão em 2.6})

### 2.8 Wrap-up Quarterly Report {quarter}
**Link**: [{quarterly_url}]({quarterly_url}) — publicado {quarterly_date}
({Que mudou no último trimestre — guidance, segment trends, one-offs})

### 2.9 Growth decomposition & constraints
({Combined output a partir de prompts\03a + 03b + 03c — volume/price/M&A breakdown, Theory of Constraints bottleneck, growth assumption verdict Supported/Weakly/Not.})

### 2.10 Análise técnica
Preço actual {price} vs SMA50 {sma50}, SMA200 {sma200}. RSI {rsi}. MACD {macd_signal}. Drawdown máx 1Y: {dd}%.

### 2.11 DCF + Intrinsic value
{If dcf_valid=true:}
![DCF](IMG/{date}_{ticker}_dcf.png)
DCF intrínseco: **{dcf_intrinsic} {currency}** vs preço {price} {currency} → upside **{upside}%**.
(Assumptions: discount rate 10%, terminal growth 2.5%, based on yfinance 5y FCF)

{If dcf_valid=false:}
⚠️ **DCF not meaningful** — {dcf_reason verbatim}. Do not use the computed intrinsic as a price target; valuation is driven by P/E, PEG and FCF-yield components instead. Normalised-FCF DCF could be done manually by estimating mid-cycle FCF, but that estimate is out of scope here.

### 2.12 Peer comparison
| Métrica | {ticker} | Peer 1 | Peer 2 | Peer 3 | Peer 4 | Median | Ranking |
|---------|----------|--------|--------|--------|--------|--------|---------|
| P/E | ... | ... | ... | ... | ... | ... | **{N/5}** |
| EV/EBITDA | ... | ... | ... | ... | ... | ... | ... |
| Rev growth 3y | ... | ... | ... | ... | ... | ... | ... |
| Net margin | ... | ... | ... | ... | ... | ... | ... |
| ROE | ... | ... | ... | ... | ... | ... | ... |
| FCF yield | ... | ... | ... | ... | ... | ... | ... |

**Strengths vs peers**: bullet list, 2-4 items.
**Weaknesses vs peers**: bullet list, 2-4 items.

### 2.13 3-Layer Risk Audit
({Ranked risk tables + narrative a partir de prompts\04_risk_audit.md. Três sub-secções: Operational / Financial / Structural. AI Disruption callout no fim.})

### 2.14 Consensus & sell-side ("O que a rua pensa") (Borja #18)
(From `consensus` JSON block — yfinance only, no paywalled feed. Closes Borja factor #18 without subscribing to a service.)

| Métrica | Valor |
|---|---|
| Recommendation key | {recommendation_key} (mean {recommendation_mean}, {analyst_count} analysts) |
| Price target (mean / median) | {target_mean} / {target_median} {currency} |
| Price target range | {target_low} – {target_high} {currency} |
| EPS estimate (current / next year) | {eps_estimate_current_year} / {eps_estimate_next_year} |
| Revenue estimate (current / next year) | {revenue_estimate_current_year} / {revenue_estimate_next_year} |

**Implied upside vs current**: {((target_mean - price_current)/price_current * 100)}%.

**Color** (1 short paragraph, LLM, with `_style_rules.md` appended): is consensus directionally aligned with the verdict and bear case? Where does the deep-dive disagree with the street, and why? Label inferred claims `(inferred)`. Skip the paragraph entirely if `analyst_count < 3` — note "thin coverage" instead.

### 2.15 Bear case — "If X happens, thesis is broken."
({400-600 palavras a partir de prompts\05_bear_case.md. A última linha é o trigger que vai para frontmatter.})

### 2.16 Market timing detalhado
({VIX histórico, put/call trend, FGI breakdown — discussão curta})

### 2.17 Operator vs Investor view
({2 short paragraphs — Operator lens (execução, bottlenecks) e Investor lens (profit pools, moats). Cross-cutting summary destilado das secções anteriores.})

### 2.18 Veredicto final
**{verdict_label}** — {2-3 linhas justificando o score e a action recomendada. Se management_flag=true, referenciar explicitamente.}

## 3. Links para ir mais fundo
- 📘 [Annual report {year}]({annual_url}) — publicado {annual_date}
- 📄 [Q{q} {year} report]({quarterly_url}) — publicado {quarterly_date}
- 🏢 [Investor Relations]({ir_page_url})
- 📂 [[_industry/{slug}|Full industry analysis ({sector})]]
- 📊 [Yahoo Finance — financials](https://finance.yahoo.com/quote/{TICKER}/financials)
- 📊 [Stock Analysis — fundamentals](https://stockanalysis.com/stocks/{slug}/financials/)
- 📊 [Simply Wall St]({sws_url})
- 📊 [Seeking Alpha](https://seekingalpha.com/symbol/{TICKER_BASE})
- 🌍 [Finviz](https://finviz.com/quote.ashx?t={TICKER_BASE})
```

#### Screen body (versão curta — sem charts, sem narrativa pesada, sem §2.1/2.3/2.9/2.13/2.14/2.15/2.17)

```md
# {TICKER} — {Company} — Score: {score}/10 {emoji} {verdict_label}

> [!warning] 🤖 Auto-generated. Not investment advice. Verify all figures before acting.

> [!info] Screen rápido (1 min) — 6-component score (Management não avaliado em screens)
> {emoji} {verdict_label} ({score}/10, {gates}/7 gates).
> {1-line thesis}. {1-line risk}.

## 7-Gate checklist
- {gate traffic lights, 1 linha cada}

## Fundamentals (snapshot)
| P/E | PEG | ROE | Margin | D/E | Quick | FCF yield |
|-----|-----|-----|--------|-----|-------|-----------|
| ... | ... | ... | ... | ... | ... | ... |

## Peer ranking
{ticker}: **{rank}/5** em P/E, **{rank}/5** em ROE.

## Score breakdown (6 components, renormalised)
| Fund | Val | Moat | Peer | Growth | Mkt | Composite |
|------|-----|------|------|--------|-----|-----------|
| ... | ... | ... | ... | ... | ... | {score}/10 |

## Links
- [Yahoo Finance](https://finance.yahoo.com/quote/{TICKER}/)
- [Stock Analysis](https://stockanalysis.com/stocks/{slug}/)
```

### Phase 5.5 — Auto-cascade screen→deep on `invest` verdict

**Rule**: If a SCREEN evaluation produces `verdict == "invest"` (i.e., score ≥ 7.5 in screen mode), **immediately run a deep-dive on that same ticker** in the same daily run before moving to Phase 6. The user wants every "invest" signal grounded in a full deep-dive (mgmt quality, 3-layer risk audit, bear case, charts) before it lands on the shortlist.

Implementation:

1. After Phase 5 writes the screen report, inspect the `verdict` field.
2. If `invest`, re-run Phase 2 with `--mode deep`, then full Phase 2.5 (industry cache reuse if same sector), Phase 3, Phase 4, Phase 5 → producing a second report file `{date}_{ticker}_{deep_verdict}.md`.
3. The screen report is kept on disk for audit (don't delete) — the deep report supersedes it on the shortlist via `update_shortlist.py` dedupe-by-ticker rules.
4. Both reports get logged in `_log.csv` with their respective modes.
5. Skip the cascade if (a) the same ticker already had a deep evaluation within the last 14 days (avoid double work), or (b) `dcf_valid: false` plus a clear "data not yet ready" signal (e.g., recent SPAC, IPO < 90 days) — log the skip reason.

Example: today's flow finds `screen` verdict `invest` for RYA.IR → orchestrator triggers `--ticker RYA.IR --mode deep` → both reports written → email digest covers both.

### Phase 6 — Update state

```bash
python "%SCRIPTS%\update_log.py" --entries-json '<JSON>'
python "%SCRIPTS%\update_shortlist.py"
```

- `update_log.py` v2 appends entries to `_log.csv`. Columns include `management_score, management_flag, bear_case_trigger`. First run against a v1 CSV migrates once in-place (non-destructive: old rows gain blank v2 fields).
- `update_shortlist.py` relê `_log.csv` inteiro, filtra score≥7.5 e NOT expired (90 dias), regenera `_shortlist.md`. Move entradas expiradas para `_shortlist_expired.md`.
- `update_shortlist.py` v2.1 also emits `_catalyst_calendar.md` alongside `_shortlist.md` — a rolling 30/60/90-day events table for every active shortlist ticker (earnings dates from latest `_log.csv` `earnings_date_next`, ex-div dates from yfinance). The earnings-preview cron (`bd-stocks-earnings-preview` skill) reads this file to auto-trigger 2 business days before any shortlist earnings event.

JSON entry schema (v2):

```json
{
  "ticker": "ASML.AS", "date": "2026-04-17", "mode": "deep", "verdict": "invest",
  "score": 8.7, "gates_passed": 7, "price_at_eval": 842.1, "currency": "EUR",
  "size": "big", "notes": "",
  "management_score": 8.5, "management_flag": false,
  "bear_case_trigger": "If ASML loses EUV monopoly within 3 years"
}
```

### Phase 7 — Email digest (with dashboard attachment)

**Default schedule path**: the bat wrapper (`C:\Github\.scripts\stocks-daily.bat`) invokes `send_email.py --date <today>` after Claude exits, with the empty-day guard from Commit E. This guarantees the digest is sent even if this skill skips or abbreviates its final phases.

**Manual deep-dive path (e.g. `--ticker SAP --mode deep`)**: at the end of Phase 6, **explicitly call** `send_email.py` so the user gets the report in their inbox right away — this is the pattern the user expects after every deep analysis:

```bash
python "%SCRIPTS%\send_email.py" --date 2026-04-30
```

`send_email.py` now does three things in one call:

1. Regenerates `_dashboard.html` via `build_dashboard.py` so the snapshot reflects today's reports.
2. Builds a multipart/mixed email: text+HTML body (cards + inline full reports) **plus** the dashboard as an `.html` attachment (named `StocksDaily_dashboard_{date}.html`).
3. Ships via SMTP with the existing anti-spam headers.

If SMTP fails, the script logs and exits 0 (non-fatal) — the report itself is already on disk in Obsidian.

Subject: `StocksDaily [2026-04-17]: 🟢 ASML.AS 8.7/10 · 🟡 CELH 7.1 · 🟠 JMT.LS 5.4`

Body HTML: 3 cards (ticker, score, verdict, 1-line thesis, mgmt score + flag badge if applicable, Obsidian link `obsidian://open?vault=BD_Obsidian&file=Personal%2FFinance%2FStocksDaily%2F{filename}`).

Se o email falhar (SMTP down, creds), log-only, não aborta o run.

### Phase 8 — Final output to stdout

```
=== StocksDaily 2026-04-17 ===
DEEP:    ASML.AS → score 8.7 🟢 INVEST (round 1, mgmt 8.5/10)
SCREEN:  CELH    → score 7.1 🟡 REVIEW (round 1)
SCREEN:  JMT.LS  → score 5.4 🟠 FAIR (round 1)
Industry cache: semiconductors (fresh, 12d old)
Shortlist: +1 entry (ASML.AS). Total active: {N}.
Email: deferred to bat wrapper (send_email.py runs after skill exits).
Duration: {M}m {S}s.
Cost: ~${X}.
```

## Error handling

- `pick_candidates.py` devolve empty pool → log warning, email alert, exit 0 (não erro).
- `ensure_industry_cache.py` falha → proceed sem industry snapshot, add note to report: `⚠️ Industry cache unavailable`.
- `analyze_ticker.py` falha para 1 ticker → escreve report stub com `⚠️ Analysis failed: {error}`, continua com os outros 2.
- **Phase 2.5 individual prompt failure** → continua com restante; secção ausente recebe `⚠️ {section name} not available — {reason}`.
- `finalize_score.py` não chamado (Phase 2.5 mgmt prompt failed) → composite permanece provisional (mgmt=5.0); frontmatter `management_score: null`, `management_flag: false`; report nota explicitamente.
- `render_charts.py` falha → relatório sem PNGs, apenas nota.
- `find_reports.py` não encontra reports → relatório sem links oficiais, apenas nota `⚠️ Official reports not found — fundamentals from yfinance only`, Phase 2.5 Business Model / Management prompts degradam (menos narrativa).
- Email falha → log-only.

## Manual overrides

- `/bd-stocks-daily --ticker NVDA --mode deep` → força deep-dive dum ticker específico (skip `pick_candidates.py`). Útil para testar ou avaliar on-demand.
- `/bd-stocks-daily --ticker NVDA --mode deep --dry-run` → escreve output em `OUT_DIR\_dry\` em vez do destino normal, pula Phase 6 (`_log.csv` intacto) e Phase 7 (no email). Usar para smoke-test após alterações ao skill.

## Migration notes (v1 → v2)

- `_log.csv` migra automaticamente no primeiro run com `update_log.py` v2 (headers v1 → v2, rows preserved with blanks for new columns).
- Reports antigos (pre-v2) continuam válidos; readers devem tratar ausência de `schema_version` como `schema_version: 1` e ausência de `management_score` como `null`.
- `_shortlist.md` regenera-se a partir de `_log.csv` — não requer migração.
- `_industry/` é um directório novo; criado on-demand em Phase 1.5.
