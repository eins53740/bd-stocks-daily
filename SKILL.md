---
name: bd-stocks-daily
description: Daily stock evaluation — picks 5 tickers (1 deep + 4 screens, 2 of them from non-USA markets) from the pre-filtered pool, applies Quality Compounder 7-gates, Piotroski/Altman, peer comparison, management quality score (LLM), industry context (cached per sector), 3-layer risk audit, bear case, computes 0-10 composite score (v2 weights), and writes tiered reports (5min TL;DR / 30min deep) to C:\BD_Obsidian\Personal\Finance\StocksDaily\. Run via Task Scheduler daily 17:00.
argument-hint: "[--ticker TICKER] [--mode deep|screen] [--dry-run] — optional overrides for manual runs"
---

# Daily Stock Evaluation (v4 wave-1, Phase B — scoring schema 2.2)

Avaliação diária automática de 5 acções (1 deep-dive + 4 screens, dos quais 2 garantidamente de mercados não-US) do pool pré-filtrado, com score 0-10 (scoring **v2.2**), peer comparison, market timing, **technical score & GO/NO-GO**, **management quality**, **industry context**, **3-layer risk audit** e **bear case**, layout tiered (5 min TL;DR / 30 min deep). A orquestração corre como um **pipeline de 15 nós** (sub-fases 0.5 / 1.5 / 2.2 / 2.3 / 2.5 / 2.6 / 3.5 / 5.5 incluídas).

O ecossistema v3 acrescenta, sobre as mesmas avaliações: um **dashboard de cartões** single-scroll stdlib (`build_dashboard.py`) com os cartões **Technical GO/NO-GO**, **Portfolio**, **Thesis** e **Broker** (NÃO são separadores/tabs — é layout de cartões num único scroll); cobertura **de mercado global** (TW/CN/HK/IN/KR/JP, local + EUR; ver `scripts/markets.py` e `docs/MARKET_COVERAGE_v3.md`); e um skill **paralelo** `/bd_stocks_daily_growth` para hyper-growers (roadmap item 11, renomeado de `/bd-stocks-rockets`).

**v3.1 (2026-07-15)** acrescenta ao report deep: série trimestral **EBITDA + FCF** com forecast 4Q híbrido (`financial_history.py`, Phase 2.2, cache `_fin_history/`), **metrics strip** no topo (bloco `top_strip` do analysis JSON; screens também), chart de **revenue sources** 3 anos (`_segments/`, excepção LLM documentada), chart **relative performance 30 meses** vs benchmark regional + sector ETF, tese/risco **promovidos em callouts coloridos** (labels de parser preservados), secção **§2.19 broker (€1500)** para composite ≥ 7.0, e secção **§4 macro** com cache diário `_macro/` (Phase 2.6, prompt `macro_daily.md`).

**v4 wave-1 · Phase B (2026-07-22)** acrescenta ao deep a **valuation depth** (spec rev 3 §7, overlay-only): bandas P/E & P/S da própria história (`valuation_bands.py`, Phase 2.3), forward target FY+3 TIKR-style (target @ data + est. return + IRR), sensitivity table com margin-bear row, e o bloco de **intrinsic value 5-modelos com blend + margin-of-safety** (`intrinsic_value.py`). Composite v2.2 intocado; keys aditivas no analysis JSON (`valuation_bands`, `intrinsic_value`). Fases seguintes da wave 1 (A C D E G F) por construir.

**Horizonte**: 1-5 anos (quality compounders, não day-trade).
**Output**: `C:\BD_Obsidian\Personal\Finance\StocksDaily\`
**Disclaimer obrigatório** em cada relatório e email: 🤖 Auto-generated. Not investment advice. Verify all figures before acting.
**Footer obrigatório** — última linha de cada relatório (deep e screen), após um `---`: `*Analysis written by {model name, e.g. Claude Fable 5} · bsdias©2026*`. O model name é o modelo da sessão que escreveu a análise (visível no environment do Claude Code) — nunca hard-coded.

## Ground-truth rule (CRITICAL)

**Números estruturados (revenue, P/E, margins, ROE, debt, prices) — SEMPRE de Python helpers (yfinance/stockanalysis).** Nunca extrair números de 10-K / 10-Q via WebFetch. LLM só compõe narrativa (tese, riscos, guidance management, management quality score qualitativo). Se precisares de um número, chama o helper. Qualquer secção qualitativa (§2.1, 2.3, 2.7, 2.11, 2.12, 2.14) deve citar números a partir da JSON da Phase 2 — **nunca inventar**.

**Duas excepções documentadas (v3.1), ambas com fonte + data obrigatórias em cada número:**
1. **Revenue segments** (Phase 2.5 step 7b) — nenhuma API free tem segment data; o LLM extrai a tabela oficial de segmentos do annual report para `_segments/{TICKER}.json`, sempre marcado "company filings (LLM-extracted)" + `source_url`.
2. **Macro valuation/country data** (Phase 2.6) — S&P 500 P/E/P/S/EV/EBITDA e macro por país via WebFetch (multpl/WSJ/gurufocus/fontes oficiais), cada valor com fonte + as-of date; "not available" antes de estimar.

## Composite score v2.2 (weights)

Schema `2.2`. **Weights are unchanged from v2.1** — v2.2 adds *structural* improvements only (no weight-magnitude shift; magnitude changes stay gated on the item-12 backtest, see `docs/SCORING_REVIEW_v3.md`):

| Componente                                            | Peso   | Fonte                  |
| ----------------------------------------------------- | ------ | ---------------------- |
| Fundamentals (Piotroski + gates + Altman)             | 35%    | Python                 |
| Valuation (P/E + PEG + FCF yield + DCF upside + **EV/EBIT**) | 20%    | Python                 |
| Moat (ROE consistency + margin stability; **ROIC>25% → ×1.25 Buffett opt-in**) | 12%    | Python                 |
| Peer ranking                                          | 12%    | Python + LLM narrative |
| Growth Durability (CAGR + stability + Lynch category) | 8%     | Python                 |
| **Management Quality**                                | **8%** | **LLM (Phase 2.5)**    |
| Market Context (VIX / FGI)                            | 5%     | Python                 |

**v2.2 deltas (weights unchanged):**

- **ROIC + EV/EBIT** computed in `_compact_fund` (Magic-Formula proxy): EV/EBIT feeds the Valuation sub-score; ROIC drives the Buffett moat opt-in. (Roadmap items 1 + 6.)
- **Buffett moat opt-in**: `apply_buffett_moat()` lifts the moat *sub-score* ×1.25 (capped at 10) only when ROIC > 25% — the 12% moat *weight* is untouched, so no rebalancing (`score_details.moat.buffett_moat_applied`).
- **Gate-5 growth bypass**: `gate5_growth_bypass()` lets a hyper-grower pass Gate-5 despite net margin ≤10% when rev CAGR≥25% AND ROIC≥15% AND FCF/rev improving (`gates_detail.gate_5_margin.gate_5_bypassed`).
- **News decay overlay**: `compute_news_freshness()` (half-life 7d on the last earnings date) — UX freshness signal only, **no composite effect**; `< 0.5` raises a `data_warnings` note. (Roadmap item 7.)

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
| `macro_daily.md`                 | v3.1 (Phase 2.6)                                               | Macro diário: mercados, S&P valuation (sourced), country table (TTL 7d)      | `_macro/<date>.md` + §4  |

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
    {"ticker": "JMT.LS", "size": "big", "region": "PT", ...},
    {"ticker": "6702.T", "size": "big", "region": "JP", ...},
    {"ticker": "0700.HK", "size": "big", "region": "HK", ...}
  ]
}
```

