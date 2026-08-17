"""
send_email.py — Send daily digest to configured recipients.

Reads the N latest entries from _log.csv matching --date, and builds a
multipart/alternative email (plain-text + HTML) with verdicts, scores,
1-line thesis, and obsidian:// links to each report.

Anti-spam design (2026-04-23):
- Subject line is emoji-free and uses [TAGS] — Yahoo spam filter penalises emojis
- multipart/alternative with a plain-text fallback part — classic deliverability signal
- obsidian:// links are kept in HTML but duplicated as text paths in the plain part
- List-Unsubscribe header signals this is legitimate transactional mail

Reuses BD_Finance/email_send.py SMTP config (IST, bfsd@ist.utl.pt).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import mimetypes
import os
import re
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

try:
    import markdown as _markdown  # type: ignore
except Exception:
    _markdown = None

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# Add BD_Finance to path to reuse api_keys_reader + SMTP
BD_FINANCE = Path(r"C:\Github\BD\Finance\BD_Finance")
sys.path.insert(0, str(BD_FINANCE))

LOG = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily\_log.csv")
# Phase 7 — parallel growth lens (/bd_stocks_daily_growth) keeps its own state file.
# The daily digest surfaces a Growth section IF this file exists and has rows for
# today; otherwise the section is omitted entirely (no-op — must never break the
# 17:00 email). The daily _log.csv schema above is UNTOUCHED.
GROWTH_LOG = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily\_growth_log.csv")
OUT_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
OUT_REL = "Personal/Finance/StocksDaily"  # inside BD_Obsidian vault
DASHBOARD = OUT_DIR / "_dashboard.html"
BUILD_DASHBOARD = Path(r"C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\build_dashboard.py")

# bruno.dias@secil.pt added 2026-08-12 as a delivery CANARY: the 13:57 scheduled digest of
# 2026-08-12 was accepted by the IST relay but never reached the Gmail inbox, while a
# byte-identical --force resend at 17:30 arrived fine. O365 filters independently of Gmail,
# so a day where SECIL receives and Gmail doesn't pins the loss on Gmail's side.
RECIPIENTS = ["eins.ist@gmail.com", "bruno.dias@secil.pt"]

# Send-once ledger, keyed by digest date: {"2026-07-28": {"sent_at", "message_id", "reports"}}.
# Bruno was receiving two digests per day (sometimes the same minute, sometimes a minute apart).
# A SECOND run on the same date (a manual re-run beside the 17:00 job, as happened 2026-07-28 when
# 12:22 sent 8 reports and 07:32 sent 10) can no longer produce a second digest. `--force` ignores
# this ledger; it does NOT ignore the ownership guard below.
SENT_INDEX = OUT_DIR / "_email_sent.json"

# ---------------------------------------------------------------------------
# Email ownership: exactly ONE process may send per scheduled run.
#
# stocks-daily.bat sets STOCKSDAILY_SCHEDULED=1 before launching `claude`, so every descendant --
# the quality run, the growth run, and any send_email.py they spawn -- inherits it. Only the bat's
# own final call passes --scheduled-sender, so only the bat can send on the scheduled path.
#
# Why an env var and not a documented rule: SKILL.md already said "scheduled path -> the bat sends,
# not you". On 2026-07-29 the 17:00 run sent anyway, having concluded in its own log "Sent manually
# at 17:27 since this was an interactive invocation" -- while running under `claude -p`. A skill
# cannot reliably introspect how it was invoked, so asking it to decide was the bug. The parent
# process knows for certain, and an inherited env var carries that fact down without being guessed.
#
# The 17:27 send then caused the second one: it went out BEFORE the growth lens had written its
# reports, so the digest carried no Growth section, and the growth run "fixed" that with --force at
# 17:42. Two emails, one Message-ID. Removing the premature send removes both.
SCHEDULED_ENV = "STOCKSDAILY_SCHEDULED"

# Attribution line closing every digest. The host is stamped so it is obvious at a
# glance which machine ran the 17:00 job — the laptop or a VM host.
ATTRIBUTION_MODEL = "Claude Opus 5 (1M context)"
ATTRIBUTION_OWNER = "bsdias©2026"


def run_host() -> str:
    """Hostname of the machine composing this digest ('unknown' if undiscoverable)."""
    import platform
    try:
        return platform.node() or "unknown"
    except Exception:
        return "unknown"


_COST_MARK = "<!-- run-cost -->"


def stamp_reports_with_cost(times: dict, rc: dict, wk: dict) -> int:
    """Append (or refresh) a one-line cost footnote at the bottom of each report file.

    Idempotent by design: the line is fenced by a marker comment and rewritten in place, so a
    re-sent digest never stacks duplicates onto the report. Failures are logged per file and never
    propagate -- a cost footnote is not worth corrupting a report over.
    """
    import token_stats as ts

    n = 0
    exact = rc.get("per_report_exact")
    for ticker, path in ((t, p) for t, p in times.items()):
        try:
            f = path if hasattr(path, "read_text") else None
        except Exception:
            f = None
        if f is None:
            continue
        try:
            body = f.read_text(encoding="utf-8")
        except OSError:
            continue
        tokens = rc.get("per_report", {}).get(ticker)
        if tokens is None:
            continue
        how = "measured" if exact else "run total / report count"
        line = (_COST_MARK + "\n> **Run cost** - " + ts.fmt(tokens) + " tokens for this report ("
                + how + "); " + ts.fmt(rc["total"]) + " for the whole run. Finance skills were "
                + format(wk["pct"], ".1f") + "% of all Claude Code over the last "
                + str(wk["days"]) + " days.\n")
        cut = body.find(_COST_MARK)
        if cut != -1:
            body = body[:cut].rstrip() + "\n\n"
        else:
            body = body.rstrip() + "\n\n"
        try:
            f.write_text(body + line, encoding="utf-8")
            n += 1
        except OSError as e:
            log("cost footnote failed for " + str(f.name) + ": " + str(e))
    return n


def run_cost_block(target_date: str, rows: list) -> tuple:
    """(html, text) telling the reader what this digest cost to produce.

    Reported as TOKENS, not euros, on purpose. Cache-read is ~93% of the figure and is billed at
    10% on the API and at nothing on a subscription, so a currency number here would be fiction.
    Tokens are an honest volume measure.

    Per-report values are sliced by when each report file was written, so they are MEASURED rather
    than divided. token_stats reports when that slicing failed to account for enough of the run and
    falls back to an even split; the label then says so instead of implying precision.

    Never fatal: a digest that ships without a cost line beats a digest that does not ship.
    """
    try:
        from datetime import datetime as _dt, timezone as _tz
        import token_stats as ts

        day = _dt.strptime(target_date, "%Y-%m-%d").date()
        times = {}
        paths = {}
        for r in rows:
            try:
                f = OUT_DIR / (report_filename(r) + ".md")
                if f.exists():
                    times[r.get("ticker", "?")] = _dt.fromtimestamp(f.stat().st_mtime, tz=_tz.utc)
                    paths[r.get("ticker", "?")] = f
            except Exception:
                continue

        # Persist the split. Stamping a report REWRITES it, which moves its mtime -- and mtime is
        # exactly what the slicing uses. Recomputing on a re-send therefore collapses every report
        # into whichever one now sorts first (observed: CTAS jumped 22.6M -> the full 33.4M). So the
        # split is computed once per day and reused verbatim thereafter.
        cache = OUT_DIR / ('_run_cost_' + target_date + '.json')
        rc = None
        if cache.exists():
            try:
                rc = json.loads(cache.read_text(encoding='utf-8'))
            except Exception:
                rc = None
        if rc is None:
            rc = ts.run_cost(day, times)
            try:
                cache.write_text(json.dumps(rc, indent=2), encoding='utf-8')
            except OSError as e:
                log('could not cache run cost: ' + str(e))
        wk = ts.weekly_share(7)
        if not rc["total"]:
            return "", ""

        note = ("measured per report" if rc.get("per_report_exact")
                else "run total split evenly - per-report timing inconclusive")
        ordered = sorted(rc["per_report"].items(), key=lambda kv: -kv[1])
        per_html = "".join(
            "<li><b>" + html.escape(str(k)) + "</b> - " + ts.fmt(v) + "</li>" for k, v in ordered)
        h = (
            '<hr><p style="font-size:12px;color:#888;">'
            "<b>Run cost</b> - " + ts.fmt(rc["total"]) + " tokens for this run ("
            + html.escape(note) + ")."
            '<ul style="margin:6px 0;padding-left:18px;">' + per_html + "</ul>"
            "Finance skills used <b>" + format(wk["pct"], ".1f") + "%</b> of all Claude Code in "
            "the last " + str(wk["days"]) + " days (" + ts.fmt(wk["finance"]) + " of "
            + ts.fmt(wk["total"]) + ")."
            '<br><span style="font-size:11px;">Tokens = input + output + cache. Cache-read is '
            "~93% of it, so this is a volume measure, not a bill.</span></p>")

        # Stamp the reports themselves, so a report read on its own still carries its cost.
        try:
            stamp_reports_with_cost(paths, rc, wk)
        except Exception as e:  # noqa: BLE001
            log('report cost stamping skipped (' + type(e).__name__ + ': ' + str(e) + ')')

        per_text = "\n".join("  " + str(k) + ": " + ts.fmt(v) for k, v in ordered)
        t = ("\nRUN COST\n--------\n" + ts.fmt(rc["total"]) + " tokens for this run ("
             + note + ").\n" + per_text + "\n"
             + "Finance skills used " + format(wk["pct"], ".1f") + "% of all Claude Code in the "
             "last " + str(wk["days"]) + " days (" + ts.fmt(wk["finance"]) + " of "
             + ts.fmt(wk["total"]) + ").\n")
        return h, t
    except Exception as e:  # noqa: BLE001
        log("run cost block skipped (" + type(e).__name__ + ": " + str(e) + ")")
        return "", ""


def attribution_text() -> str:
    return f"Analysis written by {ATTRIBUTION_MODEL} · {ATTRIBUTION_OWNER} · host: {run_host()}"

# v4 Phase E — price-triggered watch-list, wired into this digest.
WATCHLIST = OUT_DIR / "_watchlist.csv"
LIVE_PRICES = OUT_DIR / "_live_prices.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts dir (watchlist.py)
try:
    from watchlist import distance_to_target_pct, load_watchlist  # noqa: E402
except Exception as _wl_exc:  # never let a watch-list import break the digest
    load_watchlist = None
    distance_to_target_pct = None

# "Buy today" lead section (selection logic lives in buy_list.py, rendering here).
try:
    import buy_list  # noqa: E402
except Exception as _bl_exc:  # never let it break the digest
    buy_list = None


def regenerate_dashboard() -> None:
    """Regenerate _dashboard.html before sending so the attachment is fresh.
    Non-fatal if it fails — email still goes out without the attachment."""
    try:
        # Timeout must exceed build_dashboard's inner live-price fetch (180s),
        # otherwise slow yfinance days kill the regen and the email attaches a
        # stale dashboard.
        result = subprocess.run(
            [sys.executable, str(BUILD_DASHBOARD)],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            log(f"dashboard regenerated ({DASHBOARD.stat().st_size} bytes)")
        else:
            log(f"dashboard regen FAIL (non-fatal): rc={result.returncode}")
            log(result.stderr[-500:] if result.stderr else "(no stderr)")
    except Exception as e:
        log(f"dashboard regen EXC (non-fatal): {type(e).__name__}: {e}")


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def obsidian_link(filename: str) -> str:
    """obsidian:// URI for a note under OUT_REL. `filename` carries no extension and
    may include subdirectories (`_industry/semiconductors`), which is how wikilink
    targets inside the reports address the cached macro/industry notes."""
    import urllib.parse
    path = f"{OUT_REL}/{filename}.md"
    return f"obsidian://open?vault=BD_Obsidian&file={urllib.parse.quote(path)}"


def verdict_style(verdict: str, score: float) -> tuple[str, str, str, str]:
    """Return (emoji, subject_tag, label, color). emoji only used in HTML body, never in subject."""
    v = (verdict or "").lower()
    if v == "great" or score >= 9.0:
        return "🟢🟢", "GREAT", "GREAT BUY", "#0a8f0a"
    if v == "invest" or score >= 7.5:
        return "🟢", "BUY", "GOOD BUY", "#2ca02c"
    if v == "review" or score >= 6.0:
        return "🟡", "WATCH", "WATCH", "#f7c948"
    if v == "fair" or score >= 4.0:
        return "🟠", "FAIR", "FAIR", "#e8890b"
    return "🔴", "SKIP", "DO NOT BUY", "#d62728"


def report_filename(row: dict) -> str:
    """File naming convention: screens use 'screen' suffix; deep mode uses the verdict."""
    mode = (row.get("mode", "") or "").lower()
    suffix = "screen" if mode == "screen" else (row.get("verdict", "") or "screen")
    return f"{row['date']}_{row['ticker']}_{suffix}"


def extract_dashboard_bundle() -> dict | None:
    """Read the just-built _dashboard.html and pull the bundle JSON out of the
    `<script id="data" type="application/json">...</script>` block. Returns None
    if the dashboard hasn't been built or the block can't be parsed."""
    if not DASHBOARD.exists():
        return None
    try:
        import re
        src = DASHBOARD.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'<script id="data" type="application/json">(.*?)</script>',
                      src, re.DOTALL)
        if not m:
            return None
        import json as _json
        return _json.loads(m.group(1))
    except Exception as exc:
        log(f"dashboard bundle parse FAIL: {type(exc).__name__}: {exc}")
        return None


def latest_per_company(reports: list[dict]) -> list[dict]:
    """One row per company — the newest evaluation, across every listing.

    Applied once at the top of the inline dashboard so KPIs, top scores and the
    shortlist all count the same set. Before this, "Top scores" ranked raw report
    rows, so a name evaluated three times could take three of the five slots
    (ADBE 8.86 / 8.66 / 8.51) and TSMC could appear as both TSM and 2330.TW.
    """
    def _rank(r: dict) -> tuple:
        return (r.get("date") or "", 1 if r.get("mode") == "deep" else 0)

    try:
        import listings
        key = listings.company_key
    except Exception:  # a digest must go out even if identity resolution is broken
        def key(t):  # noqa: E306
            return t

    best: dict[str, dict] = {}
    for r in reports:
        ck = key(r.get("ticker") or "")
        if ck not in best or _rank(r) > _rank(best[ck]):
            best[ck] = r
    return list(best.values())


def build_dashboard_inline_html(bundle: dict, target_date: str) -> str:
    """Render a static (no-JS) dashboard summary that mail clients (Gmail, Yahoo)
    will display correctly inline. Mirrors the interactive dashboard's structure
    — KPI tiles, top-scores table, active shortlist, bear triggers, prefilter —
    but as plain HTML tables so it survives script-stripping."""
    reports = bundle.get("reports", []) or []
    bear = bundle.get("bear_triggers", []) or []
    prefilter = bundle.get("prefilter", {}) or {}
    today = bundle.get("today") or target_date

    # KPIs
    reports = latest_per_company(reports)
    total = len(reports)
    shortlist = [r for r in reports
                 if (r.get("score") or 0) >= 7.5 and (r.get("days_left") or 0) > 0]
    flagged = [r for r in reports if r.get("mgmt_flag")]
    deep_count = sum(1 for r in reports if r.get("mode") == "deep")
    screen_count = sum(1 for r in reports if r.get("mode") == "screen")
    pf_pass = (prefilter.get("results") or {}).get("pass")
    pf_universe = prefilter.get("universe_size")

    def _kpi(label: str, value: str, color: str = "#1f77b4") -> str:
        return (
            f"<td style='padding:10px 14px;border:1px solid #e0e0e0;background:#fff;"
            f"border-radius:6px;text-align:center;min-width:120px;'>"
            f"<div style='font-size:24px;font-weight:bold;color:{color}'>{value}</div>"
            f"<div style='font-size:11px;color:#666;text-transform:uppercase;letter-spacing:0.5px;'>{label}</div>"
            f"</td>"
        )

    kpis = (
        f"<table style='border-collapse:separate;border-spacing:8px;margin:0 auto 20px;'><tr>"
        f"{_kpi('Total reports', str(total))}"
        f"{_kpi('Active shortlist', str(len(shortlist)), '#0a8f0a')}"
        f"{_kpi('Mgmt flagged', str(len(flagged)), '#d62728')}"
        f"{_kpi('Deep / Screen', f'{deep_count}/{screen_count}')}"
        f"{_kpi('Prefilter pass', f'{pf_pass}/{pf_universe}' if pf_pass is not None else 'n/a')}"
        f"</tr></table>"
    )

    # Top 5 by score
    top5 = sorted([r for r in reports if r.get("score") is not None],
                  key=lambda r: r["score"], reverse=True)[:5]
    top_rows = []
    for r in top5:
        emoji, _t, label, color = verdict_style(r.get("verdict", ""), r.get("score") or 0)
        top_rows.append(
            f"<tr>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;'>{emoji} <b>{html.escape(r['ticker'])}</b></td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;color:{color};font-weight:bold;'>{r['score']:.2f}/10</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;color:{color};'>{html.escape(label)}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;font-size:12px;color:#666;'>{html.escape(r.get('sector') or '')}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;font-size:12px;color:#666;'>{r.get('date','')}</td>"
            f"</tr>"
        )
    top_table = (
        f"<h3 style='margin:18px 0 6px;'>Top scores</h3>"
        f"<table style='border-collapse:collapse;width:100%;font-size:13px;'>"
        f"<thead><tr style='background:#f0f0f0;'>"
        f"<th style='padding:8px 10px;text-align:left;'>Ticker</th>"
        f"<th style='padding:8px 10px;text-align:left;'>Score</th>"
        f"<th style='padding:8px 10px;text-align:left;'>Verdict</th>"
        f"<th style='padding:8px 10px;text-align:left;'>Sector</th>"
        f"<th style='padding:8px 10px;text-align:left;'>Date</th>"
        f"</tr></thead><tbody>{''.join(top_rows) or '<tr><td colspan=5>No reports.</td></tr>'}</tbody></table>"
    )

    # Active shortlist
    sl_rows = []
    for r in sorted(shortlist, key=lambda r: r.get("score") or 0, reverse=True):
        _e, _t, _l, color = verdict_style(r.get("verdict", ""), r.get("score") or 0)
        sl_rows.append(
            f"<tr>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;'><b>{html.escape(r['ticker'])}</b></td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;color:{color};font-weight:bold;'>{r['score']:.2f}</td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;font-size:12px;color:#666;'>{r.get('days_left',0)}d left</td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;font-size:12px;'>{html.escape(strip_md(r.get('thesis'))[:140])}</td>"
            f"</tr>"
        )
    sl_block = (
        f"<h3 style='margin:18px 0 6px;'>Active shortlist ({len(shortlist)})</h3>"
        + (f"<table style='border-collapse:collapse;width:100%;font-size:13px;'><tbody>{''.join(sl_rows)}</tbody></table>"
           if sl_rows else "<p style='font-size:13px;color:#888;'>No active shortlist entries.</p>")
    )

    # Bear triggers (latest 5)
    br_rows = []
    for b in sorted(bear, key=lambda b: b.get("date") or "", reverse=True)[:5]:
        br_rows.append(
            f"<tr>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;vertical-align:top;'><b>{html.escape(b.get('ticker',''))}</b></td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;font-size:12px;color:#888;vertical-align:top;'>{b.get('date','')}</td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;font-size:12px;'>{html.escape(b.get('trigger',''))}</td>"
            f"</tr>"
        )
    br_block = (
        f"<h3 style='margin:18px 0 6px;'>Recent bear triggers</h3>"
        + (f"<table style='border-collapse:collapse;width:100%;'><tbody>{''.join(br_rows)}</tbody></table>"
           if br_rows else "<p style='font-size:13px;color:#888;'>No bear triggers yet.</p>")
    )

    # Prefilter snapshot
    pf_block = ""
    if prefilter:
        pf_ts = prefilter.get("timestamp", "")[:10]
        pf_block = (
            f"<h3 style='margin:18px 0 6px;'>Prefilter snapshot ({pf_ts})</h3>"
            f"<p style='font-size:13px;color:#555;margin:4px 0;'>"
            f"Pool: <b>{pf_pass}</b> pass / <b>{pf_universe}</b> universe · "
            f"errors: {(prefilter.get('results') or {}).get('error', 0)}</p>"
        )

    return (
        f"<section style='border:1px solid #d0d0d0;border-radius:8px;padding:18px 22px;"
        f"margin:0 0 25px;background:linear-gradient(180deg,#f8f8fa 0%,#ffffff 100%);'>"
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;'>"
        f"<h2 style='margin:0;color:#1f77b4;'>📊 StocksDaily Dashboard</h2>"
        f"<span style='font-size:11px;color:#888;'>generated {today} · interactive copy attached</span>"
        f"</div>"
        f"{kpis}{top_table}{sl_block}{br_block}{pf_block}"
        f"</section>"
    )


def read_growth_rows(target_date: str) -> list[dict]:
    """Rows from _growth_log.csv for `target_date`, best score first; [] on any problem."""
    try:
        if not GROWTH_LOG.exists() or GROWTH_LOG.stat().st_size == 0:
            return []
        with GROWTH_LOG.open("r", encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r.get("date") == target_date]
        return sorted(rows, key=lambda r: float(r.get("growth_composite") or 0), reverse=True)
    except Exception as exc:
        log(f"growth log read SKIP (non-fatal): {type(exc).__name__}: {exc}")
        return []


def build_growth_section_html(target_date: str) -> str:
    """Phase 7 — render a Growth-lens section from _growth_log.csv for `target_date`.

    GUARDED: returns "" (no-op) when the growth log is absent, unreadable, or has
    no rows for the date. This guarantees the daily 17:00 email is unaffected when
    the growth skill hasn't run. Pure read of a separate file — never touches the
    daily _log.csv.
    """
    try:
        rows = read_growth_rows(target_date)
        if not rows:
            return ""
        body_rows = []
        for r in rows:
            score = float(r.get("growth_composite") or 0)
            color = "#7c3aed" if score >= 8.0 else ("#2ca02c" if score >= 6.5 else "#e8890b")
            body_rows.append(
                f"<tr>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;'><b>{html.escape(r.get('ticker',''))}</b></td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;color:{color};font-weight:bold;'>{score:.2f}/10</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;'>{html.escape((r.get('verdict','') or '').upper())}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;'>{html.escape(str(r.get('rule_of_40','')))}%</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;'>{html.escape(str(r.get('cash_runway_months','')))}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;font-size:12px;color:#666;'>{html.escape(r.get('sector','') or '')}</td>"
                f"</tr>"
            )
        return (
            f"<section style='border:1px solid #d8c8f0;border-radius:8px;padding:14px 18px;"
            f"margin:25px 0;background:#faf7ff;'>"
            f"<h2 style='margin:0 0 8px;color:#7c3aed;'>🚀 Growth lens — {target_date}</h2>"
            f"<p style='font-size:12px;color:#777;margin:0 0 8px;'>Parallel growth model "
            f"(Rule of 40, runway, NRR proxy). Gate-5 bypassed by design.</p>"
            f"<table style='border-collapse:collapse;width:100%;font-size:13px;'>"
            f"<thead><tr style='background:#f0e8fb;'>"
            f"<th style='padding:8px 10px;text-align:left;'>Ticker</th>"
            f"<th style='padding:8px 10px;text-align:left;'>Growth score</th>"
            f"<th style='padding:8px 10px;text-align:left;'>Verdict</th>"
            f"<th style='padding:8px 10px;text-align:left;'>Rule of 40</th>"
            f"<th style='padding:8px 10px;text-align:left;'>Runway</th>"
            f"<th style='padding:8px 10px;text-align:left;'>Sector</th>"
            f"</tr></thead><tbody>{''.join(body_rows)}</tbody></table></section>"
        )
    except Exception as exc:  # never let the growth section break the email
        log(f"growth section SKIP (non-fatal): {type(exc).__name__}: {exc}")
        return ""


def fetch_live_prices_for(tickers: list[str]) -> dict:
    """Live price per ticker (watch-list and buy-list). Reads the fresh _live_prices.json first
    (written by regenerate_dashboard → live_prices.py), then best-effort yfinance
    for any ticker missing there (watch-list names usually aren't dashboard
    technical-read tickers, so this fallback is the common path). Degrades to a
    partial/empty map — never raises; requires ambient Python for the yfinance leg."""
    prices: dict[str, float] = {}
    try:
        data = json.loads(LIVE_PRICES.read_text(encoding="utf-8"))
        for t, p in (data.get("prices") or {}).items():
            if isinstance(p, (int, float)):
                prices[t] = float(p)
    except Exception:
        pass
    missing = [t for t in tickers if t and t not in prices]
    if missing:
        try:
            import yfinance as yf
            from live_prices import fetch_price
            for t in missing:
                px = fetch_price(yf.Ticker(t))
                if px is not None:
                    prices[t] = px
        except Exception as exc:
            log(f"watch-list live-price fetch SKIP (non-fatal): {type(exc).__name__}: {exc}")
    return prices


def build_watchlist_html(rows: list[dict], live_prices: dict) -> tuple[str, int]:
    """(html, n_triggered). A red/bold '⭐ Watch-list triggered' callout for names
    at/below their fair-low target, plus a quiet status table (distance-to-target).
    Inline styles only (mail clients strip <style>/SVG). ("", 0) when the list is
    empty. Never raises."""
    if not rows:
        return "", 0
    triggered, status = [], []
    for r in rows:
        tkr = (r.get("ticker") or "").strip()
        try:
            target = float(r.get("target"))
        except (TypeError, ValueError):
            continue
        live = live_prices.get(tkr)
        dist = distance_to_target_pct(live, target) if distance_to_target_pct else None
        row = {"ticker": tkr, "target": target, "live": live, "dist": dist,
               "ccy": r.get("currency") or "", "thesis": r.get("thesis") or ""}
        (triggered if (live is not None and live <= target) else status).append(row)

    parts = []
    if triggered:
        items = "".join(
            f"<li style='margin:4px 0;'><b>{html.escape(t['ticker'])}</b> — "
            f"live {t['live']:,.2f} {html.escape(t['ccy'])} ≤ target {t['target']:,.2f}"
            f"{(' (%+.1f%%)' % t['dist']) if t['dist'] is not None else ''} · "
            f"<span style='color:#444;'>{html.escape(t['thesis'])}</span></li>"
            for t in triggered
        )
        parts.append(
            f"<div style='border:2px solid #d62728;border-radius:8px;padding:12px 16px;"
            f"margin:18px 0;background:#fff5f5;'>"
            f"<div style='color:#d62728;font-weight:bold;font-size:15px;margin-bottom:6px;'>"
            f"⭐ Watch-list triggered ({len(triggered)}) — quality name(s) at buy target</div>"
            f"<ul style='margin:0;padding-left:20px;font-size:13px;'>{items}</ul></div>"
        )
    if status:
        body = "".join(
            f"<tr>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;'><b>{html.escape(s['ticker'])}</b></td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;'>{s['target']:,.2f} {html.escape(s['ccy'])}</td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;'>"
            f"{('%.2f' % s['live']) if s['live'] is not None else 'n/a'}</td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;color:#888;'>"
            f"{('%+.1f%%' % s['dist']) if s['dist'] is not None else '—'}</td>"
            f"</tr>"
            for s in status
        )
        parts.append(
            f"<details style='margin:10px 0;'><summary style='cursor:pointer;color:#666;font-size:13px;'>"
            f"Watch-list status ({len(status)} not yet triggered)</summary>"
            f"<table style='border-collapse:collapse;font-size:12px;margin-top:6px;'>"
            f"<thead><tr style='background:#f6f6f6;'>"
            f"<th style='padding:6px 10px;text-align:left;'>Ticker</th>"
            f"<th style='padding:6px 10px;text-align:left;'>Target (fair-low)</th>"
            f"<th style='padding:6px 10px;text-align:left;'>Live</th>"
            f"<th style='padding:6px 10px;text-align:left;'>Distance</th>"
            f"</tr></thead><tbody>{body}</tbody></table></details>"
        )
    return "".join(parts), len(triggered)


def build_buy_today_html(result: dict) -> str:
    """The lead section: what is buyable today, best recommendation first, each with a
    max entry price. Deterministic — see buy_list.select_buys for the selection rule.

    Deliberately renders an explicit empty state rather than disappearing: "no section"
    and "nothing to buy" are different messages, and only one of them is true on a
    given day. Inline styles only (mail clients strip <style>)."""
    buys = (result or {}).get("buys") or []
    floor = (result or {}).get("floor", buy_list.BUY_FLOOR if buy_list else 7.5)
    n_above = len((result or {}).get("above_entry") or [])
    n_nocap = len((result or {}).get("no_max_entry") or [])

    excluded_bits = []
    if n_above:
        excluded_bits.append(f"{n_above} above max entry")
    if n_nocap:
        excluded_bits.append(f"{n_nocap} without a stateable max entry")
    excluded = (" · excluded: " + ", ".join(excluded_bits)) if excluded_bits else ""
    footnote = (
        f"<div style='font-size:11px;color:#777;margin-top:8px;'>"
        f"Floor is the <b>invest</b> band (composite ≥ {floor:g}); quality names at "
        f"7.0–{floor - 0.1:.1f} that are merely too expensive sit in the watch-list block, not here. "
        f"Max entry = the 5-model fair-value blend, or the technical entry zone when a report "
        f"carries no intrinsic value.{excluded}</div>"
    )

    if not buys:
        return (
            f"<section style='border:1px solid #d8d8d8;border-radius:8px;padding:12px 16px;"
            f"margin:0 0 18px;background:#fbfbfb;'>"
            f"<div style='font-weight:bold;font-size:15px;color:#555;'>🛒 Buy today — nothing</div>"
            f"<div style='font-size:13px;color:#555;margin-top:4px;'>No evaluated name is both "
            f"above the quality floor and at or below its max entry price. Patience is a position.</div>"
            f"{footnote}</section>"
        )

    rows = []
    for i, b in enumerate(buys, 1):
        ccy = html.escape(b["currency"])
        tags = []
        if b["held"]:
            tags.append(_chip("ADD to position", "#0a6640", "#e3f4ec"))
        else:
            tags.append(_chip("NEW position", "#1f4e79", "#e8f0fa"))
        if b["thin"]:
            tags.append(_chip("thin margin", "#8a6d00", "#fdf3d7"))
        if b["go_no_go"] in ("NO-GO", "NOGO", "NO_GO"):
            tags.append(_chip("timing NO-GO — scale in", "#8a6d00", "#fdf3d7"))
        if b["price_source"] == "eval":
            tags.append(_chip("price at eval, not live", "#a03000", "#fdeee4"))
        head_color = "#0a8f0a" if not b["thin"] else "#8a6d00"
        rows.append(
            f"<tr>"
            f"<td style='padding:7px 8px;border-bottom:1px solid #e8e8e8;color:#999;font-size:12px;'>{i}</td>"
            f"<td style='padding:7px 8px;border-bottom:1px solid #e8e8e8;'>"
            f"<b>{html.escape(b['ticker'])}</b>"
            f"<div style='font-size:11px;color:#777;'>{html.escape(b.get('company') or '')}</div></td>"
            f"<td style='padding:7px 8px;border-bottom:1px solid #e8e8e8;font-weight:bold;color:#0a8f0a;'>"
            f"{b['score']:.2f}<span style='font-weight:normal;color:#777;font-size:11px;'> "
            f"{html.escape((b.get('verdict') or '').upper())}</span></td>"
            f"<td style='padding:7px 8px;border-bottom:1px solid #e8e8e8;'>{b['price']:,.2f} {ccy}</td>"
            f"<td style='padding:7px 8px;border-bottom:1px solid #e8e8e8;font-weight:bold;'>"
            f"≤ {b['max_entry']:,.2f} {ccy}"
            f"<div style='font-size:10px;color:#888;font-weight:normal;'>{html.escape(b['max_entry_basis'])}</div></td>"
            f"<td style='padding:7px 8px;border-bottom:1px solid #e8e8e8;color:{head_color};font-weight:bold;'>"
            f"+{b['headroom_pct']:.1f}%</td>"
            f"<td style='padding:7px 8px;border-bottom:1px solid #e8e8e8;'>{''.join(tags)}</td>"
            f"</tr>"
        )

    return (
        f"<section style='border:2px solid #0a8f0a;border-radius:8px;padding:14px 18px;"
        f"margin:0 0 20px;background:#f4fbf4;'>"
        f"<div style='font-weight:bold;font-size:16px;color:#0a8f0a;margin-bottom:2px;'>"
        f"🛒 Buy today ({len(buys)}) — best recommendation first</div>"
        f"<div style='font-size:12px;color:#666;margin-bottom:8px;'>"
        f"Do not pay above the max entry price. Order is by composite score, not conviction in the price.</div>"
        f"<table style='border-collapse:collapse;width:100%;font-size:13px;'>"
        f"<thead><tr style='background:#e6f4e6;'>"
        f"<th style='padding:7px 8px;text-align:left;width:22px;'>#</th>"
        f"<th style='padding:7px 8px;text-align:left;'>Ticker</th>"
        f"<th style='padding:7px 8px;text-align:left;'>Score</th>"
        f"<th style='padding:7px 8px;text-align:left;'>Price now</th>"
        f"<th style='padding:7px 8px;text-align:left;'>Max entry</th>"
        f"<th style='padding:7px 8px;text-align:left;'>Room</th>"
        f"<th style='padding:7px 8px;text-align:left;'>Notes</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f"{footnote}</section>"
    )


def build_buy_today_text(result: dict) -> str:
    """Plain-text twin of build_buy_today_html for the text/plain part."""
    buys = (result or {}).get("buys") or []
    if not buys:
        return ("BUY TODAY: nothing — no evaluated name is both above the quality floor "
                "and at or below its max entry price.\n\n")
    lines = [f"BUY TODAY ({len(buys)}) — best recommendation first", "-" * 46]
    for i, b in enumerate(buys, 1):
        flags = ["ADD" if b["held"] else "NEW"]
        if b["thin"]:
            flags.append("thin margin")
        if b["go_no_go"] in ("NO-GO", "NOGO", "NO_GO"):
            flags.append("timing NO-GO")
        if b["price_source"] == "eval":
            flags.append("price at eval")
        lines.append(
            f"{i}. {b['ticker']} — {b['score']:.2f} {(b.get('verdict') or '').upper()} · "
            f"now {b['price']:,.2f} {b['currency']} · max entry {b['max_entry']:,.2f} "
            f"({b['max_entry_basis']}) · room +{b['headroom_pct']:.1f}% · {', '.join(flags)}"
        )
    lines.append("Do not pay above the max entry price.")
    return "\n".join(lines) + "\n\n"


_MD_INLINE_RE = re.compile(r"\*+|__|`")  # emphasis markers; literal * is not used in thesis text


def strip_md(text: str | None) -> str:
    """Drop inline markdown emphasis markers from text snippets rendered as plain
    HTML (cards / shortlist rows), where **bold** would otherwise show literally."""
    return _MD_INLINE_RE.sub("", text) if text else ""


def bundle_meta(bundle: dict | None, row: dict) -> dict:
    """Slim-report dict from the dashboard bundle matching this _log.csv row
    (ticker + date). Empty dict when the bundle or the report is missing, so
    cards degrade to the log-only fields."""
    if not bundle:
        return {}
    for r in bundle.get("reports", []) or []:
        if r.get("ticker") == row.get("ticker") and r.get("date") == row.get("date"):
            return r
    return {}


def _chip(text: str, fg: str, bg: str) -> str:
    return (
        f"<span style='display:inline-block;padding:2px 8px;border-radius:10px;"
        f"font-size:11px;font-weight:bold;color:{fg};background:{bg};margin-right:6px;'>{text}</span>"
    )


def build_card_html(row: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    score = float(row.get("score", 0) or 0)
    emoji, _tag, label, color = verdict_style(row.get("verdict", ""), score)
    fn = report_filename(row)
    link = obsidian_link(fn)
    company = html.escape(meta.get("company") or "")
    company_html = f" <span style='font-weight:normal;color:#555;'>{company}</span>" if company else ""

    # Chips: fair-price upside, technical GO/NO-GO, management flag
    chips = []
    fair, price = meta.get("fair_price"), meta.get("price")
    if fair and price:
        upside = (fair / price - 1) * 100
        chips.append(_chip(
            f"Fair {fair:,.0f} {meta.get('currency') or ''} ({upside:+.0f}%)".strip(),
            "#0a6640" if upside >= 0 else "#a03000",
            "#e3f4ec" if upside >= 0 else "#fdeee4",
        ))
    gng = (meta.get("go_no_go") or "").upper()
    if gng == "GO":
        chips.append(_chip(f"GO · entry {html.escape(meta.get('entry_zone') or '—')}", "#0a6640", "#e3f4ec"))
    elif gng in ("NO-GO", "NOGO", "NO_GO"):
        chips.append(_chip("NO-GO — wait", "#8a6d00", "#fdf3d7"))
    if meta.get("mgmt_flag"):
        chips.append(_chip("⚠ mgmt flag", "#a03000", "#fdeee4"))
    # Phase-H news sentiment chip (overlay — not scored)
    sent = meta.get("news_sentiment")
    if sent is not None:
        lbl = (meta.get("news_label") or "").strip()
        if sent >= 0.15:
            em, fg, bg = "📈", "#0a6640", "#e3f4ec"
        elif sent <= -0.15:
            em, fg, bg = "📉", "#a03000", "#fdeee4"
        else:
            em, fg, bg = "➖", "#555555", "#eeeeee"
        chips.append(_chip(f"{em} news {sent:+.2f}" + (f" {lbl}" if lbl else ""), fg, bg))
    chips_html = f"<div style='margin:2px 0 6px;'>{''.join(chips)}</div>" if chips else ""

    def _line(label_txt: str, value: str | None) -> str:
        if not value:
            return ""
        return (
            f"<div style='font-size:13px;color:#333;margin:2px 0;'>"
            f"<b>{label_txt}:</b> {html.escape(strip_md(value)[:220])}</div>"
        )

    return f"""
    <div style="border-left: 4px solid {color}; padding: 12px 16px; margin: 12px 0; background: #fafafa; border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,0.06);">
      <div style="font-size: 17px; font-weight: bold; color: {color}; margin-bottom: 3px;">
        {emoji} {html.escape(row['ticker'])}{company_html} — {score:.1f}/10 — {label}
      </div>
      <div style="font-size: 12px; color: #777; margin-bottom: 4px;">
        {row.get('mode','')} · round {row.get('round','')} · gates {row.get('gates_passed','')}/7 · {row.get('price_at_eval','')} {row.get('currency','')}
      </div>
      {chips_html}
      {_line('Thesis', meta.get('thesis'))}
      {_line('Action', meta.get('action'))}
      {'' if meta.get('thesis') else _line('Notes', row.get('notes'))}
      <div style="margin-top:6px;"><a href="{link}" style="color: #1f77b4; text-decoration: none;">Open report in Obsidian →</a></div>
    </div>
    """


def build_adviser_take_html(rows: list[dict], bundle: dict | None) -> str:
    """One deterministic lead paragraph in adviser voice — best idea of the day,
    or an honest 'nothing actionable' line. No LLM: composed from stored fields."""
    scored = [(float(r.get("score", 0) or 0), r) for r in rows]
    if not scored:
        return ""
    best_score, best = max(scored, key=lambda t: t[0])
    meta = bundle_meta(bundle, best)
    tick = html.escape(best.get("ticker", ""))
    if best_score >= 7.5:
        action = meta.get("action") or "review the full report before acting"
        body = (f"Strongest idea today: <b>{tick}</b> at <b>{best_score:.1f}/10</b>. "
                f"{html.escape(strip_md(meta.get('thesis'))[:180])} "
                f"Suggested next step: {html.escape(strip_md(action)[:160])}")
    elif best_score >= 6.0:
        body = (f"Nothing to buy today. <b>{tick}</b> is the best of the batch at "
                f"{best_score:.1f}/10 — a watchlist name, not an order. Patience is a position.")
    else:
        body = (f"No actionable ideas today — best was <b>{tick}</b> at {best_score:.1f}/10. "
                f"Capital stays where it is; the pipeline keeps screening.")
    return (
        f"<p style='font-size:14.5px;line-height:1.5;color:#222;background:#f2f7fd;"
        f"border-left:4px solid #1f77b4;border-radius:6px;padding:12px 16px;margin:0 0 20px;'>"
        f"💼 <b>Adviser's take</b> — {body}</p>"
    )


def _strip_frontmatter(md: str) -> str:
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end != -1:
            return md[end + 4 :].lstrip("\n")
    return md


# --- Obsidian-flavoured markdown -> email HTML -------------------------------
# python-markdown knows nothing about Obsidian's two vault-specific constructs,
# so both used to reach the inbox as literal source text:
#   [[_macro/2026-07-27|Full macro snapshot]]   ->  shown verbatim, not a link
#   > [!danger] data-quality: suspect            ->  blockquote reading "[!danger] ..."
# Both are rewritten here, ahead of the markdown pass.

_WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+?)(?:\|([^\[\]]*?))?\]\]")
_CALLOUT_START_RE = re.compile(r"^>\s*\[!([A-Za-z]+)\][+-]?\s*(.*)$")

# Obsidian callout type -> (accent, tinted background, emoji). Types are grouped
# the way Obsidian groups them, so aliases share one visual identity.
_CALLOUT_STYLES = {
    "note": ("#2563eb", "#eff5ff", "📝"),
    "abstract": ("#0891b2", "#ecfeff", "📋"),
    "summary": ("#0891b2", "#ecfeff", "📋"),
    "tldr": ("#0891b2", "#ecfeff", "⚡"),
    "info": ("#2563eb", "#eff5ff", "ℹ️"),
    "todo": ("#2563eb", "#eff5ff", "☑️"),
    "tip": ("#0d9488", "#f0fdfa", "💡"),
    "hint": ("#0d9488", "#f0fdfa", "💡"),
    "important": ("#0d9488", "#f0fdfa", "❗"),
    "success": ("#059669", "#ecfdf5", "✅"),
    "check": ("#059669", "#ecfdf5", "✅"),
    "done": ("#059669", "#ecfdf5", "✅"),
    "question": ("#d97706", "#fffbeb", "❓"),
    "help": ("#d97706", "#fffbeb", "❓"),
    "faq": ("#d97706", "#fffbeb", "❓"),
    "warning": ("#d97706", "#fffbeb", "⚠️"),
    "caution": ("#d97706", "#fffbeb", "⚠️"),
    "attention": ("#d97706", "#fffbeb", "⚠️"),
    "failure": ("#dc2626", "#fef2f2", "❌"),
    "fail": ("#dc2626", "#fef2f2", "❌"),
    "missing": ("#dc2626", "#fef2f2", "❌"),
    "danger": ("#dc2626", "#fef2f2", "🚨"),
    "error": ("#dc2626", "#fef2f2", "🚨"),
    "bug": ("#dc2626", "#fef2f2", "🐛"),
    "example": ("#7c3aed", "#f5f3ff", "🔬"),
    "quote": ("#64748b", "#f8fafc", "❝"),
    "cite": ("#64748b", "#f8fafc", "❝"),
}
_CALLOUT_DEFAULT = ("#64748b", "#f8fafc", "")


def wikilinks_to_html(text: str) -> str:
    """Rewrite `[[target]]` / `[[target|label]]` into obsidian:// anchors.

    `target` may address a sibling report (`2026-07-09_TSM_invest`) or a cached
    note in a subdirectory (`_industry/semiconductors`), optionally with a
    `#heading` suffix. Label defaults to the target's last path segment.
    """
    import urllib.parse

    def _sub(m: re.Match) -> str:
        target = (m.group(1) or "").strip()
        if not target:
            return m.group(0)
        label = (m.group(2) or "").strip() or target.split("/")[-1]
        file_part, _, anchor = target.partition("#")
        href = obsidian_link(file_part.strip())
        if anchor.strip():
            href += "%23" + urllib.parse.quote(anchor.strip())
        return (
            f'<a href="{href}" style="color:#2563eb;text-decoration:none;'
            f'border-bottom:1px dotted #93c5fd;">{html.escape(label)}</a>'
        )

    return _WIKILINK_RE.sub(_sub, text)


def _render_callout(ctype: str, title_md: str, body_lines: list[str]) -> str:
    accent, bg, emoji = _CALLOUT_STYLES.get(ctype.lower(), _CALLOUT_DEFAULT)
    lead = f"{emoji} " if emoji else ""
    title_html = _inline_markdown(title_md) if title_md else ctype.capitalize()
    body_html = ""
    body_md = "\n".join(body_lines).strip()
    if body_md:
        body_html = (
            f"<div style='margin-top:6px;font-size:13.5px;line-height:1.55;'>"
            f"{_block_markdown(body_md)}</div>"
        )
    return (
        f"<div style=\"border-left:4px solid {accent};background:{bg};"
        f"border-radius:6px;padding:10px 14px;margin:12px 0;\">"
        f"<div style='font-weight:600;color:{accent};font-size:13.5px;line-height:1.5;'>"
        f"{lead}{title_html}</div>{body_html}</div>"
    )


def callouts_to_html(text: str) -> tuple[str, dict[str, str]]:
    """Replace `> [!type]` callout blocks with placeholder tokens.

    Returns (text_with_placeholders, {token: html}). Tokens are substituted back
    after the markdown pass so python-markdown never sees — and never re-escapes
    or re-wraps — the generated HTML.
    """
    lines = text.split("\n")
    out: list[str] = []
    blocks: dict[str, str] = {}
    i = 0
    while i < len(lines):
        m = _CALLOUT_START_RE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        ctype, title = m.group(1), m.group(2)
        body: list[str] = []
        i += 1
        while i < len(lines) and lines[i].lstrip().startswith(">"):
            body.append(re.sub(r"^\s*>\s?", "", lines[i]))
            i += 1
        token = f"CALLOUTBLOCK{len(blocks)}CALLOUTBLOCK"
        blocks[token] = _render_callout(ctype, title, body)
        out.append("")
        out.append(token)
        out.append("")
    return "\n".join(out), blocks


def _inline_markdown(md: str) -> str:
    """Render a one-line fragment, stripped of the <p> wrapper markdown adds."""
    if _markdown is None:
        return html.escape(md)
    try:
        rendered = _markdown.markdown(md, extensions=["extra"]).strip()
    except Exception:
        return html.escape(md)
    if rendered.startswith("<p>") and rendered.endswith("</p>"):
        rendered = rendered[3:-4]
    return rendered


def _block_markdown(md: str) -> str:
    if _markdown is None:
        return html.escape(md).replace("\n", "<br>")
    try:
        return _markdown.markdown(md, extensions=["extra", "sane_lists", "tables", "fenced_code"])
    except Exception:
        return html.escape(md).replace("\n", "<br>")


def render_markdown_html(md: str) -> str:
    """Render markdown content to HTML for inline email embedding."""
    md_body = wikilinks_to_html(_strip_frontmatter(md))
    md_body, callout_blocks = callouts_to_html(md_body)
    if _markdown is not None:
        try:
            rendered = _markdown.markdown(
                md_body,
                extensions=["extra", "sane_lists", "tables", "fenced_code"],
            )
            for token, block_html in callout_blocks.items():
                # markdown wraps a bare token line in <p>...</p>; drop that wrapper
                # so the callout <div> is not nested inside a paragraph.
                rendered = rendered.replace(f"<p>{token}</p>", block_html).replace(token, block_html)
            return rendered
        except Exception:
            pass
    # Fallback: escape + preserve line breaks in a <pre> block
    plain = _strip_frontmatter(md)
    return f"<pre style='white-space:pre-wrap;font-family:monospace;font-size:12px;'>{html.escape(plain)}</pre>"


def load_report_markdown(row: dict, out_dir: Path = OUT_DIR) -> tuple[str, str]:
    """Return (filename, markdown_content). Empty content if file missing."""
    fn = report_filename(row)
    path = Path(out_dir) / f"{fn}.md"
    if not path.exists():
        return fn, ""
    try:
        return fn, path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        log(f"WARN: could not read {path}: {exc}")
        return fn, ""


def build_full_report_html(row: dict, out_dir: Path = OUT_DIR) -> str:
    """Render the full markdown report for one ticker as an HTML section.

    NOT in the digest body since v4.3 (E1) -- see build_cover_block_html for what replaced
    it and why. It survives as build_cover_block_html's fallback for reports rendered before
    the cover existed.

    `out_dir` is threaded through rather than read off the module constant: without it the
    fallback path silently read the LIVE report directory while its caller was pointed at a
    fixture, which is exactly how a fallback ends up untested.
    """
    fn, md = load_report_markdown(row, out_dir)
    score = float(row.get("score", 0) or 0)
    _emoji, _tag, _label, color = verdict_style(row.get("verdict", ""), score)
    link = obsidian_link(fn)
    header = (
        f"<h2 style='color:{color};border-bottom:2px solid {color};padding-bottom:4px;"
        f"margin-top:30px;'>{html.escape(row['ticker'])} — full report</h2>"
        f"<p style='font-size:12px;color:#888;margin:0 0 10px 0;'>"
        f"<a href='{link}' style='color:#1f77b4;'>Open in Obsidian</a> · source: {html.escape(fn)}.md</p>"
    )
    if not md:
        body = "<p style='color:#a00;'>[report file not found]</p>"
    else:
        body = render_markdown_html(md)
    return (
        f"<section style='margin:20px 0;padding:15px;border:1px solid #e0e0e0;"
        f"border-radius:6px;background:#fff;'>{header}{body}</section>"
    )


# --- The cover, not the whole report (v4.3 E1/E2) ----------------------------
#
# MEASURED 2026-08-17 on the canonical 1-deep + 2-screen day (2026-08-14): the digest body
# was 136,413 B, and the three inlined markdown reports were 100,989 B of it -- 74%. Gmail
# clips a message above ~102,400 B behind "View entire message", so the single largest
# thing in the mail was also the thing being truncated. Worse, it was the LEAST useful
# rendering of it: markdown inlined through python-markdown loses the cover, the charts,
# the Sankey, the SWOT and the star ratings, all of which exist only in the .html that
# already travels as an attachment.
#
# So the body now carries each report's ONE-PAGE COVER -- the verdict band plus the six
# key-financials groups, ~3.9 KB per ticker -- and the deep name's Sankey as a real image.
# Dropping the markdown alone takes the body to ~35 KB; the covers put it near 47 KB, still
# less than half the clip. The inline dashboard (14 KB) therefore STAYS: my own E1 proposal
# had it removed to buy headroom that the measurement says is not needed, and removing
# content for no benefit is not a saving.
COVER_RE = re.compile(r'<section class="cover" id="cover">.*?</section>', re.S)

# Inline styles keyed by the cover's own class names. The report's stylesheet is NOT in the
# mail, and it could not be: report_template.html lays the cover out with CSS grid, which
# Outlook renders with the Word engine and ignores completely. Everything here is inline and
# block-level, so it survives Gmail, Yahoo and Outlook; `inline-block` is the only
# progressive bit, and where it is ignored the groups simply stack vertically.
COVER_STYLES = {
    "cover": ("margin:16px 0;padding:14px 16px;border:1px solid #d5e3ef;"
              "border-radius:6px;background:#fbfdff;"),
    "cv-verb": "font-size:20px;font-weight:700;letter-spacing:.5px;color:#1f77b4;",
    "cv-tk": "font-size:15px;font-weight:600;color:#222;margin:2px 0 10px 0;",
    "sub": "font-weight:400;color:#777;font-size:12px;",
    "cv-facts": "margin:0 0 10px 0;",
    "cv-fact": ("display:inline-block;vertical-align:top;min-width:145px;"
                "margin:0 14px 8px 0;"),
    "k": "font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:#8a8a8a;",
    "v": "font-size:14px;font-weight:600;color:#222;",
    "cv-stars": "font-size:12px;color:#555;margin:0 0 10px 0;",
    "cv-line": ("font-size:13px;line-height:1.5;margin:6px 0;padding:6px 10px;"
                "border-left:3px solid #ccc;background:#ffffff;"),
    "cv-bull": "border-left-color:#2ca02c;",
    "cv-bear": "border-left-color:#d62728;",
    "cv-h": "font-size:13px;color:#1f77b4;margin:14px 0 6px 0;",
    "cv-grp": ("display:inline-block;vertical-align:top;min-width:165px;"
               "margin:0 18px 10px 0;"),
    "cv-m": "font-size:12px;color:#444;",
}

_CLASS_TAG_RE = re.compile(r'<(\w+)((?:[^>]*?)\bclass="([^"]*)"(?:[^>]*?))>')


def inline_cover_styles(fragment: str, styles: dict[str, str] | None = None) -> str:
    """Add `style="..."` to every element whose class appears in `styles`.

    Classes are applied in the order they are written on the element, so
    `class="cv-line cv-bear"` puts the bear border-colour after the base rule and wins --
    the same cascade the report's own stylesheet relies on. An element already carrying a
    style attribute is left alone rather than having two `style=`s emitted.
    """
    table = COVER_STYLES if styles is None else styles

    def repl(m: re.Match) -> str:
        tag, attrs, classes = m.group(1), m.group(2), m.group(3)
        if "style=" in attrs:
            return m.group(0)
        css = "".join(table[c] for c in classes.split() if c in table)
        if not css:
            return m.group(0)
        return f'<{tag}{attrs} style="{css}">'

    return _CLASS_TAG_RE.sub(repl, fragment)


def report_cover_html(row: dict, out_dir: Path = OUT_DIR) -> str:
    """The `<section class="cover">` block from this row's rendered report, email-styled.

    "" when the report HTML is missing or predates the cover (v4.3 wave 2.4, 2026-08-15) --
    the caller then falls back, rather than this printing an apology into the digest.
    """
    path = Path(out_dir) / f"{report_filename(row)}.html"
    if not path.exists():
        log(f"cover: {path.name} not found")
        return ""
    try:
        m = COVER_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        log(f"cover: {path.name} unreadable (non-fatal): {exc}")
        return ""
    if not m:
        log(f"cover: no cover section in {path.name} (pre-v4.3 report?)")
        return ""
    return inline_cover_styles(m.group(0))


def sankey_img_html(row: dict, out_dir: Path = OUT_DIR) -> str:
    """An <img> for this row's money-engine Sankey, or "" when there is no PNG.

    E2: the markdown carries the diagram as a ```mermaid `sankey-beta` fence, and
    python-markdown renders a fence as literal `<pre><code>` -- so what reached the inbox
    was the diagram's SOURCE CODE. mermaid_render.py already writes the PNG for the HTML
    report, so the mail can simply point at it; inline_image_refs() rewrites this src to a
    cid: reference and attaches the bytes, exactly as it does for the charts.
    """
    png = Path(out_dir) / "IMG" / f"{row.get('date', '')}_{row.get('ticker', '')}_sankey.png"
    if not png.exists():
        return ""
    return (f'<h3 style="font-size:13px;color:#1f77b4;margin:14px 0 6px 0;">Money engine</h3>'
            f'<img src="{html.escape(png.as_posix())}" alt="money engine (Sankey)" '
            f'style="max-width:100%;height:auto;">')


def build_cover_block_html(row: dict, out_dir: Path = OUT_DIR) -> str:
    """One ticker's contribution to the digest body: cover + Sankey + a pointer.

    Falls back to the inlined markdown when there is no cover, so a report rendered by an
    older version still reaches the reader. That fallback is the reason
    build_full_report_html survives.
    """
    fn = report_filename(row)
    cover = report_cover_html(row, out_dir)
    if not cover:
        return build_full_report_html(row, out_dir)
    score = float(row.get("score", 0) or 0)
    _emoji, _tag, _label, color = verdict_style(row.get("verdict", ""), score)
    header = (
        f"<h2 style='color:{color};border-bottom:2px solid {color};padding-bottom:4px;"
        f"margin-top:30px;'>{html.escape(row['ticker'])} — cover</h2>"
        f"<p style='font-size:12px;color:#888;margin:0 0 10px 0;'>"
        f"<a href='{obsidian_link(fn)}' style='color:#1f77b4;'>Open in Obsidian</a>"
        f" · full report: {html.escape(fn)}.html</p>"
    )
    return (f"<section style='margin:20px 0;'>{header}{cover}"
            f"{sankey_img_html(row, out_dir)}</section>")


_TAG_RE = re.compile(r"<[^>]+>")


def cover_text(row: dict, out_dir: Path = OUT_DIR) -> str:
    """The cover as plain text for the text/plain twin.

    html.unescape AFTER stripping tags, not before: stripping first and unescaping never
    would leave `&euro;40.82B` in the text part, which is the same entity mistake that once
    made a heading comparison report five phantom missing sections.
    """
    cover = report_cover_html(row, out_dir)
    if not cover:
        return ""
    txt = re.sub(r"</(div|section|h3|h4|p)>", "\n", cover, flags=re.IGNORECASE)
    txt = html.unescape(_TAG_RE.sub(" ", txt))
    lines = [" ".join(ln.split()) for ln in txt.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# --- Deep-report HTML attachment (v4.3, delivery decision "a + b") -----------
#
# Nothing is REMOVED from the digest: the summary cards and the inlined markdown
# reports stay exactly as they were. What the inline render cannot carry is the HTML
# artifact itself — the one-page cover, the Sankey money engine, the SWOT quadrants,
# the ⭐ ratings and the eleven charts are produced by render_report.py and live only
# in the .html. Pointing at that file with a `file://` link is useless on a phone,
# which is where this digest is read, so the file travels with the mail instead.
#
# Only the DEEP name is attached. A screen is a one-minute read that the summary card
# already covers, and attaching three ~1.5 MB artifacts to a daily mail is how a
# digest starts getting refused by the receiving MTA.
ATTACH_BUDGET_BYTES = 8 * 1024 * 1024


