# Portfolio data flow — end to end

v4.3 §4.0, audited 2026-08-15 against the live code, the live Task Scheduler and the run
logs. **This is the prerequisite for `/bd-stocks-monitor` (§4.1)**: monitoring a spreadsheet
that is not reliably updated is monitoring stale data, so the chain is verified first.

**Single source of truth: `Patrimonio BD.xlsx`.** BankBD is a *derived read model*, not a
competing master. BankBD's own README frames the Excel as something to migrate away from;
that is resolved here in writing, in the other direction — the Excel is master, and the
import is idempotent precisely so it can be re-derived at any time.

> The workbook is **password-protected** (`PATRIMONIO_PW`, read from the `.env` beside it —
> never committed). Everything below reads it; only one proposed step writes to it.

## The chain, as it actually runs

```
  Payslip PDFs ─────────► patrimonio wages --apply ──┐
  (OneDrive)              (parses, fills the month)  │
                                                     ▼
  Bank / broker ────────► [MANUAL for 7 of 17] ──► Patrimonio BD.xlsx ──► patrimonio report
  balances                [connector-able for 10]    "Dados" sheet          → Patrimonio.html
                                                     │  ▲
                                                     │  └── patrimonio audit (payslip ↔ sheet)
                                                     ▼
                                          BankBD import-excel  (idempotent, prunes)
                                                     │
                                                     ▼
                                          bankbd.db → MCP tools → /bd-stocks-monitor (§4.1)

  Yahoo "BD" portfolio ──► portfolio_ingest.py ──► _portfolio_holdings.yaml
  (CSV export, manual)     (Mon 08:30, --write)    └── held-detection: exit_plan,
                                                       thesis_dashboard, buy_list
                                                   ✗ NOTHING writes back to "Accoes (BD)"
```

`Patrimonio Monthly` (09:00, monthly) runs `monthly.cmd`: **wages → audit → report → BankBD
import**. The order is load-bearing — the report and the import must both see the writes.

### Verified from the logs, not assumed

`logs/monthly_03082026.log`, the most recent run:

| Step | Result |
|---|---|
| 1 wages | `Nothing to do — every payslip already has a filled row.` |
| 2 audit | **231 values agree (±1.00) · 0 differ** · 75 payslips unreadable (pre-2020 scans) |
| 3 report | `Patrimonio.html` 49 KB, self-contained |
| 4 BankBD | **1041 snapshots, 211 income rows, 216 months**, exit code 0 |

All **ten** finance tasks are registered and `Ready`: StocksDaily 13:30 · StocksGrowth
12:45 · StocksPrefilter Mon 14:30 · StocksWatchdog 14:15 · StocksPortfolioWeekly Mon 08:30 ·
StocksPortfolioMonthly · StocksEarningsPreview · StocksEarningsReview · StocksStrategyMonthly ·
Patrimonio Monthly 09:00.

`_portfolio_holdings.yaml` was last written **2026-08-10 09:10** (the Monday 08:30 job, after
the `job_lock` queue) and there is **no** `_portfolio_export_stale.txt`, so the Yahoo export
is current. The weekly ingest is live.

---

## Step-by-step findings

### 1. Bank cash — 10 of 17 live columns are connector-able, 7 are irreducibly manual

The `Dados` sheet carries 19 institution columns, 2 of them closed (`BPI`, `CGD` — both
mapped to `None` on purpose). BankBD ships **9 connectors**. Coverage:

| Column | Connector | Note |
|---|---|---|
| CTT · Best · Big | `gocardless` | PSD2; its docstring names exactly these three |
| Revolut | `revolut` | |
| DeGiro · XTB · Trade Republic · IBKR | `degiro` · `xtb` · `traderepublic` · `ibkr` | |
| Coinbase · Binance | `coinbase` · `binance` | |
| **Trading212 · eToro · RH · Nexo** | — | no connector |
| **IGCP · EdenRed · PPRs (BPI Pensões)** | — | no public API at all |
| BPI · CGD | n/a | closed accounts |

**The honest outcome is not "fully automatic".** PSD2/GoCardless consents expire (typically
90 days) and must be re-authorised by hand; that step cannot be automated away. The
achievable target is *"10 columns automated, consent renewal calendared, 7 columns manual"* —
and writing that down is worth more than a plan that quietly assumes 19.

### 2. Salary — already automated, and its failure is loud enough ✅

`wages --apply` is step 1 of `monthly.cmd`, and `payslips.py` is validated 70/70 for
2020-03 → 2026-03. `audit` re-checks **every** payslip against the sheet on every run and
prints the disagreement count — 231/0 on the last run. A parse failure surfaces as a
`differ` count in the log rather than as silence. **No work needed.**

The 75 unreadable pre-2020 scans are image-only PDFs; they are reported every run rather
than suppressed, which is the correct behaviour, not a defect.

### 3. Yahoo export → workbook — **the real gap** ⚠

`portfolio_ingest.py` writes `_portfolio_holdings.yaml` and **nothing else**. Nothing in the
system writes new buys or sells into the `Accoes (BD)` sheet; that remains a hand edit.

Two concrete constraints anyone implementing this must know, both verified in the code:

- `workbook.read()` is hard-wired to `SHEET = "Dados"` (module constant), and `write()`
  takes bare cell addresses (`{'Y214': 2144.55}`). **Both need a sheet parameter** before
  `Accoes (BD)` can be touched at all.
