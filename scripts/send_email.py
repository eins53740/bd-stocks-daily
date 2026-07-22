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
import html
import json
import mimetypes
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

RECIPIENTS = ["eins.ist@gmail.com"]

# v4 Phase E — price-triggered watch-list, wired into this digest.
WATCHLIST = OUT_DIR / "_watchlist.csv"
LIVE_PRICES = OUT_DIR / "_live_prices.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts dir (watchlist.py)
try:
    from watchlist import distance_to_target_pct, load_watchlist  # noqa: E402
except Exception as _wl_exc:  # never let a watch-list import break the digest
    load_watchlist = None
    distance_to_target_pct = None


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
    total = len(reports)
    raw_shortlist = [r for r in reports if (r.get("score") or 0) >= 7.5 and (r.get("days_left") or 0) > 0]
    # Dedupe per ticker — keep the most recent analysis only (latest date wins).
    _by_ticker: dict[str, dict] = {}
    for r in raw_shortlist:
        t = r.get("ticker") or ""
        prev = _by_ticker.get(t)
        if prev is None or (r.get("date") or "") > (prev.get("date") or ""):
            _by_ticker[t] = r
    shortlist = list(_by_ticker.values())
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


def fetch_watchlist_live_prices(tickers: list[str]) -> dict:
    """Live price per watch-list ticker. Reads the fresh _live_prices.json first
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


def render_markdown_html(md: str) -> str:
    """Render markdown content to HTML for inline email embedding."""
    md_body = _strip_frontmatter(md)
    if _markdown is not None:
        try:
            return _markdown.markdown(
                md_body,
                extensions=["extra", "sane_lists", "tables", "fenced_code"],
            )
        except Exception:
            pass
    # Fallback: escape + preserve line breaks in a <pre> block
    return f"<pre style='white-space:pre-wrap;font-family:monospace;font-size:12px;'>{html.escape(md_body)}</pre>"


def load_report_markdown(row: dict) -> tuple[str, str]:
    """Return (filename, markdown_content). Empty content if file missing."""
    fn = report_filename(row)
    path = OUT_DIR / f"{fn}.md"
    if not path.exists():
        return fn, ""
    try:
        return fn, path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        log(f"WARN: could not read {path}: {exc}")
        return fn, ""


def build_full_report_html(row: dict) -> str:
    """Render the full markdown report for one ticker as an HTML section."""
    fn, md = load_report_markdown(row)
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
                f"<hr><p style='font-size: 12px; color: #888;'>🤖 Auto-generated. Not investment advice.</p>"
                f"</body></html>"
            )
            text_lines = [f"StocksDaily {target_date} - growth lens only", ""]
            for r in growth_rows:
                text_lines.append(
                    f"- {r.get('ticker','')}: {float(r.get('growth_composite') or 0):.2f}/10 "
                    f"{(r.get('verdict','') or '').upper()} (Ro40 {r.get('rule_of_40','')})"
                )
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

    # v4 Phase E — price-triggered watch-list block + [WATCHLIST: n] subject tag.
    # (Distinct token from verdict_style's per-ticker WATCH tag.) Fully guarded.
    watchlist_html, n_watch = "", 0
    if load_watchlist is not None:
        try:
            wl_rows = load_watchlist(OUT_DIR)
            wl_live = fetch_watchlist_live_prices([r.get("ticker", "") for r in wl_rows])
            watchlist_html, n_watch = build_watchlist_html(wl_rows, wl_live)
        except Exception as exc:
            log(f"watch-list block SKIP (non-fatal): {type(exc).__name__}: {exc}")
    if n_watch:
        subject += f" [WATCHLIST: {n_watch}]"

    # HTML body — dashboard inline (top), summary cards, then full markdown reports.
    # We embed a static no-JS render of the dashboard because mail clients
    # (Gmail/Yahoo) strip <script> tags from inline HTML. The interactive copy
    # is kept as the attachment for full functionality.
    bundle = extract_dashboard_bundle()
    dashboard_inline_html = build_dashboard_inline_html(bundle, target_date) if bundle else ""
    adviser_take_html = build_adviser_take_html(rows, bundle)
    cards_html = "\n".join(build_card_html(r, bundle_meta(bundle, r)) for r in rows)
    growth_section_html = build_growth_section_html(target_date)  # Phase 7 — "" when no growth data
    reports_html = "\n".join(build_full_report_html(r) for r in rows)
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
        {watchlist_html}
        {adviser_take_html}
        {dashboard_inline_html}
        <h2 style="margin-top: 25px;">Today's reports — summary</h2>
        {cards_html}
        {growth_section_html}
        <h2 style="margin-top: 35px;">Full reports ({len(rows)})</h2>
        {reports_html}
        <hr>
        <p style="font-size: 12px; color: #888;">
          Horizonte: 1-5 anos · Filtro: Quality Compounder + Piotroski + Altman ·
          <a href="obsidian://open?vault=BD_Obsidian&file=Personal/Finance/StocksDaily/_shortlist.md">Open shortlist</a>
        </p>
      </body>
    </html>
    """

    # Plain-text alternative — summary + raw markdown per ticker
    cards_text = "\n".join(build_card_text(r) for r in rows)
    reports_text_parts = []
    for r in rows:
        fn, md = load_report_markdown(r)
        reports_text_parts.append(
            f"\n{'=' * 60}\n{r['ticker']} — full report ({fn}.md)\n{'=' * 60}\n\n"
            f"{_strip_frontmatter(md) if md else '[report file not found]'}\n"
        )
    reports_text = "".join(reports_text_parts)
    watch_text = f"⭐ WATCH-LIST: {n_watch} name(s) at buy target — see HTML block.\n\n" if n_watch else ""
    text_body = (
        f"StocksDaily — {target_date}\n"
        f"{'=' * 40}\n"
        f"Auto-generated. Not investment advice. Verify all figures before acting.\n\n"
        f"{watch_text}"
        f"SUMMARY\n-------\n{cards_text}\n\n"
        f"FULL REPORTS ({len(rows)})\n"
        f"{reports_text}\n"
        f"--\n"
        f"Horizon: 1-5 years. Filter: Quality Compounder + Piotroski + Altman.\n"
        f"Shortlist: BD_Obsidian/{OUT_REL}/_shortlist.md\n"
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
    args = ap.parse_args()

    # Always regenerate the dashboard before composing the email so the attachment
    # reflects the latest reports, including anything written today.
    regenerate_dashboard()

    rows = load_for_date(args.date)
    subject, html_body, text_body = build_email(rows, args.date)

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

        with smtplib.SMTP_SSL("mail.ist.utl.pt", 465, timeout=20) as smtp:
            smtp.login(sender, pwd)
            smtp.sendmail(sender, RECIPIENTS, msg.as_string())
        log(f"email sent to {', '.join(RECIPIENTS)}")
        print('{"email_sent": true}')
        return 0
    except Exception as e:
        log(f"email FAIL (not fatal): {type(e).__name__}: {e}")
        import json as _json
        print(_json.dumps({"email_sent": False, "error": f"{type(e).__name__}: {e}"}))
        return 0  # non-fatal


if __name__ == "__main__":
    sys.exit(main())