def deep_report_attachments(rows: list[dict], out_dir: Path = OUT_DIR,
                            budget: int = ATTACH_BUDGET_BYTES) -> list[tuple[Path, str]]:
    """[(path, filename)] for today's deep-report HTML(s), inside a size budget.

    Returns [] — never raises — when there is no deep row, when the renderer produced
    no HTML, or when the file would blow the budget. Every skip logs its reason: an
    attachment that silently vanishes is worse than one that was never promised.
    """
    picked: list[tuple[Path, str]] = []
    spent = 0
    for row in rows or []:
        if (row.get("mode", "") or "").strip().lower() != "deep":
            continue
        path = Path(out_dir) / f"{report_filename(row)}.html"
        if not path.exists():
            log(f"deep report HTML not found ({path.name}); nothing to attach")
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:
            log(f"deep report unreadable ({path.name}, non-fatal): {exc}")
            continue
        if spent + size > budget:
            log(f"deep report {path.name} ({size} B) skipped — over the "
                f"{budget} B attachment budget")
            continue
        picked.append((path, path.name))
        spent += size
    return picked


def attachment_notice_html(names: list[str]) -> str:
    """Tell the reader the artifact is in the mail. An attachment nobody is told about
    is an attachment nobody opens."""
    if not names:
        return ""
    items = " · ".join(html.escape(n) for n in names)
    return (
        "<p style='font-size:13px;color:#444;background:#eef5fb;border-left:3px solid "
        "#1f77b4;padding:8px 12px;margin:12px 0;'>📎 <strong>Attached:</strong> "
        f"{items} — the full rendered report (cover, charts, Sankey, SWOT, ⭐). "
        "Open it from the mail; it needs no network and no vault.</p>"
    )