Os screens são 4: 1 big + 1 small_growth (qualquer região) + **2 garantidamente non-US** (`region != US`, qualquer size — foco deliberado em mercados fora dos EUA). Se o pool elegível tiver menos de 2 nomes non-US disponíveis, o script avisa em stderr e devolve os que houver.

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
schema_version: "2.2"
sources: [url1, url2, ...]
---
```

Screens do NOT trigger industry cache checks.

### Phase 2 — Analyse each ticker (sequential, to avoid yfinance rate limits)

For **each** of the 5 tickers (deep first, then the 4 screens):

```bash
python "%SCRIPTS%\analyze_ticker.py" --ticker ASML.AS --mode deep
```

**After each analyse call, check these flags in the JSON output:**

- `earnings_today: true` → material event risk within hours. For the **deep** ticker, pick a replacement manually from `_prefiltered.yaml` (same `size` bucket, not in the 183-day dedupe window per `_log.csv`) and re-run `analyze_ticker.py` on it; do NOT re-run `pick_candidates.py` — it's date-seeded and will return the same ticker. For a **screen** ticker, annotate the screen report with an explicit "⚠️ Earnings today" banner and keep going (cheaper to note than to re-pick).
- `dcf_valid: false` → **do not quote `dcf_intrinsic` as a price target anywhere in the narrative.** The `dcf_reason` field explains why the model can't be trusted (negative FCF, TTM/annual divergence, or |upside|>70% sanity trip). Section 2.11 should reference the reason verbatim and mark the intrinsic as "not meaningful".
- `score_details.peer_info.peers_source` → `by_ticker` means a precise sub-industry peer set was used; `by_industry` means yfinance's industry bucket; `by_sector` is a coarse fallback; `none` means no peers and the peer score is a neutral 5.0 placeholder. Mention the source in §2.10 so the reader can calibrate trust in the ranking.
- `fundamentals.revenue_cagr_basis` → `5y_financials` / `4y_financials` / `3y_financials` / `3y_income_stmt` / `1y_yoy_fallback` / `unavailable`. v2.1+ tolerates NaN years and short series. When basis is `1y_yoy_fallback`, mention it in §2.9 (Growth decomposition) so the reader knows the CAGR is a single-year proxy, not a multi-year trend.
- `data_quality` → `ok` / `corrected` / `suspect` (3 validation layers).
  - **`corrected`** → Layer 2 self-healed a stale `info` price using `history()`'s last close (and recomputed `market_cap`). Read `corrected_fields` for what changed — the numbers in the JSON are already the FIXED ones, safe to use. This auto-fixes the CMO.MC €8.49→€38 class. Add a small "ℹ️ price auto-corrected from history()" note.
  - **`suspect`** → Layer 0 found an UNFIXABLE inconsistency. **DO NOT trust the raw numbers** — read `consistency_issues` and `cross_validation.divergences`, cross-check the affected fields against the official filing before quoting, and add a "⚠️ data-quality: suspect" note. This catches the distorted-margin/PE class (e.g. SEM.LS P/E 50 vs margin 31%).
  - `cross_validation.error` containing "no coverage" just means FMP free can't validate this ticker (EU exchanges) — Layers 0+2 cover it. Note: no free quote API (FMP/Polygon/Finnhub free, Stooq) covers Iberian small-caps; Layers 0+2 (pure yfinance) are the protection there.
- **v2.2 flags:** `gates_detail.gate_5_margin.gate_5_bypassed: true` (+ `gate_5_bypass_reason`) → a hyper-grower passed Gate-5 on the growth bypass (rev CAGR≥25% AND ROIC≥15% AND FCF/rev improving) despite net margin ≤10% — say so in §2.6/§2.9, do not call it a margin failure. `news_freshness` (0–1, half-life 7d on the last earnings date) is a UX freshness overlay only (no composite effect); when `< 0.5` a `data_warnings` note flags that the data lags the next print — surface it in the TL;DR. `score_details.moat.buffett_moat_applied: true` means ROIC>25% lifted the moat sub-score 1.25x (still inside the unchanged 12% moat weight).

v2 output JSON (the ground truth — USE THESE NUMBERS):

```json
{
  "ticker": "ASML.AS",
  "mode": "deep",
  "schema_version": "2.2",
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

### Phase 2.2 — Financial history + forecast (deep only, v3.1)

Runs right after `analyze_ticker.py` for the deep ticker (needs its JSON for the consensus block):

```bash
python "%SCRIPTS%\financial_history.py" --ticker ASML.AS --analysis-json "%OUT_DIR%\_tmp\{date}_{ticker}.json"
```

- Fetches a quarterly EBITDA/FCF/revenue series (alvo 40 trimestres): Alpha Vantage para listings US (sem sufixo), yfinance fallback (~5-6 trimestres + série anual) para o resto. Cache `_fin_history/{TICKER}.json` (TTL 80 dias) — re-runs e re-avaliações não voltam à rede.
- **AV budget**: 2 chamadas por deep; worst case diário (1 deep + 4 cascades) = 10 vs limite free de 25. Guard automático em `_fin_history/_av_budget.json` — a partir de 20 chamadas/dia o script salta AV e usa yfinance.
- Forecast 4 trimestres (híbrido): receita interpolada do consensus (`revenue_estimate_current/next_year`) via seasonal split histórico × margem mediana trailing → EBITDA/FCF. Sem consensus (`analyst_count < 3`) → extrapolação de tendência, labelled. Menos de 4 trimestres de histórico → forecast suprimido (`forecast_suppressed_reason`).
- Copiar `source` e `quarters_available` para o frontmatter (`fin_history_source`, `fin_history_quarters`).
- Falha total → JSON `{"error": ...}`, chart skipped, nota no report. Non-fatal.
- Screens NÃO correm esta phase.

### Phase 2.3 — Valuation depth (deep only, v4 Phase B)

Corre logo a seguir à Phase 2.2 (usa o cache `_fin_history/` para o P/S band e o CAGR ladder) e antes da Phase 2.5. **Ordem obrigatória** — bands primeiro, intrinsic depois (lê o band do JSON):

```bash
python "%SCRIPTS%\valuation_bands.py" --ticker ASML.AS --analysis-json "%OUT_DIR%\_tmp\{date}_{ticker}.json" --update
python "%SCRIPTS%\intrinsic_value.py" --analysis-json "%OUT_DIR%\_tmp\{date}_{ticker}.json" --update
```

- **Overlay-only**: composite e weights intocados; `--update` acrescenta as keys aditivas `valuation_bands` e `intrinsic_value` ao analysis JSON (schema continua 2.2).
- **P/E band**: EPS anual via Alpha Vantage `EARNINGS` (US, 1 chamada, **budget partilhado** `_fin_history/_av_budget.json`) ou yfinance `income_stmt` (~4-5 anos, não-US — banda **esperada shallow**; `depth_years` sempre presente). Cache `_valuation/{TICKER}.json`, TTL 80 dias. **P/S band**: revenue anual do cache `_fin_history/` ÷ shares actuais.
- **Exit multiple = MEDIANA da banda** (não a média — anos de transição com EPS≈0 inflacionam a média para >50×; caso ADSK 2026-07-22), capped no máximo histórico (`justified_exit_pe`).
- **Guards automáticos**: rescale de histórico em pence (classe EXPN.L, GBp ×0.01); `unit_check` por banda (`ok`/`skewed`/`mismatch`/`unknown` — `mismatch` ⇒ banda degrada para "not available", nunca renderiza lixo; `skewed` = provável currency skew statements-vs-quote, renderiza com warning); `sanity_flag` no forward target quando o IRR sai de [−15%, +30%]/ano.
- **Flags a ler no output**: `forward_target.sanity_flag` (→ apresentar como *cenário*, não como target), `blend.label` (que modelos entraram e porquê os excluídos ficaram fora — ex. "blend of 4/5 — dcf excluded: cyclical distortion"), `mos_class` (`deep_value`/`fair`/`rich`/`not_computable`), `pe_band.unit_check`.
- Falha total → `{"error": ...}` + exit 0; a §2.11 degrada para o bloco DCF v3.1. Screens NÃO correm esta phase.

### Phase 2.5 — Qualitative LLM pass (deep only)

Runs in Claude's orchestration context. Skipped entirely for screens.

1. **Refresh industry cache if stale** (from Phase 1.5 directive). Substitute `{INDUSTRY}` = `deep.sector`. Run `industry_macro.md` first → use output as `{MACRO_OUTPUT}` for `industry_customer.md` → use both as context for `industry_architecture.md`. Write the combined result to `_industry/<slug>.md` with the frontmatter above. Use WebFetch over 3-5 credible sources (trade association reports, consulting-firm industry overviews, SEC filings for the sector's top-3 players).

2. **Business model** — run `01_business_model.md` with `{ANNUAL_NARRATIVE}` from Phase 4's WebFetch. Output → §2.1.

3. **Management quality** — run `02_management_quality.md`. Parse the line `Management Quality Score: X.X/10` → that's `mgmt_score`. The rest of the output → §2.3.

4. **Growth decomposition & constraints** — run `03a_growth_decomposition.md`, then `03b_constraints.md` with 03a's output, then `03c_growth_assumption_check.md`. Combined output → §2.9.

5. **3-Layer Risk Audit** — run `04_risk_audit.md`. Output → §2.13.

6. **Consensus color** (Borja #18) — 1 short paragraph reconciling the deep-dive verdict with the `consensus` JSON block (recommendation key, target mean/range, EPS/revenue estimates). Skip entirely if `analyst_count < 3`. Output → §2.14.

7. **Bear case** — derive `{BULL_THESIS}` from §2.1 + §2.9 + TL;DR thesis line; run `05_bear_case.md`. Parse the FINAL LINE `If {X} happens, the thesis is broken.` → `bear_case_trigger`. Full output → §2.15.

7b. **Revenue segments (v3.1 — excepção documentada à ground-truth rule)** — se `_segments/{TICKER}.json` não existe ou tem >1 ano (`extracted_at`), extrair a tabela de segment revenue do annual report já fetched na Phase 4 (a nota de segmentos do 10-K traz 3 anos numa só tabela) e escrever:

   ```json
   {"fiscal_years": ["FY2023","FY2024","FY2025"], "currency": "USD",
    "segments": [{"name": "...", "values": [x, y, z]}],
    "source_url": "...", "extracted_at": "ISO"}
   ```

   para `%OUT_DIR%\_segments\{TICKER}.json`. **Esta é a ÚNICA situação em que números vêm do LLM** — porque nenhuma API free tem segment data. O chart e a §2.1 marcam sempre a origem ("company filings, LLM-extracted") + `source_url`. Sem filing disponível → não escrever JSON, chart skipped, `segments_available: false` + `⚠️ Segment data unavailable` na §2.1. Valores só da tabela oficial — nunca estimar nem interpolar.

8. **Finalise composite**:
   
   ```bash
   python "%SCRIPTS%\finalize_score.py" --json-path {analyze_json_path} --mgmt-score {mgmt_score}
   ```
   
   Use the returned JSON for Phase 5. Sets `management_score`, `management_flag`, recomputes `scores.composite` and `verdict`.
   
   **Then write `finalize_score.py` stdout to `%OUT_DIR%\_tmp\{date}_{ticker}.json` (overwrite Phase 2's intermediate).** Phase 3 (`render_charts.py`) reads from this file via `--analysis-json`. Without this step, the radar PNG will be skipped (validation gate) and the report loses its score breakdown.
   
   *(This is step 8 of Phase 2.5 — referenced from Phase 3's pre-condition below.)*

If any Phase 2.5 step fails, log a warning and continue with what you have — the report degrades gracefully (missing section + `(assumption — evidence gap)` note), it does not abort.

### Phase 2.6 — Macro snapshot (once per run, v3.1)

Corre UMA vez por run (não por ticker), antes da Phase 5:

```bash
python "%SCRIPTS%\macro_snapshot.py" --check
```

- `stale: false` → o `_macro/{today}.md` existe; todos os reports do dia embedam dele. Nada mais a fazer.
- `stale: true` → duas metades:
  1. **Python**: `python "%SCRIPTS%\macro_snapshot.py" --fetch` → índices/VIX/yields/FX/commodities/BTC com Δ1d/Δ1w → `_macro/{today}.json`.
  2. **LLM**: correr `prompts\macro_daily.md` com `{PYTHON_METRICS_JSON}` = o JSON acima, `{COUNTRY_TABLE_FRESH}` da directive, `{PREVIOUS_MACRO_MD}` = conteúdo do `fallback_md` (ou "none"). WebFetch para S&P 500 P/E / forward P/E / P/S / EV/EBITDA (multpl.com, WSJ, gurufocus — **fonte + data em cada número; "not available" antes de estimar**). Tabela country (US/EU/China/Japão: GDP, CPI, policy rate, unemployment) só re-fetch quando `country_table_fresh: no` (TTL 7 dias — são dados mensais); caso contrário copiar do anterior. Escrever `_macro/{today}.md` com frontmatter (`date`, `country_table_date`, `sources`).
- **Degradação**: qualquer metade falha → reports embedam o `fallback_md` mais recente com `⚠️ macro snapshot stale ({N} days)`. A §4 nunca desaparece silenciosamente.
- Cada report do dia grava `macro_cache_date` no frontmatter.

### Phase 3 — Render charts (deep only)

**Pre-condition (CRITICAL):** the analysis JSON for this ticker MUST have been written to `%OUT_DIR%\_tmp\{date}_{ticker}.json` first, with all 7 score components populated. For deep mode, this means writing the `finalize_score.py` stdout (Phase 2.5 step 8) to that file. For screens, write Phase 2's stdout. **Without this file, render_charts will validate-skip the radar chart and the report will lose its score-breakdown PNG.** A canonical `--analysis-json` argument prevents the silent-empty-stdin bug that produced misleading 0/10 radars.

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
- `YYYY-MM-DD_TICKER_ebitda_fcf.png` — v3.1: EBITDA (barras) + FCF (linha) trimestral, profundidade real no título, forecast 4Q tracejado (lê `_fin_history/{TICKER}.json`; skip limpo se ausente)
- `YYYY-MM-DD_TICKER_relperf.png` — v3.1: 30 meses normalizados a 100 — ticker vs benchmark regional (`BENCH_BY_SUFFIX`) vs sector SPDR ETF; anota fallback quando não há índice regional mapeado
- `YYYY-MM-DD_TICKER_segments.png` — v3.1: revenue por segmento, 3 anos fiscais (lê `_segments/{TICKER}.json`; skip limpo se ausente)

Screens não chamam este script.

### Phase 3.5 — Technical Score & GO/NO-GO (deep only, fund score ≥ 7.0)

Runs **only for the deep ticker** and **only when its fundamental score ≥ 7.0** (read `scores.fundamentals` from the analysis JSON — the per-axis fundamental sub-score, not the composite). For names below the gate, skip this phase entirely: the technical read adds no value if the business hasn't cleared the fundamental bar, and the report's §2.10 keeps the indicator table without a GO/NO-GO badge.

```bash
python "%SCRIPTS%\technical_score.py" --ticker ASML.AS --fundamental-score {scores.fundamentals} --analysis-json "%OUT_DIR%\_tmp\2026-04-30_ASML.AS.json"
```

- Indicator math is **reused** from `BD_Finance/technical/*` (RSI/ATR/ADX/Bollinger/max-drawdown) — no TA-Lib, no reimplementation. The script imports them with a yfinance stub so their import-time demo downloads don't fire.
- It fetches ~2y daily OHLCV (yfinance), computes RSI(14)/MACD/SMA50/SMA200/ADX(20)/ATR(14)/support-resistance/volume-trend/relative-strength vs a region index, then emits: `technical_score` (0–10), `go_no_go` (GO/NO-GO), `combined_score` (0.6·fund + 0.4·tech), `entry_zone` (price band), `suggested_stop_loss` ([1.5×ATR, 2×ATR] below price), `risk_level` (Low/Med/High from ATR%), plus all raw indicators under `indicators`.
- If fund score < 7.0 it exits 0 with `{"skipped": true, ...}` — handle gracefully (no GO/NO-GO in §2.10).
- The script persists `%OUT_DIR%\_technical\{TICKER}.json` automatically (the offline, stdlib-only dashboard reads the same fields from report frontmatter).
- **Wire the output into the report:** fill §2.10's callout + indicator table from this JSON, and write the six scalars into frontmatter (`technical_score`, `go_no_go`, `combined_score`, `entry_zone`, `suggested_stop_loss`, `tech_risk_level`) so `build_dashboard.py` surfaces the row in the Technical GO/NO-GO table. Use `go_callout = "success"` when GO, `"warning"` when NO-GO.
- Screens do **not** run this phase.

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

Returns a JSON dict with `business_summary` (yfinance `longBusinessSummary`, ~1500 chars MD&A-equivalent), `recent_news` (yfinance `Ticker.news`), `ir_url`, `stockanalysis_fundamentals_url`, and a `narrative_quality` grade (`good` / `partial` / `degraded`). Use the combined `business_summary + recent_news` content as the `{ANNUAL_NARRATIVE}` substitution. If quality is `good` or `partial`, you can skip WebFetch entirely. If `degraded`, then try WebFetch on `annual_url` / `ir_page_url` from `find_reports.py` (avoid SEC EDGAR direct URLs — they 403). Degraded final state → §2.7 / §2.8 carry the `⚠️ Official report narrative unavailable` note and Phase 2.5 prompts label inferred claims accordingly. **Always copy the final grade into report frontmatter as `narrative_quality`** (after any WebFetch upgrade attempt — record what the report was actually written from), so degraded narratives are visible without opening the report.

### Phase 5 — Write the report

**Nome do ficheiro**: `{date}_{ticker}_{verdict}.md` (deep) ou `{date}_{ticker}_screen.md` (screens).
`verdict` ∈ {`great` ≥9.0, `invest` 7.5-8.9, `review` 6.0-7.4, `fair` 4.0-5.9, `reject` <4.0}.

**Fair price (deep + screen)** — every report whose verdict signals decent fundamentals (`great` / `invest` / `review`) records a fair-price anchor in frontmatter: `fair_price` = `dcf_intrinsic` when `dcf_valid: true`, otherwise `consensus.target_median` when `analyst_count ≥ 3` (both straight from the analyze JSON — no LLM estimate). Set `fair_price_basis` to `dcf` or `consensus` accordingly. For `fair` / `reject` verdicts **omit both keys** — a price anchor on a weak thesis is noise. `build_dashboard.py` surfaces these as the "Fair Px" / "Upside" columns in All Evaluations.

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
fair_price: 920                # dcf_intrinsic se dcf_valid, senão consensus target_median (≥3 analistas); OMITIR quando verdict ∈ {fair, reject} ou sem âncora fiável
fair_price_basis: dcf          # dcf | consensus ; presente sse fair_price presente
fair_value_low: 830            # v4 Phase B: intrinsic_value.fair_value_range (min/blend/max dos modelos válidos); omitir os 3 se blend not computable
fair_value_mid: 940            # o blend 5-model — a âncora do MoS
fair_value_high: 1105
mos_class: fair                # deep_value | fair | rich ; omitir se not_computable
valuation_depth_years: 14      # pe_band.depth_years ; omitir se banda degradada (unit mismatch) ou ausente
earnings_date_next: 2026-04-24
manual_reviewed: false
narrative_quality: good        # good | partial | degraded — source quality the narrative was written from (get_narrative.py / post-WebFetch)
management_score: 8.5          # null for screens
management_flag: false         # true only if <7.0 and mode==deep
industry_cache_date: 2026-04-17
industry_cache_slug: semiconductors
bear_case_trigger: "If ASML loses EUV monopoly to a credible competitor within 3 years"
technical_score: 8.4            # Phase 3.5; omit when fund score < 7.0 or screen
go_no_go: GO                    # GO | NO-GO ; omit when not run
combined_score: 8.28            # 0.6*fund + 0.4*tech ; omit when not run
entry_zone: "1284.39–1514.60"   # omit when not run
suggested_stop_loss: "1400.75–1429.21"  # [1.5xATR, 2xATR] ; omit when not run
tech_risk_level: Med            # Low | Med | High ; omit when not run
fin_history_source: alphavantage  # alphavantage | yfinance ; omit se financial_history falhou
fin_history_quarters: 38          # profundidade real da série; omit se falhou
segments_available: true          # false quando não há _segments/{TICKER}.json válido
broker_reco: "XTB — €3.80 round-trip"  # só quando composite ≥ 7.0 E mercado coberto; omit caso contrário
macro_cache_date: 2026-07-15      # data do _macro embed usado na §4
schema_version: "2.2"
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
> **Conviction**: {High | Medium | Low} — {razão em meia linha, e.g. "all pillars intact, but valuation leaves no margin of safety"}
> **Fair price**: {fair_price} {currency} ({fair_price_basis}) → upside {pct}% vs {price_at_eval} — omitir a linha quando não há fair_price
> **Thesis**: {1-line bull case}
> **Risks**: {2-3 key risks}
> **Bear trigger**: {bear_case_trigger}
> **Action**: {explicit next step}
> **Position size**: {sizing band da tabela abaixo, e.g. "Starter 1.5–3% of equity book; build to 4% on execution"} — always end with "(guideline, not advice)"
> **Entry plan**: {se GO + entry_zone: "accumulate inside {entry_zone}; invalidation below {stop_loss}"; se NO-GO: "thesis ok, timing not — wait for {condição concreta}"; se sem tech read: "no timing read — size entry in thirds"}
> **Earnings watch**: próximos earnings em {earnings_date_next}

**Position-size guideline (deterministic — apply, don't improvise):** start from the verdict band — `great` ≥9.0 → core 4–6%; `invest` 7.5–8.9 → starter 1.5–3%, build to 4%; `review` 6.0–7.4 → watchlist only (0%, define a trigger); `fair`/`reject` → no position. Then shift **one band down** (core→starter, starter→watchlist) for each of: `management_flag: true`, `tech_risk_level: High`, `go_no_go: NO-GO`, `data_quality: suspect` — applied at most once in total, not cumulatively below watchlist. Conviction line: High = no downshift triggered and ≥6 gates; Low = any downshift triggered; Medium otherwise.

> [!success] 💚 **Thesis**: **{bull case em 1-2 frases, bold — versão expandida da linha do TL;DR}**

> [!danger] 🔴 **Risks**: **{risco #1 + bear trigger, bold — versão expandida da linha do TL;DR}**

*(Estes dois callouts PROMOVEM a tese/risco visualmente. CRÍTICO: mantêm os labels literais `**Thesis**:` e `**Risks**:` — `build_dashboard.py`/`send_email.py`/`thesis_dashboard.py` fazem regex-match desses labels; as linhas do TL;DR ficam também intactas.)*

### 📊 Metrics strip

**P/E {pe_ttm}x · Forward P/E {forward_pe}x**

| Rev CAGR 5y | FCF margin | FCF yield | ROE | ROIC | Gross margin | Net debt/EBITDA | Net payout | Price 1y | Price {5y ou "since {date}"} |
|---|---|---|---|---|---|---|---|---|---|
| {x}% | {x}% | {x}% | {x}% | {x}% | {x}% | {x}x | {x}% | {x}% | {x}% |

(Fonte: bloco `top_strip` do analysis JSON — nunca recalcular à mão. Price returns são dividend-adjusted; quando `price_return_5y_span != "5y"`, o header da última coluna mostra "since {date}".)

![EBITDA & FCF](IMG/{date}_{ticker}_ebitda_fcf.png)
*EBITDA & FCF — {n} trimestres ({source}); forecast 4Q: {forecast basis} — derived estimate, not guidance. Omitir a imagem + caption se o chart foi skipped.*

![Price 1Y](IMG/{date}_{ticker}_price.png)

![Relative 2.5y](IMG/{date}_{ticker}_relperf.png)
*{1 linha: out/underperformance vs {benchmark} e vs sector proxy {ETF} nos últimos 30 meses.}*

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

![Revenue sources](IMG/{date}_{ticker}_segments.png)
*Fontes de receita — 3 anos fiscais. Source: company filings (LLM-extracted) — verificar contra {source_url}. Omitir imagem + caption se `segments_available: false` (nesse caso escrever `⚠️ Segment data unavailable`).*

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
| #8  | **EV/EBIT** | {ev_ebit}x | — | Magic Formula (v2.2); feeds Valuation sub-score |
| #9  | Net income | {net_income:,} | — | |
| #9  | P/E (trailing) | {pe_ratio}x | — | |
| #9  | PEG | {peg}x | — | |
| #10 | Gross margin | {gross_margin_ttm}% | — | |
| #10 | Operating margin | {operating_margin_ttm}% | — | |
| #10 | Net margin | {net_margin_ttm}% | {net_margin_5y_avg}% avg | |
| #11 | ROE | {roe_ttm}% | {roe_5y_avg}% avg | |
| #11 | **ROCE** | {roce_ttm}% | — | EBIT / (Assets − Current Liab.) |
| #11 | **ROIC** | {roic_ttm}% | — | v2.2 Magic Formula; >25% triggers Buffett moat 1.25x (`score_details.moat.buffett_moat_applied`) |
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

### 2.10 Análise técnica — Technical Score & GO/NO-GO
> [!{go_callout}] Technical Score **{technical_score}/10** · **{go_no_go}** · Combined (fund+tech) **{combined_score}/10** · Risco {tech_risk_level}
> **Entry zone**: {entry_zone} {currency} · **Stop sugerido (ATR)**: {stop_loss} {currency} ({reason curto})

| Indicador | Valor | Leitura |
|---|---|---|
| Preço vs SMA50 / SMA200 | {price} / {sma50} / {sma200} | {tendência: acima/abaixo, golden/death cross} |
| RSI(14) | {rsi} | {sobrecompra >70 / saudável 50-70 / fraqueza <40} |
| MACD / signal | {macd} / {macd_signal} | {bullish se macd>signal>0} |
| ADX(20) | {adx} | {força de tendência: >25 forte, <20 fraca} |
| Força relativa 6m vs {benchmark} | {rel_strength_6m} | {out/underperform vs índice} |
| ATR(14) ({atr_pct} do preço) | {atr} | {volatilidade → risco} |
| Suporte / Resistência (60d) | {support} / {resistance} | {breakout: sim/não} |
| Drawdown máx 1Y | {max_drawdown_1y} | — |

*GO/NO-GO timing-only: requer technical_score ≥ 6.0, preço acima da SMA200, RSI ≤ 80 e MACD não profundamente baixista. Um NO-GO não invalida a tese fundamental — apenas sinaliza que o momento de entrada não está alinhado. Só corre para tickers com fundamental score ≥ 7.0 (ver Phase 3.5).*

### 2.11 Valuation depth + Intrinsic value (v4 Phase B)

**a) Own-history bands** (do bloco `valuation_bands`; sempre com depth):

| Banda | Current | Min | Mediana | Média | Max | Percentil | Depth |
|---|---|---|---|---|---|---|---|
| P/E | {pe_band.current} | {min} | {median} | {mean} | {max} | {percentile}% | {depth_years}y ({eps source}) |
| P/S | {ps_band...} | | | | | | {depth_years}y |

{unit_check=skewed → nota "⚠️ possível currency skew statements-vs-quote"; mismatch → a linha vira "not available (unit mismatch)"; depth_years<5 → "banda shallow — histórico limitado ({source})"}

**b) Forward target FY+3 (TIKR-style)** — os três números lado a lado, para um total return grande não se disfarçar de bom retorno anual:

| Target @ {horizon_label} | Est. total return | IRR anualizado |
|---|---|---|
| **{target_price} {currency}** | {est_total_return_pct}% | **{irr_annualized_pct}%/ano** |

Growth anchor g = {g} (mediana de: {basis} — nunca uma taxa isolada), exit P/E = **mediana da banda** {exit_pe} (capped no máx histórico). CAGR ladder ao lado do consensus: 1y {1y} · 3y {3y} · 5y {5y} · 10y {10y|n/a} · 15y {15y|n/a}.
{sanity_flag → callout ⚠️ com o texto verbatim — apresentar como CENÁRIO, não target}

**c) Sensitivity** ({sensitivity.rows}): fair value a múltiplo conservador (p15) / médio / máximo histórico + **margin-bear row** (margem líquida mínima 5y × múltiplo médio).

**d) Intrinsic value — 5 modelos** (do bloco `intrinsic_value`):

| Modelo | Valor | Válido | Nota |
|---|---|---|---|
| 2-min EPS-growth | {value} | ✓/✗ | {reason se inválido} |
| Lynch PEG | ... | | |
| P/E forward target | ... | | |
| DCF (v3.1) | {dcf_intrinsic} | {dcf_valid} | {dcf_reason} |
| ROE residual income | ... | | Ke = {cost_of_equity} (rf {rf} + β {beta}·5%) |

**Blend**: {blend.label} → **{blend.value} {currency}** · **MoS {mos_pct}% → {mos_class}** · Range **{low} / {mid} / {high}**.
**EV vs Market cap**: {ev_vs_market_cap.note} (wedge {wedge_pct}%).

**e) DCF (modelo v3.1)**:
{If dcf_valid=true:}
![DCF](IMG/{date}_{ticker}_dcf.png)
DCF intrínseco: **{dcf_intrinsic} {currency}** vs preço {price} {currency} → upside **{upside}%**.
(Assumptions: discount rate 10%, terminal growth 2.5%, based on yfinance 5y FCF)

{If dcf_valid=false:}
⚠️ **DCF not meaningful** — {dcf_reason verbatim}. Do not use the computed intrinsic as a price target; the blend already excludes it (see `blend.label`).

{Se a Phase 2.3 falhou por completo: manter apenas o bloco (e) como na v3.1 + nota "valuation depth unavailable".}

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

### 2.18 Veredicto final — Adviser's letter
Escrever como uma carta curta de um senior adviser ao cliente (5 parágrafos de 1-3 frases, sem headers):

1. **The call** — {verdict_label} + conviction, em linguagem corrente ("This is a business we'd own; the price is the problem").
2. **Why now** — o que nos números de hoje sustenta (ou trava) a decisão. Se management_flag=true, referenciar explicitamente.
3. **How to act** — position size band + entry plan (repetir os do TL;DR, coerentes).
4. **What we're watching** — 2-3 monitorização concreta com números (e.g. "net margin holding >25% at Q3 print", ligada aos pillars e ao bear trigger).
5. **When we'd walk away** — o bear trigger reformulado como instrução de saída.

### 2.19 Broker recommendation (€1500)

**Só quando `scores.composite ≥ 7.0`** — omitir a secção inteira caso contrário.

Dados: `python "%SCRIPTS%\broker_compare.py" --small 1500 --out "%OUT_DIR%\_tmp\{date}_brokers1500.json"` (CLI já existente; correr 1x por run, reutilizar para todos os deeps do dia). Ler a linha do mercado do ticker via o mapa suffix→MARKET_KEY:

| Sufixo | MARKET_KEY (brokers.yaml) |
|--------|---------------------------|
| (sem sufixo — US) | US |
| .IR | IE |
| .LS | PT |
| .TW / .TWO | TW |
| .HK | HK |
| .T | JP |
| .SZ | CN_SZ |

Template da secção:

```md
| Broker | Custo round-trip (€1500) | Notas |
|--------|--------------------------|-------|
| **{cheapest}** ✅ | €{cost} | {fee breakdown 1 linha} |
| {broker 2} | €{cost} | |
| {broker 3} | €{cost} | |
```

+ 1 linha: *"Para uma posição de ~€1500 em {exchange}, o broker mais barato é **{cheapest}** (€{cost} round-trip, {pct}% da posição)."* Escrever o resultado no frontmatter `broker_reco`.

**Mercado não coberto** (sufixo fora da tabela — .AS/.PA/.DE/.L/etc.): a secção renderiza apenas `⚠️ {exchange} não coberto em brokers.yaml — sem comparação de brokers.` e `broker_reco` é omitido do frontmatter.

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

## 4. Macro context ({macro_cache_date})

({Embed de ~15 linhas do `_macro/{date}.md`: tabela Markets today & this week + linha de S&P 500 valuation (P/E, fwd P/E, P/S, EV/EBITDA com fontes) + 2-3 frases do read-through. Não repetir a tabela country inteira — só o embed curto.})

📂 Snapshot completo: [[_macro/{date}|Full macro snapshot]]

{Se o snapshot de hoje falhou: embed do mais recente disponível + `⚠️ macro snapshot stale ({N} days)` — nunca omitir a secção silenciosamente.}

---
*Analysis written by {model name} · bsdias©2026*
```

#### Screen body (versão curta — sem charts, sem narrativa pesada, sem §2.1/2.3/2.9/2.13/2.14/2.15/2.17)

```md
# {TICKER} — {Company} — Score: {score}/10 {emoji} {verdict_label}

> [!warning] 🤖 Auto-generated. Not investment advice. Verify all figures before acting.

> [!info] Screen rápido (1 min) — 6-component score (Management não avaliado em screens)
> {emoji} {verdict_label} ({score}/10, {gates}/7 gates).
> **Thesis**: {1-line thesis}
> **Risks**: {1-line risk}
> **Action**: {explicit next step — e.g. "queue for deep-dive", "revisit after Q3 print", "pass — valuation"}

**P/E {pe_ttm}x · Forward P/E {forward_pe}x**

| Rev CAGR 5y | FCF margin | FCF yield | ROE | ROIC | Gross margin | Net debt/EBITDA | Net payout | Price 1y | Price {5y ou "since {date}"} |
|---|---|---|---|---|---|---|---|---|---|
| {x}% | {x}% | {x}% | {x}% | {x}% | {x}% | {x}x | {x}% | {x}% | {x}% |

(Metrics strip do bloco `top_strip` — screens ganham SÓ isto do v3.1: sem charts, sem broker, sem macro embed.)

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

---
*Analysis written by {model name} · bsdias©2026*
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
SCREEN:  6702.T  → score 7.8 🟢 INVEST (round 1, non-US)
SCREEN:  0700.HK → score 6.9 🟡 REVIEW (round 1, non-US)
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

## Portfolio Management Dashboard (v3 Phase 4)

A holdings-level view on top of the daily evaluations. Two scripts feed a precomputed
`_portfolio.json` that the stdlib `build_dashboard.py` renders as a Portfolio card.

```bash
# 1) Read live holdings from BankBD (READ-ONLY) + yfinance prices -> JSON bundle
python "%SCRIPTS%\portfolio_sync.py"            # stdout = bundle; stderr = summary
python "%SCRIPTS%\portfolio_sync.py" --no-prices  # skip yfinance (use stored EUR value)

# 2) Enrich with fund/tech scores + run the decision engine -> writes _portfolio.json
python "%SCRIPTS%\portfolio_dashboard.py"

# 3) Re-render the dashboard (Portfolio card reads _portfolio.json, stdlib-only)
python "%SCRIPTS%\build_dashboard.py"
```

- **Source of truth**: BankBD SQLite (`C:\Github\BD\Finance\BankBD\bankbd.db`),
  tables `positions` + `position_values`. Opened **read-only** via
  `file:...?mode=ro`; never written. Empty positions table → 0 holdings (card shows
  an empty-state note).
- **Ticker mapping / filtering**: reuses `canon()` (ADR/dual-listing) and
  `classify_nonequity()` from `C:\Github\.scripts\portfolio_deepdive_gap.py`; the
  `asset_type` column also excludes crypto/bond/etf.
- **Scores**: Fundamental score + verdict come from `_log.csv` (most-recent per
  canonical ticker); Technical score / GO-NO-GO come from report frontmatter.
  Anything older than 90 days is flagged `score_stale` and routed to **Review**
  ("needs screen") — old numbers are never silently used.
- **Overall Investment Score** = 0.70·fund + 0.30·tech (whichever is present).
- **Decision engine** (`decide()`, pure/tested) → one of **Hold / Buy-More / Sell /
  Review**, each with a cited trigger: stale→Review; thesis broken→Sell; fundamental
  deterioration (reject/fair or fund<5)→Sell; technical NO-GO on a moderate name→Sell;
  weight>20%→Review (reallocation); strong score + below cost + not NO-GO→Buy-More;
  else Hold.
- **Tests**: `tests/test_portfolio.py` covers the engine + freshness gating
  (network/DB-free).

## Investment Thesis Dashboard (v3 Phase 5)

A thesis-tracker view (FS2 graft) on top of the stored evaluations. One precomputed
`_thesis.json` feeds a **Thesis card** in the stdlib `build_dashboard.py`. **No new LLM
pass, no composite recomputation** — it reuses `_log.csv`, report frontmatter, stored
narratives, and `bear_case_trigger`.

```bash
# 1) Aggregate per-name thesis from stored data -> writes _thesis.json (stdlib-only)
python "%SCRIPTS%\thesis_dashboard.py"

# 2) Re-render the dashboard (Thesis card reads _thesis.json, stdlib-only)
python "%SCRIPTS%\build_dashboard.py"
```

- **Per name** (most-recent report per ticker): Fundamental / Technical / Overall
  scores + Quality / Valuation / Risk reads + a **Buy / Hold / Sell** stance with a
  cited rationale block.
- **Stance logic** (`derive_stance`, pure/tested): thesis broken / weak verdict
  (reject·fair) / score<5 → **Sell**; strong verdict-or-overall≥7.5 + all pillars
  intact + not NO-GO → **Buy**; everything else → **Hold** (with monitoring criteria).
- **Pillars (FS2 — `derive_pillars`)**: 3–5 testable pillars per name — Business
  quality (gates+Piotroski), Valuation (composite band), Balance-sheet resilience
  (Altman-Z), Management & capital allocation (mgmt score/flag), Thesis-failure guard
  (the stored `bear_case_trigger`). Each carries **status** (intact/weakened/broken)
  + **conviction** (High/Med/Low) derived deterministically from stored scalars.
  When a caller supplies `thesis_status` (from `thesis_check.py`), it overrides the
  guard pillar so a drift-detected break shows.
- **Tests**: `tests/test_thesis_dashboard.py` covers reads / pillars / stance / shape
  (network-free, synthetic report dicts).

## Business-model Sankey — standardised palette (v3 Phase 5)

`prompts/01_business_model.md` now defines an explicit colour palette so every money-
engine Sankey is consistent: 🔵 Revenue `#2563eb` · 🟢 value-creation/profit `#16a34a`
(reserved — Gross Profit, Operating Income, Net Income, FCF, Retained Earnings) ·
🔴 operating costs `#dc2626` · 🟤 Interest & Tax `#b45309` · 🟣 Capex `#7c3aed` ·
🟡 capital allocation `#ca8a04`. Uses a YAML `config.sankey.nodeColors` map +
`linkColor: source`, plus a **mandatory legend caption** so the mapping survives
renderers that ignore `nodeColors`. Validated as `sankey-beta` via mermaid-cli 11.12.
