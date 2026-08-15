r"""
token_stats.py — what a run actually cost, and what share of all Claude Code it represents.

Reads the session transcripts under ~/.claude/projects/**/*.jsonl and sums the `usage` block of
every assistant event. Nothing here talks to the API; it is pure post-hoc accounting over files the
CLI has already written, so it is safe to call from the email step after a run has finished.

WHY THE NUMBERS ARE WHAT THEY ARE
---------------------------------
* "Tokens" means input + output + cache-creation + cache-read. **Cache-read is ~93% of the total**,
  so this figure is dominated by re-reading context, not by generation. On a subscription plan it is
  billed at nothing; treat it as a VOLUME measure, not a bill.
* Attribution to a skill can NOT be done by searching for its name: CLAUDE.md, MEMORY.md and the
  available-skills catalogue are injected into every session, and the catalogue's own text contains
  strings like "/bd-stocks-portfolio". A naive match reports 100% of all usage as finance. We key on
  a real invocation instead — see FINANCE detection below.
* Subagent transcripts live at <project>/<parent-session-uuid>/subagents/<id>.jsonl and can never
  classify themselves (a subagent never types a slash command), so they inherit their parent's
  verdict.
"""
from __future__ import annotations

import json
import re
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")

_SKILLS = (r"bd-stocks-daily|bd_stocks_daily_growth|bd-stocks-prefilter"
           r"|bd-stocks-earnings-preview|bd-strategy-monthly|bd-stocks-portfolio")
_CMD = re.compile(rf"<command-name>[^<]*({_SKILLS})", re.IGNORECASE)
_TOOL = re.compile(rf'"(?:skill|name)"\s*:\s*"({_SKILLS})"', re.IGNORECASE)
_SLASH_START = re.compile(rf"^\s*/({_SKILLS})\b", re.IGNORECASE)
_INJECTED = re.compile(
    r"<system-reminder>.*?</system-reminder>|<local-command-caveat>.*?</local-command-caveat>",
    re.DOTALL)


def _own_words(ev: dict) -> str:
    msg = ev.get("message") or {}
    if msg.get("role") != "user":
        return ""
    c = msg.get("content")
    if isinstance(c, str):
        text = c
    elif isinstance(c, list):
        text = "\n".join(b.get("text", "") for b in c
                         if isinstance(b, dict) and b.get("type") == "text")
    else:
        return ""
    return _INJECTED.sub("", text)


# Identifying an UNATTENDED run, in two parts, because neither alone is sufficient:
#   1. its first user message is a bare slash-command envelope (no prose around it), and
#   2. it ran from the working directory every Stocks* .bat cds into.
# Matching marker strings (STOCKSDAILY_SCHEDULED, run_with_timeout) does NOT work: an interactive
# session that merely DISCUSSES the scheduler contains them, which billed 152M tokens of one such
# conversation to "the scheduled run" whose real cost is ~15M. Prompt shape alone does not work
# either: typing /bd-stocks-daily by hand produces the identical envelope.
_CMD_ONLY = re.compile(rf"^<command-message>[^<]*</command-message>\s*"
                       rf"<command-name>/({_SKILLS})</command-name>$", re.IGNORECASE)
SCHEDULED_PROJECT = "C--Github-BD-Finance-BD-Finance"


def _scan(path: Path) -> dict:
    """One transcript -> tokens, whether it invoked a finance skill, and its event timeline."""
    tokens = 0
    finance = False
    scheduled = False
    first_prompt = None
    events: list[tuple[datetime, int]] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if first_prompt is None and '"user"' in line:
                    try:
                        w = _own_words(json.loads(line)).strip()
                    except Exception:
                        w = ""
                    if w:
                        first_prompt = w
                        scheduled = bool(_CMD_ONLY.match(w))
                        if scheduled:
                            finance = True
                if not finance:
                    if _CMD.search(line) or _TOOL.search(line):
                        finance = True
                    elif ("/bd-stocks" in line or "/bd_stocks" in line
                          or "/bd-strategy" in line) and '"user"' in line:
                        try:
                            if _SLASH_START.search(_own_words(json.loads(line))):
                                finance = True
                        except Exception:
                            pass
                if '"usage"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                u = (ev.get("message") or {}).get("usage") or ev.get("usage")
                if not isinstance(u, dict):
                    continue
                n = sum(v for k, v in u.items() if k in FIELDS and isinstance(v, int))
                tokens += n
                ts = ev.get("timestamp")
                if ts:
                    try:
                        events.append((datetime.fromisoformat(ts.replace("Z", "+00:00")), n))
                    except ValueError:
                        pass
    except OSError:
        return {"tokens": 0, "finance": False, "scheduled": False, "events": []}
    return {"tokens": tokens, "finance": finance, "scheduled": scheduled, "events": events}