def attachment_notice_text(names: list[str]) -> str:
    if not names:
        return ""
    return ("ATTACHED: " + " | ".join(names) +
            "\n  Full rendered report — cover, charts, Sankey, SWOT, ratings.\n\n")


def build_card_text(row: dict) -> str:
    """Plain-text version of a card for the multipart/alternative text part."""
    score = float(row.get("score", 0) or 0)
    _emoji, _tag, label, _color = verdict_style(row.get("verdict", ""), score)
    fn = report_filename(row)
    notes = row.get("notes", "") or ""
    return (
        f"{row['ticker']} — {score:.1f}/10 — {label}\n"
        f"  Mode: {row.get('mode','')} | Round: {row.get('round','')} | "
        f"Gates: {row.get('gates_passed','')}/7 | "
        f"Price: {row.get('price_at_eval','')} {row.get('currency','')}\n"
        f"  Notes: {notes}\n"
        f"  Report: {fn}.md (inside BD_Obsidian/{OUT_REL}/)\n"
    )


def build_email(rows: list[dict], target_date: str) -> tuple[str, str, str]:
    """Return (subject, html_body, text_body)."""
    if not rows:
        # No daily evaluations — the growth lens may still have run today (it keeps
        # its own _growth_log.csv), so render a growth-only digest before falling
        # back to the empty stub.
        growth_section_html = build_growth_section_html(target_date)
        if growth_section_html:
            growth_rows = read_growth_rows(target_date)
            subject_parts = [
                f"{r.get('ticker','')} {float(r.get('growth_composite') or 0):.1f} [{(r.get('verdict','') or '').upper()}]"
                for r in growth_rows
            ]
            subject = f"StocksDaily {target_date} - growth lens: " + " | ".join(subject_parts)
            html_body = (
                f"<html><body style='font-family: Segoe UI, Arial, sans-serif; max-width: 820px;"
                f" margin: 0 auto; padding: 20px; color: #222;'>"
                f"<h2>StocksDaily {target_date}</h2>"
                f"<p>No daily (quality-lens) evaluations for this date - growth lens only.</p>"
                f"{growth_section_html}"
                f"<hr><p style='font-size: 12px; color: #888;'>🤖 Auto-generated. Not investment advice."
                f"<br>{html.escape(attribution_text())}</p>"
                f"</body></html>"
            )
            text_lines = [f"StocksDaily {target_date} - growth lens only", ""]
            for r in growth_rows:
                text_lines.append(
                    f"- {r.get('ticker','')}: {float(r.get('growth_composite') or 0):.2f}/10 "
                    f"{(r.get('verdict','') or '').upper()} (Ro40 {r.get('rule_of_40','')})"
                )
            text_lines += ["", "--", attribution_text()]
            return subject, html_body, "\n".join(text_lines) + "\n"
        subject = f"StocksDaily {target_date} - no evaluations"
        html_body = (
            f"<html><body><h2>StocksDaily {target_date}</h2>"
            f"<p>No evaluations recorded for this date.</p></body></html>"
        )
        text_body = f"StocksDaily {target_date}\n\nNo evaluations recorded for this date.\n"
        return subject, html_body, text_body

    # Subject: emoji-free, tag-driven (helps Yahoo/Gmail spam filters)
    subject_parts = []
    for r in rows:
        score = float(r.get("score", 0) or 0)
        _emoji, tag, _label, _color = verdict_style(r.get("verdict", ""), score)
        subject_parts.append(f"{r['ticker']} {score:.1f} [{tag}]")
    subject = f"StocksDaily {target_date} - " + " | ".join(subject_parts)

    # The dashboard bundle is the report corpus for both price-driven blocks below
    # (buy list, watch-list), so it is extracted before them and reused afterwards.
    bundle = extract_dashboard_bundle()

    # Live prices, fetched ONCE for the union of both blocks' tickers — the yfinance
    # fallback leg is the slow part of composing this email, so it runs a single time.
    wl_rows = []
    if load_watchlist is not None:
        try:
            wl_rows = load_watchlist(OUT_DIR)
        except Exception as exc:
            log(f"watch-list load SKIP (non-fatal): {type(exc).__name__}: {exc}")
    buy_candidates = []
    if buy_list is not None and bundle:
        try:
            buy_candidates = buy_list.candidate_tickers(bundle.get("reports") or [])
        except Exception as exc:
            log(f"buy-list candidates SKIP (non-fatal): {type(exc).__name__}: {exc}")
    price_tickers = sorted({r.get("ticker", "") for r in wl_rows} | set(buy_candidates))
    live_prices = fetch_live_prices_for([t for t in price_tickers if t]) if price_tickers else {}

    # "Buy today" lead section + [BUY: n] subject tag. Fully guarded.
    buy_today_html, buy_today_text, n_buy = "", "", 0
    if buy_list is not None and bundle:
        try:
            buy_result = buy_list.select_buys(
                bundle.get("reports") or [], live_prices,
                holdings=buy_list.load_holdings_safe(OUT_DIR),
            )
            buy_today_html = build_buy_today_html(buy_result)
            buy_today_text = build_buy_today_text(buy_result)
            n_buy = len(buy_result["buys"])
            log(f"buy-list: {n_buy} buyable, {len(buy_result['above_entry'])} above max entry, "
                f"{len(buy_result['no_max_entry'])} without a max entry")
        except Exception as exc:
            log(f"buy-list block SKIP (non-fatal): {type(exc).__name__}: {exc}")
    if n_buy:
        subject += f" [BUY: {n_buy}]"

    # v4 Phase E — price-triggered watch-list block + [WATCHLIST: n] subject tag.
    # (Distinct token from verdict_style's per-ticker WATCH tag.) Fully guarded.
    watchlist_html, n_watch = "", 0
    if wl_rows:
        try:
            watchlist_html, n_watch = build_watchlist_html(wl_rows, live_prices)
        except Exception as exc:
            log(f"watch-list block SKIP (non-fatal): {type(exc).__name__}: {exc}")
    if n_watch:
        subject += f" [WATCHLIST: {n_watch}]"

    # HTML body — buy list + dashboard inline (top), summary cards, then full markdown
    # reports. We embed a static no-JS render of the dashboard because mail clients
    # (Gmail/Yahoo) strip <script> tags from inline HTML. The interactive copy
    # is kept as the attachment for full functionality.
    dashboard_inline_html = build_dashboard_inline_html(bundle, target_date) if bundle else ""
    # What this run cost. Computed here so BOTH bodies can use it; returns ('','') on any
    # failure so a cost line can never block a digest.
    cost_html, cost_text = run_cost_block(target_date, rows)
    adviser_take_html = build_adviser_take_html(rows, bundle)
    cards_html = "\n".join(build_card_html(r, bundle_meta(bundle, r)) for r in rows)
    growth_section_html = build_growth_section_html(target_date)  # Phase 7 — "" when no growth data
    # E1: covers, not the whole markdown. See the COVER_RE block for the measurement.
    reports_html = "\n".join(build_cover_block_html(r) for r in rows)
    # Recomputed in main() when the MIME parts are assembled. Two stat() calls on one
    # file is cheaper than widening this function's return tuple, which six email tests
    # and one caller unpack positionally.
    attach_names = [name for _p, name in deep_report_attachments(rows)]
    attach_html = attachment_notice_html(attach_names)
    html_body = f"""
    <html>
      <head>
        <style>
          body {{ font-family: Segoe UI, Arial, sans-serif; max-width: 820px; margin: 0 auto; padding: 20px; color: #222; }}
          h1 {{ color: #1f77b4; }}
          h2, h3, h4 {{ color: #1f77b4; }}
          table {{ border-collapse: collapse; margin: 10px 0; }}
          th, td {{ border: 1px solid #ddd; padding: 6px 10px; font-size: 13px; }}
          th {{ background: #f0f0f0; text-align: left; }}
          code {{ background: #f4f4f4; padding: 1px 4px; border-radius: 3px; font-size: 12px; }}
          pre {{ background: #f4f4f4; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; }}
          blockquote {{ border-left: 3px solid #ccc; margin: 10px 0; padding: 4px 12px; color: #555; background: #fafafa; }}
          hr {{ border: none; border-top: 1px solid #e0e0e0; margin: 30px 0; }}
        </style>
      </head>
      <body>
        <h1>StocksDaily — {target_date}</h1>
        <p style="color: #666; font-size: 13px;">
          Auto-generated. Not investment advice. Verify all figures before acting.
        </p>
        {attach_html}
        {buy_today_html}
        {watchlist_html}
        {adviser_take_html}
        {dashboard_inline_html}
        <h2 style="margin-top: 25px;">Today's reports — summary</h2>
        {cards_html}
        {growth_section_html}
        <h2 style="margin-top: 35px;">Covers ({len(rows)})</h2>
        {reports_html}
        {cost_html}
        <hr>
        <p style="font-size: 12px; color: #888;">
          Horizonte: 1-5 anos · Filtro: Quality Compounder + Piotroski + Altman ·
          <a href="obsidian://open?vault=BD_Obsidian&file=Personal/Finance/StocksDaily/_shortlist.md">Open shortlist</a>
          <br>{html.escape(attribution_text())}
        </p>
      </body>
    </html>
    """

    # Plain-text alternative — summary + raw markdown per ticker
    # Mirrors the HTML part: covers, not whole reports. Gmail's ~102 KB clip is measured on
    # the delivered message, so leaving the 85 KB markdown archive in the text twin would
    # keep the mail clipped no matter what the HTML part does.
    cards_text = "\n".join(build_card_text(r) for r in rows)
    reports_text_parts = []
    for r in rows:
        fn = report_filename(r)
        ctext = cover_text(r)
        if not ctext:
            _fn, md = load_report_markdown(r)
            ctext = _strip_frontmatter(md) if md else "[report file not found]"
        reports_text_parts.append(
            f"\n{'=' * 60}\n{r['ticker']} — cover ({fn}.html)\n{'=' * 60}\n\n{ctext}\n"
        )
    reports_text = "".join(reports_text_parts)
    watch_text = f"⭐ WATCH-LIST: {n_watch} name(s) at buy target — see HTML block.\n\n" if n_watch else ""
    text_body = (
        f"StocksDaily — {target_date}\n"
        f"{'=' * 40}\n"
        f"Auto-generated. Not investment advice. Verify all figures before acting.\n\n"
        f"{attachment_notice_text(attach_names)}"
        f"{buy_today_text}"
        f"{watch_text}"
        f"SUMMARY\n-------\n{cards_text}\n\n"
        f"COVERS ({len(rows)})\n"
        f"{reports_text}\n"
        f"{cost_text}"
        f"--\n"
        f"Horizon: 1-5 years. Filter: Quality Compounder + Piotroski + Altman.\n"
        f"Shortlist: BD_Obsidian/{OUT_REL}/_shortlist.md\n"
        f"{attribution_text()}\n"
    )

    return subject, html_body, text_body


