---
name: bd-stocks-daily
description: Daily stock evaluation — picks 3 tickers (1 deep + 2 screens, 1 of them from a non-USA market) from the pre-filtered pool, applies Quality Compounder 7-gates, Piotroski/Altman, peer comparison, management quality score (LLM), industry context (cached per sector), 3-layer risk audit, bear case, computes 0-10 composite score (v2 weights), and writes tiered reports (5min TL;DR / 30min deep) to C:\BD_Obsidian\Personal\Finance\StocksDaily\. Run via Task Scheduler daily 13:30.
argument-hint: "[--ticker TICKER] [--mode deep|screen] [--dry-run] — optional overrides for manual runs"
---

# Daily Stock Evaluation (v4.2 — scoring schema 2.2)

> **Versão e histórico**: a versão corrente é sempre a do último tag git (`git describe --tags`)
> e o histórico completo por versão vive em `docs/CHANGELOG.md`. Este H1 esteve desactualizado
> uma versão inteira (dizia "v4.1 Phase H" enquanto o corpo já documentava a v4.2); não voltar
> a escrever contagens de testes nem estado de wave aqui — pertencem ao changelog.

Avaliação diária automática de 3 acções (1 deep-dive + 2 screens, dos quais 1 garantidamente de mercado não-US) do pool pré-filtrado, com score 0-10 (scoring **v2.2**), peer comparison, market timing, **technical score & GO/NO-GO**, **management quality**, **industry context**, **3-layer risk audit** e **bear case**, layout tiered (5 min TL;DR / 30 min deep). A orquestração corre como um **pipeline de 22 nós** (sub-fases 0.5 / 1.5 / 2.2 / 2.3 / 2.4 / 2.5 / 2.55 / 2.56 / 2.57 / 2.58 / 2.59 / 2.6 / 3.5 / 5.5 / 5.7 incluídas).

O ecossistema v3 acrescenta, sobre as mesmas avaliações: um **dashboard de cartões** single-scroll stdlib (`build_dashboard.py`) com os cartões **Technical GO/NO-GO**, **Portfolio**, **Thesis** e **Broker** (NÃO são separadores/tabs — é layout de cartões num único scroll); cobertura **de mercado global** (TW/CN/HK/IN/KR/JP, local + EUR; ver `scripts/markets.py` e `docs/MARKET_COVERAGE_v3.md`); e um skill **paralelo** `/bd_stocks_daily_growth` para hyper-growers (roadmap item 11, renomeado de `/bd-stocks-rockets`).


> **Histórico por versão** → `docs/CHANGELOG.md`. Os parágrafos de versão que viviam aqui
> foram movidos para lá **verbatim** na v4.3 §3.3 (anexo no fim do ficheiro); os resumos por
> versão estão no corpo. Não voltar a acumular histórico neste cabeçalho: era ~13 % do maior
> ficheiro do skill e estava duplicado no `README.md`.

**Charts — PNGs transparentes (2026-07-28)** — os PNGs não pintam fundo (`transparent=True` / `omit_background`), porque uma imagem estática **não** responde ao tema do leitor: o Obsidian não a troca. Assim, a mesma imagem serve Obsidian claro, Obsidian escuro, email e papel. Consequências que NÃO se devem reverter por engano: (a) a ink é **mid-tone** (INK `#787772` etc.), escolhida para ≥3:1 em ambas as superfícies — o tecto teórico é ~3.9:1, logo passa AA para texto grande/bold mas não os 4.5:1 de corpo de texto em ambas ao mesmo tempo; (b) a paleta foi **re-steppada** para a banda de luminosidade escura L [0.48, 0.67], que é subconjunto da clara — validada nos DOIS modos com `validate_palette.js`; (c) todo o *knockout* cor-de-superfície desapareceu (anéis de marcador → `RING`, chips e halos → só contorno), porque um preenchimento opaco vira uma mancha clara em fundo escuro.

**Charts (2026-07-28)** — `chart_theme.py` continua o sistema visual único; `chart_browser.py` acrescenta um **segundo renderer** (HTML/CSS/SVG via Chromium headless, playwright já instalado para o pdfgen) para os **dois** charts que se estudam a sério: `ebitda_fcf` e `relperf`. É **fallback-first**: qualquer falha devolve `False` e o `render_charts.py` cai no matplotlib — o job das 17:00 nunca regride. `BD_CHARTS_BROWSER=0` força o caminho matplotlib. Os dois renderers consomem os MESMOS números (o relperf partilha a série já buscada via `_relperf_payload`), pelo que só o acabamento difere.

**Horizonte**: 1-5 anos (quality compounders, não day-trade).
**Output**: `C:\BD_Obsidian\Personal\Finance\StocksDaily\`
**Disclaimer obrigatório** em cada relatório e email: 🤖 Auto-generated. Not investment advice. Verify all figures before acting.
**Footer obrigatório** — última linha de cada relatório (deep e screen), após um `---`: `*Analysis written by {model name, e.g. Claude Fable 5} · bsdias©2026 · host: {hostname}*`. O model name é o modelo da sessão que escreveu a análise (visível no environment do Claude Code) — nunca hard-coded. O `{hostname}` é o nome da máquina que correu o job (`platform.node()`, ex. `SecilPT-uPkZhVs`) — serve para saber de imediato se o relatório saiu do portátil ou de um VM host.

## Headless rule (CRITICAL)

**Este skill corre quase sempre sem ninguém a ler.** O job das 13:30 invoca-o como `claude -p` (**non-interactive**) via `C:\Github\.scripts\stocks-daily.bat`. Nesse modo **não existe utilizador para responder** a nada. Logo:

- **NUNCA terminar um run com uma pergunta** — "envio o email?", "queres (a), (b) ou (c)?" — nem usar ferramentas de pergunta interactiva. Não há resposta possível; a pergunta apenas atrasa (ou bloqueia) o pipeline.
- **Decidir e registar, não perguntar.** Havendo julgamento a fazer, escolhe o **default documentado**, executa-o, e escreve no output final *o que* decidiste e *porquê* — ex. "digest enviado com 10 reports; 5 são do run da manhã, duplicados de propósito". O Bruno lê um resultado, não um menu.
- **O email NÃO é decisão deste skill.** O `send_email.py` é invocado pelo **bat**, depois de o skill sair (ver Phase 7). Não o suprimas nem peças autorização. Se suspeitas de digest duplicado, **di-lo no output** — não travas nada.
- Aplica-se igualmente ao `/bd_stocks_daily_growth`.
- Em run **manual/interactivo** perguntar é legítimo; a proibição é para o caminho `-p`. Na dúvida sobre o modo, **age e reporta** — o custo de um default executado é sempre menor que o de um pipeline parado.

**Porque existe esta regra (incidente 2026-07-28):** o run das 17:00 terminou todo o trabalho às 17:50 e acabou a perguntar *"The email — your call: (a) send as-is, (b) skip, (c) trimmed digest"*. Ninguém podia responder. O processo **nunca saiu**, o bat ficou bloqueado na linha imediatamente anterior ao email, e o digest só saiu às **07:32 do dia seguinte — 13.7 h tarde**. Um default executado mais uma nota no output teria custado zero. O bat passou a ter timeout de 5400 s (`run_with_timeout.ps1`) como rede de segurança, mas **a rede não substitui a regra**.

## Ground-truth rule (CRITICAL)

**Números estruturados (revenue, P/E, margins, ROE, debt, prices) — SEMPRE de Python helpers (yfinance/stockanalysis).** Nunca extrair números de 10-K / 10-Q via WebFetch. LLM só compõe narrativa (tese, riscos, guidance management, management quality score qualitativo). Se precisares de um número, chama o helper. Qualquer secção qualitativa (§2.1, 2.3, 2.7, 2.11, 2.13, 2.15) deve citar números a partir da JSON da Phase 2 — **nunca inventar**.

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
| `04_risk_audit.md`               | `5_step_system.md` Step 4                                      | 3 layers + leading indicators                                                | §2.14                    |
| `05_bear_case.md`                | `5_step_system.md` Step 5                                      | "If X happens, thesis is broken."                                            | §2.16                    |
| `06_swot.md`                     | v4 Phase C (idea #3)                                           | SWOT 2×2, Threats/Risks-weighted; cites `red_flags` + numbers JSON           | SWOT card (§2.18a)       |
| `07_thesis_duel.md`              | v4.2 (2026-08-05)                                              | Moat mechanism · bull vs bear side-by-side · **LEAN** (BULL/BEAR/BALANCED, never a %) · sector structural forces | **Cartão §0** (topo do report) |
| `08_earnings_commentary.md`      | v4.3 (2026-08-15) · **OPT-IN** `BD_EARNINGS_COMMENT=1`         | O que a gestão disse e o que mudou no último 10-Q/10-K real (`edgar.py --text`); guidance, segmentos, margem, one-offs, tom vs print anterior | §2.8 (e §2.7 no annual) |
| `industry_macro.md`              | `ai_industry_analysis_framework.md` Step 1                     | Market, value chain, players, disruption                                     | `_industry/<slug>.md` §1 |
| `industry_customer.md`           | `ai_industry_analysis_framework.md` Step 2                     | Buyer journey, switching costs                                               | `_industry/<slug>.md` §2 |
| `industry_architecture.md`       | `ai_industry_analysis_framework.md` Step 3                     | Winning models, moats, top-15 KPIs                                           | `_industry/<slug>.md` §3 |
| `macro_daily.md`                 | v3.1 + v4 Phase D (Phase 2.6)                                  | Macro §8: mercados, valuation vs história, breadth RSP/SPY + sectores (JSON ground-truth), country (TTL 7d), Buffett+M2, forward-profit | `_macro/<date>.md` + §4  |

`ai_industry_analysis_framework.md` Step 4 ("Synthesize with NotebookLM") is intentionally not wired in — that step is an external-tool synthesis, not something the skill can automate.

For the full theoretical context (PT-PT/EN bilingual), see `C:\BD_Obsidian\Personal\Finance\StocksDaily\docs\STRATEGY_GUIDE.md` — comprehensive synthesis of TIKR + Modelo Integrado + 5_step_system frameworks with `IN-USE` / `PLANNED` / `SKIPPED` tags per technique and a roadmap.

## Version flag — `--version {v3, v4}` (default: latest)

Argumento opcional de orquestração. **Omitir = correr a última versão** (hoje `v4`). Resolver SEMPRE via o gate (nunca hard-codar o default):

```bash
python "%SCRIPTS%\version_gate.py" --version {arg ou omitir}
```

Devolve `{version, skip_nodes, skip_scripts, skip_json_keys, note}`. Regras para o orquestrador:
- **`v4` (ou omitido / desconhecido / v9…)** → `skip_nodes: []` → correr o pipeline **completo** (todos os nós abaixo).
- **`v3`** → **SALTAR** os nós overlay v4 listados em `skip_nodes` (2.3 · 2.4 · 2.55 · 2.56 · 2.57 · 2.58 · 2.59 · 5.7): não correr esses scripts, não escrever as suas keys aditivas, e escrever o report na **shape v3.1** (md-primário, sem os cartões overlay). O resto do pipeline (nós 2, 2.2, 2.5, 2.6, 3, 3.5, 4, 5, 5.5, 6, 7) corre igual.
- **`v1`/`v2`** → NÃO alcançáveis por este flag (antecedem o schema 2.2). O gate resolve-os para `latest`; para reproduzir v1/v2 usar git tags + worktrees.
- **Garantia**: as componentes **determinísticas** do composite (gates, Piotroski, Altman, valuation, peer, growth, market) são idênticas entre v3 e v4 — o score é materialmente o mesmo. *Ressalva*: a componente **management** (8%) é escrita por LLM a partir do analysis JSON, que sob v4 contém os blocos overlay e sob v3 não — logo o composite é *materialmente*, não *bit-a-bit*, idêntico (o mgmt read já é não-determinístico de run para run). O flag muda o que renderiza; nunca os pesos nem as componentes determinísticas.

## Node timing (v4.3 — OBRIGATÓRIO nos nós pesados)

O job das 13:30 corre com um tecto de **1800 s** e mediu **22m21s** e **23m41s** nos dois dias
anteriores a 2026-08-15 — ou seja, ~6 minutos de folga. Para decidir o que pode ficar
default-on é preciso **medir**, não adivinhar. `node_timing.py` regista o tempo de cada nó.

Prefixa a invocação dos nós **pesados** (2, 2.2, 2.3, 2.5, 2.56, 2.58, 2.59, 3, 3.5, 5.7) com:

```bash
python "%SCRIPTS%\node_timing.py" --node 2.2 --ticker ASML.AS -- python "%SCRIPTS%\financial_history.py" --ticker ASML.AS --analysis-json "..."
```

O wrapper é **transparente**: devolve o exit code do comando filho intacto, e uma falha da
própria instrumentação nunca rebenta o pipeline (escreve nada e segue). Grava uma linha JSONL
em `OUT_DIR\_timings\{date}.jsonl` — append-only, para que um run morto a meio **mantenha** o
que já mediu (foi exactamente o que se perdeu no timeout de 2026-08-15, que matou a Phase 6).

No fim do run, inclui no output da Phase 8 a linha de topo de:

```bash
python "%SCRIPTS%\node_timing.py" --report
```

`BD_TIMINGS=0` desliga a gravação. Nós leves (update_log, update_shortlist, watchlist) não
precisam de wrapper — o custo do wrapper não compensa o sinal.

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

Status values: `intact` / `weakened` / `broken`. **Surface the status in the TL;DR** as `Thesis status (round {N}): {emoji} {overall_status}`. If `broken`, the report gets a 🚨 banner at the top and §2.16 (Bear case) opens with the broken pillar.

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

**Nomes `size: hyper_growth` são excluídos deste run** (desde 2026-07-28) — pertencem ao `/bd_stocks_daily_growth`, que desde 2026-07-31 corre **antes** deste, na sua própria task (`StocksGrowth`, 12:45), e os avalia com critérios de crescimento. O gate-5 (net margin > 10%) deste modelo rejeitá-los-ia por construção. Os slots deep/big/small já filtravam por size, mas o slot non-US e o shuffle de extras aceitavam qualquer size — daí a exclusão explícita. `pool_stats.hyper_growth_reserved` conta quantos foram reservados.

If any ticker has `round > 1`, the report gets a `🔁 Reavaliação #N` badge at the top and a link back to the prior evaluation, **e o report ganha a secção §5 Histórico** (ver Phase 5).