def _transcripts(since: datetime | None = None):
    """All transcripts, optionally only those touched since `since` (a cheap mtime prefilter that
    keeps the weekly figure from costing a full 900 MB sweep on every email)."""
    if not PROJECTS.is_dir():
        return
    cutoff = since.timestamp() if since else None
    for p in PROJECTS.rglob("*.jsonl"):
        try:
            if cutoff and p.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        yield p


def _key(p: Path) -> tuple[str, bool, str]:
    rel = p.relative_to(PROJECTS)
    is_sub = "subagents" in rel.parts
    parent = rel.parts[1] if is_sub and len(rel.parts) > 2 else p.stem
    return rel.parts[0], is_sub, parent


def weekly_share(days: int = 7) -> dict:
    """Finance skills as a share of ALL Claude Code usage over the trailing `days`."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    scanned = {}
    for p in _transcripts(since):
        scanned[p] = (_key(p), _scan(p))
    verdict = {k[2]: r["finance"] for k, r in scanned.values() if not k[1]}
    fin = tot = 0
    for (proj, is_sub, parent), r in scanned.values():
        is_fin = verdict.get(parent, r["finance"]) if is_sub else r["finance"]
        tot += r["tokens"]
        if is_fin:
            fin += r["tokens"]
    return {"days": days, "finance": fin, "total": tot,
            "pct": (100.0 * fin / tot) if tot else 0.0}


def run_cost(day: _date, report_times: dict[str, datetime] | None = None,
             scheduled_only: bool = True) -> dict:
    """Tokens spent by the finance skills on `day`, optionally split per report.

    `report_times` maps a label (ticker) to when its report file was written. Tokens are then
    sliced by those boundaries: everything generated between the previous report and this one is
    attributed to it. That is a real measurement, not a division — but it is only valid when the
    reports were written sequentially, so `per_report_exact` says whether to trust it.
    """
    since = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=1)
    sessions = []
    for p in _transcripts(since):
        key, r = _key(p), _scan(p)
        if not r["events"]:
            continue
        if any(e[0].date() == day for e in r["events"]):
            sessions.append((key, r))
    verdict = {k[2]: r["finance"] for k, r in sessions if not k[1]}
    sched_of = {k[2]: r["scheduled"] for k, r in sessions if not k[1]}
    fin_events: list[tuple[datetime, int]] = []
    total = 0
    for (proj, is_sub, parent), r in sessions:
        is_fin = verdict.get(parent, r["finance"]) if is_sub else r["finance"]
        if not is_fin:
            continue
        if scheduled_only and not (proj == SCHEDULED_PROJECT
                                   and (r["scheduled"] or sched_of.get(parent))):
            continue
        today_ev = [e for e in r["events"] if e[0].date() == day]
        fin_events.extend(today_ev)
        total += sum(n for _, n in today_ev)

    out = {"day": day.isoformat(), "total": total, "sessions": len(fin_events) and len(sessions),
           "per_report": {}, "per_report_exact": False}
    if not report_times or not fin_events:
        return out

    fin_events.sort(key=lambda e: e[0])
    order = sorted(report_times.items(), key=lambda kv: kv[1])
    prev = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    assigned = 0
    for label, when in order:
        w = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        n = sum(tok for ts, tok in fin_events if prev < ts <= w)
        out["per_report"][label] = n
        assigned += n
        prev = w
    # Trust the slicing only if it actually accounts for most of the run; otherwise the reports
    # were not written sequentially (or mtimes were touched later) and an even split is honester.
    out["per_report_exact"] = total > 0 and assigned >= 0.6 * total
    if not out["per_report_exact"] and report_times:
        share = total // max(1, len(report_times))
        out["per_report"] = {k: share for k in report_times}
    return out


def fmt(n: float) -> str:
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(n) >= div:
            return f"{n/div:,.2f}{unit}"
    return f"{n:,.0f}"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=_date.today().isoformat())
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    d = datetime.strptime(a.date, "%Y-%m-%d").date()
    rc = run_cost(d)
    ws = weekly_share(a.days)
    print(f"run {d}: {fmt(rc['total'])} tokens")
    print(f"last {ws['days']}d: finance {fmt(ws['finance'])} of {fmt(ws['total'])} "
          f"= {ws['pct']:.1f}% of all Claude Code")