- Writes must keep going through **Excel COM against a local copy**: openpyxl would destroy
  2 chartsheets, 31 chart parts and 12 drawings on save, and Excel opens password-encrypted
  files on the OneDrive path read-only, so `Save()` silently no-ops there. This is not a
  detail to simplify away.

**Proposed shape** (not built in this wave): a `patrimonio positions` sub-command that diffs
the Yahoo export against `Accoes (BD)`, inserts new lots and closes disposed positions
(writing the VENDA block) — **dry-run by default with a printed diff**, the same contract
`portfolio_ingest.py` already uses, plus the existing timestamped `.BACKUP_<stamp>.xlsx`.
Monthly cadence.

### 4. BankBD import — the "known broken" premise was **false**, twice over ✅

The v4.3 plan inherited from `Patrimonio/README.md` the claim that `excel_importer.py`
hardcodes column indices. **The code says the opposite**, in its own docstring: columns are
resolved from the sheet's header row via `patrimonio.workbook`, *never by fixed index*,
because the layout has already shifted twice (Trading212 and eToro inserted, CGD moved to
the end) and an index-based mapping "would have silently filed Coinbase balances under
'Robin Hood'".

Re-checked this session, two further plan assumptions also proved already satisfied:

- **Trading212, eToro and CGD are all in `HEADER_TO_ACCOUNT`** (CGD deliberately `None` —
  closed). Nothing to add.
- The unmapped check is **bidirectional**. It reports both map-entries missing from the
  sheet *and* `"(column present but unmapped)"` for money columns between `ANO` and `TOTAL`
  that the map does not know — so a newly inserted institution column cannot be silently
  ignored. The last run logged no warning, meaning the map is currently complete.

The import also **prunes**: a cleared cell removes the corresponding row, scoped to
`source='excel_import'` so live connector snapshots are never touched. A "refresh" cannot
leave behind a value the source no longer asserts.

**What is actually missing is one thing, not a rebuild**: a **post-import reconciliation
assert** — row count and per-month totals recomputed from the sheet and compared with what
landed — so a *partial* import fails loudly instead of returning a plausible smaller number.
Today `import_excel` returns `{snapshots, income, months, pruned, unmapped}` and the caller
prints them; nothing checks them against the source. Estimated **~1 h**, not a rewrite.

### 5. HTML dashboard — runs after the writes ✅

`patrimonio report` is step 3 of `monthly.cmd`, after `wages` and `audit`, and before the
BankBD import. Verified in the log: 49 KB self-contained output. Correct ordering, no change.

### 6. End-to-end verdict

The chain is **sound and running**. Its weaknesses are, in order:

1. **Position lots are hand-maintained** (step 3) — the only structural gap.
2. **7 of 17 balance columns are manual** and always will be (step 1); the other 10 are
   automatable but gated on PSD2 consent renewals that expire ~90 days.
3. **No reconciliation assert** on the import (step 4) — the one cheap fix.

Two traps that must survive any future change:

- **A green Task Scheduler result proves nothing** when `run_hidden.vbs` is in the chain
  (documented in `SCHEDULING.md`). Verify from the logs, as this audit did.
- **`PATRIMONIO_PW` never gets committed.** The password lives in the `.env` beside the
  workbook and is resolved by `patrimonio.workbook`, explicitly so that the BankBD repo —
  which has a git remote — never sees it.

---

## What §4.1 may and may not do

`/bd-stocks-monitor` reads the workbook through `patrimonio.workbook` (which already
decrypts and resolves by header) and **never writes to it**. The acceptance test is
byte-identity of `Patrimonio BD.xlsx` before and after a monitor run.

`Dados` gives the monthly balance series back to **January 2009** — that is the long
performance history the monitor's benchmark comparison needs. `Accoes (BD)` gives the equity
lots and cost basis; `Obrigacoes` the bonds; the deposit/IGCP columns the cash. BankBD's MCP
tools (`bankbd_net_worth`, `bankbd_positions`, `bankbd_accounts`) are the live cross-check —
and, per finding 4, they are trustworthy on mapping, with the residual risk being a *partial*
import that nothing currently asserts against.

## Changes proposed by this audit, and where they land

| # | Change | Repo | Status |
|---|---|---|---|
| 1 | Reconciliation assert after `import_excel` | `C:\Github\BD\Finance\BankBD` | **proposed** — outside the three repos this plan writes to; needs a go-ahead |
| 2 | `patrimonio positions` (Yahoo → `Accoes (BD)`, dry-run default) | `C:\Github\BD\Finance\Patrimonio` | **proposed** — same |
| 3 | Correct the stale "hardcoded column indices" claim in `Patrimonio/README.md` | `C:\Github\BD\Finance\Patrimonio` | **proposed** — same |
| 4 | Assert Excel-as-master in writing where BankBD's README contradicts it | `C:\Github\BD\Finance\BankBD` | **proposed** — same |

Items 1–4 are **not** implemented by this wave: they modify two repositories outside the
plan's declared write scope (`~/.claude/skills/`, `C:\BD_Obsidian`, `C:\Github\.scripts`).
The audit that gates §4.1 is complete without them — §4.1 only needs to know the chain is
sound, which it is.
