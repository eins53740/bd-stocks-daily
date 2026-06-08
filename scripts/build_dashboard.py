"""
build_dashboard.py — Regenerate the StocksDaily HTML dashboard from current Obsidian state.

Reads:
  * Every YYYY-MM-DD_*.md report at the root of StocksDaily/
  * _log.csv (for bear-case triggers)
  * _prefilter_stats.json
  * _dashboard/template.html (with __DATA__ marker)

Writes:
  * _dashboard.html (overwritten without prompt)

stdlib-only by design — no yfinance / requests / bs4 / yaml. Frontmatter parsing is line-based.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# Avoid creating __pycache__ next to the script
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONPYCACHEPREFIX", str(Path(tempfile.gettempdir()) / "stocksdaily_pyc"))

ROOT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
TEMPLATE = ROOT / "_dashboard" / "template.html"
OUTPUT = ROOT / "_dashboard.html"
LOG = ROOT / "_log.csv"
PREFILTER_STATS = ROOT / "_prefilter_stats.json"

REPORT_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_.+\.md$")


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def parse_frontmatter(text: str) -> dict:
    """
    Pull the leading --- ... --- block and parse it as `key: value` lines.
    Skips list items (lines starting with '- ') and any keys whose value
    is multiline (bracketed).
    """
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end].lstrip("\n")
    fm: dict = {}
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("- "):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        # Skip "tags: [..]" array values for our slim purposes — we only need scalars
        if val.startswith("[") and val.endswith("]"):
            continue
        # Strip surrounding quotes (single or double)
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        fm[key] = val
    return fm


def safe_float(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def safe_int(v):
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def safe_bool(v) -> bool:
    return str(v).lower() in ("true", "yes", "1")


def extract_field(body: str, label: str) -> str | None:
    """
    Pull a `**Label**: ...` block from the report body. Captures everything up to a
    blank line, the next callout marker (\n>), or end-of-input. Strips trailing > used
    in callout blocks.
    """
    pat = re.compile(
        rf"\*\*{re.escape(label)}\*\*:\s*(.*?)(?:\n\s*\n|\n>|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    m = pat.search(body)
    if not m:
        return None
    out = m.group(1).strip()
    # Strip leading "> " quoting on subsequent lines (callout)
    out = "\n".join(re.sub(r"^>\s?", "", ln) for ln in out.splitlines())
    out = out.strip()
    # Trim trailing markdown noise
    if out.endswith(">"):
        out = out[:-1].rstrip()
    return out or None


def slim_report(path: Path, today: dt.date) -> dict | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = parse_frontmatter(text)
    if not fm:
        return None
    # Only include reports that actually have a ticker + date in frontmatter
    ticker = fm.get("ticker")
    date_str = fm.get("date")
    if not ticker or not date_str:
        return None
    # Body = everything after frontmatter close
    body_start = text.find("\n---", 3)
    body = text[body_start + 4 :] if body_start != -1 else text

    try:
        report_date = dt.date.fromisoformat(date_str)
    except ValueError:
        report_date = today

    expires = report_date + dt.timedelta(days=90)
    days_left = (expires - today).days

    # Risks label varies (Risks vs Risk)
    risks = extract_field(body, "Risks") or extract_field(body, "Risk")

    return {
        "ticker": ticker,
        "exchange": fm.get("exchange"),
        "region": fm.get("region"),
        "sector": fm.get("sector"),
        "size": fm.get("size"),
        "date": date_str,
        "round": safe_int(fm.get("round")) or 1,
        "mode": fm.get("mode"),
        "verdict": fm.get("verdict"),
        "score": safe_float(fm.get("score")),
        "gates_passed": safe_int(fm.get("gates_passed")),
        "piotroski": safe_int(fm.get("piotroski_fscore")),
        "altman": safe_float(fm.get("altman_zscore")),
        "price": safe_float(fm.get("price_at_eval")),
        "currency": fm.get("currency"),
        "earnings_next": fm.get("earnings_date_next"),
        "mgmt": safe_float(fm.get("management_score")),
        "mgmt_flag": safe_bool(fm.get("management_flag")),
        "expires": expires.isoformat(),
        "days_left": days_left,
        "filename": path.name,
        "thesis": extract_field(body, "Thesis"),
        "risks": risks,
        "action": extract_field(body, "Action"),
        # ---- Phase-3 technical fields (frontmatter, scalars only) ----
        "tech_score": safe_float(fm.get("technical_score")),
        "go_no_go": fm.get("go_no_go"),
        "combined_score": safe_float(fm.get("combined_score")),
        "entry_zone": fm.get("entry_zone"),
        "stop_loss": fm.get("suggested_stop_loss"),
        "tech_risk": fm.get("tech_risk_level"),
    }


def load_bear_triggers() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    with LOG.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            trig = (row.get("bear_case_trigger") or "").strip()
            if not trig:
                continue
            out.append({
                "ticker": row.get("ticker"),
                "date": row.get("date"),
                "trigger": trig,
                "verdict": row.get("verdict"),
                "score": safe_float(row.get("score")),
            })
    return out


def load_prefilter() -> dict:
    if not PREFILTER_STATS.exists():
        return {}
    try:
        return json.loads(PREFILTER_STATS.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"WARN: could not parse {PREFILTER_STATS}: {e}")
        return {}


def main() -> int:
    if not TEMPLATE.exists():
        log(f"ERROR: template not found at {TEMPLATE}")
        return 1

    today = dt.date.today()
    reports: list[dict] = []
    for p in sorted(ROOT.glob("*.md")):
        if not REPORT_NAME_RE.match(p.name):
            continue
        slim = slim_report(p, today)
        if slim is not None:
            reports.append(slim)

    bundle = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "today": today.isoformat(),
        "reports": reports,
        "bear_triggers": load_bear_triggers(),
        "prefilter": load_prefilter(),
    }

    template = TEMPLATE.read_text(encoding="utf-8")
    rendered = template.replace("__DATA__", json.dumps(bundle, ensure_ascii=False), 1)
    OUTPUT.write_text(rendered, encoding="utf-8")

    # Summary
    active_shortlist = [r for r in reports if (r.get("score") or 0) >= 7.5 and (r.get("days_left") or 0) > 0]
    flagged = [r for r in reports if r.get("mgmt_flag")]
    top3 = sorted(reports, key=lambda r: (r.get("score") or 0), reverse=True)[:3]
    print(f"Total reports:     {len(reports)}")
    print(f"Active shortlist:  {len(active_shortlist)} (score>=7.5 and days_left>0)")
    print(f"Mgmt flagged:      {len(flagged)}")
    if top3:
        print("Top 3 by score:")
        for r in top3:
            print(f"  - {r['ticker']:<10} {r.get('score','?'):>5}/10  {r.get('verdict','?')}  ({r.get('date')})")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
