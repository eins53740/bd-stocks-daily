"""
update_shortlist.py — Rebuild _shortlist.md from _log.csv.

Rules:
- Include entries with score >= 7.5 AND date within last 90 days (shortlist expiry)
- Entries older than 90 days move to _shortlist_expired.md (append, deduped)
- Sort by score desc, then date desc
- Preserve `manual_reviewed` flag across rebuilds (read from existing _shortlist.md)
- Earnings watch: flag if next earnings date has passed since evaluation
"""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

OUT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
LOG = OUT / "_log.csv"
SHORTLIST = OUT / "_shortlist.md"
EXPIRED = OUT / "_shortlist_expired.md"
CATALYST_CAL = OUT / "_catalyst_calendar.md"

EXPIRY_DAYS = 90
CATALYST_WINDOW_DAYS = 90


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def parse_manual_reviewed(md_text: str) -> dict[tuple[str, str], str]:
    """Parse existing shortlist, return {(ticker, date): manual_review_flag}."""
    out = {}
    # Look for rows: | TICKER | ... | date | ... | manual_review_flag | ...
    for line in md_text.splitlines():
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")]
        # We store manual_reviewed near the end; easiest: regex for ticker + date + yes/no
        m = re.search(r"\|\s*([A-Z0-9\.\-]+)\s*\|.*?\|\s*(\d{4}-\d{2}-\d{2})\s*\|.*?\|\s*(yes|no)\s*\|", line, re.I)
        if m:
            out[(m.group(1), m.group(2))] = m.group(3).lower()
    return out


def load_log() -> list[dict]:
    if not LOG.exists() or LOG.stat().st_size == 0:
        return []
    with LOG.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def is_active(row: dict, today: date) -> bool:
    try:
        d = datetime.strptime(row["date"], "%Y-%m-%d").date()
        score = float(row["score"])
    except (KeyError, ValueError):
        return False
    if (today - d).days > EXPIRY_DAYS:
        return False
    return score >= 7.5


def fmt_verdict(verdict: str, score: float) -> str:
    v = (verdict or "").lower()
    if v == "great" or score >= 9.0:
        return "🟢🟢 GREAT BUY"
    if v == "invest" or score >= 7.5:
        return "🟢 GOOD BUY"
    if v == "review" or score >= 6.0:
        return "🟡 WATCH"
    if v == "fair" or score >= 4.0:
        return "🟠 FAIR"
    return "🔴 DO NOT BUY"


def safe_filename(ticker: str, date_str: str, verdict: str) -> str:
    return f"{date_str}_{ticker}_{verdict}"