_IMG_SRC_RE = re.compile(r'<img\b([^>]*?)\bsrc=(["\'])([^"\']+)\2', re.IGNORECASE)


def inline_image_refs(html_body: str) -> tuple[str, list[tuple[Path, str, str]]]:
    """Rewrite local <img src="..."> references to cid: URIs so email clients render them.

    Returns (rewritten_html, [(file_path, cid, mime_subtype), ...]). Remote URLs
    (http/https/cid/data) are left untouched. Missing files are also left untouched
    so the alt text falls back gracefully.
    """
    attachments: list[tuple[Path, str, str]] = []
    seen: dict[str, str] = {}  # resolved-path -> cid

    def _replace(m: re.Match) -> str:
        pre, quote, src = m.group(1), m.group(2), m.group(3)
        low = src.lower()
        if low.startswith(("http://", "https://", "cid:", "data:", "mailto:")):
            return m.group(0)
        # Resolve relative to the reports directory (markdown lives in OUT_DIR)
        candidate = (OUT_DIR / src).resolve()
        if not candidate.is_file():
            return m.group(0)
        key = str(candidate).lower()
        cid = seen.get(key)
        if cid is None:
            mime, _ = mimetypes.guess_type(candidate.name)
            subtype = "png"
            if mime and mime.startswith("image/"):
                subtype = mime.split("/", 1)[1]
            cid = f"img-{uuid.uuid4().hex}@stocksdaily"
            seen[key] = cid
            attachments.append((candidate, cid, subtype))
        return f"<img{pre}src={quote}cid:{cid}{quote}"

    return _IMG_SRC_RE.sub(_replace, html_body), attachments