#### Listing primário vs ADR (2026-08-05)

`pick_candidates.py` reescreve cada pick para a **linha primária/home** da empresa antes de a analisar. Um ADR é um invólucro: mesma empresa, mesmos filings, com um banco depositário e uma perna cambial pelo meio. A identidade de empresa vive em **`listings.py` → `REGISTRY`** (13 empresas), que substituiu as três tabelas de aliases contraditórias que existiam antes (`pick_candidates.TICKER_ALIASES`, `portfolio_deepdive_gap.EQUIV_GROUPS`, `exit_plan.ALIASES`).

**Porque isto importa — não é arrumação, é correcção.** Quando `financialCurrency != currency` (o caso normal de um ADR), o yfinance devolve **market cap em USD e demonstrações na moeda de casa**. Todos os rácios que dividem um pelo outro saem errados pelo factor cambial. Medido em TSM, 2026-07-27:

| Métrica | 2330.TW (home) | TSM (ADR) | Erro |
|---------|----------------|-----------|------|
| P/S | 13.72 | **0.46** | ÷29.74 = taxa TWD/USD |
| EV/EBITDA | 18.41 | **4.49** | mistura EV USD com EBITDA TWD |
| P/E, PEG, ROE, margens | iguais | iguais | ✅ calculados dentro de uma só moeda |

Esses múltiplos falsamente baratos inflaram os sub-scores **peer (6.67 → 8.92)** e **valuation (3.5 → 4.5)**, e o ADR pontuou **8.14** contra os **7.80** da mesma empresa dois dias antes. Analisar a linha home elimina isto à nascença.

**Excepção — data thinness.** `listings.preferred_listing()` sonda ambas as linhas (`.info`, 17 campos que o modelo consome, cache 30 dias em `_tmp/_listing_probe.json`) e só mantém o ADR se a home cobrir **< 80%** do que o ADR cobre. Em 2026-08-05 as 13 empresas resolveram todas para home (a mais apertada foi a Samsung: 005930.KS 88% vs SSUN.F 100%). Se **nenhuma** linha for legível a escolha é a home — uma sonda vazia é sinal de rate-limit no yfinance, não de uma home fina, e cair para o ADR nesse sinal desfaria a política exactamente nos dias maus.

O JSON do pick ganha `listing_home`, `listing_reason`, `listing_alternatives` e (quando houve troca) `listing_swapped_from`; `region` é re-derivada do novo sufixo. `--no-probe` desliga a sonda e usa a home sem rede. ADRs ainda não mapeados são apanhados em `analyze_ticker.py` por `listings.adr_suspicion()`, que **avisa mas nunca adivinha** o símbolo home — inventar um par fundiria o histórico de duas empresas.

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

For **each** of the 3 tickers (deep first, then the 2 screens):

```bash
python "%SCRIPTS%\analyze_ticker.py" --ticker ASML.AS --mode deep
```

**After each analyse call, check these flags in the JSON output:**

- `earnings_today: true` → material event risk within hours. For the **deep** ticker, pick a replacement manually from `_prefiltered.yaml` (same `size` bucket, not in the 183-day dedupe window per `_log.csv`) and re-run `analyze_ticker.py` on it; do NOT re-run `pick_candidates.py` — it's date-seeded and will return the same ticker. For a **screen** ticker, annotate the screen report with an explicit "⚠️ Earnings today" banner and keep going (cheaper to note than to re-pick).
- `dcf_valid: false` → **do not quote `dcf_intrinsic` as a price target anywhere in the narrative.** The `dcf_reason` field explains why the model can't be trusted (negative FCF, TTM/annual divergence, or |upside|>70% sanity trip). Section 2.11 should reference the reason verbatim and mark the intrinsic as "not meaningful".
- `score_details.peer_info.peers_source` → `by_ticker` means a precise sub-industry peer set was used; `by_industry` means yfinance's industry bucket; `by_sector` is a coarse fallback; `none` means no peers and the peer score is a neutral 5.0 placeholder. Mention the source in §2.13 (peer comparison) so the reader can calibrate trust in the ranking.
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

### Phase 2.2 — Financial history + forecast (deep **+ screens**, v3.1 · screens desde v4.3)

Runs right after `analyze_ticker.py` for the deep ticker (needs its JSON for the consensus block):

```bash
python "%SCRIPTS%\financial_history.py" --ticker ASML.AS --analysis-json "%OUT_DIR%\_tmp\{date}_{ticker}.json"
```