def build_shortlist(rows: list[dict], manual_flags: dict) -> str:
    today = date.today()
    active = [r for r in rows if is_active(r, today)]
    # Latest per ticker (keep most recent)
    latest = {}
    for r in active:
        t = r["ticker"]
        if t not in latest or r["date"] > latest[t]["date"]:
            latest[t] = r

    sorted_rows = sorted(
        latest.values(),
        key=lambda r: (-float(r["score"]), r["date"]),
        reverse=False,
    )
    # Actually want score desc, date desc
    sorted_rows = sorted(
        latest.values(),
        key=lambda r: (float(r["score"]), r["date"]),
        reverse=True,
    )

    lines = [
        "---",
        "tags: [finance, stocks, shortlist]",
        f"updated: {today.isoformat()}",
        "---",
        "",
        "# 🟢 Shortlist — Boas acções para comprar (horizonte 1–5 anos)",
        "",
        "> [!info] Auto-gerado por `/bd-stocks-daily`. Validade por entrada: **90 dias**. Verifica manualmente antes de investir.",
        ">",
        "> 🤖 Auto-generated. Not investment advice. Verify all figures before acting.",
        "",
        f"## Activas (score ≥ 7.5) — {len(sorted_rows)} entries",
        "",
        "| Ticker | Region | Size | Sector | Date | Round | Score | Verdict | Gates | Manual review | Expires | Link |",
        "|--------|--------|------|--------|------|-------|-------|---------|-------|---------------|---------|------|",
    ]

    region_count: dict[str, int] = defaultdict(int)
    sector_count: dict[str, int] = defaultdict(int)
    scores_total = 0.0

    for r in sorted_rows:
        ticker = r["ticker"]
        date_str = r["date"]
        score = float(r["score"])
        scores_total += score
        verdict_raw = r.get("verdict", "")
        verdict = fmt_verdict(verdict_raw, score)
        region = r.get("notes", "").split("|")[0] if "|" in (r.get("notes") or "") else ""
        size = r.get("size", "")
        # Try to pull region/sector from notes
        notes = r.get("notes", "") or ""
        region = ""
        sector = ""
        if "region=" in notes:
            try:
                region = notes.split("region=")[1].split(";")[0].strip()
            except Exception:
                pass
        if "sector=" in notes:
            try:
                sector = notes.split("sector=")[1].split(";")[0].strip()
            except Exception:
                pass
        region_count[region or "?"] += 1
        sector_count[sector or "?"] += 1
        mr = manual_flags.get((ticker, date_str), "no")
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        expires = (d + timedelta(days=EXPIRY_DAYS)).isoformat()

        # Screens always save as {date}_{ticker}_screen.md regardless of verdict.
        suffix = "screen" if r.get("mode", "").lower() == "screen" else (verdict_raw or "invest")
        link_name = safe_filename(ticker, date_str, suffix)
        link = f"[[{link_name}]]"

        lines.append(
            f"| {ticker} | {region} | {size} | {sector} | {date_str} | {r.get('round','')} | {score:.1f} | {verdict} | {r.get('gates_passed','')}/7 | {mr} | {expires} | {link} |"
        )

    lines.append("")
    lines.append("## Estatísticas")
    lines.append("")
    lines.append(f"- **Total activas**: {len(sorted_rows)}")
    if sorted_rows:
        avg = scores_total / len(sorted_rows)
        lines.append(f"- **Score médio**: {avg:.2f}/10")
        lines.append(f"- **Por região**: " + ", ".join(f"{k}={v}" for k, v in sorted(region_count.items())))
        lines.append(f"- **Por sector**: " + ", ".join(f"{k}={v}" for k, v in sorted(sector_count.items())))
    lines.append("")
    lines.append("## Ver também")
    lines.append("")
    lines.append("- [[_shortlist_expired]] — entradas expiradas (>90 dias)")
    lines.append("- [[README]] — documentação da pasta")
    lines.append("- [[Stocks - buy 5y]] — flowchart original de 7 gates")
    lines.append("")

    return "\n".join(lines)


def append_expired(rows: list[dict]) -> None:
    today = date.today()
    expiring = []
    for r in rows:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d").date()
            score = float(r["score"])
        except (KeyError, ValueError):
            continue
        if (today - d).days > EXPIRY_DAYS and score >= 7.5:
            expiring.append(r)
    if not expiring:
        return
    # Read existing expired to dedupe by (ticker, date)
    seen = set()
    if EXPIRED.exists():
        existing = EXPIRED.read_text(encoding="utf-8")
        for m in re.finditer(r"\|\s*([A-Z0-9\.\-]+)\s*\|.*?\|\s*(\d{4}-\d{2}-\d{2})", existing):
            seen.add((m.group(1), m.group(2)))
    else:
        existing = "---\ntags: [finance, stocks, expired]\n---\n\n# Shortlist expirado\n\n| Ticker | Date | Score | Verdict |\n|--------|------|-------|---------|\n"
    new_rows = []
    for r in expiring:
        key = (r["ticker"], r["date"])
        if key in seen:
            continue
        seen.add(key)
        v = fmt_verdict(r.get("verdict", ""), float(r["score"]))
        new_rows.append(f"| {r['ticker']} | {r['date']} | {r['score']} | {v} |")
    if new_rows:
        EXPIRED.write_text(existing + "\n".join(new_rows) + "\n", encoding="utf-8")