def digest_message_id(target_date: str, subject: str, row_count: int) -> str:
    """Deterministic Message-ID for a digest.

    The script used to set no Message-ID at all, leaving the MTA to invent one per route.

    A stable id is worth having, but do NOT treat it as duplicate protection. It was originally
    added on the assumption that Gmail suppresses a message whose Message-ID it has already filed.
    **That is false on this route, and was measured false on 2026-07-29**: two sends 15 minutes
    apart carried the identical id <stocksdaily.2026-07-29.ab542a1d0ce9@ist.utl.pt> and Gmail
    delivered BOTH -- it threaded them together, which is all a repeated id buys here.

    What the id is genuinely good for: it makes duplicates diagnosable. Same id in two headers
    means one digest sent twice; different ids mean two genuinely different digests. Preventing the
    second send is the job of the ownership guard and the send-once ledger, not of this function.

    Derived from (date, subject, row count) rather than random so a re-send of the same digest is
    identifiable as such, while a digest with more reports gets its own id.
    """
    key = hashlib.sha1(
        f"{target_date}|{subject}|{row_count}".encode("utf-8")
    ).hexdigest()[:12]
    return f"<stocksdaily.{target_date}.{key}@ist.utl.pt>"


def not_email_owner(scheduled_sender: bool) -> str | None:
    """Reason this process must not send, or None if it may.

    Deliberately env-driven rather than argument-driven: the check must fire for a send_email.py
    that a *skill* spawns without knowing any of this, which is exactly the 2026-07-29 case.
    """
    if not os.environ.get(SCHEDULED_ENV):
        return None                      # manual/interactive path -- sending is the point
    if scheduled_sender:
        return None                      # the bat's own call, the one designated to send
    return (
        f"{SCHEDULED_ENV}=1 is set, so this is a scheduled run and the bat owns the email; "
        f"this caller did not pass --scheduled-sender"
    )


