# ROADMAP — `/bd-stocks-daily` (live backlog)

**Created 2026-07-30.** Forward-looking queue only. The *historical* record of what
shipped and why lives in `STRATEGY_GUIDE.md §10` (items 1–14, closed at the v3
Phase 9 review) and in the wave plans; this file tracks only what is **not
deployed**, with the reason and the trigger that would unblock it.

Effort: **S** ≤ 2 h · **M** 3–6 h · **L** > 6 h.
State: **READY** (plan written, no blocker) · **AGREED-DEFERRED** (decided not to
do now, on purpose) · **GATED** (waiting on an external trigger) · **BACKLOG** (no
ETA) · **WON'T DO** (decided against).

---

## Now — READY, nothing blocking

### R1. `update_shortlist.py`: deep must supersede screen on the same day — **S**

`build_shortlist()` dedupes per ticker with `r["date"] > latest[t]["date"]`. On a
Phase 5.5 auto-cascade the screen and the deep row share a date, so the strict `>`
keeps the **first** CSV row — the screen — and the shortlist links the screen
report. That contradicts the skill spec ("deep supersedes screen on the
shortlist").

Fix is written and is one function:

```python
def _rank(r):
    return (r["date"], 1 if r.get("mode", "").lower() == "deep" else 0)
# keep r when t not in latest or _rank(r) > _rank(latest[t])
```

- **Found** 2026-06-10. Deferred only because editing `~/.claude/skills/` was
  denied by the auto-mode classifier at the time; that is no longer true.
- **Known symptom**: PYPL's shortlist row was hand-corrected on 2026-06-10 and
  reverts on every `update_shortlist.py` run until this lands.
- **Needs**: a go-ahead. Nothing else.

### R2. Macro gauges — Buffett Indicator + M2 regime + forward-profit horizons — **M**

`_macro/<date>.md` §6 and §7 have been rendering "not available" because these
three gauges are WebFetch-sourced and no source is pinned in `macro_daily.md`.

- **Decided 2026-07-30** (Bruno): build it. Chosen over the segments chart because
  the cost is one-off — the `_macro/` cache is daily, so there is **zero per-run
  cost** once the sources are pinned.
- **Plan**: FRED `M2SL` for the liquidity regime (clean public JSON API);
  market-cap-to-GDP for the Buffett Indicator needs a source picked and pinned;
  index-level forward-profit horizons (3m/6m/1Y/2Y/3Y) from the same
  multpl/gurufocus family already used for P/E and CAPE.
- **Constraint**: keep the existing per-gauge independent degradation — one dead
  source must never blank the section, and **"not available" always beats an
  estimate**.

### R3. Prefilter never re-validates what it promoted — **M**

Two halves of the same hole, both verified 2026-07-30:

1. `run_prefilter.py` **clears `_universe_pending.yaml`** after every run
   (line 451) and **never writes `_universe.yaml`** (only reads it, line 152). A
   ticker seeded via pending therefore gets exactly **one** evaluation, ever.
2. `build_work_list()` reads universe + pending + retry only, so a name sitting in
   `_prefiltered.yaml` but absent from `_universe.yaml` is **never re-checked and
   never droppable** — it coasts in the pool indefinitely on a stale verdict.

Twelve names were in exactly that state on 2026-07-30 (`MRVL, DELL, UBER, NUE,
UMC, GFS, HPE, LDO.MI, SAAB-B.ST, MRLN, 2026.HK, 066570.KS`) and were repaired by
hand-adding them to `_universe.yaml`. The mechanism that created the drift is
untouched.

- **Plan**: merge passing pending entrants into `_universe.yaml` at the end of a
  run, and/or fold `_prefiltered.yaml` members into the work list so every pool
  member is re-validated.
- **Watch out**: raising the work-list size raises the run's API budget; the
  prefilter already runs a 2 h timeout.

### R4. Twelve Data cross-check compares the wrong venue — **S**

`fetch_twelvedata_validation` resolves `ADS.DE` on the free tier, but the quote comes back
from **`exchange: XSTU` (Stuttgart)**, a thin secondary venue — not Xetra. On 2026-07-30 it
returned a stale €182.25 while Xetra had gapped **−18%** on earnings, and the divergence was
recorded as a yfinance `data_quality: suspect` flag. **The reference price was wrong, not the
data being checked.**

- **Found** 2026-07-30 by the provider audit (ReadNow PDF 0263).
- **Plan**: read `exchange` from the TD response and either refuse the comparison when it is
  not the ticker's primary venue, or record the venue alongside the divergence so a
  cross-venue gap is never reported as a data error.
- **Also**: free-tier TD covers **one** of the six non-US markets held. Euronext is
  `402 Grow/Venture`, TW/HK/KR `402 Pro/Venture`. Restricting TD to US cross-checks is the
  honest alternative.

### R5. Rotate the six Alpha Vantage keys instead of retrying one — **S**

`config/api_keys.txt` holds **six** AV keys (`api_key_alphavantage` + `…1`–`…5`). The free
limit is 5 requests/**minute** per key, and a throttled `CASH_FLOW` call silently produced
FCF-less caches for 10 of 33 names over three months (fixed 2026-07-30 with a 20 s spaced
retry — which treats the symptom).

- **Plan**: round-robin the pool in `financial_history.py` / `valuation_bands.py`, raising the
  ceiling to ~30 req/min and removing the burst throttle at its cause.
- **Keep** the spaced retry as the backstop; the pool reduces how often it fires.

---

## Next — AGREED-DEFERRED

### N0. Probe FinancialReports for EU filings + new listings — **S**

The provider audit found the only credible free source of **European** filings and new
listings: FinancialReports (`financialreports.eu`, now 301→`financialfilings.com`) — 57
markets, 69,647 companies, **500 free credits/month**, 600 req/min, REST + Python SDK, and a
daily European IPO index. 500 calls/month is ample at weekly cadence.

- **Why it matters**: **no free API gives European IPOs.** Finnhub's calendar returns 142
  entries, all NASDAQ/NYSE; AlphaVantage's returns 3 rows; FMP's is `402`. yfinance has no
  IPO endpoint at all.
- **Unverified**: which fields the free 500 credits unlock, and whether the IPO index is
  exposed via API or only on the website. One free key + one probe answers both.
- **Caveat**: the domain rebranded recently — treat stability as unproven.

### N1. Revenue-segment charts, behind an opt-in `--segments` flag — **M**

- **Decided 2026-07-30** (Bruno, on my recommendation): do **not** put this in the
  scheduled path. Build it opt-in so the unattended 17:00 job never fetches a PDF,
  and pull it on demand for a name actually being studied.
- **Why not in the daily run**: this is the *only* place in the pipeline where
  numbers come from an LLM reading a filing (the documented ground-truth
  exception, `SKILL.md` Phase 2.5 step 7b). It adds a WebFetch + an LLM extraction
  to every deep-dive — new latency and a new failure mode in the job that already
  hung once and needed `run_with_timeout.ps1`.
- **Today's behaviour is fine**: `segments_available: false` degrades cleanly with
  a `⚠️ Segment data unavailable` note. Nothing is broken; this buys one chart.
- **Contract to keep**: every segment number stays tagged "company filings
  (LLM-extracted)" with a `source_url`, values only from the official table —
  never estimated or interpolated.

### N2. `op_margin_3y_delta` — Scalable Kings tie-breaker (§10 item 5) — **S**

Add `op_margin_3y_delta` to `_compact_fund` and use it as a **tie-breaker inside
the Moat sub-score**, not as a new weight. Separates margin-expanders from
margin-stable names within the same moat score.

- **Why still deferred**: the Scalable-Kings signal overlaps a Moat component that
  `SCORING_REVIEW_v3.md §2.1` already calls double-counted. Not urgent, and adding
  it as a *weight* would need the item-12 harness.
- **Architecture**: one extra JSON field + 3 years of operating margin via
  `Ticker.financials`.

### N3. P/E band depth guard — **S**

The own-history P/E band is unusable when its window contains an
earnings-collapse year, and nothing currently says so. adidas on 2026-07-30: a
**3-year** band whose *minimum* (25.44×) sat above the live multiple (19.20×) and
whose median reached **47.73×**, because 2023 EPS approached zero after the Yeezy
termination. That median then propagated into `justified_exit_pe`, two of the five
intrinsic models, a €608 forward target (IRR +60.8%, correctly sanity-flagged) and
an exit ladder whose first trim rung was **2.9× the current price**.

- **Plan**: refuse to publish a band (or mark it `unusable`, alongside the existing
  `skewed`/`mismatch` states) when depth < ~5 years **or** when any year's EPS is
  within a small epsilon of zero. Consumers already handle a degraded band.
- **Note**: using the median instead of the mean was the earlier fix for this
  class of problem (ADSK 2026-07-22). It is not sufficient on a 3-year window.

### N4. Revisit `fair_price` vs the ±70% DCF gate — **S**

MSFT on 2026-07-30: `dcf_valid` stayed true at **−69.70%** against a ±70%
invalidation threshold — surviving by **0.30pp** — so the deterministic rule
("DCF when valid, else consensus median") published **$118.35** as `fair_price`
against a live price of $390.54 and a 54-analyst consensus median of **$550**. The
dashboard's Fair Px / Upside columns therefore show a known artefact, and the
company's own 15-year P/E band put it at the 53rd percentile (i.e. ordinary).

- **Options**: tighten the gate; require the DCF to agree within some band of the
  blend before it may become `fair_price`; or prefer the blend over a lone model.
- **Do not** simply exclude the DCF — on the 24-name sample,
  `roe_residual_income` set the low in 12 cases against the DCF's 5.
- **Related, already fixed** 2026-07-30: the watch-list moved off
  `fair_value_range.low` onto the blend for exactly this reason.

### N5. Peer-set quality when `peers_source == by_sector` — **M**

adidas was ranked against **Amazon, McDonald's, Home Depot, Starbucks** and Nike
because yfinance could not resolve a footwear peer set. Only Nike is a peer, yet
the resulting 7.33/10 carries the full **12%** peer weight in the composite.

- **Plan**: either add a curated fallback in `peers.json` for common industries, or
  damp the peer sub-score toward neutral (5.0) when the source is `by_sector` —
  the same honesty the `none` case already gets.

---

## Gated — waiting on a trigger

### G1. Naive backtest to calibrate `WEIGHTS_V2_DEEP` (§10 item 12) — **M**

T+6m / T+12m attribution of `price_at_eval` vs benchmark, replacing
educated-guess weights with measured ones. **Still gated as of 2026-07-30.**

- `_log.csv`: 259 rows, 253 with `price_at_eval`, earliest **2026-04-17**, span
  **3 months**. Rows old enough for T+6m: **0**. For T+12m: **0**.
- **Trigger dates**: first T+6m attribution possible **≈ 2026-10-17**; first T+12m
  **≈ 2027-04-17**.
- **The clock is protected**: `price_at_eval` has survived every schema bump
  including v2.1 → v2.2, so the 12-month clock has never been reset
  (`SCORING_REVIEW_v3.md §S5`). Do not break that column.

### G2. Sector-specific dynamic weights in the Valuation sub-score (§10 item 8) — **M**

Detect `lynch_category` and adjust the sub-weights *inside* Valuation (never the
top-level composite weights). **Blocked on G1** — changing weight magnitudes
without a backtest is an educated guess on top of an educated guess
(`SCORING_REVIEW_v3.md §4`).

---

## Backlog — no ETA

| # | Item | Effort | Note |
|---|------|--------|------|
| B1 | Port the v4 overlays into `/bd_stocks_daily_growth` | **L** | Q4 of the skills guide (ReadNow 0245). Read `ReadNow\_markdown_\stocks_skills_guide_NOTES.md` first — it holds the port checklist. |
| B2 | `/bd-stocks-fallen-angels` sub-skill (Biggest Losers) (§10 item 13) | **M** | Counter-thesis to the compounder mandate; needs its own "fallen angels" prefilter. yfinance exposes `52WeekChange`. |
| B3 | News-sentiment NLP via BERT, own pipeline (§10 item 14) | **L** | Heavy infra (model + scraping + cache) that belongs in a separate service; incompatible with the ~$20/run budget. Phase H's LLM-classified dials already cover the use case cheaply. |
| B4 | Four yfinance names with no FCF series at all | **S** | `0175.HK, CMO.MC, FLOW.AS, INGA.AS` — thin non-US statements where FCF genuinely is not published. Correct degradation today; only worth revisiting if a second source is added. |

---

## Won't do — decided against

- **TIKR screens #7–#10** (Yield / Deep Value / Net-Nets) — incompatible with the
  Quality Compounder mandate (`STRATEGY_GUIDE.md §10`).
- **A summable 4×10 SWOT scorecard** — the SWOT stays a qualitative overlay with
  no number entering the composite (§10 item 4).
- **A standalone `/bd-stocks-timing` sub-skill** — absorbed by the Technical card
  and GO/NO-GO, which is exactly the intended scope (§10 item 10).
- **ATR trailing stops in the exit plan** — `atr_context.enabled` stays `false` by
  design: a compounder tolerates normal 20–30% drawdowns, and exit discipline is
  the P/E band plus the thesis. Trailing stops belong to the growth skill.

---

## Maintaining this file

Add an item when work is **consciously not done** — with the reason and the
trigger, not just the title. Move it out when it ships, and record the outcome in
`STRATEGY_GUIDE.md §10` (the historical record) rather than leaving a DONE row
here. A roadmap of finished things is a changelog wearing the wrong hat.
