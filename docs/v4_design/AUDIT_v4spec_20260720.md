# Adversarial audit — bd-stocks-daily v4 spec + design assets (2026-07-20, pre-build)

Two independent auditors ran the night before build start. Every finding below was either
**folded into the spec** (`ReadNow\0232-bd-stocks-daily-v4-spec-*.pdf`, §14b) or **applied
directly to `sample_report_v2.html`**. Kept here so build sessions (B→A→C→D→E→F) can consult
the raw findings. Status column = how it was resolved on 2026-07-20.

## Auditor 1 — spec (v4_spec.md vs SKILL.md / build_dashboard.py / send_email.py / financial_history.py / analyze_ticker.py / AUDIT_v31.md)

| ID | Sev | Finding | Resolution |
|---|---|---|---|
| B1 | BLOCKER | HTML-primary breaks the email digest: `send_email.py` is md-based (report_filename → load_report_markdown → md→inline HTML; `obsidian://` links target `.md` notes — an `.html` is not a note). v2 layout (grid/gradient/`<style>`) would be stripped by Gmail/Outlook. | SPEC §11: digest stays md→inline-table unchanged; report HTML never inlined into mail body; HTML = on-disk primary + optional attachment. Decision #6. |
| B2 | BLOCKER | md parser contract not frozen: 4 consumers hard-parse frontmatter + `**Thesis**:`/`**Risks**:`/`**Action**:` + H1 (build_dashboard, send_email, thesis_check, thesis_dashboard). AUDIT_v31 already caught one parser BLOCKER here. | SPEC §11: frozen contract + regression test `build_dashboard.slim_report()` green on a v4 report (Phase F acceptance gate). Decision #7. |
| M1 | MAJOR | "Reuse `template.html` + `__DATA__`, zero new dependency" is FALSE — that's the dashboard's one-token JSON + client-JS pattern; the report needs static JS-free markup, list builders (N flags/peers/points) + programmatic SVG (radar polar math, gauge %, sparklines). matplotlib PNG embedding unspecified. | SPEC §11 renderer paragraph rewritten (Python-side templating, own `report_template.html`, base64 PNGs ≤~1.5 MB); §13 Phase F = L, 2 sessions. Decision #8. |
| M2 | MAJOR | 10y P/E/P/S band has no verified free source for non-US names (TD free = price only; FMP free ≈5y US-centric; AV 25 req/day already ~10 consumed by financial_history). | SPEC §7: band degrades to `depth_years`, endpoint+limit documented per source, shared AV budget guard (§5 principle 7). |
| M3 | MAJOR | Exit ladder used inputs that don't exist: "⅓ at 2× cost" (no cost basis for non-held tickers) and "sector ceiling" (no such input anywhere). | SPEC §6: ladder relative to fair value; cost rung only when held (BankBD); exit-P/E capped at own historical high; sector ceiling dropped. |
| m1 | MINOR | Beneish often "not computable" on non-US names (Receivables/SG&A/Depreciation thin in yfinance abroad); red_flags must not re-fetch. | SPEC §8: expectation stated; red_flags.py reuses analyze_ticker JSON. |
| m2 | MINOR | API keys: reuse `BD_Finance\config\api_keys.txt`; skill repo lacks defensive .gitignore for key files. | SPEC §5 principle 6 (gitignore line lands with Phase B code). |
| m3 | MINOR | No per-phase acceptance criteria. | SPEC §13 acceptance-gate table added. |
| m4 | MINOR | schema_version / additive keys undocumented. | SPEC §5 principle 5: stays 2.2; keys listed; parser tolerance required. |
| m5 | MINOR | Email size (base64 PNGs × 5 reports vs Gmail 25 MB). | Mooted by B1 fix (report HTML not inlined; attachment optional). |
| m6 | MINOR | New scrape targets = silent-break surface. | SPEC §9: every gauge degrades independently. |
| m7 | MINOR | Stale refs: "140-test" (real: 188); SCORING_REVIEW_v3.md lives in OUT_DIR docs, not skill docs. | SPEC §1 + §5 corrected. |