def load_sent_index() -> dict:
    """Read the send-once ledger. Any problem returns {} -- a corrupt or missing ledger must
    never be the reason a digest fails to go out."""
    try:
        if SENT_INDEX.exists():
            data = json.loads(SENT_INDEX.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as e:
        log(f"sent-ledger unreadable ({type(e).__name__}: {e}); treating as empty")
    return {}


def record_sent(target_date: str, message_id: str, row_count: int) -> None:
    """Append this digest to the ledger. Non-fatal: the mail is already delivered, so a write
    failure must not turn a successful send into a reported error."""
    try:
        index = load_sent_index()
        index[target_date] = {
            "sent_at": _now_iso(),
            "message_id": message_id,
            "reports": row_count,
        }
        SENT_INDEX.parent.mkdir(parents=True, exist_ok=True)
        SENT_INDEX.write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        log(f"sent-ledger write FAIL (non-fatal): {type(e).__name__}: {e}")


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def load_for_date(target_date: str) -> list[dict]:
    if not LOG.exists():
        return []
    with LOG.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r.get("date") == target_date]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true", help="Print body, don't send")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Send even if a digest for --date already went out (bypasses the send-once ledger, "
             "NOT the scheduled-run ownership guard)",
    )
    ap.add_argument(
        "--scheduled-sender",
        action="store_true",
        help=f"Assert this call is the designated sender of a scheduled run. Only "
             f"stocks-daily.bat passes it; a skill never should. Without it, any call made while "
             f"{SCHEDULED_ENV}=1 refuses to send.",
    )
    args = ap.parse_args()

    # Ownership guard -- FIRST, and ahead of the ledger. Two reasons it goes before everything:
    # a refused caller should cost nothing, and unlike the ledger this guard is absolute
    # (--force cannot lift it, because --force is precisely how the 17:42 duplicate got out).
    if not args.dry_run:
        blocked = not_email_owner(args.scheduled_sender)
        if blocked:
            log(f"NOT sending: {blocked}")
            print(json.dumps({
                "email_sent": False,
                "skipped": "not_email_owner",
                "date": args.date,
                "reason": blocked,
            }))
            return 0

    # Always regenerate the dashboard before composing the email so the attachment
    # reflects the latest reports, including anything written today.
    regenerate_dashboard()

    rows = load_for_date(args.date)
    subject, html_body, text_body = build_email(rows, args.date)
    message_id = digest_message_id(args.date, subject, len(rows))

    # Send-once guard. Checked BEFORE the SMTP block so a duplicate costs nothing, and after
    # build_email so the ledger records what would have gone out. --dry-run is never blocked.
    if not args.dry_run and not args.force:
        prior = load_sent_index().get(args.date)
        if prior:
            log(
                f"digest for {args.date} already sent at {prior.get('sent_at')} "
                f"({prior.get('reports')} reports, {prior.get('message_id')}); "
                f"skipping duplicate — use --force to override"
            )
            print(json.dumps({
                "email_sent": False,
                "skipped": "already_sent",
                "date": args.date,
                "previous": prior,
            }))
            return 0

    if args.dry_run:
        print("SUBJECT:", subject)
        print("---TEXT PART---")
        print(text_body)
        print("---HTML PART---")
        print(html_body)
        return 0

    try:
        from api_keys_reader import api_keys_reader
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.image import MIMEImage
        from email.mime.multipart import MIMEMultipart

        keys = api_keys_reader(str(BD_FINANCE / "config" / "api_keys.txt"))
        pwd = keys.get("password_bfsd")
        if not pwd:
            log("ERROR: password_bfsd not found in api_keys.txt")
            return 1

        # Rewrite local <img src="IMG/..."> to cid: refs and collect attachments.
        # Required because mail clients can't resolve relative file:// paths.
        html_body, inline_imgs = inline_image_refs(html_body)

        sender = "bfsd@ist.utl.pt"
        # MIME structure:
        #   multipart/mixed
        #     multipart/related        (HTML body + inline cid: images)
        #       multipart/alternative
        #         text/plain
        #         text/html
        #       image/png × N          (Content-ID, Content-Disposition: inline)
        #     application/octet-stream (dashboard attachment)
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = ", ".join(RECIPIENTS)
        msg["Reply-To"] = sender
        # Explicit + deterministic so duplicate deliveries of one digest collapse. See
        # digest_message_id(); without this the MTA invents a fresh id per route.
        msg["Message-ID"] = message_id
        # Transactional-mail header helps spam filters classify this as legit automation
        msg["List-Unsubscribe"] = f"<mailto:{sender}?subject=unsubscribe-stocksdaily>"

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(text_body, "plain", "utf-8"))
        alt.attach(MIMEText(html_body, "html", "utf-8"))

        if inline_imgs:
            related = MIMEMultipart("related")
            related.attach(alt)
            for img_path, cid, subtype in inline_imgs:
                try:
                    img = MIMEImage(img_path.read_bytes(), _subtype=subtype)
                    img.add_header("Content-ID", f"<{cid}>")
                    img.add_header("Content-Disposition", "inline",
                                   filename=img_path.name)
                    related.attach(img)
                except Exception as e:
                    log(f"inline image FAIL ({img_path.name}, non-fatal): "
                        f"{type(e).__name__}: {e}")
            msg.attach(related)
            log(f"inlined {len(inline_imgs)} image(s)")
        else:
            msg.attach(alt)

        # Attach the dashboard if present (regenerated above). Failure here is non-fatal.
        try:
            if DASHBOARD.exists():
                dash_bytes = DASHBOARD.read_bytes()
                from email.mime.application import MIMEApplication
                attach = MIMEApplication(dash_bytes, _subtype="octet-stream")
                attach.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=f"StocksDaily_dashboard_{args.date}.html",
                )
                attach.add_header("Content-Type", "text/html; charset=utf-8")
                msg.attach(attach)
                log(f"attached dashboard ({len(dash_bytes)} bytes)")
            else:
                log(f"dashboard not found at {DASHBOARD}; sending without attachment")
        except Exception as e:
            log(f"attach dashboard FAIL (non-fatal): {type(e).__name__}: {e}")

        # Attach the deep report's rendered HTML (delivery decision "a + b", v4.3).
        # Non-fatal by the same rule as the dashboard: the digest going out matters
        # more than any one attachment reaching it.
        try:
            from email.mime.application import MIMEApplication
            for path, filename in deep_report_attachments(rows):
                blob = path.read_bytes()
                part = MIMEApplication(blob, _subtype="octet-stream")
                part.add_header("Content-Disposition", "attachment", filename=filename)
                part.add_header("Content-Type", "text/html; charset=utf-8")
                msg.attach(part)
                log(f"attached deep report {filename} ({len(blob)} bytes)")
        except Exception as e:
            log(f"attach deep report FAIL (non-fatal): {type(e).__name__}: {e}")

        with smtplib.SMTP_SSL("mail.ist.utl.pt", 465, timeout=20) as smtp:
            smtp.login(sender, pwd)
            smtp.sendmail(sender, RECIPIENTS, msg.as_string())
        log(f"email sent to {', '.join(RECIPIENTS)} (Message-ID {message_id})")
        record_sent(args.date, message_id, len(rows))
        print(json.dumps({"email_sent": True, "message_id": message_id}))
        return 0
    except Exception as e:
        log(f"email FAIL (not fatal): {type(e).__name__}: {e}")
        import json as _json
        print(_json.dumps({"email_sent": False, "error": f"{type(e).__name__}: {e}"}))
        return 0  # non-fatal


if __name__ == "__main__":
    sys.exit(main())