def build_catalyst_calendar(rows: list[dict]) -> str:
    """v2.1: rolling 30/60/90-day events for every active shortlist ticker.

    Fetches `Ticker.calendar` (earnings + ex-div) fresh from yfinance — ~20
    calls per run, fast enough for the daily window. Reads-only and degrades
    gracefully on rate-limit / missing data.
    """
    today = date.today()
    horizon = today + timedelta(days=CATALYST_WINDOW_DAYS)
    active = [r for r in rows if is_active(r, today)]
    # Latest per ticker
    latest: dict[str, dict] = {}
    for r in active:
        t = r["ticker"]
        if t not in latest or r["date"] > latest[t]["date"]:
            latest[t] = r

    try:
        import yfinance as yf  # lazy import — only needed for calendar build
    except ImportError:
        log("yfinance unavailable — emitting empty catalyst calendar")
        return _empty_catalyst_md(today, "yfinance import failed")

    events: list[dict] = []
    warnings: list[str] = []
    for ticker, row in latest.items():
        try:
            cal = yf.Ticker(ticker).calendar
            if cal is None:
                continue
            # yfinance returns dict OR pandas Series depending on version
            if hasattr(cal, "get"):
                ed = cal.get("Earnings Date")
                xd = cal.get("Ex-Dividend Date")
            elif hasattr(cal, "loc"):
                ed = cal.loc["Earnings Date"] if "Earnings Date" in cal.index else None
                xd = cal.loc["Ex-Dividend Date"] if "Ex-Dividend Date" in cal.index else None
            else:
                continue
            for label, val in (("Earnings", ed), ("Ex-dividend", xd)):
                if val is None:
                    continue
                if hasattr(val, "__iter__") and not isinstance(val, str):
                    try:
                        val = list(val)[0]
                    except Exception:
                        pass
                try:
                    d = val if hasattr(val, "isoformat") else datetime.fromisoformat(str(val)[:10]).date()
                    if today <= d <= horizon:
                        events.append({
                            "ticker": ticker,
                            "date": d.isoformat(),
                            "event": label,
                            "score": float(row["score"]),
                        })
                except Exception:
                    continue
        except Exception as e:
            warnings.append(f"{ticker}: {e}")

    events.sort(key=lambda e: e["date"])
    return _render_catalyst_md(today, events, len(latest), warnings)


def _empty_catalyst_md(today: date, reason: str) -> str:
    return (
        "---\ntags: [finance, stocks, calendar]\n"
        f"updated: {today.isoformat()}\n---\n\n"
        "# 📅 Catalyst calendar — shortlist (próximos 90 dias)\n\n"
        f"> [!warning] Catalyst calendar unavailable — {reason}.\n"
    )


def _render_catalyst_md(today: date, events: list[dict], n_tickers: int, warnings: list[str]) -> str:
    lines = [
        "---",
        "tags: [finance, stocks, calendar]",
        f"updated: {today.isoformat()}",
        "---",
        "",
        "# 📅 Catalyst calendar — shortlist (próximos 90 dias)",
        "",
        "> [!info] Auto-gerado por `update_shortlist.py` (v2.1). Eventos pulled de yfinance fresh.",
        ">",
        f"> {n_tickers} shortlist tickers · {len(events)} eventos no horizonte de 90 dias.",
        "",
        "| Date | Days | Ticker | Event | Score |",
        "|------|------|--------|-------|-------|",
    ]
    for e in events:
        days = (datetime.fromisoformat(e["date"]).date() - today).days
        lines.append(f"| {e['date']} | {days}d | {e['ticker']} | {e['event']} | {e['score']:.1f} |")
    if not events:
        lines.append("| — | — | — | (no events in window) | — |")
    lines.append("")
    if warnings:
        lines.append("## ⚠️ Warnings")
        lines.append("")
        for w in warnings[:10]:
            lines.append(f"- {w}")
        lines.append("")
    lines.append("## Ver também")
    lines.append("")
    lines.append("- [[_shortlist]] — active shortlist")
    lines.append("- `bd-stocks-earnings-preview` skill auto-fires 2 business days before any Earnings event in this calendar")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    rows = load_log()
    existing_md = SHORTLIST.read_text(encoding="utf-8") if SHORTLIST.exists() else ""
    manual_flags = parse_manual_reviewed(existing_md)
    md = build_shortlist(rows, manual_flags)
    SHORTLIST.write_text(md, encoding="utf-8")
    append_expired(rows)
    # v2.1: emit catalyst calendar alongside shortlist
    try:
        cal_md = build_catalyst_calendar(rows)
        CATALYST_CAL.write_text(cal_md, encoding="utf-8")
        log(f"catalyst calendar updated: {CATALYST_CAL}")
    except Exception as e:
        log(f"catalyst calendar build failed (non-fatal): {e}")
    log(f"shortlist updated: {SHORTLIST}")
    print(f'{{"shortlist_path": "{SHORTLIST}", "expired_path": "{EXPIRED}", "catalyst_calendar_path": "{CATALYST_CAL}"}}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
