"""
build_dashboard.py — Regenerate the StocksDaily HTML dashboard from current Obsidian state.

Reads:
  * Every YYYY-MM-DD_*.md report at the root of StocksDaily/
  * _log.csv (for bear-case triggers)
  * _prefilter_stats.json
  * _dashboard/template.html (with __DATA__ marker)
  * _dashboard/template_brokers.html (with __DATA__ marker)

Writes:
  * _dashboard.html (overwritten without prompt)
  * _dashboard_brokers.html (standalone Broker Analysis page, linked from the main dashboard)

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
TEMPLATE_BROKERS = ROOT / "_dashboard" / "template_brokers.html"
OUTPUT = ROOT / "_dashboard.html"
OUTPUT_BROKERS = ROOT / "_dashboard_brokers.html"
LOG = ROOT / "_log.csv"
PREFILTER_STATS = ROOT / "_prefilter_stats.json"
PORTFOLIO_JSON = ROOT / "_portfolio.json"
THESIS_JSON = ROOT / "_thesis.json"
BROKERS_JSON = ROOT / "_brokers.json"
LIVE_PRICES_JSON = ROOT / "_live_prices.json"
TECH_DIR = ROOT / "_technical"
PREFILTERED_YAML = ROOT / "_prefiltered.yaml"
TMP_DIR = ROOT / "_tmp"

REPORT_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_.+\.md$")

# Fair price is only meaningful for names with good fundamentals (quality lens)
# or a good growth profile (growth lens).
FAIR_PRICE_VERDICTS = {"great", "invest", "review", "rocket", "accelerate", "watch"}

# Body fallbacks for reports written before fair_price landed in frontmatter.
# Only the canonical template forms are matched — anything else stays blank.
_DCF_BOLD_RE = re.compile(
    r"DCF intr[íi]nseco(?:\s*\(helper\))?:\s*\*\*\s*[^\d*]*([\d][\d,]*\.?\d*)\s*[A-Za-z$€£]*\s*\*\*"
)
_DCF_TABLE_RE = re.compile(r"\|\s*DCF intrinsic\s*\|\s*[^|\d]*([\d][\d,]*\.?\d*)")
_TARGET_ROW_RE = re.compile(
    r"\|\s*Price target \(mean / median\)\s*\|\s*[^\d|]*([\d][\d,]*\.?\d*)\s*/\s*[^\d|]*([\d][\d,]*\.?\d*)"
)


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


# Report H1 is `# {TICKER} — {Company name} — ...Score: ...` (both lenses)
_H1_COMPANY_RE = re.compile(r"^#\s+[^\n—]+—\s*([^\n—]+?)\s*—", re.M)
_COMPANY_SUFFIX_RE = re.compile(
    r"[,\s]+(incorporated|inc|corporation|corp|company|co|ltd|limited|plc|nv|n\.v"
    r"|sa|s\.a|se|ag|asa|ab|oyj|spa|s\.p\.a|holdings?|group)\.?$",
    re.IGNORECASE,
)


def extract_company(body: str) -> str | None:
    """Short company name from the report title — legal suffixes stripped
    iteratively ('Alibaba Group Holding Limited' -> 'Alibaba')."""
    m = _H1_COMPANY_RE.search(body)
    if not m:
        return None
    name, prev = m.group(1).strip(), None
    while name and name != prev:
        prev = name
        name = _COMPANY_SUFFIX_RE.sub("", name).strip().rstrip(",")
    return name or None


def _parse_price(s: str):
    return safe_float(s.replace(",", ""))


def extract_fair_price(fm: dict, body: str, verdict) -> tuple[float | None, str | None]:
    """Fair-price anchor for a report. Frontmatter wins (fair_price / fair_price_basis,
    written by the skill since 2026-06). For older reports, fall back to the canonical
    body lines — DCF intrinsic first, analyst consensus median second — but only for
    verdicts where a price anchor is meaningful (good fundamentals / good growth).
    A body-derived DCF more than ±70% away from price_at_eval is discarded, mirroring
    analyze_ticker's dcf_valid sanity trip (old reports quoted those DCFs anyway)."""
    fp = safe_float(fm.get("fair_price"))
    if fp is not None:
        return fp, fm.get("fair_price_basis") or "dcf"
    if verdict not in FAIR_PRICE_VERDICTS:
        return None, None
    price = safe_float(fm.get("price_at_eval"))
    m = _DCF_BOLD_RE.search(body) or _DCF_TABLE_RE.search(body)
    if m:
        dcf = _parse_price(m.group(1))
        if dcf and not (price and abs(dcf / price - 1) > 0.7):
            return dcf, "dcf"
    m = _TARGET_ROW_RE.search(body)
    if m:
        return _parse_price(m.group(2)), "consensus"
    return None, None


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

    verdict = fm.get("verdict")
    if verdict and verdict.strip().lower() in ("null", "none"):
        verdict = None
    fair_price, fair_price_basis = extract_fair_price(fm, body, verdict)

    return {
        "ticker": ticker,
        "company": extract_company(body),
        "exchange": fm.get("exchange"),
        "region": fm.get("region"),
        "sector": fm.get("sector"),
        "size": fm.get("size"),
        "date": date_str,
        "round": safe_int(fm.get("round")) or 1,
        # Growth-lens reports carry `lens: growth` instead of a mode
        "mode": fm.get("mode") or ("growth" if fm.get("lens") == "growth" else None),
        "verdict": verdict,
        "score": safe_float(fm.get("score")),
        "growth_composite": safe_float(fm.get("growth_composite")),
        "fair_price": fair_price,
        "fair_price_basis": fair_price_basis,
        "gates_passed": safe_int(fm.get("gates_passed")),
        "piotroski": safe_int(fm.get("piotroski_fscore")),
        "altman": safe_float(fm.get("altman_zscore")),
        "price": safe_float(fm.get("price_at_eval")),
        "currency": fm.get("currency"),
        "earnings_next": fm.get("earnings_date_next"),
        "mgmt": safe_float(fm.get("management_score")),
        "mgmt_flag": safe_bool(fm.get("management_flag")),
        "narrative_quality": fm.get("narrative_quality"),
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
        # ---- Phase-H news sentiment (frontmatter scalars, overlay) ----
        "news_sentiment": safe_float(fm.get("news_sentiment_stock")),
        "news_label": fm.get("news_sentiment_label"),
        # ---- Phase-I screener numerics (durable frontmatter; _tmp supplements P/E, FCF) ----
        "beta": safe_float(fm.get("beta_3y")),
        "alpha": safe_float(fm.get("alpha_ann_pct")),
        "mos_class": fm.get("mos_class"),
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


def load_portfolio() -> dict:
    """Read the precomputed _portfolio.json written by portfolio_dashboard.py.
    The dashboard computes nothing — it only renders this. Missing/invalid -> empty."""
    if not PORTFOLIO_JSON.exists():
        return {"holdings": []}
    try:
        return json.loads(PORTFOLIO_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"WARN: could not parse {PORTFOLIO_JSON}: {e}")
        return {"holdings": []}


def load_thesis() -> dict:
    """Read the precomputed _thesis.json written by thesis_dashboard.py.
    The dashboard computes nothing — it only renders this. Missing/invalid -> empty."""
    if not THESIS_JSON.exists():
        return {"names": []}
    try:
        return json.loads(THESIS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"WARN: could not parse {THESIS_JSON}: {e}")
        return {"names": []}


def load_brokers() -> dict:
    """Read the precomputed _brokers.json written by broker_compare.py.
    The dashboard computes nothing — it only renders this. Missing/invalid -> empty."""
    if not BROKERS_JSON.exists():
        return {"markets": [], "support_matrix": {}}
    try:
        return json.loads(BROKERS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"WARN: could not parse {BROKERS_JSON}: {e}")
        return {"markets": [], "support_matrix": {}}


def _fmt_range(v):
    if isinstance(v, (list, tuple)) and len(v) == 2 and all(x is not None for x in v):
        return f"{float(v[0]):.2f}–{float(v[1]):.2f}"
    return v or None


def load_technical_store() -> list[dict]:
    """Read _technical/*.json (Phase 3.5 persists one per ticker) so the Technical
    card shows ALL names with a tech read — frontmatter only covers reports written
    after the tech fields landed there."""
    out = []
    if not TECH_DIR.exists():
        return out
    for p in sorted(TECH_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"WARN: bad technical json {p.name}: {e}")
            continue
        out.append({
            "ticker": d.get("ticker") or p.stem,
            "tech_score": safe_float(d.get("technical_score")),
            "go_no_go": d.get("go_no_go"),
            "combined_score": safe_float(d.get("combined_score")),
            "fund_score": safe_float(d.get("fundamental_score")),
            "entry_zone": _fmt_range(d.get("entry_zone")),
            "stop_loss": _fmt_range(d.get("suggested_stop_loss")),
            "tech_risk": d.get("risk_level"),
            "fetched_at": d.get("fetched_at"),
        })
    return out


def load_live_prices(reports: list[dict], tech_store: list[dict], skip: bool) -> dict:
    """Refresh + read _live_prices.json for tickers carrying a technical read, so the
    Technical card can compare live price vs entry zone ("buy range"). The yfinance
    fetch lives in live_prices.py (subprocess) — this module stays import-stdlib-only.
    Any failure degrades to the last JSON on disk, or to no live column at all."""
    tickers = sorted(
        {
            r["ticker"] for r in reports
            if r.get("tech_score") is not None and (r.get("score") or 0) >= 7.0 and r.get("entry_zone")
        }
        | {s["ticker"] for s in tech_store if s.get("entry_zone") and (s.get("fund_score") or 0) >= 7.0}
    )
    if tickers and not skip:
        try:
            import subprocess
            subprocess.run(
                [sys.executable, str(Path(__file__).parent / "live_prices.py"),
                 "--tickers", ",".join(tickers)],
                timeout=180, check=False,
            )
        except Exception as e:
            log(f"WARN: live price refresh failed (non-fatal): {e}")
    if not LIVE_PRICES_JSON.exists():
        return {"prices": {}}
    try:
        return json.loads(LIVE_PRICES_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"WARN: could not parse {LIVE_PRICES_JSON}: {e}")
        return {"prices": {}}


def _yaml_scalar(v: str):
    """Unquote a simple YAML scalar. Numbers stay strings (consumers coerce)."""
    v = v.strip()
    if len(v) >= 2 and v[0] in "'\"" and v[-1] == v[0]:
        return v[1:-1]
    return v


def load_universe() -> list[dict]:
    """Minimal line-based reader for the `tickers:` list in _prefiltered.yaml — the
    full pre-filtered pool (region/size/sector/composite/gates/piotroski/altman). No
    pyyaml (this module is stdlib-only); each record starts at a '- ' line and its
    indented 'key: value' lines belong to it. Returns [] on any problem."""
    if not PREFILTERED_YAML.exists():
        return []
    try:
        lines = PREFILTERED_YAML.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        log(f"WARN: could not read {PREFILTERED_YAML}: {e}")
        return []
    rows: list[dict] = []
    cur: dict | None = None
    in_tickers = False
    for raw in lines:
        if not in_tickers:
            if raw.rstrip() == "tickers:":
                in_tickers = True
            continue
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        starts_record = stripped.startswith("- ")
        if starts_record:
            if cur:
                rows.append(cur)
            cur = {}
            stripped = stripped[2:].strip()
        if cur is None or ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        cur[key.strip()] = _yaml_scalar(val)
    if cur:
        rows.append(cur)
    return rows


def enrich_from_tmp(ticker: str, date: str) -> dict:
    """Pull screener numerics an evaluated report doesn't carry in frontmatter, from
    the in-flight analysis JSON _tmp/{date}_{ticker}.json (Phase-B/E overlays):
    P/E, FCF yield, α, β, margin-of-safety class/%. Returns {} if absent/unreadable."""
    if not ticker or not date:
        return {}
    p = TMP_DIR / f"{date}_{ticker.replace('/', '_')}.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    ts = d.get("top_strip") or {}
    ab = d.get("alpha_beta") or {}
    iv = d.get("intrinsic_value") or {}
    return {
        "pe": safe_float(ts.get("pe_ttm")),
        "fcf_yield": safe_float(ts.get("fcf_yield_pct")),
        "beta": safe_float(ab.get("beta")),
        "alpha": safe_float(ab.get("alpha_ann_pct")),
        "mos_class": iv.get("mos_class"),
        "mos_pct": safe_float(iv.get("mos_pct")),
    }


def _report_href(filename: str | None) -> str | None:
    """The Phase-F HTML report is a sibling of the .md (same base). None if no report."""
    if filename and filename.endswith(".md"):
        return filename[:-3] + ".html"
    return None


def build_screener(reports: list[dict], universe: list[dict]) -> list[dict]:
    """Full-pool screener rows: the pre-filtered universe LEFT-JOINed with evaluated
    reports (by ticker, latest report wins), enriched with _tmp numerics. Evaluated
    names carry verdict/score + a report link; pool-only names carry universe stats.
    Evaluated names outside the pool (e.g. portfolio adds) are appended too."""
    by_ticker: dict[str, dict] = {}
    for r in reports:  # reports arrive filename-sorted (date asc) → last write wins
        if r.get("ticker"):
            by_ticker[r["ticker"]] = r

    def row_for(tk: str, u: dict | None) -> dict:
        r = by_ticker.get(tk)
        u = u or {}
        upside = None
        fp, px = (r or {}).get("fair_price"), (r or {}).get("price")
        if fp and px:
            upside = round((fp / px - 1) * 100, 1)
        row = {
            "ticker": tk,
            "region": (r or {}).get("region") or u.get("region"),
            "sector": (r or {}).get("sector") or u.get("sector"),
            "size": (r or {}).get("size") or u.get("size"),
            "evaluated": bool(r),
            # composite: the evaluated score if present, else the prefilter composite
            "composite": (r or {}).get("score")
            if r else safe_float(u.get("composite_score")),
            "verdict": (r or {}).get("verdict"),
            "gates_passed": (r or {}).get("gates_passed")
            if r else safe_int(u.get("gates_passed")),
            "piotroski": (r or {}).get("piotroski") if r else safe_int(u.get("piotroski")),
            "altman": (r or {}).get("altman") if r else safe_float(u.get("altman_z")),
            "tech_score": (r or {}).get("tech_score"),
            "go_no_go": (r or {}).get("go_no_go"),
            "fair_price": fp,
            "upside": upside,
            "currency": (r or {}).get("currency"),
            "date": (r or {}).get("date"),
            "report_href": _report_href((r or {}).get("filename")),
        }
        if r:
            # Durable frontmatter (β/α/MoS) wins; _tmp supplements P/E & FCF yield
            # and fills any gap the older-frontmatter reports leave.
            e = enrich_from_tmp(tk, r.get("date"))
            row["beta"] = r.get("beta") if r.get("beta") is not None else e.get("beta")
            row["alpha"] = r.get("alpha") if r.get("alpha") is not None else e.get("alpha")
            row["mos_class"] = r.get("mos_class") or e.get("mos_class")
            row["mos_pct"] = e.get("mos_pct")
            row["pe"] = e.get("pe")
            row["fcf_yield"] = e.get("fcf_yield")
        return row

    seen, rows = set(), []
    for u in universe:
        tk = u.get("ticker")
        if not tk or tk in seen:
            continue
        seen.add(tk)
        rows.append(row_for(tk, u))
    for tk in by_ticker:
        if tk not in seen:
            seen.add(tk)
            rows.append(row_for(tk, None))
    return rows


def dump_for_script(bundle: dict) -> str:
    """JSON for embedding inside a <script> block: escape "</" so a literal
    "</script>" in report text can't close the data block and blank the page."""
    return json.dumps(bundle, ensure_ascii=False).replace("</", "<\\/")


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

    generated_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    bundle = {
        "generated_at": generated_at,
        "today": today.isoformat(),
        "reports": reports,
        "bear_triggers": load_bear_triggers(),
        "prefilter": load_prefilter(),
        "portfolio": load_portfolio(),
        "thesis": load_thesis(),
        "technical_store": (tech_store := load_technical_store()),
        "live_prices": load_live_prices(reports, tech_store, skip="--no-live" in sys.argv),
        "screener": build_screener(reports, load_universe()),
    }

    template = TEMPLATE.read_text(encoding="utf-8")
    rendered = template.replace("__DATA__", dump_for_script(bundle), 1)
    OUTPUT.write_text(rendered, encoding="utf-8")

    # Broker Analysis lives on its own page (linked from the main dashboard)
    if TEMPLATE_BROKERS.exists():
        broker_bundle = {
            "generated_at": generated_at,
            "today": today.isoformat(),
            "brokers": load_brokers(),
        }
        broker_template = TEMPLATE_BROKERS.read_text(encoding="utf-8")
        broker_rendered = broker_template.replace("__DATA__", dump_for_script(broker_bundle), 1)
        OUTPUT_BROKERS.write_text(broker_rendered, encoding="utf-8")
    else:
        log(f"WARN: broker template not found at {TEMPLATE_BROKERS} — skipping {OUTPUT_BROKERS.name}")

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
    if OUTPUT_BROKERS.exists():
        print(f"Wrote {OUTPUT_BROKERS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