- Fetches a quarterly EBITDA/FCF/revenue series (alvo 40 trimestres): Alpha Vantage para listings US (sem sufixo), yfinance fallback (~5-6 trimestres + série anual) para o resto. Cache `_fin_history/{TICKER}.json` (TTL 80 dias) — re-runs e re-avaliações não voltam à rede.
- **AV budget** (corrigido v4.3, medido — não estimado): são **3 chamadas por nome US**, não 2 — `INCOME_STATEMENT` + `CASH_FLOW` aqui, mais o `EARNINGS` que a Phase 2.3 (`valuation_bands`) dispara na mesma run. Com 3 picks todos US e todos cache-cold ≈ **9 chamadas**.
- **O limite de 25/dia da free tier é por ENDEREÇO IP, não por key** (medido 2026-08-15: uma key esgotada, as outras quatro recusadas no mesmo instante). As 6 entradas em `api_keys.txt` são **5 keys distintas** e valem exactamente o mesmo que uma. Logo esta máquina tem **um único orçamento de 25 chamadas/dia**, partilhado por `financial_history.py` e `valuation_bands.py` — que é precisamente o que o contador partilhado `_fin_history/_av_budget.json` já modela. **Não adicionar key pools** (ver `docs/ROADMAP.md`, R5 em WON'T DO).
- Guard automático: a partir de 20 chamadas/dia o script salta AV e usa yfinance. Uma recusa de cap diário **satura o contador de imediato** e não é repetida — esperar não a resolve antes da meia-noite.
- Forecast 4 trimestres (híbrido): receita interpolada do consensus (`revenue_estimate_current/next_year`) via seasonal split histórico × margem mediana trailing → EBITDA/FCF. Sem consensus (`analyst_count < 3`) → extrapolação de tendência, labelled. Menos de 4 trimestres de histórico → forecast suprimido (`forecast_suppressed_reason`).
- Copiar `source` e `quarters_available` para o frontmatter (`fin_history_source`, `fin_history_quarters`).
- Falha total → JSON `{"error": ...}` em stdout, **nenhum ficheiro de cache escrito** (uma falha nunca fica cacheada 80 dias), chart skipped, nota no report. Non-fatal.
- **Screens TAMBÉM correm esta phase (v4.3)** — G-B e G-C, a seguir ao respectivo `analyze_ticker.py`, exactamente com o mesmo comando. Os screens ganham o chart EBITDA/FCF e o frontmatter `fin_history_*`.
  - **Custo medido**: ~3-5 s por ticker (≈10 s pelos dois screens), contra ~6 min de folga num job de 22-24 min — 0,6 % do orçamento. Instrumentar com `node_timing.py --node 2.2 --ticker <T>` como nos restantes nós pesados.
  - **Degradação honesta**: em screens não-US a AV devolve vazio → yfinance (~5-6 trimestres + anual), etiquetado em `fin_history_source`. Mercados que reportam **semestralmente** (p. ex. `.AX` australiano) não têm linhas trimestrais de todo → sem ficheiro, sem chart, `fin_history_*` omitido. Isto é estrutura de mercado, não falha — não inventar uma série.
  - Se o orçamento AV do dia já estiver gasto, os screens US caem em yfinance como qualquer outro nome; o report continua completo, só com menos profundidade.

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

### Phase 2.4 — Red-flag scanner + Beneish (deep only, v4 Phase C)

Corre a seguir à Phase 2.3 e **antes da Phase 2.5** (o `red_flags` fica disponível como contexto quando o LLM escreve o SWOT e a commentary por statement). **Puro consumidor do JSON — zero rede, zero chamadas API** (lê o `statements_raw` que `analyze_ticker.py` persiste na Phase 2):

```bash
python "%SCRIPTS%\red_flags.py" --ticker ASML.AS --analysis-json "%OUT_DIR%\_tmp\{date}_{ticker}.json" --update
```

- **Overlay-only**: `--update` acrescenta a key aditiva `red_flags` (schema continua 2.2; composite e `scores` **intocados**). O scanner **surface-a um veto** (glyph + cor) mas **nunca auto-demota** o veredicto (mesmo padrão do `management_flag`).
- **Checks** (spec §8, lista completa; cada check degrada a `na` independentemente quando falta o line item — esperado em non-US): Income (gross margin <10% · operating margin <15% · interest coverage <2× · SG&A >30% · one-time items >15% NI · gross-margin YoY swing >5pts · receivables-vs-revenue divergence); Balance (current <1.0 · quick <0.6 · D/E >2.0 · **Net Debt/EBITDA >3.0** · working capital <0 · inventory turnover <2× · AR days >60 · book value/share a cair); Cash-flow (OCF <0 · FCF <0 · earnings-quality CFO-vs-NI · capex <10% OCF · dividends >OCF · cash interest coverage <1×).
- **Beneish M-score** (8 índices: DSRI/GMI/AQI/SGI/DEPI/SGAI/LVGI/TATA; flag se **M > −2.22**). Qualquer índice sem inputs ⇒ `m_score: null`, `status: na`, lista `missing` — **esperado em non-US** (receivables/SG&A/depreciation são as linhas mais finas do yfinance lá fora). Par natural do Altman Z.
- **Pills positivos** (nunca vetos, ✓ met / ○ neutral): **net payout yield > 4%** e **ROCE ≥ 20%** (valores já no JSON, `capital_returns` / `fundamentals`).
- **Três sub-scores 0-10 determinísticos** (`income`/`balance`/`cashflow` `.subscore_0_10`), calculados só sobre os checks **computáveis** de cada statement (pass=1 · warn=0.5 · bad=0; `round(10·earned/computable, 1)`). Mesmo JSON → mesmo 0-10. **Nunca entram no composite** — são overlay para render.
- **Flags a ler no output**: `summary.verdict` (`clean`/`watch`/`elevated`) + `summary.glyph`, `beneish.flag`, `beneish.missing`, cada `*.subscore_0_10`. Frontmatter aditivo sugerido (single-line, tolerado pelos parsers): `red_flags_verdict`, `red_flags_bad`, `red_flags_beneish` (número ou `n/a`), `red_flags_income_score` / `_balance_score` / `_cashflow_score`.
- Falha total → `{"error": ...}` + exit 0; o cartão degrada para nota "red-flag scan unavailable". Screens NÃO correm esta phase.

### Phase 2.4b — Category & return-metric lens (deep only, v4.3 wave 3)

Corre a seguir à Phase 2.4 e **antes da Phase 2.5** — o LLM que escreve o SWOT e a tese precisa de saber que está a olhar para um cíclico no topo do ciclo, e não descobre isso do composite. **Puros consumidores de JSON — zero rede, zero chamadas API** (`category_lens` lê o cache `_fin_history/` da Phase 2.2; `roic_lens` lê `intrinsic_value.capm` da Phase 2.3, logo **a ordem 2.3 → 2.4b é obrigatória**):

```bash
python "%SCRIPTS%\category_lens.py" "%OUT_DIR%\_tmp\{date}_{ticker}.json" --update
python "%SCRIPTS%\roic_lens.py"     "%OUT_DIR%\_tmp\{date}_{ticker}.json" --update
```

- **Overlay-only**: keys aditivas `category_lens` e `roic_lens` (schema continua 2.2). `lynch_category` fica **intocado** — alterá-lo mexia no sub-score de Growth-durability e portanto no composite, que v4.3 não pode mudar. A lente vive **ao lado** dele e diz por palavras onde os dois discordam.
- **`category_lens`** testa três coisas com bandas publicadas em `docs/CATEGORIES.md`: amplitude de lucros ao longo de um ciclo (pico → vale **sustentado** → recuperação), inflexão prejuízo→lucro **com lucro anterior à perda**, e preço contra book **tangível**. Sinais a ler: `primary`, `peak_earnings_warning` (o trap clássico — P/E baixo no pico), `flags.cyclical.secular_decline` (queda sem retorno: não é ciclo), `disagreement_note`.
- **`roic_lens`** aplica a doutrina de `docs/ROIC_vs_ROE.md`: qual das métricas se aplica (bancos/seguradoras → ROE/ROTE; ROIC `None` pelo guard de net-cash → ROE), ROIC vs WACC como teste de valor económico, e a flag de **ROE fabricado por alavancagem** (ROE>20% ∧ D/E>1.0 ∧ ROIC<12%). Diz também, em voz alta, que o multiplicador Buffett (ROIC>25%) **não dispara** quando o ROIC está suprimido — correcto, mas até agora invisível.
- **Custo medido**: <0,1 s por ticker os dois juntos (nenhum I/O de rede). Default-on no deep.
- **Degradação honesta**: sem `_fin_history` cached os testes de amplitude devolvem `detected: null` e a secção diz que o teste não correu — nunca "não há ciclo". Sem `intrinsic_value.capm` não há WACC (nunca uma taxa inventada).
- Falha total → `{"error": ...}` + exit 0; o cartão §2.20c degrada para nota. **Screens NÃO correm esta phase.**

### Phase 2.5 — Qualitative LLM pass (deep only)

Runs in Claude's orchestration context. Skipped entirely for screens.

1. **Refresh industry cache if stale** (from Phase 1.5 directive). Substitute `{INDUSTRY}` = `deep.sector`. Run `industry_macro.md` first → use output as `{MACRO_OUTPUT}` for `industry_customer.md` → use both as context for `industry_architecture.md`. Write the combined result to `_industry/<slug>.md` with the frontmatter above. Use WebFetch over 3-5 credible sources (trade association reports, consulting-firm industry overviews, SEC filings for the sector's top-3 players).

2. **Business model** — run `01_business_model.md` with `{ANNUAL_NARRATIVE}` from Phase 4's WebFetch. Output → §2.1.

3. **Management quality** — run `02_management_quality.md`. Parse the line `Management Quality Score: X.X/10` → that's `mgmt_score`. The rest of the output → §2.3.

4. **Growth decomposition & constraints** — run `03a_growth_decomposition.md`, then `03b_constraints.md` with 03a's output, then `03c_growth_assumption_check.md`. Combined output → §2.9.

5. **3-Layer Risk Audit** — run `04_risk_audit.md`. Output → §2.14.

6. **Consensus color** (Borja #18) — 1 short paragraph reconciling the deep-dive verdict with the `consensus` JSON block (recommendation key, target mean/range, EPS/revenue estimates). Skip entirely if `analyst_count < 3`. Output → §2.15.

7. **Bear case** — derive `{BULL_THESIS}` from §2.1 + §2.9 + TL;DR thesis line; run `05_bear_case.md`. Parse the FINAL LINE `If {X} happens, the thesis is broken.` → `bear_case_trigger`. Full output → §2.16. **Keep the parsed trigger at hand — Phase 2.55 receives it via `--bear-trigger`.**

7b. **Revenue segments (v3.1 — excepção documentada à ground-truth rule)** — se `_segments/{TICKER}.json` não existe ou tem >1 ano (`extracted_at`), extrair a tabela de segment revenue do annual report já fetched na Phase 4 (a nota de segmentos do 10-K traz 3 anos numa só tabela) e escrever:

   ```json
   {"fiscal_years": ["FY2023","FY2024","FY2025"], "currency": "USD",
    "segments": [{"name": "...", "values": [x, y, z]}],
    "source_url": "...", "extracted_at": "ISO"}
   ```

   para `%OUT_DIR%\_segments\{TICKER}.json`. **Esta é a ÚNICA situação em que números vêm do LLM** — porque nenhuma API free tem segment data. O chart e a §2.1 marcam sempre a origem ("company filings, LLM-extracted") + `source_url`. Sem filing disponível → não escrever JSON, chart skipped, `segments_available: false` + `⚠️ Segment data unavailable` na §2.1. Valores só da tabela oficial — nunca estimar nem interpolar.

7c. **SWOT (v4 Phase C)** — run `06_swot.md` with `{RED_FLAGS_JSON}` = the `red_flags` block from Phase 2.4 and `{BULL_THESIS}` (same as step 7). Output → the SWOT card (§2.18a). The **Threats/Risks quadrant leads and gets double depth**, and must reconcile every `bad`/`warn` scanner flag + the Beneish verdict. Overlay-only narrative — no number enters the composite.
   - **Se a Phase 2.4b detectou uma categoria**, incluir a linha de evidência de `category_lens` no contexto do prompt: um SWOT de um cíclico no topo do ciclo que não menciona o ciclo, ou de um turnaround que não menciona a sobrevivência do balanço, está errado independentemente do que escreve. O mesmo vale para `roic_lens.leverage_manufactured_roe` quando disparada — é Weakness, não curiosidade.

7d. **Statement commentary (v4 Phase C)** — for each of the three statement sub-sections (Income / Balance / Cash-Flow, §2.6a–c), write a 2–3 sentence anomaly note. **The 0-10 sub-score is the deterministic number from `red_flags.py` (Phase 2.4) — do NOT recompute it in the LLM**; the LLM only names the anomalies behind the flagged checks (ground-truth rule). Skip a statement's commentary if its sub-score is `null` (all checks n/a).

7d-bis. **Earnings-report commentary (v4.3 · OPT-IN, default OFF no path agendado)** — se `BD_EARNINGS_COMMENT=1` (o default é `1` em runs manuais/`--dry-run`, `0` no job das 13:30), correr `08_earnings_commentary.md` para **cada um dos 3 picks**:

   ```bash
   REM US: metadata + prosa do último 10-Q/10-K numa só chamada (já cacheada)
   python "%SCRIPTS%\edgar.py" --ticker {TICKER} --text --out-dir "%OUT_DIR%"
   ```

   Non-US não tem EDGAR → usar o annual/quarterly report já apanhado na Phase 4 (`find_reports.py` + `get_narrative.py`).

   **Output → §2.8 (quarterly) e §2.7 (annual). NÃO é uma secção nova.** As duas secções já existem e já são exactamente este trabalho — o que lhes faltava era a prosa do filing. Hoje imprimem `⚠️ Official report narrative unavailable` mesmo em nomes US grandes (MPWR 2026-08-14 diz-o com todas as letras, e dá a razão: *"SEC EDGAR is not fetched directly per the skill's 403 policy"* — uma política que a Phase 1.5 já removeu). Uma §2.6d nova ao lado destas seria uma terceira secção a dizer o mesmo enquanto as duas antigas continuavam vazias.

   **Custa um WebFetch + uma chamada LLM por ticker**, por isso fica opt-in até o timing harness provar que cabe nos 30 min (o job já corre a 22-24 min do tecto). Sem filing → a secção imprime `Latest filing not available.` e mais nada — nunca uma secção vazia.

   ⚠️ **Ground-truth rule**: a prosa do filing alimenta **só narrativa**. Todo o número citado vem do `{NUMBERS_JSON}` da Phase 2 (ou dos factos XBRL, que são structured data de um helper Python). Isto **não** cria uma terceira excepção — é a mesma fronteira que a Phase 4 já impõe.

7e. **Thesis duel (v4.2)** — run `07_thesis_duel.md` **last of the qualitative calls**, with `{BULL_THESIS}` (step 7), `{BEAR_CASE}` (the `05_bear_case.md` output), `{MOAT_JSON}` (`scores.moat` + `score_details.moat`), `{SECTOR}` and `{INDUSTRY_CACHE}` (the `_industry/<slug>.md` body). It **judges** the two cases already written — it must not re-derive them. Output → the **cartão §0** at the top of the report (moat band, bull-vs-bear table, LEAN, sector context). Overlay-only: the LEAN never touches the composite or the verdict, and is never rendered as a percentage.

8. **Finalise composite**:
   
   ```bash
   python "%SCRIPTS%\finalize_score.py" --json-path {analyze_json_path} --mgmt-score {mgmt_score}
   ```
   
   Use the returned JSON for Phase 5. Sets `management_score`, `management_flag`, recomputes `scores.composite` and `verdict`.
   
   **Then write `finalize_score.py` stdout to `%OUT_DIR%\_tmp\{date}_{ticker}.json` (overwrite Phase 2's intermediate).** Phase 3 (`render_charts.py`) reads from this file via `--analysis-json`. Without this step, the radar PNG will be skipped (validation gate) and the report loses its score breakdown.
   
   *(This is step 8 of Phase 2.5 — referenced from Phase 3's pre-condition below.)*

If any Phase 2.5 step fails, log a warning and continue with what you have — the report degrades gracefully (missing section + `(assumption — evidence gap)` note), it does not abort.

### Phase 2.55 — Exit & thesis plan (deep only, v4 Phase A)

Corre DEPOIS da Phase 2.5 (recebe o `bear_case_trigger` fresco do step 7 — nunca persiste um placeholder) e antes da Phase 2.6. Zero chamadas de rede:

```bash
python "%SCRIPTS%\exit_plan.py" --ticker ASML.AS --analysis-json "%OUT_DIR%\_tmp\{date}_{ticker}.json" --update --bear-trigger "{bear_case_trigger}" [--thesis-status {overall_status}]
```

- **Overlay-only**: `--update` acrescenta a key aditiva `exit_plan` ao analysis JSON (schema continua 2.2; composite intocado).
- **Inputs** (tudo já no JSON ou em ficheiros locais): `target_exit_pe` = `justified_exit_pe(pe_band)` (mediana capped no máx — regra Phase B); `fair_value_range` do bloco `intrinsic_value`; **profit-take ladder** ancorada no fair value (trim ⅓ @ fair-high, trim ⅓ @ fair-high × 1.5, hold ⅓) + **rung de custo 2×** apenas quando o ticker está **held**.
- **Cost basis & held detection**: `_portfolio_holdings.yaml` (`holdings[].avg_cost`, moeda nativa) — a fonte mantida pelo `/bd-stocks-portfolio`. **NÃO BankBD** (positions table vazia; decisão 2026-07-22). Alias `SHEL.L → SHELL.AS`. **Currency guard por labels**: rescale só GBp/GBX↔GBP (×0.01/×100); qualquer outro mismatch (e.g. cost em TWD, análise em USD) ⇒ cost rung + yield-on-cost "not computable (currency mismatch)" — nunca dividir entre moedas nem usar heurística de rácio de preços (corromperia o cost basis de um 100×).
- **`yield_on_cost`** = `dividend_rate ÷ avg_cost` (held equity only; `dividend_rate` None/0 ⇒ "no dividend"); não-held ⇒ `"n/a (not held)"` verbatim; crypto/non-equity ⇒ sem rung de custo nem yield.
- **`thesis_broken_trigger`**: `--bear-trigger` (fresco) → fallback última linha `bear_case_trigger` no `_log.csv` → null + warning. `--thesis-status` = `overall_status` do thesis_check (round>1).
- **`atr_context`**: lê `_technical/{TICKER}.json` se existir; **sempre `enabled: false`** — um compounder aguenta drawdowns normais de 30-40%; trailing stops pertencem ao growth skill. Sem ficheiro ⇒ `available: false`.
- Falha total → `{"error": ...}` + exit 0; a §2.12 degrada para nota "exit plan unavailable". Screens NÃO correm esta phase.

### Phase 2.56 — Return profile: α/β + CAPM + Lynch prior + portfolio fit (deep only, v4 Phase E)

Corre DEPOIS da Phase 2.55 (lê `intrinsic_value.capm.rf`, já no JSON) e antes da Phase 2.6. **Corre sob o Python312 ambiente** (`C:\Program Files\Python312\python.exe`, tem yfinance+pandas) — o venv `uv` do skill não os tem:

```bash
"C:\Program Files\Python312\python.exe" "%SCRIPTS%\alpha_beta.py" --analysis-json "%OUT_DIR%\_tmp\{date}_{ticker}.json" --update
```

- **Overlay-only**: `--update` acrescenta a key aditiva `alpha_beta` e injecta `beta_3y` + `alpha_ann_pct` no bloco `top_strip` (a metrics strip renderiza de uma só fonte). Composite/verdict **intocados**; schema continua 2.2.
- **α/β** vs benchmark regional (mapa `BENCH_BY_SUFFIX` de `technical_score.py`, match por sufixo `.XX`; US → `^GSPC`), 3 anos de retornos mensais: **β = cov/var**, **α = intercepto anualizado (Jensen)** sobre retornos em excesso. `n < 24` meses ⇒ "not computable" (degrada, não aborta).
- **Linha CAPM**: `realized_return_ann_pct` vs `capm_expected_return_ann_pct` (= rf + β·(retorno do benchmark − rf)); `rf` reutilizado de `intrinsic_value.capm.rf` (fallback constante 4% com `rf_source` etiquetado).
- **`price_cagr_ladder`** 1/3/5/10/15y a partir de 15 anos de closes mensais ajustados (proxy total-return). É o sinal de longo prazo real — o CAGR de **revenue** raramente chega a 10/15y com dados grátis (rungs nulos, etiquetados por `depth_years`).
- **`lynch_prior`**: `lynch_category` → banda de retorno/drawdown esperados (prior de report, etiquetado — **nunca entra no score**).
- **`portfolio_comparison`** (best-effort, cache diário `_portfolio_riskprofile.json`): série de retornos mensais ponderada por valor de mercado das holdings **equity** (crypto excluído), convertida para EUR close-a-close (histórico FX mensal `EUR{ccy}=X`), regredida vs o benchmark mundial **URTH**; o ticker é regredido vs o MESMO URTH (EUR) para a linha apples-to-apples. `verdict_beta`/`verdict_alpha` = `raises`/`dilutes`/`neutral` (ticker vs portfolio; para β = mais/menos risco, para α = accretive/dilutive ao retorno). < 3 holdings usáveis ou FX em falha ⇒ `available: false` (nunca bloqueia a α/β do ticker).
- Falha total → `{"error": ...}` + exit 0; a §2.20a degrada para nota. Screens NÃO correm esta phase.

### Phase 2.57 — Watch-list maintenance (deep only, v4 Phase E)

Corre DEPOIS da Phase 2.56 (precisa de `scores.composite`, `verdict`, `intrinsic_value.mos_class` + `fair_value_range.low`). Sem rede:

```bash
python "%SCRIPTS%\watchlist.py" --analysis-json "%OUT_DIR%\_tmp\{date}_{ticker}.json" --update
```

- **Regra única** (mantém na lista **sse e só se** `scores.composite ≥ 7` **E** `intrinsic_value.mos_class == "rich"` **E** não-held **E** há `fair_value_range.low`): um nome de qualidade travado **só** pelo preço. Qualquer outro caso ⇒ garante ausência — o que subsume as três remoções da spec: comprado (agora held, via `exit_plan.find_holding`/`load_holdings` + alias SHEL.L→SHELL.AS), tese quebrada / qualidade perdida (score < 7), e graduação para barato (`mos_class` deixa de ser "rich").
- Escreve `_watchlist.csv` (colunas `ticker,target,currency,added_date,fair_low,mos_class,score,fail_reason,thesis`; `target` = fair-low; `added_date` preservada no update). Overlay-only — **não escreve no analysis JSON**. Falha → `{"error": ...}` + exit 0.

### Phase 2.58 — Opinion panel: 3 personas (deep only, v4 Phase G)

Corre DEPOIS da Phase 2.57 e antes da Phase 2.6. **Sob Python312 ambiente** (SDKs `groq` + `google.generativeai`; o venv `uv` não os tem):

```bash
"C:\Program Files\Python312\python.exe" "%SCRIPTS%\second_opinion.py" --analysis-json "%OUT_DIR%\_tmp\{date}_{ticker}.json" --update
```

- **Segunda opinião independente** (spec §10b): um modelo não-autor (Groq `llama-3.3-70b-versatile` → Gemini `gemini-2.0-flash` fallback, via `llm_client.py`; chaves `api_key_groq`/`api_key_gemini` de `api_keys.txt` ou env `GROQ_API_KEY`/`GEMINI_API_KEY`), **3 personas prompted**: **value** (Graham/Klarman), **growth** (Fisher/Lynch), **contrarian** (bear-first). Cada uma devolve JSON estrito `{verdict, conviction_0_100, one_liner}` na escala **0–100, 50=neutral, 100=buy now**.
- **Independência (não eco)**: o painel vê a *evidência* (`compact_evidence` — top_strip, gates, intrinsic_value, red_flags, alpha_beta, exit_plan, consensus, management) mas **NUNCA o composite nem o verdict** — esses são excluídos do input. O composite é lido só localmente para o check de divergência.
- **Consenso** = mediana das convicções disponíveis → label (`buy_now`≥75/`accumulate`≥60/`hold`≥40/`cautious`≥25/`avoid`). **Divergência** sinalizada quando spread entre personas ≥25 pts **ou** |mediana − composite×10| ≥25 pts.
- **Overlay-only**: `--update` funde a key aditiva `opinion_panel`; composite/verdict/top_strip intocados. Cartões etiquetados *opinion* (isentos da regra ground-truth, como o management score). Uma persona morta (JSON inválido / erro de provider / sem chave) → cartão `available:false` sem bloquear as outras. Falha total → `{"error": ...}` + exit 0. Screens NÃO correm esta phase.

### Phase 2.59 — News & market sentiment (deep only, v4.1 Phase H)

Corre DEPOIS da Phase 2.58 e antes da Phase 2.6. **Sob Python312 ambiente** (precisa de yfinance + os SDKs groq/gemini via `llm_client`; a chamada NewsAPI é `requests` lazy + guarded):

```bash
"C:\Program Files\Python312\python.exe" "%SCRIPTS%\news_sentiment.py" --analysis-json "%OUT_DIR%\_tmp\{date}_{ticker}.json" --update
```

- **Sentimento de notícias** (spec §11c Phase H, idea #6): recolhe headlines recentes (**yfinance news = primário**; opcionalmente **1 única** query NewsAPI na trial key `api_key_newsapi` de `api_keys.txt`), depois **1 chamada LLM** classifica-as em dois diais — **stock** e **market** — cada um −1..+1 com 2-3 temas nomeados + citações das headlines.
- **NewsAPI é opcional e descartável**: sem chave → yfinance-only; 401/429/quota esgotada → **descarta o NewsAPI para o run** (warning) e continua. Política: quando os créditos acabarem, remover a chave de vez.
- **Overlay-only, NÃO entra no composite** — sentimento é *contexto, não gate*. Funde a key aditiva `news_sentiment` (composite/verdict/top_strip intocados). Complementa o `news_freshness` (freshness = quão stale; sentiment = que direcção).
- **Degradação graciosa**: sem headlines ou sem chave LLM → bloco `available:false` (o report mostra um *cartão n/a*, não crash). Falha total → `{"error": ...}` + exit 0. Screens NÃO correm esta phase.

### Phase 2.6 — Macro snapshot (once per run, v3.1)

Corre UMA vez por run (não por ticker), antes da Phase 5:

```bash
python "%SCRIPTS%\macro_snapshot.py" --check
```

- `stale: false` → o `_macro/{today}.md` existe; todos os reports do dia embedam dele. Nada mais a fazer.
- `stale: true` → duas metades:
  1. **Python**: `python "%SCRIPTS%\macro_snapshot.py" --fetch` → índices/VIX/yields/FX/commodities/BTC com Δ1d/Δ1w → `_macro/{today}.json`. **Depois** (v4 Phase D) `python "%SCRIPTS%\macro_breadth.py" --update` → funde as keys aditivas `breadth` (RSP/SPY) + `sectors` (11 SPDR ETFs + linha SPY) no mesmo `_macro/{today}.json` (**nunca toca em `metrics`** — overlay-only; cada símbolo mau vira `{"error": ...}`, uma falha nunca aborta a tabela).
  2. **LLM**: correr `prompts\macro_daily.md` com `{PYTHON_METRICS_JSON}` = o bloco `metrics`, `{BREADTH_JSON}` = o bloco `breadth`, `{SECTORS_JSON}` = o bloco `sectors` (todos ground-truth — formatar, nunca alterar), `{COUNTRY_TABLE_FRESH}` da directive, `{PREVIOUS_MACRO_MD}` = conteúdo do `fallback_md` (ou "none"). WebFetch para as gauges sourced (§2 valuation vs história: P/E / forward P/E / P/S / P/B / **EV/EBITDA** / Shiller CAPE com mediana — **uma linha por gauge SEMPRE, mesmo que "not available"**; nunca omitir a linha, senão não se distingue de um gauge que ninguém procurou; §6 Buffett Indicator + regime M2 via FRED `M2SL`; §7 forward-profit do índice — multpl.com, WSJ, gurufocus, longtermtrends, FRED, FactSet: **fonte + data em cada número; "not available" antes de estimar**). Tabela country (US/EU/China/Japão) só re-fetch quando `country_table_fresh: no` (TTL 7 dias); caso contrário copiar do anterior. Escrever `_macro/{today}.md` (8 secções) com frontmatter (`date`, `country_table_date`, `sources`, `schema_version`).
- **Degradação independente por gauge**: qualquer número não sourceable / qualquer entry `{"error": ...}` no JSON → só essa gauge mostra "not available"; a secção e o ficheiro nunca ficam em branco. Se ambas as metades Python falharem → reports embedam o `fallback_md` mais recente com `⚠️ macro snapshot stale ({N} days)`. A §4 nunca desaparece silenciosamente.
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
- `YYYY-MM-DD_TICKER_ni_pe.png` — v4 Phase A: net income anual (barras) vs P/E da própria história (linha, eixo direito) — join por ano fiscal; precisa de `annual.net_income` (fin_history) + `pe_band.series` (valuation_bands); skip limpo se faltar um dos lados
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

### Phase 1.5 — SEC EDGAR official filings (US listings, v4.3)

Corre **antes** da Phase 4 para nomes US (sem sufixo); nomes não-US saltam-na sozinha (o script devolve `available: false` com a razão, sem fazer um único pedido HTTP).

```bash
python "%SCRIPTS%\edgar.py" --ticker IBM --out-dir "%OUT_DIR%"            :: filings (deep + screens)
python "%SCRIPTS%\edgar.py" --ticker IBM --out-dir "%OUT_DIR%" --text     :: + narrativa do 10-Q/10-K (deep)
python "%SCRIPTS%\edgar.py" --ticker IBM --out-dir "%OUT_DIR%" --facts    :: + XBRL companyfacts (opt-in)
```

- **Sem API key.** Só exige um `User-Agent` que identifique quem chama — é isso, e apenas isso, que o antigo "EDGAR dá 403" era.
- **Custo medido (2026-08-15)**: `submissions` 166 KB / 0,28 s · documento primário do 10-Q **3,67 MB** / 0,5 s · `companyfacts` **5,6 MB** / 2,7 s. Run completo com `--text`: **~1,0 s**. Cache em `_edgar/` — TTL **1 dia** para filings (um 8-K novo não pode esperar um mês para aparecer) e **30 dias** para companyfacts.
- **`--facts` é opt-in** — 5,6 MB é demasiado para o caminho agendado sem motivo; usar quando se quiser cruzar os números do yfinance com os que a empresa **de facto arquivou**.
- **Fronteira ground-truth (não há excepção nova)**: os **XBRL facts são números estruturados vindos de um helper Python** → válidos como ground truth. O **texto** do filing é narrativa e **nunca** é lido para extrair números — exactamente a mesma regra da Phase 4.
- **Bloco no report**: "Latest official filings" com form, data, período e link directo. Os **items do 8-K são traduzidos para catalisadores** (`2.02` = earnings release, `5.02` = saída/entrada de administrador, `4.01` = mudança de auditor). **`4.02` = *PRIOR FINANCIALS NOT RELIABLE*** — é o pior sinal que o EDGAR carrega e tem de aparecer com destaque, nunca como uma linha discreta.
- **`--text` alimenta `{QUARTERLY_NARRATIVE}` / `{ANNUAL_NARRATIVE}` da Phase 2.5** para nomes US, substituindo o blurb de ~1500 chars do yfinance pelo MD&A verdadeiro (extracção limitada a 12 000 chars, secção localizada por heading).
- **Degradação honesta, toda testada**: não-US → `available: false` sem rede · ticker sem CIK → razão explícita · **foreign private issuer** (ADR que arquiva 20-F/40-F, p. ex. `NVO`) → `available: true` com `filings: []` e nota a dizer porquê, **não** um erro · rede morta → nunca levanta excepção, exit 0.

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

**v2.1 narrative fallback** — para nomes **não-US** (e como rede de segurança em qualquer nome), corre primeiro:

```bash
python "%SCRIPTS%\get_narrative.py" --ticker NVDA --max-news 5
```

**US primeiro — o EDGAR é a fonte, não o `get_narrative.py`.** Para qualquer nome sem sufixo, corre primeiro:

```bash
python "%SCRIPTS%\edgar.py" --ticker MPWR --text --out-dir "%OUT_DIR%"
```

O bloco `filing_text` que isso devolve (MD&A do último 10-Q, ou Item 7 do 10-K, ≤12000 chars, com `form`/`period`/`filed`/`url`) é o `{QUARTERLY_NARRATIVE}` / `{ANNUAL_NARRATIVE}`. **Só se isso falhar** (não-US, sem CIK, rede em baixo) é que se cai para o `get_narrative.py` abaixo. Um 10-Q real vale muito mais do que um blurb de 1500 chars, e desde a Phase 1.5 não há razão nenhuma para não o ler.

Returns a JSON dict with `business_summary` (yfinance `longBusinessSummary`, ~1500 chars MD&A-equivalent), `recent_news` (yfinance `Ticker.news`), `ir_url`, `stockanalysis_fundamentals_url`, and a `narrative_quality` grade (`good` / `partial` / `degraded`). Use the combined `business_summary + recent_news` content as the `{ANNUAL_NARRATIVE}` substitution **when EDGAR was unavailable**. If quality is `good` or `partial`, you can skip WebFetch entirely. If `degraded`, try WebFetch on `annual_url` / `ir_page_url` from `find_reports.py`. Degraded final state → §2.7 / §2.8 carry the `⚠️ Official report narrative unavailable` note and Phase 2.5 prompts label inferred claims accordingly. **Always copy the final grade into report frontmatter as `narrative_quality`** (after any WebFetch upgrade attempt — record what the report was actually written from), so degraded narratives are visible without opening the report.

> **v4.3 — a instrução "evita o SEC EDGAR, dá 403" foi REMOVIDA daqui, e deliberadamente.**
> O 403 nunca foi um bloqueio: é a política declarada da SEC de recusar pedidos sem um
> User-Agent que identifique quem chama. **Medido 2026-08-15**: sem User-Agent → 403; com
> User-Agent → 200, nos três endpoints. Para **nomes US o EDGAR é agora a fonte preferida**
> de narrativa (Phase 1.5 abaixo) e o `get_narrative.py` passa a ser o fallback, não o
> caminho principal — um 10-Q real vale muito mais do que um blurb de 1500 chars do yfinance.

### Phase 5 — Write the report

**Nome do ficheiro**: `{date}_{ticker}_{verdict}.md` (deep) ou `{date}_{ticker}_screen.md` (screens).
`verdict` ∈ {`great` ≥9.0, `invest` 7.5-8.9, `review` 6.0-7.4, `fair` 4.0-5.9, `reject` <4.0}.

**Fair price (deep + screen)** — every report whose verdict signals decent fundamentals (`great` / `invest` / `review`) records a fair-price anchor in frontmatter. **v4.3 §3.1 (roadmap N4): o valor é DETERMINÍSTICO e vem do bloco `intrinsic_value.fair_price`** — `fair_price` e `fair_price_basis` são copiados de lá tal e qual, nunca escolhidos pelo LLM. A ordem é: **blend** (≥3 modelos válidos) → **blend_median** (quando os modelos divergem ≥6.0×, a mediana é a estatística robusta, não a média) → **dcf** (só quando não há blend) → **consensus** (`analyst_count ≥ 3`) → **omitir**. Porquê: a regra antiga ("DCF quando `dcf_valid`, senão consensus") publicou **$118.35** para a MSFT (2026-07-30) contra $390.54 em bolsa e uma mediana de consenso de $550 — o DCF sobreviveu ao gate de ±70% por **0,30 pp** e um modelo isolado passou por cima dos outros quatro. Para verdicts `fair` / `reject` **omitir ambas as keys** — uma âncora de preço sobre uma tese fraca é ruído. Sem o bloco `intrinsic_value` (screens), manter a regra antiga como fallback. `build_dashboard.py` mostra estes valores nas colunas "Fair Px" / "Upside" de All Evaluations.

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
fair_price: 920                # COPIAR de intrinsic_value.fair_price.fair_price (determinístico, v4.3 N4); OMITIR quando verdict ∈ {fair, reject} ou sem âncora
fair_price_basis: blend        # blend | blend_median | dcf | consensus ; presente sse fair_price presente
fair_value_low: 830            # v4 Phase B: intrinsic_value.fair_value_range (min/blend/max dos modelos válidos); omitir os 3 se blend not computable
fair_value_mid: 940            # o blend 5-model — a âncora do MoS
fair_value_high: 1105
mos_class: fair                # deep_value | fair | rich ; omitir se not_computable
valuation_depth_years: 14      # pe_band.depth_years ; omitir se banda degradada (unit mismatch) ou ausente
red_flags_verdict: clean       # v4 Phase C: red_flags.summary.verdict (clean|watch|elevated); omit se scanner falhou
red_flags_bad: 0               # nº de checks bad (red_flags.summary.bad)
red_flags_beneish: -2.8        # red_flags.beneish.m_score ; "n/a" quando not computable (non-US)
red_flags_income_score: 9.3    # red_flags.income.subscore_0_10 (0-10, overlay — NÃO entra no composite); omit se null
red_flags_balance_score: 8.6   # red_flags.balance.subscore_0_10
red_flags_cashflow_score: 10.0 # red_flags.cashflow.subscore_0_10
beta_3y: 0.89                  # v4 Phase E: alpha_beta.beta (3y monthly vs regional benchmark); omit se not computable (n<24m) ou screen
alpha_ann_pct: 4.2             # alpha_beta.alpha_ann_pct (Jensen α anualizado, overlay — NÃO entra no composite); omit se not computable ou screen
opinion_median: 80             # v4 Phase G: opinion_panel.consensus_conviction (mediana 0-100 das 3 personas, overlay — NÃO entra no composite); omit se painel indisponível ou screen
opinion_consensus: buy_now     # opinion_panel.consensus_verdict (buy_now|accumulate|hold|cautious|avoid)
opinion_divergence: true       # opinion_panel.divergence.flag (personas discordam ou divergem do composite)
news_sentiment_stock: 0.40     # v4.1 Phase H: news_sentiment.stock.score (−1..+1, overlay — NÃO entra no composite); omit se indisponível ou screen
news_sentiment_market: 0.10    # news_sentiment.market.score (−1..+1)
news_sentiment_label: bullish  # news_sentiment.stock.label (bullish|neutral|bearish); alimenta o chip do email digest
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
listing_home: 2330.TW             # linha primária da empresa; omit se cotação única
listing_alternatives: [TSM]       # outras cotações da MESMA empresa; omit se cotação única
listing_reason: "home listing preferred — coverage 100% vs TSM 100%"  # porquê esta linha
prior_evaluations: 7              # nº de avaliações anteriores da empresa (§5); omit se 0
company_name: "Taiwan Semiconductor Manufacturing Company Limited"  # alimenta _company_names.json
thesis_lean: bull                 # bull | bear | balanced — narrativa; NUNCA entra no composite
moat_label: wide                  # wide (≥8) | narrow (5–7.9) | none (<5) — derivado de scores.moat
insider_pct: 0.041                # heldPercentInsiders — INSIDERS, não gestão executiva
institutional_pct: 0.168          # heldPercentInstitutions
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
> **Exit**: {1 linha do bloco `exit_plan`, e.g. "trim ⅓ @ {fair_high} / ⅓ @ {fair_high×1.5}; exit P/E {target_exit_pe}; broken if {trigger curto}" — held: acrescentar "YoC {yield_on_cost}%"; omitir a linha se o exit_plan falhou}
> **Red flags**: {red_flags.summary.glyph} {verdict} — {bad} bad · {warn} watch; Beneish {m_score|n/a} — omitir a linha se o scanner falhou (§2.12a)
> **Opinion panel**: 🤖 {opinion_median}/100 ({opinion_consensus}), {n_available}/3 personas{se divergence: " · ⚠️ divergência"} — omitir a linha se o painel falhou (§2.20b)
> **News**: 📰 {stock_emoji} stock {news_sentiment_stock:+.2f} ({news_sentiment_label}) · market {news_sentiment_market:+.2f} — {tema #1 do dial stock} — omitir a linha se o `news_sentiment` estiver indisponível (overlay, não afecta o composite)
> **Action**: {explicit next step}
> **Position size**: {sizing band da tabela abaixo, e.g. "Starter 1.5–3% of equity book; build to 4% on execution"} — always end with "(guideline, not advice)"
> **Entry plan**: {se GO + entry_zone: "accumulate inside {entry_zone}; invalidation below {stop_loss}"; se NO-GO: "thesis ok, timing not — wait for {condição concreta}"; se sem tech read: "no timing read — size entry in thirds"}
> **Earnings watch**: próximos earnings em {earnings_date_next}

**Position-size guideline (deterministic — apply, don't improvise):** start from the verdict band — `great` ≥9.0 → core 4–6%; `invest` 7.5–8.9 → starter 1.5–3%, build to 4%; `review` 6.0–7.4 → watchlist only (0%, define a trigger); `fair`/`reject` → no position. Then shift **one band down** (core→starter, starter→watchlist) for each of: `management_flag: true`, `tech_risk_level: High`, `go_no_go: NO-GO`, `data_quality: suspect` — applied at most once in total, not cumulatively below watchlist. Conviction line: High = no downshift triggered and ≥6 gates; Low = any downshift triggered; Medium otherwise.

### 🏰 MOAT — {moat_score}/10 · {WIDE se ≥8 · NARROW se 5–7.9 · NONE se <5}

> ## **{mecanismo do moat numa linha — switching costs / escala / rede / licença / marca / curva de custo}**

{2–3 frases do bloco MOAT do prompt `07_thesis_duel.md`: o que sustenta o moat, o que o erode e em que horizonte. Ancorar em ROIC {roic_ttm}% e no score computado — nunca inventar um score diferente. Se os números não suportam um mecanismo identificável, dizê-lo: ROIC alto sem mecanismo é um windfall, não um moat.}

### ⚔️ Bull vs Bear

| | 🐂 **BULL** | 🐻 **BEAR** |
|---|---|---|
| **Claim** | {1 frase} | {1 frase} |
| **Se acontecer (3–5 anos)** | {1 frase} | {1 frase} |
| **Depende de / Gatilho** | {NEEDS} | {TRIGGER} |

> [!success] 💚 **Thesis**: **{bull case em 1-2 frases, bold — versão expandida da linha do TL;DR}**

> [!danger] 🔴 **Risks**: **{risco #1 + bear trigger, bold — versão expandida da linha do TL;DR}**

> [!abstract] ⚖️ **MAIS PROVÁVEL: {🐂 BULL · 🐻 BEAR · ⚖️ EQUILIBRADO}**
> {1 frase, ≤40 palavras, a citar o número que decidiu — output LEAN do prompt 07.}
> *Leitura narrativa. **Não entra no composite, não altera o veredicto, e nunca é expressa em percentagem** — não há dados de calibração que sustentem um "70% bull", e um número desses parece evidência sem a ser. `EQUILIBRADO` é uma resposta legítima e esperada com frequência.*

> [!info] 🧾 **Skin in the game · Sector**
> **Insiders**: {insider_pct}% · **Instituições**: {institutional_pct}% {se recent_insider_transactions: "· últimas transacções: {posição} {compra/venda} {shares}"}
> ⚠️ `heldPercentInsiders` conta **insiders** — fundadores, administradores, trusts familiares e participações cruzadas — **não é a participação da gestão executiva**. Rotular como "management ownership" seria enganador; para o sinal de gestão usar as transacções por `position` (CEO/CFO) e §2.3/§2.4.
> **Sector — {sector}**: {2–3 frases do bloco SECTOR CONTEXT do prompt 07 — força estrutural, direcção, e o que a inverteria. Nunca um y/n.}

*(Este é o **cartão §0**, imediatamente abaixo do TL;DR e acima do chart de preço — moat, os dois lados da tese e o lean ficam todos above the fold. CRÍTICO: os callouts mantêm os labels literais `**Thesis**:` e `**Risks**:` — `build_dashboard.extract_field()` faz regex-match desses labels e apanha a PRIMEIRA ocorrência, que é a linha do TL;DR; as linhas do TL;DR ficam intactas.)*

### 📊 Metrics strip

**P/E {pe_ttm}x · Forward P/E {forward_pe}x · β 3y {beta_3y} · α 3y ann. {alpha_ann_pct}%**

| Rev CAGR 5y | FCF margin | FCF yield | ROE | ROIC | Gross margin | Net debt/EBITDA | Net payout | Price 1y | Price {5y ou "since {date}"} |
|---|---|---|---|---|---|---|---|---|---|
| {x}% | {x}% | {x}% | {x}% | {x}% | {x}% | {x}x | {x}% | {x}% | {x}% |

(Fonte: bloco `top_strip` do analysis JSON — nunca recalcular à mão. Price returns são dividend-adjusted; quando `price_return_5y_span != "5y"`, o header da última coluna mostra "since {date}". `β 3y`/`α 3y` (v4 Phase E, bloco `alpha_beta` → injectado no `top_strip`) só existem em deep-dives — omitir de screens; overlay, não afectam o composite.)

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

### Onde comprar (só quando a empresa tem >1 cotação)

Bloco determinístico — **gerado por script, nunca escrito pelo LLM**:

```bash
python "%SCRIPTS%\listings.py" {TICKER} --table
```

Devolve `''` para nomes com uma só cotação (não renderizes nada nesse caso). Para nomes dual-listed devolve a tabela `Ticker | Mercado | Moeda | Tipo | Rácio | Broker mais barato (€1500)` com a linha home a **negrito**, mais um callout a lembrar que o rácio ADR↔ordinária tem de ser aplicado antes de comparar preços cotados. Se já correste `broker_compare.py` neste run, passa os custos para preencher a última coluna; mercados fora de `brokers.yaml` ficam `—` (nunca um número inventado).

Frontmatter que acompanha: `listing_home`, `listing_alternatives`, `listing_reason` (vindos do JSON do pick).

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

![Peers 5y total return](IMG/{date}_{ticker}_peers5y.png)
*5 anos de retorno TOTAL (dividendos reinvestidos) convertido a EUR e indexado a 100, contra os MESMOS peers do bar chart acima. A caption do PNG diz de que tier veio o peer set — `by_ticker` é curado, `by_industry`/`by_sector` são proxies e vêm marcados a amarelo. Omitir imagem + caption se o chart foi skipped.*

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

#### 2.6a Income-statement review — {red_flags.income.subscore_0_10}/10  *(v4 Phase C · does not affect the composite)*
({Deterministic sub-score from `red_flags.py`. Render the income checks as a mini traffic-light list: for each `red_flags.income.checks[]` a ✓/⚠/✗ glyph from `status` (pass/warn/bad; `na` → "n/a") + `label` + `value` vs `threshold`. Then the LLM 2–3-sentence anomaly note from Phase 2.5 step 7d — names what drives any warn/bad flag. Skip the note if sub-score is null.})

#### 2.6b Balance-sheet review — {red_flags.balance.subscore_0_10}/10  *(v4 Phase C · does not affect the composite)*
({Same pattern over `red_flags.balance.checks[]` — leverage, liquidity, working capital, inventory turnover, AR days, book-value trend. + anomaly note.})

#### 2.6c Cash-flow review — {red_flags.cashflow.subscore_0_10}/10  *(v4 Phase C · does not affect the composite)*
({Same pattern over `red_flags.cashflow.checks[]` — OCF, FCF, earnings quality (CFO vs NI), capex intensity, dividends vs OCF, cash interest coverage. + anomaly note.})

### 2.7 Wrap-up Annual Report {year}
**Link**: [{annual_url}]({annual_url}) — publicado {annual_date}
({Narrativa do management discussion — tese de crescimento, strategic priorities, capital allocation. NÃO repete números, esses estão em 2.6})

### 2.8 Wrap-up Quarterly Report {quarter}
**Link**: [{quarterly_url}]({quarterly_url}) — publicado {quarterly_date}

({Output de `08_earnings_commentary.md` (Phase 2.5 step 7d-bis) quando `BD_EARNINGS_COMMENT=1`. Formato: linha `**{FORM}, {PERIOD}, filed {DATE}**`, depois 3-5 bullets de uma frase, depois `**Tone vs prior print:** …`. Para nomes US a prosa vem do `edgar.py --text` (MD&A do 10-Q real); non-US do IR fetch da Phase 4.})

({Sem filing e sem commentary: manter o comportamento actual — "Que mudou no último trimestre — guidance, segment trends, one-offs" a partir do que houver, ou `Latest filing not available.`})

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

### 2.12 Plano de saída (Exit plan) — v4 Phase A

(Do bloco `exit_plan` — números do Python, narrativa só a ligar. **Overlay-only: nunca altera o veredicto.**)

**Sell discipline** ({held ? "posição actual: {quantity} sh @ {avg_cost} {holding.currency}" : "não held — plano hipotético"}):

| Elemento | Valor | Base |
|---|---|---|
| Target exit P/E | **{target_exit_pe.value}×** | mediana da banda própria ({depth_years}y), capped no máx |
| Fair value range | {low} / {mid} / **{high}** {currency} | {fair_value_range.basis} |
| Trim ⅓ | **{ladder[0].trigger_price} {currency}** | fair-value high |
| Trim ⅓ | **{ladder[1].trigger_price} {currency}** | fair-value high × 1.5 |
| Hold ⅓ | — | run winners; re-avaliar em thesis break |
| {held: Cost 2×} | {trigger_price} {currency} | 2× cost (held) |
| {held: Yield on cost} | {yield_on_cost.pct}% | dividend_rate / avg_cost — o argumento para aguentar drawdowns |

**Tese quebrada se**: {thesis_broken_trigger.text} *(ver §2.16; pillars: {pillars_status})*

{atr_context.available: 1 linha — "Contexto ATR(14): {atr} ({atr_pct}%), stop sugerido {suggested_stop_loss} — **contexto apenas, OFF by default**: a disciplina de saída é fundamental (P/E + tese), não um trailing stop."}

![Net income vs P/E](IMG/{date}_{ticker}_ni_pe.png)
*Net income anual vs P/E da própria história — earnings a subir com multiple a descer = re-rating pendente; o inverso = multiple expansion sem earnings. Omitir imagem + caption se o chart foi skipped.*

![Long-horizon evolution](IMG/{date}_{ticker}_evolution.png)
*Painel de longo prazo (ANUAL): preço · P/E + price/EBITDA · EBITDA + EPS, no mesmo eixo de anos. Só é desenhado com ≥8 anos de história anual — abaixo disso não existe (ver `EVOLUTION_MIN_YEARS`), o que na prática significa que só nomes US (Alpha Vantage) o têm; os não-US caem para ~4 anos de yfinance e o chart não é gerado. A linha price/EBITDA é um múltiplo de EQUITY, **não** EV/EBITDA — não há histórico de net debt persistido. Omitir imagem + caption se o chart foi skipped.*

{yield_on_cost.reason quando não computável: mostrar a razão verbatim (e.g. "n/a (not held)") em vez das linhas held.}
{Se o bloco `exit_plan` falhou/ausente: "⚠️ exit plan unavailable" e nada mais.}

*A carta do adviser (§2.19, "When we'd walk away") é a versão narrativa desta disciplina — os números vivem aqui.*

### 2.12a Red-flag scanner {red_flags.summary.glyph} {red_flags.summary.verdict}  *(v4 Phase C · overlay — surfaces a veto, never demotes)*
(Do bloco `red_flags` (Phase 2.4) — números do Python. **Bearish veto independente do composite; o utilizador decide.**)

**Traffic-light** ({red_flags.summary.bad} bad · {red_flags.summary.warn} watch · {red_flags.summary.pass} pass): render each `red_flags.{income,balance,cashflow}.checks[]` as one line — ✓ (pass) / ⚠ (warn) / ✗ (bad) / — (n/a) glyph + `label` + `value` vs `threshold`. Colour never stands alone (always paired with a glyph).

| Integrity | Valor | Threshold | Estado |
|---|---|---|---|
| **Beneish M-score** | {red_flags.beneish.m_score \| "n/a"} | M > −2.22 | {beneish.status} {beneish.missing → "missing: …"} |
| Altman Z-Score | {red_flags.summary.altman_zscore} | <1.8 distress | see §2.6 |
| Earnings quality (CFO vs NI) | {cashflow earnings_quality.value}× | CFO ≥ NI | {status} |

**Quality pills** (positivos, nunca vetos): {net payout yield ✓/○ {value}% (rule >4%)} · {ROCE ✓/○ {value}% (rule ≥20%)}.

{Beneish "not computable" (non-US sem line items) → mostrar "Beneish M: n/a — {missing}" e continuar; o cartão nunca desaparece.}
{Se o bloco `red_flags` falhou/ausente: "⚠️ red-flag scan unavailable" e nada mais.}

### 2.13 Peer comparison
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

### 2.14 3-Layer Risk Audit
({Ranked risk tables + narrative a partir de prompts\04_risk_audit.md. Três sub-secções: Operational / Financial / Structural. AI Disruption callout no fim.})

### 2.15 Consensus & sell-side ("O que a rua pensa") (Borja #18)
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

### 2.16 Bear case — "If X happens, thesis is broken."
({400-600 palavras a partir de prompts\05_bear_case.md. A última linha é o trigger que vai para frontmatter.})

### 2.17 Market timing detalhado
({VIX histórico, put/call trend, FGI breakdown — discussão curta})

### 2.18 Operator vs Investor view
({2 short paragraphs — Operator lens (execução, bottlenecks) e Investor lens (profit pools, moats). Cross-cutting summary destilado das secções anteriores.})

### 2.18a SWOT  *(v4 Phase C · overlay — qualitative, no score into the composite)*
(Output de `06_swot.md` (Phase 2.5 step 7c). Render como um cartão 2×2 com o quadrante **Threats/Risks primeiro e com dupla profundidade**. Cada facto cita um número da JSON entre parênteses ou é marcado `(inferred)`.)

**Cada item leva a sua tag de materialidade e vai numa linha própria separada por `<br>`:** `**MATERIAL** — …` quando mudaria o *veredicto* ou o *tamanho da posição*, `*minor* — …` quando não mudaria nenhum dos dois. Reports antigos sem tags continuam a renderizar como parágrafo — `build_swot` degrada, não parte.

| ⚠️ **Threats / Risks** *(leads · deepest)* | ✅ **Strengths** |
|---|---|
| ({external/downside forces; reconcilia cada flag `bad`/`warn` do §2.12a + o veredicto Beneish; cross-link §2.14 risco + §2.16 bear}) | ({vantagens competitivas evidenciadas pelos números — margens, ROIC/ROCE, net-payout, balanço}) |
| 🔸 **Weaknesses** | 🚀 **Opportunities** |
| ({soft spots internos — os `warn`/`bad` company-internal: leverage, tendência de margem, cash conversion}) | ({optionality realista de upside — TAM, pricing, capital allocation}) |

{Se o SWOT não foi gerado: omitir a secção (não é blocker).}

### 2.19 Veredicto final — Adviser's letter
Escrever como uma carta curta de um senior adviser ao cliente (5 parágrafos de 1-3 frases, sem headers):

1. **The call** — {verdict_label} + conviction, em linguagem corrente ("This is a business we'd own; the price is the problem").
2. **Why now** — o que nos números de hoje sustenta (ou trava) a decisão. Se management_flag=true, referenciar explicitamente.
3. **How to act** — position size band + entry plan (repetir os do TL;DR, coerentes).
4. **What we're watching** — 2-3 monitorização concreta com números (e.g. "net margin holding >25% at Q3 print", ligada aos pillars e ao bear trigger).
5. **When we'd walk away** — o bear trigger reformulado como instrução de saída.

### 2.20 Broker recommendation (€1500)

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

### 2.20a Return profile — α/β · CAPM · Lynch prior · portfolio fit  *(v4 Phase E · overlay — não afecta o composite)*

Renderiza do bloco `alpha_beta` (Phase 2.56). Números ground-truth (yfinance); o LLM só escreve as 1-2 frases de leitura. **Sufixo de secção (`a`) → zero renumeração**; os parsers dependem de labels/frontmatter, não do número. Se `alpha_beta` ausente ou `"error"` ⇒ nota "return profile unavailable" e saltar a secção.

```md
**α/β (3 anos, mensal, vs {benchmark})** — β {beta} · α anualizado {alpha_ann_pct}% · R² {r2} · n={n_months}m
{quando not computable (n<24m): "β/α não calculáveis — histórico insuficiente ({n_months}m)"}

| Métrica | Valor |
|---|---|
| Retorno realizado (anualizado) | {realized_return_ann_pct}% |
| CAPM esperado (rf + β·(mkt−rf)) | {capm_expected_return_ann_pct}% |
| rf ({rf_source}) | {rf_pct}% |

*Leitura: α positivo = bateu o CAPM; a diferença realizado − esperado ≈ α.*

**CAGR de preço (total-return proxy, closes mensais ajustados · profundidade {depth_years}a)**

| 1y | 3y | 5y | 10y | 15y |
|---|---|---|---|---|
| {x}% | {x}% | {x}% | {x ou "n/a"}% | {x ou "n/a"}% |

*(rungs `n/a` quando o histórico não chega — etiquetado por `depth_years`. O CAGR de revenue 10/15y raramente existe em dados grátis; este é o sinal de longo prazo.)*

**Lynch prior ({lynch_prior.category})** — retorno esperado {lynch_prior.expected_return_band} · drawdown típico {lynch_prior.drawdown_band}. {lynch_prior.note}
*(Prior de categoria — orientação, nunca entra no score.)*

**Portfolio fit (vs {portfolio_comparison.benchmark}, EUR)** — β do ticker {ticker_vs_world.beta} vs portfolio {portfolio.beta} ({verdict_beta}: {"aumenta"|"reduz"} o β da carteira) · α do ticker {ticker_vs_world.alpha_ann_pct}% vs portfolio {portfolio.alpha_ann_pct}% ({verdict_alpha}: {"accretive"|"dilutive"} ao α da carteira). Base: {portfolio.holdings_used} holdings equity ponderadas por valor de mercado (crypto excluído).
{quando portfolio_comparison.available == false: "Portfolio fit não disponível — {reason}."}
```

### 2.20b 🤖 Opinion panel — value · growth · contrarian  *(v4 Phase G · overlay — segunda opinião, não afecta o composite)*

Renderiza do bloco `opinion_panel` (Phase 2.58). Modelo **independente** (Groq→Gemini) — cartões etiquetados *opinion* (isentos da regra ground-truth). Se `opinion_panel` ausente/`"error"` ⇒ nota "opinion panel unavailable" e saltar. Cartões `available:false` mostram "não disponível" individualmente.

```md
| Persona | Veredicto | Convicção (0–100, 50=neutral) | One-liner |
|---|---|---|---|
| 💰 Value | {verdict} | {conviction_0_100} {barra ▓ com marca no 50} | {one_liner} |
| 🚀 Growth | {verdict} | {conviction_0_100} | {one_liner} |
| 🐻 Contrarian | {verdict} | {conviction_0_100} | {one_liner} |

**Consenso: {consensus_conviction}/100 ({consensus_verdict})** · {n_available}/3 personas · modelo {model_chain}
{se divergence.flag: "⚠️ Divergência — {divergence.reason} (a discordância é o sinal: rever a tese)."}
```

*(A convicção do painel é uma opinião de modelo independente, não uma medida ground-truth; use-a como contraste ao composite, nunca como substituto.)*

### 2.20c Category & return-metric lens  *(v4.3 wave 3 · overlay — lente sobre os números, não altera nenhum)*

Renderiza dos blocos `category_lens` e `roic_lens` (Phase 2.4b). **Ambos determinísticos** — o LLM escreve no máximo a frase de leitura; nenhum número aqui vem de LLM. Bandas publicadas em `docs/CATEGORIES.md` e `docs/ROIC_vs_ROE.md`. Se ambos os blocos faltarem ⇒ saltar a secção inteira.

```md
**Categoria: {category_lens.primary ou "nenhuma das três — aplica-se a régua Quality Compounder"}**
{por cada flag detectada: "- **{Cyclical|Turnaround|Asset play}** ({confidence}): {evidence}"}
{se peak_earnings_warning: "> [!warning] Late-cycle — o P/E trailing está medido sobre lucros de topo de ciclo. Avaliar por EPS mid-cycle e por EV/EBITDA contra a própria banda do ciclo, não contra a mediana do sector."}
{se flags.cyclical.secular_decline: "> [!warning] Declínio secular — os lucros caíram do pico e não recuperaram. Não é um ciclo: não existe \"mid-cycle\" para onde reverter."}
{se disagreement_note: "*Divergência com `lynch_category` = {lynch_category}: {disagreement_note}*"}
{se asset_play detectada: "*Catalisador de realização: não derivável de dados financeiros — ver narrativa. Sem catalisador, um desconto sobre o book é uma armadilha, não uma tese.*"}

**Métrica de retorno aplicável: {roic_lens.preferred_metric}** — {preferred_reason}

| ROIC | ROIC ex-goodwill | ROE | ROTE | ROCE | WACC | Spread |
|---|---|---|---|---|---|---|
| {roic}% | {roic_ex_goodwill}% | {roe}% | {rote}% | {roce}% | {wacc.value}% | {spread}% → **{verdict}** |

{se leverage_manufactured_roe.flagged: "> [!danger] ROE fabricado por alavancagem — {note}"}
{se buffett_multiplier.note: "*{note}*"}
{por cada nota de intensidade de capital: "*{note}*"}
```

*(Overlay puro: nenhum destes valores entra no composite, nas gates ou no veredicto. A lente explica **porque** o score lê como lê — não o corrige.)*

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

({Embed curto (~18 linhas) do `_macro/{date}.md` — só um resumo, o detalhe completo (8 secções) vive no ficheiro linkado abaixo: tabela Markets today & this week + linha de valuation vs história (P/E, fwd P/E, P/S, CAPE com fontes) + **uma linha de breadth** (RSP/SPY: percentil + seta, ex.: "Breadth: RSP/SPY no percentil 2 ↓ — liderança mega-cap estreita") + **uma linha de sectores** (líderes/laggards + se o volume confirma, ex.: "Sectores: XLV/XLI/XLF ↑; volume não confirma") + **uma linha de regime** (Buffett Indicator + M2, ex.: "Buffett Ind. ~2.1× (rich); M2 a expandir") + 2-3 frases do read-through. Não repetir tabelas inteiras (country/sectores) — só o embed curto. Cada item que esteja "not available" no cache omite-se da linha, nunca inventar.})

📂 Snapshot completo: [[_macro/{date}|Full macro snapshot]]

{Se o snapshot de hoje falhou: embed do mais recente disponível + `⚠️ macro snapshot stale ({N} days)` — nunca omitir a secção silenciosamente.}

## 5. Histórico de avaliações

(Bloco **determinístico, gerado por script** — o LLM não escreve nem resume nada aqui. Omitido por completo quando é a primeira avaliação da empresa.)

```bash
python "%SCRIPTS%\report_history.py" --ticker {TICKER} --date {date} \
  --score {composite} --verdict {verdict} --price {price_at_eval} --currency {currency} --block
```

Cola a saída tal e qual. Contém: um callout a dizer que este report substitui os anteriores, uma frase de tendência calculada (Δ score vs a avaliação anterior, amplitude histórica, veredicto estável ou a cadeia de mudanças, variação de preço) e uma tabela de todas as avaliações anteriores — **da empresa, não do ticker**, portanto as 7 avaliações de TSMC espalhadas por `TSM` e `2330.TW` aparecem como um só histórico.

O "resumo" de cada linha é extraído **verbatim** do report antigo (a linha `> **Thesis**:` do TL;DR, ou o one-liner do callout `[!info] Screen rápido`) — 343 de 355 reports em 2026-08-05. Sem âncora, cai para `notes` do `_log.csv` e depois para `—`. Custo em tokens: zero.

⚠️ Variações de preço só são calculadas **entre avaliações na mesma moeda** — a linha TWD e o ADR em USD cotam a mesma empresa com 30× de diferença, e subtrair uma da outra fabricaria um "movimento" de 3000%.

---
*Analysis written by {model name} · bsdias©2026 · host: {hostname}*
```

#### Screen body (versão curta — sem charts, sem narrativa pesada, sem §2.1/2.3/2.9/2.12/2.14/2.15/2.16/2.18)

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
*Analysis written by {model name} · bsdias©2026 · host: {hostname}*
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

### Phase 5.6 — Chart gate (OBRIGATÓRIO, antes do render HTML)

```bash
python "%SCRIPTS%\check_report_charts.py" --report "%OUT_DIR%\{date}_{ticker}_{verdict}.md"
```

**Se sair non-zero, cola as linhas que ele imprime no sítio certo do report e volta a correr até passar.** Não avances para 5.7 com o gate vermelho.

Porquê um gate e não uma instrução: as linhas `![...](IMG/...)` já estão no template desde sempre e mesmo assim **32 de 169 deep reports** tinham charts renderizados que o `.md` nunca referenciou — o `dcf` 25 vezes, e em 2026-08-05 os três reports do dia (KLAC, WKL.AS, ZTS) omitiram o **conjunto completo** (5 a 7 charts cada). Uma instrução que falha 19% das vezes não é uma instrução, é uma sugestão; o gate é determinístico (filesystem + regex, zero API).

⚠️ **Âmbito real do estrago — o HTML nunca foi afectado.** `render_report.py` monta o caminho `IMG/{date}_{ticker}_{kind}.png` **directamente** (linha ~709), não lê os links do markdown. Verificado: os HTML de KLAC e ZTS já tinham os 7 charts embebidos em base64, e re-renderizá-los não mudou o tamanho. O que estava partido era o **`.md` que se lê no Obsidian** — que é a fonte contratual e o que se abre no dia-a-dia. Portanto: bug real, mas os charts nunca se perderam.

Apanha as duas direcções: **órfãos** (PNG em disco que o report não referencia) e **links partidos** (o report referencia um PNG que não existe — 5 reports linkavam um `_segments.png` que nunca foi produzido, e o VST linkava os 4 charts sem nenhum ter sido renderizado). Screens são ignorados por construção (só levam a metrics strip). `--audit` varre tudo o que está em disco.

**Backfill** — `--fix` insere os órfãos na âncora do template (radar sob *Score breakdown*, peers sob *Peer ranking snapshot*, dcf em §2.11, ni_pe em §2.12, o trio da metrics strip acima de `## 1.`) e remove os links mortos, deixando a prosa por baixo intacta (nos casos `segments` é precisamente o parágrafo que explica a ausência). **Não re-renderiza** um chart em falta: o analysis JSON de um report antigo já saiu do `_tmp`, e correr o pipeline hoje traria os preços de hoje para um report datado de há meses — um chart em falta é uma lacuna, um chart do período errado é uma mentira. `--dry-run` mostra o plano. Idempotente. Backlog histórico corrigido em 2026-08-06 (+48 imagens, −9 links mortos, 32 reports; gate a 170/170).

### Phase 5.7 — Render HTML report (v4 Phase F, primary artifact)

Corre DEPOIS de o `.md` estar escrito (Phase 5), dos charts existirem (Phase 3) e do **gate 5.6 passar**. **Sob Python312 ambiente** (na verdade puro stdlib — corre em qualquer runtime):

```bash
python "%SCRIPTS%\render_report.py" --md "%OUT_DIR%\{date}_{ticker}_{verdict}.md" --analysis-json "%OUT_DIR%\_tmp\{date}_{ticker}.json" --out-dir "%OUT_DIR%"
# after ALL of the day's reports render, refresh the daily hub (session 2):
python "%SCRIPTS%\render_report.py" --index {date} --out-dir "%OUT_DIR%"
```

- **HTML = artefacto primário** (spec §11): `render_report.py` lê o `.md` (frontmatter + narrativa) + o analysis JSON e escreve `{report}.html` ao lado do `.md`. O `.md` mantém-se a **fonte** (contrato congelado — o renderer só LÊ; `build_dashboard.slim_report` continua a popular, com teste de regressão).
- **Estático, JS-free, self-contained**: templating Python-side contra `report_template.html` (NÃO o `__DATA__` client-JS do dashboard). Header answer-first com **action verb determinístico** (`verdict × mos_class × go_no_go → ACCUMULATE/BUY-DIP/HOLD/WATCH/AVOID`), snowflake 5-eixos (Quality/Value/Growth/Health/Mgmt, derivado dos 7 `scores`) em SVG inline, gauge fair-value + range bar bear/base/bull, cartões A/B/C/E/G, tabela de peers com grades A–D, e um `<details>` "Full written analysis" (md→HTML minimal). PNGs do `IMG/` embebidos base64 com budget ≤1.5 MB (dropa os de menor prioridade + loga). Moeda vem do JSON (nunca `€` hardcoded); cada visual tem null-render.
- **Email intocado** (BLOCKER B1): o HTML estilizado NUNCA é inlined no corpo do email; o digest continua md→inline-table; os links `obsidian://` continuam a apontar para o `.md`. O HTML é o primário on-disk (+ anexo opcional, wave 2).
- Falha → `{"error": ...}` + exit 0; o `.md` já está em disco. **Deep e screen** (screen = variante curta).
- **v4.3 — três cartões novos, que fecham o buraco `.md` → HTML.** Até aqui o `.md` tinha
  conteúdo que o HTML (o artefacto entregue) **não tinha builder nenhum** para renderizar, o
  que tornava lossy qualquer passagem a HTML-only:
  - **`build_thesis_duel`** (§0 v4.2) — tabela bull/bear + o veredicto **LEAN** (`MAIS
    PROVÁVEL`), com a direcção a chegar à classe CSS (`lean bull|bear|even`). Reports
    pré-v4.2 não têm duelo → devolve `""`, nunca um cartão vazio.
  - **`build_swot`** (§2.18a) — 2×2 com **Threats primeiro**, como `prompts/06_swot.md` os
    pesa. Os quadrantes são casados pela **etiqueta**, não pela posição, e o parser aceita as
    **duas** disposições que existem no corpus (grelha 2×2 e lista um-quadrante-por-linha).
    40/40 SWOTs do corpus parseiam completos.
  - **`build_sankey`** — ver a secção "Business-model Sankey" no fim deste ficheiro.
- **v4.3 — capa de uma página (`build_cover`).** Página 1 = a resposta, depois os números
  que a suportam. Duas bandas: (1) action verb · verdict · score · preço · fair value ·
  MoS · GO/NO-GO · ⭐ ratings · thesis · risk · bear trigger; (2) **key financials** em 6
  grupos (Scale · Profitability · Valuation · Health · Growth · Risk/return) — tudo já
  existente em `fundamentals`/`top_strip`, logo **layout, não computação nova**, e custo
  zero no budget de 30 min.
  - A capa vive **fora do `<main>`**, logo a seguir ao header, porque dentro do `<main>`
    caía para a página 2 atrás do radar — confirmado por screenshot em `media=print`, que
    é a única forma de o ver.
  - **Medido a A4** (726×1039 px @96dpi): quatro capas reais em 887–954 px. O header
    colapsa para uma banda fina em impressão (os seus factos estão todos repetidos na
    capa), o que recupera os ~90 px que impediam o CSCO de caber.
  - **Nunca imprime zero por ausência**: `n/a` quando falta, e `<0.01` quando um rácio
    real arredondaria a `0.00` (o D/E 0.00486 da MPWR lia-se como "sem dívida").
  - ROIC cai para **ROE com a etiqueta trocada** quando o guard `IC_MIN_FRACTION` da v4.2
    devolve `None` — não é workaround, é a métrica certa para balanços cash-rich.
  - `COVER_PROSE_BUDGET_CHARS = 1200` é **advisory**: excedê-lo escreve um aviso no log,
    nunca trunca. Cortar um bear trigger a meio da frase é pior do que uma capa com mais
    uma linha.
- **v4.3 — `build_stars` (⭐ quality ratings).** Cinco dimensões × 1-5 estrelas, 100 %
  determinístico a partir das bandas publicadas em `docs/STAR_RATINGS.md`. **Nenhuma
  estrela entra no composite nem no veredicto.** Sem dados suficientes → `n/a`, nunca uma
  estrela. Calculado no renderer, **não persistido**: uma estrela guardada podia divergir
  das bandas publicadas depois de uma mudança de banda; uma calculada não pode.
- **v4.3 — link GuruFocus por ticker** (`markets.gurufocus_url`). O prefixo é o namespace
  do GuruFocus, **não** o sufixo Yahoo nem fiavelmente o MIC ISO 10383: Paris é `XPAR`
  (MIC) mas Londres é `LSE`, Tóquio `TSE`, HK `HKSE`, Milão `MIL`, Taipé `TPE`. Os 17
  mercados mapeados foram **lidos das próprias páginas do GuruFocus** a 2026-08-15; um
  sufixo não verificado **não gera link** — um 404 num report em que se age é pior do que
  link nenhum.
- **v4.3 — `build_valuation_compare`.** Todos os métodos lado a lado; o cartão é sobre a
  **discordância**, não sobre o blend. Modelos inválidos aparecem **com a razão**, não são
  escondidos. O spread max/min é **sempre impresso**; o banner "methods disagree
  materially" só dispara acima de **6.0×** — calibrado, não assumido: medido nos 59 JSONs
  em disco o spread mediano é **3.37×**, logo o 2.5× do plano dispararia em 61 % dos
  reports (um aviso que aparece na maioria é papel de parede). 6.0× dispara em ~24 %.
- **v4.3 — índice cumulativo.** `index.html` — o ficheiro que o bookmark abre — passa a ser
  o **índice cumulativo de todos os reports**, regenerado em cada corrida via
  `docs/_build_index.py`. O hub do dia passa para `_index_{date}.html`. Os dois ficheiros
  nunca foram duplicados e essa era a origem real do "índice desactualizado": `index.html`
  era o hub de um só dia, **reescrito todos os dias**, e o cumulativo vivia em `_index.html`
  que nada agendava (parado desde 2026-08-06). `refresh_cumulative_index()` **nunca levanta
  excepção** — a Phase 6 é exactamente o passo que o timeout de 2026-08-15 saltou.
  ⚠️ `_index.html` fica em disco como órfão; apagar quando confirmares que nada lhe aponta.
- **v4.3 — watermark de versão.** O rodapé passa a `… · host: {hostname} · user: {username}
  · skill v{__version__}`, lido de `scripts/version.py` (fonte única). O H1 do `SKILL.md`
  derivou uma versão inteira precisamente por a versão viver em prosa.
- **Phase F sessão 2 ✅** — cartão **"Valuation metric families — equity vs enterprise"**: Equity (P/E, PEG, P/S, P/B, earnings yield) + Enterprise (EV/Sales, EV/EBITDA, EV/EBIT, FCF/EV), valores tirados do JSON (`fundamentals` + `score_details.valuation.ev_ebit`; P/B e FCF/EV calculados; yields em %), com **tint cheap/fair/rich** por banda (`metrics_glossary.band_for`). Cheat-sheet estático (`metrics_glossary.py`, sem API) em **3 modos**: tooltip `title=` no ecrã · `<details>` por família no mobile · **coluna cinzenta** em impressão (`@media print`). Hub diário opcional `index.html` (`--index {date}`) varre os reports do dia (via frontmatter do `.md` irmão) → grelha de cartões ticker/verdict/score/action.

### Phase 6 — Update state

```bash
python "%SCRIPTS%\update_log.py" --entries-json '<JSON>'
python "%SCRIPTS%\update_shortlist.py"
python "%SCRIPTS%\report_history.py" --archive
```

- `update_log.py` v2 appends entries to `_log.csv`. Columns include `management_score, management_flag, bear_case_trigger`. First run against a v1 CSV migrates once in-place (non-destructive: old rows gain blank v2 fields).
- `update_shortlist.py` relê `_log.csv` inteiro, filtra score≥7.5 e NOT expired (90 dias), regenera `_shortlist.md`. Move entradas expiradas para `_shortlist_expired.md`. Desde 2026-08-05 deduplica **por empresa** (`listings.company_key`), não por string de ticker — `TSM` e `2330.TW` são uma posição, logo uma linha.
- `report_history.py --archive` move os reports **superados** (`.md` + o `.html` irmão) para `_archive/`, deixando **um report por empresa** na raiz. Regra: data mais recente ganha; dentro da mesma data o `deep` ganha ao `screen` que lhe deu origem. `_log.csv` **mantém todas as linhas** — o histórico e o backtesting precisam delas; só os ficheiros renderizados são colapsados. Os caminhos `](IMG/...)` são reescritos para `](../IMG/...)` na cópia arquivada para os charts continuarem a abrir; o HTML embute os charts em base64 e não precisa. `--dry-run` mostra o plano sem mexer em nada.

  Isto é o que faz desaparecer as duplicações no digest e no dashboard: `build_dashboard.py` faz glob só à raiz, portanto o que está em `_archive/` deixa de entrar no bundle. Em cima disso, `build_dashboard.collapse_by_company()` e `send_email.latest_per_company()` voltam a colapsar em memória — um re-run manual entre passagens do arquivador não pode repor a duplicação.
- `update_shortlist.py` v2.1 also emits `_catalyst_calendar.md` alongside `_shortlist.md` — a rolling 30/60/90-day events table for every active shortlist ticker (earnings dates from latest `_log.csv` `earnings_date_next`, ex-div dates from yfinance). The earnings-preview cron (`bd-stocks-earnings-preview` skill) reads this file to auto-trigger 2 business days before any shortlist earnings event.
- `watchlist.py` (v4 Phase E, Phase 2.57) mantém `_watchlist.csv` — nomes composite≥7 travados só pelo preço (`mos_class == "rich"`, não-held); target = `intrinsic_value.fair_value_range.low`. Regra idempotente (upsert preserva `added_date`; remove em compra/perda-de-qualidade/graduação). Lido por `send_email.py` para o bloco triggered. `alpha_beta.py` (Phase 2.56) mantém o cache diário `_portfolio_riskprofile.json` (α/β da carteira vs URTH, EUR) — recomputado 1×/dia, reutilizado por todos os deeps.

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

> **Não é uma decisão deste skill** (ver *Headless rule*). No caminho agendado o skill **não envia nem suprime** o email: sai, e o bat envia. Se o digest for sair com reports repetidos (dois boards no mesmo dia), a resposta correcta é **uma nota no output final**, nunca uma pergunta nem um `send_email.py` suprimido. O bat conta as linhas de HOJE em `_log.csv` **e** `_growth_log.csv`, por isso um dia só-growth continua a mandar email.

#### Como saber em que caminho estás — NÃO adivinhes

```bash
python -c "import os;print(os.environ.get('STOCKSDAILY_SCHEDULED') or 'manual')"
```

`1` ⇒ **caminho agendado: não envias**. Qualquer outra coisa ⇒ manual, envias.

**Isto não é uma sugestão, é uma verificação.** Não inferes o caminho a partir de "isto parece interactivo", da presença de `--ticker`, nem de qualquer outro sinal indirecto — só desta variável, que o `stocks-daily.bat` põe antes de lançar o `claude` e que é herdada por todos os processos filhos.

> **Porquê (incidente 2026-07-29, o segundo email):** esta secção já dizia que no caminho agendado o email é do bat. O run das 17:00 enviou-o mesmo assim, escrevendo no próprio log *"Sent manually at 17:27 since this was **an interactive invocation**"* — a correr sob `claude -p`. Esse envio saiu **antes** de o growth lens ter escrito os reports, portanto sem secção Growth; o run do growth "corrigiu" isso com `--force` às 17:42. **Dois emails, um só Message-ID** (o Gmail entregou os dois — ver abaixo). A lição: **um skill não consegue introspeccionar como foi invocado**, logo pedir-lhe que decida era o bug. O `send_email.py` passou a ter uma guarda de posse que recusa qualquer chamada feita com `STOCKSDAILY_SCHEDULED=1` sem `--scheduled-sender` (que só o bat passa) — mesmo com `--force`. Se te esqueceres desta regra, a guarda trava-te; a regra existe para não gastares o run a tentar.

**Manual deep-dive path (e.g. `--ticker SAP --mode deep`)**: at the end of Phase 6, **explicitly call** `send_email.py` so the user gets the report in their inbox right away — this is the pattern the user expects after every deep analysis:

```bash
python "%SCRIPTS%\send_email.py" --date 2026-04-30
```

`send_email.py` now does three things in one call:

1. Regenerates `_dashboard.html` via `build_dashboard.py` so the snapshot reflects today's reports (this also refreshes `_live_prices.json`).
2. Builds a multipart/mixed email: text+HTML body (cards + inline full reports) **plus** the dashboard as an `.html` attachment (named `StocksDaily_dashboard_{date}.html`).
3. Ships via SMTP with the existing anti-spam headers.

**Watch-list block (v4 Phase E):** near the top of the body (após o disclaimer, antes do adviser-take), `send_email.py` lê `_watchlist.csv` (via `watchlist.load_watchlist`) e, para cada nome, compara o preço **live** com o `target` (fair-low). Preço live: `_live_prices.json` primeiro, depois fallback yfinance para os tickers em falta (a watch-list raramente coincide com os tickers técnicos do dashboard, por isso o fallback é o caminho comum — **requer Python ambiente com yfinance**, como o bat já usa). Nomes com `live ≤ target` ⇒ bloco vermelho **"⭐ Watch-list triggered"** + tag `[WATCHLIST: n]` no assunto; os restantes vão para uma tabela `<details>` "status" com distância-ao-target %. Tudo guarded — uma falha degrada para status-only, nunca aborta o email. O corpo mantém-se markdown→HTML inline (o report HTML estilizado **nunca** é inlined).

**Três defesas contra o digest duplicado (2026-07-29).** O Bruno recebia **dois** digests por dia (às vezes no mesmo minuto, às vezes com 1 min de diferença). Por ordem de força:

1. **Guarda de posse (`STOCKSDAILY_SCHEDULED`)** — a defesa real. Num run agendado só **uma** chamada pode enviar: a do bat, a única que passa `--scheduled-sender`. Qualquer outra é recusada (`{"email_sent": false, "skipped": "not_email_owner"}`, exit 0). **`--force` NÃO a levanta** — foi exactamente por aí que saiu o duplicado de 2026-07-29. Uma chamada recusada **não consome a data** no ledger, senão travaria o envio legítimo do bat a seguir.
2. **`_email_sent.json`** (ledger por data) — um segundo `send_email.py` para uma data já enviada é **recusado** (`{"email_sent": false, "skipped": "already_sent"}`, exit 0). Mata o caso de 2026-07-28, em que um run manual às 12:22 mandou 8 reports e o agendado às 07:32 mandou 10. `--force` ignora **este** ledger (e só este). Um ledger ausente/corrupto lê como vazio — **nunca** é motivo para o digest não sair; e um send falhado **não** consome a data.
3. **`Message-ID` determinístico** — derivado de (data, subject, nº de rows). É **diagnóstico, não defesa**: dois headers iguais ⇒ um digest enviado duas vezes; diferentes ⇒ dois digests genuinamente diferentes. E o `run_host()` no footer diz qual máquina os produziu.

> **Duas coisas que este ficheiro afirmava e que ficaram provadas FALSAS em 2026-07-29** — não as reintroduzas:
> - *"o duplicado nasce no caminho de entrega, não numa chamada dupla"* (a partir de 60/60 runs com uma única linha `email sent to`). **Falso**: eram dois sends de dois processos diferentes. Contar linhas no log do bat não vê o que um skill envia via tool-call — os dois emails das 17:27 e 17:42 traziam preços live do TSM diferentes (376.69 vs 377.00), e uma mensagem entregue duas vezes não pode ter dois corpos.
> - *"um Message-ID igual faz o mailbox colapsar as duas entregas"*. **Falso nesta rota**: os dois emails traziam o **mesmo** `<stocksdaily.2026-07-29.ab542a1d0ce9@ist.utl.pt>` e o Gmail **entregou ambos** — só os agrupou na mesma thread. Um id repetido não suprime nada aqui.

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

## Business-model Sankey — rendered to PNG, no palette (v4.3)

**The standardised colour palette this section used to document never existed.**
`sankey.nodeColors` is not a Mermaid API — the string appears nowhere in mermaid 11.12's
distribution, the version behind both mermaid-cli and Obsidian's bundled renderer — and
`themeVariables.cScale0..N` is ignored for sankey as well, because node hues come from a
hard-coded d3 scheme. Measured against `2026-08-12_FAE.MC_review.md`, which emits the full
`nodeColors` map and still renders in the defaults. So from v4.3 the prompt emits **no
colour config and no colour legend**: meaning is carried by position and width, and the
report caption says so rather than describing a palette the reader never sees.

What v4.3 *does* deliver is the diagram itself reaching the HTML. `scripts/mermaid_render.py`
renders the fence to a transparent PNG via mermaid-cli 11.12, and `render_report.build_sankey`
embeds it as the **Money engine** card. Before this, 170 reports carried a diagram that
Obsidian rendered and the primary artifact did not.

- **Cached by content hash** (`IMG/_mermaid/{sha}.png`, key = source + config + renderer
  version). A render spawns headless Chromium — measured 7.3 s cold, 3.6 s warm — so a
  re-run of the same ticker costs a file read. Bump `RENDERER_VERSION` to invalidate.
- **Fallback-first**: missing `mmdc`, a parse error, a timeout and `BD_MERMAID=0` all return
  no image and no exception. The fence still sits in the collapsed appendix.
- **Shared image budget**: the Sankey is embedded *before* the charts and its bytes are
  passed into `build_charts(used=…)`, so the 1.5 MB cap stays one allowance instead of
  silently becoming one-per-builder.
- **Doc diagrams**: the 9 mermaid blocks in `docs/` are committed as PNGs in `docs/IMG/`
  with the source kept in a collapsed `<details>`, so they survive PDF/HTML export (pdfgen
  has no mermaid support at all). Two were broken and were fixed rather than baked into an
  image: `STRATEGY_GUIDE.md`'s Layer-3 chart failed to parse (chained arrows + a
  backtick-string node containing `<slug>`), and `_sources/Stocks - buy 5y.md` had an
  unterminated fence *and* the dead P/E gate the audit found.