Cleared vectors: overlay-only holds in all 6 phases; ground-truth holds (every number feature names a Python helper; macro = WebFetch + source + as-of); build order B→A→C→D→E→F matches data dependencies; α/β feasible from yfinance 3y monthly; FRED M2SL/VIXCLS stable.

## Auditor 2 — design assets (docs/v4_design/ vs build_dashboard.py / send_email.py / SKILL.md / make_pdf.py)

| ID | Sev | Finding | Resolution |
|---|---|---|---|
| M1 | MAJOR | `__DATA__` pattern doesn't fit (template has zero JS; needs Python-side multi-slot templating + generated SVG). | Same as spec M1 — SPEC §11 rewritten. |
| M2 | MAJOR | "ACCUMULATE" header verb has no backing field (skill vocabulary = great/invest/review/fair/reject; "accumulate" only appears as entry-zone prose). | SPEC §11: deterministic action-verb map (verdict × MoS × tech GO/NO-GO → ACCUMULATE/BUY-DIP/HOLD/WATCH/AVOID). |
| M3 | MAJOR | No missing/null-data states (dcf_valid:false, peers_source:none, negative P/E, shallow band, no dividend, hardcoded €). | SPEC §11 null-render table; implement in Phase F. |
| M4 | MAJOR | Print CSS hid `<summary>` → Macro §8 printed headingless. | **FIXED in template**: summary kept in print as styled heading, marker removed. |
| M5 | MAJOR | `break-inside:avoid` on whole variable-height cards → A4 clipping. | **FIXED in template**: avoid moved to metric/side/box/li/tr; cards may break. |
| m6 | MINOR | Malformed + duplicate `.gB` rule. | **FIXED** (single valid rule). |
| m7 | MINOR | Verdict badge hardcoded gold; `--good` vs "invest" naming. | **FIXED**: per-verdict classes `.verdict.{great,invest,review,fair,reject}`; var renamed `--invest`. |
| m8 | MINOR | Embedded icon oversampled (was ~75% of file weight). | **FIXED**: 128→96 px re-encode; HTML 78→54 KB. |
| m9 | MINOR | `bdfinance_logo_wordmark.svg` unused. | Documented in reference_sources.md — kept as brand reference. |
| m10 | MINOR | Unquoted `Segoe UI`. | **FIXED**. |
| m11 | MINOR | Claimed 360 px breakpoint absent; radar SVG fixed-width. | **FIXED**: 360 px rule added; `.snow svg{max-width:100%;height:auto}`. |
| m12 | MINOR | `nav .tag` gold-on-white ≈1.9:1 contrast. | **FIXED**: darkened to #a9791a. |
| m13 | MINOR | reference_sources.md promises more than template shows (VIX, P/B, size-regime, Jitta time-series line, CAGR slots). | Reconciliation section added to reference_sources.md. |
| m14 | MINOR | Radar generator undecided (inline SVG vs render_charts.py PNG). | SPEC §11 "still open": inline SVG preferred; port polar math in Phase F. |
| m15 | MINOR | Hardcoded provenance ("as-of 2026-07-20", "Claude Opus 4.8"). | SPEC §11 "still open": become render slots in Phase F. |

Cleared vectors: self-containment (system fonts, data: URI icon, no CDN); email reuse safe today (digest doesn't touch the v2 template); print colour path verified (`print-color-adjust:exact` + make_pdf print_background=True). Note for SKILL.md later: ad-hoc browser Ctrl+P needs "background graphics" checked.

## Still open at build time
1. Radar axis labels ("Value"/"Mgmt") clip at SVG edge (pre-audit known nit).
2. Gauge caption crowds scale labels at narrow widths (pre-audit known nit).
3. Radar source decision + polar-math port (m14) — Phase F.
4. Provenance/date slots (m15) — Phase F.
5. `.gitignore` key guard (m2) — land with Phase B.
