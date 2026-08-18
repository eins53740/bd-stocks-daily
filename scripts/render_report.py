"""
render_report.py — v4 Phase F: deterministic HTML-primary report renderer.

Reads a deep report's markdown (frontmatter + narrative) + its analysis JSON and
emits a self-contained, static (JS-free) HTML file matching the locked design
`docs/v4_design/sample_report_v2.html`. HTML is the primary artifact; the md stays
the source (frozen contract — this script only READS it).

Design (audit-fixed): NOT the dashboard's client-JS `__DATA__` pattern. Python-side
templating against `report_template.html`: list builders for variable-length
sections + programmatic inline SVG (radar / gauge / range-bar / sparklines). The
existing matplotlib PNGs (from render_charts.py, in OUT_DIR/IMG/) are embedded
base64 under a ≤1.5 MB budget. Every visual has a null render.

Pure stdlib — no pandas/yfinance/markdown lib — so it runs under uv AND ambient and
its logic is fully unit-testable. Overlay-only: reads the analysis JSON, never
writes to it, never touches composite/verdict.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

def _sibling(mod_name):
    """Import a sibling script whether or not scripts/ is on sys.path."""
    try:
        return __import__(mod_name)
    except ImportError:  # pragma: no cover - only if scripts/ not on path
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            mod_name, Path(__file__).resolve().parent / f"{mod_name}.py")
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod


glossary = _sibling("metrics_glossary")
# Pure function of the analysis JSON, so it is COMPUTED here rather than persisted. A
# stored star could disagree with the published bands after a band change; a computed one
# cannot. `star_ratings.py` also has a CLI, so any other consumer gets the same numbers.
star_ratings = _sibling("star_ratings")
markets = _sibling("markets")
version = _sibling("version")
# Pure stdlib, like this module — see mermaid_render's docstring for why it does not
# import chart_theme (and therefore matplotlib) to get its ink.
mermaid_render = _sibling("mermaid_render")

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE = SCRIPT_DIR / "report_template.html"
ICON = SCRIPT_DIR.parent / "docs" / "v4_design" / "assets" / "bdfinance_icon.png"
OUT_DIR_DEFAULT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
# ≤~1.5 MB of embedded PNGs per report (spec §11). Re-measured for v4.3 before
# adding to it, not after: a full MPWR deep dive spends 459 KB — 8 charts plus a
# Sankey at 358 KB, the two new v4.3 charts at 101 KB — so 31% of the cap. The
# cap stands unchanged; there was no need to raise it or downscale anything.
IMG_BUDGET_BYTES = 1_500_000
# Cover prose (thesis + risk + bear trigger + exit trigger) that still fits on one printed
# A4 page. Derived from four measured covers — see build_cover for the working. Advisory:
# exceeding it logs, never truncates.
COVER_PROSE_BUDGET_CHARS = 1200

VERDICT_LABELS = {"great": "GREAT", "invest": "INVEST", "review": "REVIEW",
                  "fair": "FAIR", "reject": "REJECT"}
VERDICT_EMOJI = {"great": "🟢", "invest": "🟢", "review": "🟡", "fair": "🟠", "reject": "🔴"}
# PNG embedding priority (highest first) — lowest are dropped when over budget.
CHART_ORDER = ["price", "ni_pe", "ebitda_fcf", "evolution", "relperf", "peers5y",
               "dcf", "peers", "radar", "segments"]


def log(msg: str) -> None:
    print(f"[render_report] {msg}", file=sys.stderr)


def esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


# ===================================================================
# Pure helpers (unit-tested)
# ===================================================================
def _num(v):
    # Accept real numbers AND numeric strings — frontmatter values arrive as strings
    # (fair_price, score…), and rejecting them silently printed "n/a" everywhere.
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else v
    if isinstance(v, str):
        try:
            f = float(v.strip())
        except ValueError:
            return None
        return None if math.isnan(f) else f
    return None


CURRENCY_SYMBOL = {"EUR": "€", "USD": "$", "GBP": "£", "GBp": "p", "GBX": "p",
                   "JPY": "¥", "CHF": "CHF ", "TWD": "NT$", "HKD": "HK$", "DKK": "kr "}


def fmt_money(v, currency) -> str:
    n = _num(v)
    if n is None:
        return "n/a"
    sym = CURRENCY_SYMBOL.get(currency or "", (currency + " ") if currency else "")
    return f"{sym}{n:,.2f}"


def fmt_pct(v, decimals=1) -> str:
    n = _num(v)
    return "n/a" if n is None else f"{n:.{decimals}f}%"


def action_verb(verdict, mos_class, go_no_go) -> str:
    """Deterministic answer-first verb (spec §11): verdict × MoS × tech GO/NO-GO
    → {ACCUMULATE, BUY-DIP, HOLD, WATCH, AVOID}."""
    v = (verdict or "").lower()
    if v == "reject":
        return "AVOID"
    if v == "fair" or v not in ("great", "invest", "review"):
        return "WATCH"  # quality not established (or unknown verdict)
    # quality established (great/invest/review) — price/timing decide the verb
    if mos_class == "rich":
        return "WATCH"                       # good company, price too high
    if mos_class in ("deep_value", "fair"):
        return "BUY-DIP" if go_no_go == "NO-GO" else "ACCUMULATE"
    return "HOLD"                            # mos not_computable / absent


def gate_family_scores(scores: dict, red_flags: dict | None) -> dict:
    """Derive the 5-axis snowflake (Quality/Value/Growth/Health/Mgmt) from the
    7-axis `scores` + red-flag statement sub-scores. Missing axis → None."""
    scores = scores or {}

    def g(k):
        return _num(scores.get(k))

    def mean(vals):
        vals = [x for x in vals if x is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    rf = red_flags or {}
    health = mean([_num((rf.get("balance") or {}).get("subscore_0_10")),
                   _num((rf.get("cashflow") or {}).get("subscore_0_10"))])
    if health is None:
        health = g("fundamentals")
    return {
        "Quality": mean([g("fundamentals"), g("moat")]) if (g("fundamentals") or g("moat")) is not None else None,
        "Value": g("valuation"),
        "Growth": g("growth_durability"),
        "Health": health,
        "Mgmt": g("management"),
    }


def radar_svg(fam: dict) -> str:
    """Inline-SVG pentagon of the 5 gate-family scores. "" when <3 axes available
    (mirror render_charts thin-score gating). cx,cy=100,100, R=80, 72°/axis from top."""
    order = ["Quality", "Value", "Growth", "Health", "Mgmt"]
    vals = [_num(fam.get(a)) for a in order]
    if sum(1 for v in vals if v is not None) < 3:
        return ""
    cx = cy = 100.0
    R = 80.0

    def pt(v, idx):
        r = (max(0.0, min(10.0, v)) / 10.0) * R
        a = math.radians(72 * idx)
        return cx + r * math.sin(a), cy - r * math.cos(a)

    def poly(vs):
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(v, i) for i, v in enumerate(vs)))

    ring10 = poly([10] * 5)
    ring5 = poly([5] * 5)
    data = poly([v if v is not None else 0 for v in vals])
    label_pos = [("Quality", 100, 12, "middle"), ("Value", 186, 74, "start"),
                 ("Growth", 150, 186, "middle"), ("Health", 50, 186, "middle"),
                 ("Mgmt", 14, 74, "end")]
    labels = "".join(
        f'<text x="{x}" y="{y}" text-anchor="{anc}">{esc(name)}'
        f'{(" %.1f" % v) if v is not None else " n/a"}</text>'
        for (name, x, y, anc), v in zip(label_pos, vals))
    return (f'<svg viewBox="0 0 200 198" width="210" role="img" aria-label="Gate-family radar">'
            f'<polygon points="{ring10}" fill="none" stroke="#E4EAE7" stroke-width="1"/>'
            f'<polygon points="{ring5}" fill="none" stroke="#EDF2EF" stroke-width="1"/>'
            f'<polygon points="{data}" fill="rgba(31,138,91,.22)" stroke="#1F8A5B" stroke-width="2"/>'
            f'<g font-size="9.5" fill="#5B6B66" font-family="Arial">{labels}</g></svg>')


def gauge_marker_pct(price, fair_mid) -> float | None:
    """Marker position 3–97% on the expensive→cheap gauge from price vs fair-mid."""
    p, m = _num(price), _num(fair_mid)
    if p is None or m is None or m <= 0:
        return None
    return max(3.0, min(97.0, 50.0 + ((m - p) / m) * 100.0))


def range_bar_pcts(low, mid, high) -> tuple | None:
    """(bear%, base%, bull%) ticks for the fair-value range bar. None if unusable."""
    lo, md, hi = _num(low), _num(mid), _num(high)
    if None in (lo, md, hi) or hi <= lo:
        return None
    bear, bull = 15.0, 94.0
    base = bear + (md - lo) / (hi - lo) * (bull - bear)
    return bear, max(bear, min(bull, base)), bull


def sparkline_svg(series, color="#1F8A5B") -> str:
    vals = [float(v) for v in (series or []) if isinstance(v, (int, float))]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pts = [(i / (n - 1) * 66.0, 17.0 - (v - lo) / rng * 15.0) for i, v in enumerate(vals)]
    poly = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)
    ex, ey = pts[-1]
    return (f'<svg class="spark" width="66" height="18" viewBox="0 0 66 18">'
            f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="1.5"/>'
            f'<circle cx="{ex:.0f}" cy="{ey:.0f}" r="2" fill="{color}"/></svg>')


def grade_letter(percentile) -> str | None:
    p = _num(percentile)
    if p is None:
        return None
    if p >= 75:
        return "A"
    if p >= 50:
        return "B"
    if p >= 25:
        return "C"
    return "D"


# ---- markdown helpers (frozen-contract reads + appendix) ----
def split_frontmatter(md: str) -> tuple[dict, str]:
    fm: dict = {}
    body = md
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end != -1:
            block = md[3:end]
            body = md[end + 4:].lstrip("\n")
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("- ") or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                v = v.strip()
                if v.startswith("[") and v.endswith("]"):
                    continue
                fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


def extract_label(body: str, label: str) -> str | None:
    """Same capture as build_dashboard.extract_field for the frozen `**Label**:` form."""
    pat = re.compile(rf"\*\*{re.escape(label)}\*\*:\s*(.*?)(?:\n\s*\n|\n>|\Z)",
                     re.DOTALL | re.IGNORECASE)
    m = pat.search(body)
    if not m:
        return None
    return re.sub(r"^\s*>\s?", "", m.group(1).strip(), flags=re.M).strip() or None


_HEADING_RE = re.compile(r"^(#{1,6})\s")


def extract_section(body: str, pattern: str) -> str | None:
    """The text under the first heading matching `pattern`, up to the next heading of
    the same or higher level.

    Matched with `re.search` against the heading's own text, not `==`, because these
    headings carry decoration the prompts vary freely: emoji, a score
    ("### 🏰 MOAT — 8.95/10 · WIDE") and italic parentheticals
    ("### 2.18a SWOT *(v4 Phase C · overlay …)*"). Anchoring on the stable words and
    letting the rest float is what makes this survive a prompt edit.
    """
    rx = re.compile(pattern, re.IGNORECASE)
    lines = (body or "").split("\n")
    start = level = None
    for i, ln in enumerate(lines):
        m = _HEADING_RE.match(ln.strip())
        if not m:
            continue
        if start is None:
            if rx.search(ln):
                start, level = i + 1, len(m.group(1))
            continue
        if len(m.group(1)) <= level:
            return "\n".join(lines[start:i]).strip() or None
    if start is None:
        return None
    return "\n".join(lines[start:]).strip() or None


def parse_md_table(chunk: str) -> list[list[str]]:
    """The first markdown table in `chunk` as rows of raw cell text, separator dropped.

    Returns [] when there is no table. Cells keep their markdown — callers run them
    through the same inline formatter the appendix uses, so bold and code survive.
    """
    rows: list[list[str]] = []
    for ln in (chunk or "").split("\n"):
        s = ln.strip()
        if not s.startswith("|"):
            if rows:
                break          # table ended
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(set(c) <= set("-: ") and c for c in cells):
            continue           # the |---|---| separator
        rows.append(cells)
    return rows


def extract_callout(body: str, kind: str) -> tuple[str, list[str]] | None:
    """An Obsidian callout `> [!kind] title` → (title, following lines).

    Used for the v4.2 LEAN verdict (`[!abstract] ⚖️ MAIS PROVÁVEL: …`), which lives in
    the markdown and had no path into the HTML at all.
    """
    lines = (body or "").split("\n")
    head = re.compile(r"^\s*>\s*\[!" + re.escape(kind) + r"\]\s*(.*)$", re.IGNORECASE)
    for i, ln in enumerate(lines):
        m = head.match(ln)
        if not m:
            continue
        rest = []
        for nxt in lines[i + 1:]:
            if not nxt.strip().startswith(">"):
                break
            rest.append(re.sub(r"^\s*>\s?", "", nxt).strip())
        return m.group(1).strip(), [r for r in rest if r]
    return None


_INLINE = [(re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"),
           # Single-asterisk italics run AFTER bold, so `**x**` is already <b>x</b> and
           # cannot be re-matched. The lookarounds stop a stray `*` from swallowing the
           # rest of a line. Without this rule the reports leaked literal asterisks into
           # the HTML — "*and*", "*negative*", "*(inferred)*" all appear in real prose.
           (re.compile(r"(?<![\*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\*\w])"), r"<i>\1</i>"),
           (re.compile(r"`(.+?)`"), r"<code>\1</code>"),
           (re.compile(r"==(.+?)=="), r"<mark>\1</mark>")]


def md_inline(t) -> str:
    """Escape, then apply the inline markdown the reports actually use.
    Module-level because the card builders format single cells with it, not just
    the appendix."""
    t = esc(t)
    for pat, rep in _INLINE:
        t = pat.sub(rep, t)
    return t


def md_to_html(body: str) -> str:
    """Minimal, dependency-free markdown→HTML for the collapsible appendix.
    Handles headings, bold/code/highlight, tables, lists, blockquotes/callouts,
    hr and paragraphs. Not a full parser — enough for the report's own prose."""
    lines = body.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    inline = md_inline

    while i < n:
        ln = lines[i]
        s = ln.strip()
        if not s:
            i += 1
            continue
        if re.match(r"^#{1,6}\s", s):
            lvl = len(s) - len(s.lstrip("#"))
            out.append(f"<h{min(lvl,4)}>{inline(s[lvl:].strip())}</h{min(lvl,4)}>")
            i += 1
        elif s.startswith("|") and "|" in s[1:]:
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
            body_rows = [r for r in cells if not all(set(c) <= set("-: ") for c in r)]
            html_rows = []
            for ri, r in enumerate(body_rows):
                tag = "th" if ri == 0 else "td"
                html_rows.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in r) + "</tr>")
            out.append("<table>" + "".join(html_rows) + "</table>")
        elif re.match(r"^[-*]\s", s):
            items = []
            while i < n and re.match(r"^\s*[-*]\s", lines[i]):
                items.append(f"<li>{inline(re.sub(r'^\s*[-*]\s', '', lines[i]))}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
        elif s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{inline(' '.join(x for x in buf if x.strip()))}</blockquote>")
        elif re.match(r"^(-{3,}|\*{3,})$", s):
            out.append("<hr>")
            i += 1
        else:
            out.append(f"<p>{inline(s)}</p>")
            i += 1
    return "\n".join(out)


# ===================================================================
# Section builders (return HTML strings)
# ===================================================================
def _card(title, inner, anchor=None, new=False):
    """`new` may be True (legacy "v4" badge) or a version string like "v4.3" — a badge
    that says v4 on a card introduced in v4.3 tells the reader the wrong thing about
    what changed in the report they are holding."""
    aid = f' id="{anchor}"' if anchor else ""
    ver = "v4" if new is True else new
    tag = f'<span class="new">NEW · {esc(ver)}</span>' if new else ""
    return (f'<section class="card"{aid}><h2><span class="pip"></span>{esc(title)}{tag}</h2>'
            f'{inner}</section>')


def _external_links(ticker: str) -> str:
    """External deep links for the header. Empty when nothing is verifiable.

    Only GuruFocus for now, and only for the venues `markets._GURUFOCUS_PREFIX` was
    confirmed against live pages. An unmapped venue emits **no link** rather than a
    guessed one — a 404 in a report you act on is worse than no link at all.
    """
    url = markets.gurufocus_url(ticker or "")
    if not url:
        return ""
    return (f' · <a href="{esc(url)}" target="_blank" rel="noopener noreferrer">GuruFocus</a>')


def build_header(data, fm, icon_b64):
    ticker = data.get("ticker") or fm.get("ticker") or "?"
    name = data.get("company_name") or ""
    sector = data.get("sector") or fm.get("sector") or ""
    region = data.get("region") or fm.get("region") or ""
    currency = data.get("currency") or fm.get("currency")
    verdict = (data.get("verdict") or fm.get("verdict") or "").lower()
    score = _num((data.get("scores") or {}).get("composite")) or _num(fm.get("score"))
    iv = data.get("intrinsic_value") or {}
    mos_class = iv.get("mos_class")
    mos_pct = _num(iv.get("mos_pct"))
    go = fm.get("go_no_go")
    verb = action_verb(verdict, mos_class, go)
    asof = (data.get("fetched_at") or fm.get("date") or "")[:10]
    icon = f'<img class="brand-icon" alt="BD Finance" src="data:image/png;base64,{icon_b64}">' if icon_b64 else ""
    price = fmt_money(data.get("price_current"), currency)
    mos_txt = (f"Price {abs(mos_pct):.0f}% {'below' if mos_pct >= 0 else 'above'} fair value"
               if mos_pct is not None else "MoS n/a")
    score_txt = f"{score:.1f}/10" if score is not None else "n/a"
    vclass = verdict if verdict in VERDICT_LABELS else "review"
    dial = f'{score:.1f}' if score is not None else '–'
    return (
        '<header>'
        f'<div class="brand">{icon}<div class="brand-txt"><span class="wm">BD <b>Finance</b></span>'
        '<small>EQUITY RESEARCH</small></div></div>'
        '<div class="hdr-mid">'
        f'<div class="tk">{esc(name or ticker)} · {esc(ticker)}</div>'
        f'<div class="sub">{esc(sector)}{" · " + esc(region) if region else ""} · Quality Compounder · as-of {esc(asof)}{_external_links(ticker)}</div>'
        f'<div class="decide">Quality <b>{esc(score_txt)}</b> · {esc(mos_txt)} · Horizon 1–5y → <b>{esc(verb)}</b></div>'
        '</div>'
        f'<div class="hdr-right"><div class="verdict {vclass}">{esc(VERDICT_LABELS.get(verdict,"REVIEW"))}</div>'
        f'<div class="dial">{esc(dial)}<small>QUALITY</small></div></div>'
        '</header>')


def _metric_tile(k, v, sub="", spark=""):
    sub_html = f'<div class="sub">{esc(sub)}</div>' if sub else ""
    spark_html = f'<div class="spark">{spark}</div>' if spark else ""
    return (f'<div class="metric"><div class="k">{esc(k)}</div>'
            f'<div class="v">{v}</div>{spark_html}{sub_html}</div>')


def build_hero(data):
    scores = data.get("scores") or {}
    rf = data.get("red_flags") or {}
    ts = data.get("top_strip") or {}
    ab = data.get("alpha_beta") or {}
    cur = data.get("currency")
    radar = radar_svg(gate_family_scores(scores, rf))
    snow = (f'<figure class="snow">{radar}<figcaption>Gate-family shape (0–10 each)</figcaption></figure>'
            if radar else '<div class="nabox">Radar n/a (thin scores).</div>')

    cagr = (ab.get("price_cagr_ladder") or {})
    cagr_series = [cagr.get(k) for k in ("1y", "3y", "5y", "10y", "15y") if _num(cagr.get(k)) is not None]
    r1y = _num(ts.get("price_return_1y_pct"))
    tiles = []
    tiles.append(_metric_tile("Price 1y", f'<span class="{"up" if (r1y or 0)>=0 else "dn"}">{fmt_pct(r1y)}</span>',
                              sub="total return", spark=sparkline_svg(cagr_series)))
    fwd = _num(ts.get("forward_pe"))
    tiles.append(_metric_tile("Fwd P/E", f"{fwd:.1f}×" if fwd is not None else "n/a",
                              sub=f"P/E {ts.get('pe_ttm')}×" if _num(ts.get("pe_ttm")) is not None else ""))
    roic = _num(ts.get("roic_pct"))
    tiles.append(_metric_tile("ROIC", fmt_pct(roic),
                              sub="Buffett moat ✓" if (roic or 0) >= 25 else "return on capital"))
    rc = _num(ts.get("revenue_cagr_5y_pct"))
    tiles.append(_metric_tile("Rev CAGR 5y", fmt_pct(rc), sub="revenue growth",
                              spark=sparkline_svg(cagr_series, "#0E6E6E")))
    beta = _num(ts.get("beta_3y")) if _num(ts.get("beta_3y")) is not None else _num(ab.get("beta"))
    alpha = _num(ts.get("alpha_ann_pct")) if _num(ts.get("alpha_ann_pct")) is not None else _num(ab.get("alpha_ann_pct"))
    tiles.append(_metric_tile("β / α (3y)", f"{beta:.2f}" if beta is not None else "n/a",
                              sub=f"α {fmt_pct(alpha)} vs {esc(ab.get('benchmark') or 'bench')}" if alpha is not None else ""))
    z = _num(data.get("altman_zscore"))
    beneish = _num((rf.get("beneish") or {}).get("m_score"))
    tiles.append(_metric_tile("Altman / Beneish", f"Z {z:.1f}" if z is not None else "n/a",
                              sub=(f"M {beneish:.2f}" if beneish is not None else "M n/a") +
                                  (" · both clean ✓" if (z or 0) >= 3 and beneish is not None and beneish < -2.22 else "")))
    return f'<div class="hero">{snow}<div class="strip">{"".join(tiles)}</div></div>'


def build_tldr(fm, body, data):
    verdict = (data.get("verdict") or fm.get("verdict") or "").lower()
    score = _num((data.get("scores") or {}).get("composite")) or _num(fm.get("score"))
    thesis = extract_label(body, "Thesis") or "—"
    risks = extract_label(body, "Risks") or extract_label(body, "Risk") or "—"
    action = extract_label(body, "Action") or "—"
    fair = fmt_money(fm.get("fair_price"), data.get("currency") or fm.get("currency"))
    rows = [
        f'<b>Verdict:</b> {VERDICT_EMOJI.get(verdict,"")} {esc(VERDICT_LABELS.get(verdict, verdict.upper()))}'
        f' ({score:.1f}/10)' if score is not None else f'<b>Verdict:</b> {esc(verdict.upper())}',
        f'<b>Fair price:</b> {esc(fair)} ({esc(fm.get("fair_price_basis") or "n/a")})',
        f'<b>Thesis:</b> {esc(thesis)}',
        f'<b>Risks:</b> {esc(risks)}',
        f'<b>Action:</b> {esc(action)}',
    ]
    return _card("TL;DR — the 60-second read", "<p>" + "<br>".join(rows) + "</p>", "tldr")


def build_exit(data):
    xp = data.get("exit_plan") or {}
    if not xp or xp.get("error"):
        return ""
    cur = data.get("currency")
    tpe = xp.get("target_exit_pe")
    tpe_v = (tpe.get("value") if isinstance(tpe, dict) else tpe)
    ladder = xp.get("profit_take_ladder")
    ladder_txt = ladder.get("summary") if isinstance(ladder, dict) else (ladder or "n/a")
    trigger = xp.get("thesis_broken_trigger")
    trigger_txt = trigger.get("text") if isinstance(trigger, dict) else trigger
    yoc = xp.get("yield_on_cost")
    yoc_txt = yoc.get("display") if isinstance(yoc, dict) else yoc
    boxes = [
        f'<div class="box"><div class="k">Target exit P/E</div><div class="v">{esc(tpe_v if tpe_v is not None else "n/a")}</div></div>',
        f'<div class="box"><div class="k">Profit-take ladder</div><div class="v" style="font-size:13px">{esc(ladder_txt or "n/a")}</div></div>',
        f'<div class="box"><div class="k">Thesis-broken trigger</div><div class="v" style="font-size:13px">{esc(trigger_txt or "n/a")}</div></div>',
    ]
    yoc_html = f'<div class="callout">Yield on cost (if held): <b>{esc(yoc_txt)}</b></div>' if yoc_txt else ""
    return _card("Exit Plan",
                 f'<div class="exit-grid">{"".join(boxes)}</div>{yoc_html}{build_watchlist_state(data)}',
                 "exit", new=True)


def build_watchlist_state(data):
    """The watch-list outcome as recorded by watchlist.py — never as narrated prose.

    Roadmap R17: on 2026-08-17 a report told the reader twice that ROVI.MC was "already in
    `_watchlist.csv`" when that file had not been written since 2026-08-10 and held four
    other names. The narrative had no data channel to the node that decides membership, so
    it guessed. This renders `watchlist_action`, which node 2.57 now writes; absent the
    block it says nothing rather than implying either answer.
    """
    wa = data.get("watchlist_action") or {}
    reason = wa.get("reason")
    if not reason:
        return ""
    icon = "⭐" if wa.get("on_list") else "—"
    return (f'<div class="callout">{icon} Watch-list: <b>{esc(reason)}</b>'
            f'<span class="sub"> (recorded by node 2.57, not narrated)</span></div>')


def build_valuation(data):
    iv = data.get("intrinsic_value") or {}
    fvr = iv.get("fair_value_range") or {}
    cur = data.get("currency")
    price = data.get("price_current")
    if not iv and not fvr:
        return _card("Valuation", '<div class="nabox">Valuation blend n/a.</div>', "val", new=True)
    marker = gauge_marker_pct(price, fvr.get("mid"))
    if marker is not None:
        mos = ((_num(fvr.get("mid")) - _num(price)) / _num(fvr.get("mid"))) * 100
        gauge = (f'<div class="gauge"><div class="seg" style="left:10%">expensive</div>'
                 f'<div class="seg" style="left:55%">fair</div><div class="seg" style="left:90%">cheap</div>'
                 f'<div class="you" style="left:{marker:.0f}%"><b>{esc(fmt_money(price,cur))} now · {mos:+.0f}% to fair</b></div></div>')
    else:
        gauge = '<div class="nabox">Fair-value gauge n/a (no blend or NM price).</div>'
    rp = range_bar_pcts(fvr.get("low"), fvr.get("mid"), fvr.get("high"))
    if rp:
        bear, base, bull = rp
        def tick(p, v):
            return f'<div class="tick" style="left:{p:.0f}%"><span>{esc(fmt_money(v,cur))}</span></div>'
        rng = (f'<div class="range"><div class="fill" style="left:{bear:.0f}%;right:{100-bull:.0f}%"></div>'
               f'{tick(bear,fvr.get("low"))}{tick(base,fvr.get("mid"))}{tick(bull,fvr.get("high"))}</div>')
    else:
        rng = ""
    mos_class = iv.get("mos_class") or "n/a"
    blend = iv.get("blend") or {}
    contrib = blend.get("label") or (f'{blend.get("n_valid")}/{blend.get("n_models")} models' if blend.get("n_valid") else "")
    caption = f'<p class="sub">Margin of safety: <b>{esc(mos_class)}</b> · blend {esc(contrib)} · fair €low/mid/high shown on the bar.</p>'
    return _card("Valuation — fair value & margin of safety", gauge + rng + caption, "val", new=True)


def metric_values(data: dict) -> dict:
    """Pull the 9 metric-family values from the analysis JSON (all confirmed
    present in the schema). Missing / non-computable → None. Yields are %."""
    fund = data.get("fundamentals") or {}
    val = (data.get("score_details") or {}).get("valuation") or {}
    price = _num(data.get("price_current"))
    pe = _num(fund.get("pe_ratio"))
    bv = _num(fund.get("book_value"))
    ev = _num(fund.get("enterprise_value"))
    fcf = _num(fund.get("fcf_ttm"))
    return {
        "pe": pe,
        "peg": _num(fund.get("peg")),
        "ps": _num(fund.get("ps_ratio")),
        "pb": (price / bv) if (price is not None and bv and bv > 0) else None,
        "earnings_yield": (100.0 / pe) if (pe and pe > 0) else None,
        "ev_sales": _num(fund.get("ev_revenue")),
        "ev_ebitda": _num(fund.get("ev_ebitda")),
        "ev_ebit": _num(val.get("ev_ebit")),
        "fcf_ev": (100.0 * fcf / ev) if (fcf is not None and ev and ev > 0) else None,
    }


def _fmt_metric(value, unit) -> str:
    n = _num(value)
    if n is None:
        return "n/a"
    if unit == "%":
        return f"{n:.1f}%"
    if unit == "x":
        return f"{n:.1f}×"
    return f"{n:.2f}"


def build_metric_families(data):
    """Equity vs Enterprise valuation multiples with a greyed cheat-sheet
    (tooltip on screen · <details> on mobile · grey column in print). Values come
    from the JSON; the cheat text is static (metrics_glossary). Spec §11."""
    vals = metric_values(data)
    fams = glossary.families()
    fam_blocks = []
    any_value = False
    for fam_label, ids in fams.items():
        rows, cheat_rows = [], []
        for mid in ids:
            g = glossary.entry(mid) or {}
            v = vals.get(mid)
            if v is not None:
                any_value = True
            disp = _fmt_metric(v, g.get("unit"))
            band = glossary.band_for(mid, v)
            tint = f" tint-{band}" if band else ""
            band_txt = f" · {band}" if band else ""
            tip = f'{g.get("advantages","")} — Limits: {g.get("limitations","")}'
            rows.append(
                f'<tr><td class="mname" title="{esc(tip)}">{esc(g.get("label", mid))}'
                f'<span class="info">ⓘ</span></td>'
                f'<td class="val{tint}">{esc(disp)}</td>'
                f'<td class="cheat">{esc(g.get("when_to_use",""))} <em>({esc(g.get("reference",""))})</em></td></tr>')
            cheat_rows.append(
                f'<div class="row"><b>{esc(g.get("label", mid))}</b> — {esc(disp)}{esc(band_txt)}<br>'
                f'{esc(g.get("when_to_use",""))} <em>({esc(g.get("reference",""))})</em></div>')
        table = ('<table class="mf"><tr><th>Metric</th><th class="val">Value</th>'
                 '<th class="cheat">When to use · reference</th></tr>' + "".join(rows) + "</table>")
        details = (f'<details class="cheat-m"><summary>ℹ️ {esc(fam_label)} cheat-sheet</summary>'
                   f'{"".join(cheat_rows)}</details>')
        fam_blocks.append(f'<div class="mf-fam"><h3>{esc(fam_label)}</h3>{table}{details}</div>')
    if not any_value:
        return ""
    note = ('<p class="sub">Equity multiples use market cap / share price (leverage-sensitive); '
            'enterprise multiples are capital-structure neutral. Hover a metric (or expand on mobile) '
            'for its edge, limits and reference band.</p>')
    return _card("Valuation metric families — equity vs enterprise",
                 "".join(fam_blocks) + note, "metrics", new=True)


def build_redflags(data):
    rf = data.get("red_flags") or {}
    if not rf or rf.get("error"):
        return ""
    summ = rf.get("summary") or {}
    checks = rf.get("checks") or []
    items = []
    if isinstance(checks, list) and checks:
        for c in checks[:16]:
            st = (c.get("status") or "").lower()
            cls = {"pass": "ok", "ok": "ok", "warn": "warn", "bad": "bad", "fail": "bad"}.get(st, "warn")
            label = c.get("label") or c.get("name") or c.get("check") or ""
            items.append(f'<li><span class="pill {cls}">{esc(st.upper() or "?")}</span>'
                         f'<span>{esc(label)}{": " + esc(c.get("detail")) if c.get("detail") else ""}</span></li>')
    else:
        for name, key in (("Income", "income"), ("Balance", "balance"), ("Cash flow", "cashflow")):
            sc = _num((rf.get(key) or {}).get("subscore_0_10"))
            cls = "ok" if (sc or 0) >= 7 else ("warn" if (sc or 0) >= 4 else "bad")
            items.append(f'<li><span class="pill {cls}">{("%.1f"%sc) if sc is not None else "n/a"}/10</span>'
                         f'<span>{esc(name)}-statement review</span></li>')
    beneish = _num((rf.get("beneish") or {}).get("m_score"))
    bcls = "ok" if beneish is not None and beneish < -2.22 else ("bad" if beneish is not None else "warn")
    items.append(f'<li><span class="pill {bcls}">{("M %.2f"%beneish) if beneish is not None else "M n/a"}</span>'
                 f'<span>Beneish manipulation score (flag if &gt; −2.22)</span></li>')
    note = '<p class="sub">A bearish veto surfaces risk — it never auto-demotes the verdict.</p>'
    return _card("Red-Flag Scanner", f'<ul class="flags">{"".join(items)}</ul>{note}', "flags", new=True)


_CATEGORY_LABEL = {"cyclical": "Cyclical", "turnaround": "Turnaround",
                   "asset_play": "Asset play"}


def _pct100(v):
    """Fraction → percent. The lens blocks store 0.078; `fmt_pct` prints a percent."""
    n = _num(v)
    return None if n is None else n * 100.0


def _clip(text: str, limit: int) -> str:
    """Truncate on a word boundary — a sentence cut mid-word reads as a rendering bug."""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def build_lens(data):
    """§2.21 — the category lens (3.5) and the ROIC-vs-ROE doctrine (3.6), in one card.

    Both blocks answer the same reader question — "what do these numbers actually mean for
    this kind of company?" — so they share a card rather than adding two entries to a NAV
    the plan already flagged as growing past what a reader scans. Either block alone is
    enough to render it; neither is required.
    """
    cat = data.get("category_lens") or {}
    roic = data.get("roic_lens") or {}
    if (not cat or cat.get("error")) and (not roic or roic.get("error")):
        return ""
    rows = []

    if cat and not cat.get("error"):
        primary = cat.get("primary")
        head = (f'<span class="pill bad">{esc((_CATEGORY_LABEL.get(primary, primary) or "").upper())}</span>'
                if primary else '<span class="pill ok">DEFAULT LENS</span>')
        rows.append(head + " " + (
            "<b>Category:</b> the default yardsticks — trailing P/E, TTM margins, the "
            "growth gates — misread this shape; see the notes below"
            if primary else
            "<b>Category:</b> none of cyclical / turnaround / asset play — the Quality "
            "Compounder yardsticks apply as written"))
        for key in ("cyclical", "turnaround", "asset_play"):
            f = (cat.get("flags") or {}).get(key) or {}
            if not f.get("detected"):
                continue
            # The LATE-CYCLE line gets its own pill row below; repeating it here is what
            # pushed the joined evidence past the truncation limit mid-sentence.
            ev = _clip("; ".join(e for e in (f.get("evidence") or [])
                                 if not e.startswith("LATE-CYCLE")), 300)
            rows.append(f'<b>{esc(_CATEGORY_LABEL[key])}</b> '
                        f'({esc(f.get("confidence") or "n/a")}): {esc(ev)}')
        if cat.get("peak_earnings_warning"):
            rows.append('<span class="pill bad">LATE-CYCLE</span> trailing P/E is measured '
                        'on cycle-high earnings — judge on mid-cycle EPS, not TTM')
        if ((cat.get("flags") or {}).get("cyclical") or {}).get("secular_decline"):
            rows.append('<span class="pill warn">SECULAR</span> earnings fell from their '
                        'peak and have not recovered — a decline, not a cycle')
        if cat.get("disagreement_note"):
            rows.append(f'<b>vs <code>lynch_category</code> = '
                        f'{esc(cat.get("lynch_category") or "n/a")}:</b> '
                        f'{esc(cat["disagreement_note"])}')

    if roic and not roic.get("error"):
        pref = roic.get("preferred_metric")
        # roic_lens stores FRACTIONS (0.078); fmt_pct formats a PERCENT (7.8). Missing
        # this printed "ROIC 0.1% vs WACC 0.2%" on a company earning 7.8% against 17.0%.
        vals = " · ".join(
            f"{lbl} {fmt_pct(_pct100(roic.get(k)))}"
            for lbl, k in (("ROIC", "roic"), ("ex-goodwill", "roic_ex_goodwill"),
                           ("ROE", "roe"), ("ROTE", "rote"), ("ROCE", "roce"))
            if roic.get(k) is not None)
        rows.append(f'<b>Return metric — {esc((pref or "n/a").upper())}:</b> '
                    f'{esc(roic.get("preferred_reason") or "")}')
        if vals:
            rows.append(f'<b>Measured:</b> {vals}')
        rv = roic.get("roic_vs_wacc") or {}
        if rv.get("verdict"):
            cls = {"creates value": "ok", "marginal": "warn",
                   "destroys value": "bad"}.get(rv["verdict"], "warn")
            rows.append(f'<span class="pill {cls}">{esc(rv["verdict"].upper())}</span> '
                        f'<b>ROIC vs WACC:</b> {fmt_pct(_pct100(rv.get("roic")))} vs '
                        f'{fmt_pct(_pct100(rv.get("wacc")))} '
                        f'(spread {fmt_pct(_pct100(rv.get("spread")))})')
        lev = roic.get("leverage_manufactured_roe") or {}
        if lev.get("flagged"):
            rows.append(f'<span class="pill bad">LEVERAGED ROE</span> {esc(lev["note"])}')
        bm = roic.get("buffett_multiplier") or {}
        if bm.get("note"):
            rows.append(f'<span class="sub">{esc(bm["note"])}</span>')

    if not rows:
        return ""
    note = ('<p class="sub">Overlay — a lens on the numbers, not a change to them. '
            'Neither block enters the composite, the gates or the verdict. '
            'Thresholds: <code>docs/CATEGORIES.md</code>, <code>docs/ROIC_vs_ROE.md</code>.</p>')
    return _card("Category & return-metric lens",
                 "<p>" + "<br>".join(rows) + "</p>" + note, "lens", new=True)


def build_return_profile(data):
    ab = data.get("alpha_beta") or {}
    if not ab or ab.get("error"):
        return ""
    beta, alpha = _num(ab.get("beta")), _num(ab.get("alpha_ann_pct"))
    realized, capm = _num(ab.get("realized_return_ann_pct")), _num(ab.get("capm_expected_return_ann_pct"))
    lynch = ab.get("lynch_prior") or {}
    pc = ab.get("portfolio_comparison") or {}
    rows = [
        f'<b>α / β (3y vs {esc(ab.get("benchmark") or "bench")}):</b> β {beta:.2f} · α {fmt_pct(alpha)} (Jensen, annualised)'
        if beta is not None else '<b>α / β:</b> not computable (thin history)',
        f'<b>CAPM:</b> realized {fmt_pct(realized)} vs expected {fmt_pct(capm)}',
        f'<b>Lynch prior ({esc(lynch.get("category") or "n/a")}):</b> {esc(lynch.get("expected_return_band") or "n/a")}'
        f' · drawdown {esc(lynch.get("drawdown_band") or "n/a")}',
    ]
    if pc.get("portfolio") and pc.get("ticker_vs_world"):
        p, t = pc["portfolio"], pc["ticker_vs_world"]
        rows.append(f'<b>Portfolio fit (vs {esc(pc.get("benchmark") or "URTH")}):</b> ticker β {t.get("beta")} / α {fmt_pct(_num(t.get("alpha_ann_pct")))}'
                    f' vs portfolio β {p.get("beta")} / α {fmt_pct(_num(p.get("alpha_ann_pct")))}'
                    f' → β {esc(pc.get("verdict_beta"))}, α {esc(pc.get("verdict_alpha"))}')
    cagr = ab.get("price_cagr_ladder") or {}
    ladder = " · ".join(f"{w} {fmt_pct(_num(cagr.get(w)),0)}" for w in ("1y", "3y", "5y", "10y", "15y")
                        if _num(cagr.get(w)) is not None)
    if ladder:
        rows.append(f'<b>Price CAGR:</b> {esc(ladder)} <span class="sub">({esc(cagr.get("basis") or "")}, depth {cagr.get("depth_years")}y)</span>')
    return _card("Return profile — α/β · CAPM · Lynch · portfolio fit",
                 "<p>" + "<br>".join(rows) + '</p><p class="sub">Overlay — does not affect the composite.</p>', "ret")


def build_opinion(data):
    op = data.get("opinion_panel") or {}
    if not op or op.get("error"):
        return ""
    cards = []
    icon = {"value": "💰 Value", "growth": "🚀 Growth", "contrarian": "🐻 Contrarian"}
    for c in op.get("personas") or []:
        nm = icon.get(c.get("name"), esc(c.get("name")))
        if not c.get("available"):
            cards.append(f'<div class="oc"><div class="k">{nm}</div><div class="v">n/a</div>'
                         f'<div class="sub">{esc(c.get("reason") or "unavailable")}</div></div>')
            continue
        conv = _num(c.get("conviction_0_100")) or 0
        cards.append(f'<div class="oc"><div class="k">{nm}</div>'
                     f'<div class="v">{esc(c.get("verdict"))} · {conv:.0f}/100</div>'
                     f'<div class="bar"><div class="f" style="width:{conv:.0f}%"></div><div class="mid"></div></div>'
                     f'<div class="sub">{esc(c.get("one_liner"))}</div></div>')
    med = _num(op.get("consensus_conviction"))
    div = op.get("divergence") or {}
    cons = (f'<p><b>Consensus: {med:.0f}/100</b> ({esc(op.get("consensus_verdict"))}) · '
            f'{op.get("n_available")}/3 personas · {esc(op.get("model_chain") or "")}</p>' if med is not None else "")
    divn = f'<div class="callout">⚠️ Divergence — {esc(div.get("reason"))} (the disagreement is the signal).</div>' if div.get("flag") else ""
    note = '<p class="sub">Independent-model opinion (sees the evidence, not the house verdict). Overlay — not scored.</p>'
    return _card("🤖 Opinion panel — value · growth · contrarian",
                 f'<div class="op">{"".join(cards)}</div>{cons}{divn}{note}', "op", new=True)


def build_news_sentiment(data):
    ns = data.get("news_sentiment") or {}
    if not ns or ns.get("error"):
        return ""
    if not ns.get("available"):
        reason = esc(ns.get("reason") or "no recent news")
        return _card("📰 News & market sentiment",
                     f'<p class="sub">News sentiment not available — {reason}.</p>', "news", new=True)

    def dial(title, d):
        score = _num(d.get("score"))
        pct = ((score + 1) / 2 * 100) if score is not None else 50
        val = f"{score:+.2f}" if score is not None else "n/a"
        themes = ", ".join(esc(t) for t in (d.get("themes") or [])) or "—"
        return (f'<div class="oc"><div class="k">{esc(title)}</div>'
                f'<div class="v">{esc(d.get("label") or "n/a")} · {val}</div>'
                f'<div class="bar"><div class="f" style="width:{pct:.0f}%"></div><div class="mid"></div></div>'
                f'<div class="sub">{themes}</div></div>')

    dials = dial("Stock", ns.get("stock") or {}) + dial("Market", ns.get("market") or {})
    heads = ""
    if ns.get("headlines"):
        items = "".join(
            f'<li>{esc(h.get("title"))}'
            + (f' <span class="sub">({esc(h.get("publisher"))})</span>' if h.get("publisher") else "")
            + "</li>" for h in ns["headlines"][:5])
        heads = (f'<p class="sub">Headlines ({ns.get("n_headlines")} scanned · '
                 f'{esc(", ".join(ns.get("sources_used") or []))}):</p><ul class="flags">{items}</ul>')
    note = ('<p class="sub">Overlay — sentiment is context, not scored. '
            'Complements the news-freshness decay.</p>')
    return _card("📰 News & market sentiment",
                 f'<div class="op">{dials}</div>{heads}{note}', "news", new=True)


def build_peers(data):
    pi = (data.get("score_details") or {}).get("peer_info") or {}
    metrics = pi.get("peer_metrics") or pi.get("peers")
    if not metrics:
        return ""
    rankings = pi.get("rankings") or {}
    header = "<tr><th>Ticker</th><th class='num'>Fwd P/E</th><th class='num'>ROIC</th><th class='num'>Rev CAGR</th><th>Grade</th></tr>"
    rows = []
    items = metrics.items() if isinstance(metrics, dict) else [(m.get("ticker"), m) for m in metrics]
    for tk, m in list(items)[:8]:
        if not isinstance(m, dict):
            continue
        g = grade_letter(_num((rankings.get(tk) or {}).get("percentile"))) if isinstance(rankings, dict) else None
        gcell = f'<span class="grade g{g}">{g}</span>' if g else "—"
        rows.append(f"<tr><td>{esc(tk)}</td>"
                    f"<td class='num'>{esc(m.get('forward_pe') or m.get('pe') or '—')}</td>"
                    f"<td class='num'>{esc(m.get('roic') or m.get('roic_pct') or '—')}</td>"
                    f"<td class='num'>{esc(m.get('revenue_cagr') or m.get('rev_cagr') or '—')}</td>"
                    f"<td>{gcell}</td></tr>")
    if not rows:
        return ""
    return _card("Peer comparison", f"<table>{header}{''.join(rows)}</table>", "peer")


def _fmt_big(v, currency=None) -> str:
    """Compact money for the cover strip: $2.79B, €711M, -$1.39bn. "n/a" when absent."""
    n = _num(v)
    if n is None:
        return "n/a"
    sym = CURRENCY_SYMBOL.get(currency or "", (currency + " ") if currency else "")
    sign = "-" if n < 0 else ""
    a = abs(n)
    for cut, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")):
        if a >= cut:
            return f"{sign}{sym}{a / cut:.2f}{unit}"
    return f"{sign}{sym}{a:,.2f}"


METHOD_LABELS = {
    "two_minute_eps_growth": ("2-minute EPS growth", "Lynch's exit-multiple sketch"),
    "lynch_peg": ("Lynch PEG", "fair P/E = growth rate"),
    "forward_pe_target": ("Forward P/E target", "consensus FY3, discounted"),
    "dcf": ("DCF", "±70% sanity gate"),
    "roe_residual_income": ("ROE residual income", "sets the low in most cases"),
    "gordon_growth": ("Gordon growth", "dividend payers only"),
}
# CALIBRATED, not assumed. The plan proposed ~2.5×, so I measured the max/min spread of
# valid models across the 59 analysis JSONs on disk: p25 2.05× · **median 3.37×** · p75
# 5.79×, range 1.19× (0669.HK) to 40.3× (AMD). A 2.5× banner would fire on 61 % of reports
# and a 3× banner on 53 % — a warning that appears on most reports is wallpaper, and the
# reader stops seeing it precisely when it matters. 6.0× fires on 24 %, roughly the top
# quartile, which is what "materially" should mean.
#
# The spread is printed on EVERY report regardless, so the reader can judge a 4× themselves
# instead of inferring "fine" from the absence of a banner.
VALUATION_DISPERSION_X = 6.0
MEDIAN_DISPERSION_X = 3.37     # the measured median, quoted in the card so the reader has
                               # a yardstick rather than an unanchored multiple


def build_valuation_compare(data: dict) -> str:
    """Every valuation method side by side — the card is about DISAGREEMENT.

    `intrinsic_value.py` already computes a five-model blend; the report surfaced the
    blend, which is exactly the number that conceals a model saying half what its
    neighbour says. This lays them out, marks the invalid ones **with their reason**
    rather than dropping them, and raises a banner when the valid spread exceeds
    `VALUATION_DISPERSION_X`.

    No new fetches: every input is already in the analysis JSON.
    """
    iv = data.get("intrinsic_value") or {}
    models = iv.get("models") or {}
    price = _num(data.get("price_current"))
    cur = data.get("currency")

    def upside(v):
        n = _num(v)
        if n is None or price is None or price <= 0:
            return "—"
        pct = (n - price) / price * 100.0
        cls = "up" if pct >= 0 else "down"
        return f'<span class="vc-{cls}">{pct:+.0f}%</span>'

    rows = [(f'<b>Current price</b>', fmt_money(price, cur), "—", "anchor", "")]
    valid_values = []

    for key, m in models.items():
        label, note = METHOD_LABELS.get(key, (key.replace("_", " ").title(), ""))
        val = _num((m or {}).get("value"))
        if (m or {}).get("valid") and val is not None:
            valid_values.append(val)
            rows.append((esc(label), fmt_money(val, cur), upside(val), note, ""))
        else:
            # Invalid models are SHOWN with their reason, not hidden. "The DCF was
            # excluded" is information; a table that silently has four rows instead of
            # five is not.
            reason = (m or {}).get("reason") or "not computable"
            rows.append((esc(label), '<span class="sub">excluded</span>', "—",
                         esc(reason), "vc-out"))

    pe = ((data.get("valuation_bands") or {}).get("pe_band") or {})
    # Back out today's EPS from price ÷ current P/E, then re-price it on the own-history
    # median multiple. Written out rather than chained: the one-line version read fine and
    # divided None by a float the moment `price_current` was absent, which a test caught.
    cur_pe, med = _num(pe.get("current")), _num(pe.get("median"))
    eps = (price / cur_pe) if (price and cur_pe and cur_pe > 0) else None
    if eps and med:
        # Own-history median P/E × the EPS implied by today's price and current P/E.
        band_val = eps * med
        depth = pe.get("depth_years")
        valid_values.append(band_val)
        rows.append(("Own-history P/E band", fmt_money(band_val, cur), upside(band_val),
                     f"median {med:.1f}× over {esc(depth)}y", ""))

    cons = data.get("consensus") or {}
    n_an = _num(cons.get("analyst_count"))
    tgt = _num(cons.get("target_median"))
    if tgt and n_an and n_an >= 3:
        valid_values.append(tgt)
        rows.append(("Consensus median", fmt_money(tgt, cur), upside(tgt),
                     f"sell-side, {int(n_an)} analysts", ""))

    blend = iv.get("blend") or {}
    bval = _num(blend.get("value"))
    if bval is not None:
        # The blend's own label restates every exclusion reason verbatim, which is already
        # on the excluded model's row. Two paragraphs of duplicated prose in the summary
        # row is what buries the number the row exists to show.
        n_valid, n_models = blend.get("n_valid"), blend.get("n_models")
        note = (f"blend of {n_valid}/{n_models} valid models"
                if n_valid and n_models else (blend.get("label") or ""))
        rows.append(('<b>Blend</b>', f'<b>{esc(fmt_money(bval, cur))}</b>', upside(bval),
                     esc(note), "vc-blend"))

    if len(rows) <= 2:
        return ""

    banner = ""
    positives = [v for v in valid_values if v > 0]
    if len(positives) >= 2:
        lo, hi = min(positives), max(positives)
        spread = hi / lo
        if spread >= VALUATION_DISPERSION_X:
            banner = (f'<div class="vc-warn"><b>Methods disagree materially.</b> '
                      f'The valid methods span {esc(fmt_money(lo, cur))} to '
                      f'{esc(fmt_money(hi, cur))} — a <b>{spread:.1f}× spread</b>, against '
                      f'a {MEDIAN_DISPERSION_X:.1f}× median across this system\'s own '
                      f'reports. A single blended fair value is not a safe summary here; '
                      f'read the rows, not the blend.</div>')
        else:
            banner = (f'<p class="sub">Spread across valid methods: <b>{spread:.1f}×</b> '
                      f'({esc(fmt_money(lo, cur))}–{esc(fmt_money(hi, cur))}); the median '
                      f'across this system\'s reports is {MEDIAN_DISPERSION_X:.1f}×.</p>')

    body = "".join(
        f'<tr class="{cls}"><td>{lbl}</td><td class="num">{val}</td>'
        f'<td class="num">{up}</td><td class="sub">{note}</td></tr>'
        for lbl, val, up, note, cls in rows)
    table = ('<table class="vc"><tr><th>Method</th><th class="num">Value/share</th>'
             '<th class="num">vs price</th><th>Note</th></tr>' + body + "</table>")
    return _card("Valuation — methods side by side", banner + table, "vcompare", new="v4.3")


def _normalise_ws(s) -> str:
    """Whitespace- and case-insensitive form, for comparing two prose strings."""
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _fmt_ratio(v, decimals=2) -> str:
    """A plain ratio (D/E, quick ratio) — but a small non-zero value is shown as `<0.01`
    rather than rounded to `0.00`. MPWR's D/E is 0.005, and a cover printing `0.00` reads
    as missing data or as an exact zero; it is neither."""
    n = _num(v)
    if n is None:
        return "n/a"
    out = f"{n:.{decimals}f}"
    # Decided on the FORMATTED result, not on a hand-derived threshold. Comparing against
    # `0.5 * 10**-decimals` looked equivalent and was not: float representation put 0.005
    # on the wrong side of its own boundary, so the guard fired for a value that rounds
    # perfectly well. Ask the formatter what it produced instead of predicting it.
    if n != 0 and float(out) == 0:
        return f"{'-' if n < 0 else '<'}{10 ** -decimals:.{decimals}f}"
    return out


def _fmt_x(v, decimals=1) -> str:
    """A multiple: 83.3×. Distinct from a percentage so a cover reader cannot misread one
    as the other at a glance."""
    n = _num(v)
    return "n/a" if n is None else f"{n:.{decimals}f}×"


def _cover_groups(data: dict, fm: dict) -> list[tuple[str, list[tuple[str, str]]]]:
    """The cover's key-financials strip: six labelled groups of (metric, value).

    Every field here already exists in `fundamentals` / `top_strip` — verified against a
    live analysis JSON — so this is **layout, not new computation**, and it adds nothing
    to the 30-minute budget.

    ROIC falls back to ROE when ROIC is `None`, which is not a workaround: the v4.2
    `IC_MIN_FRACTION` guard deliberately returns `None` for cash-rich balance sheets where
    the net-cash subtraction has hollowed out invested capital, and ROE is the right
    metric there. The label changes with it so the reader always knows which they are
    looking at.
    """
    f = data.get("fundamentals") or {}
    ts = data.get("top_strip") or {}
    cur = data.get("currency") or fm.get("currency")
    iv = data.get("intrinsic_value") or {}

    roic, roe = _num(f.get("roic_ttm")), _num(f.get("roe_ttm"))
    roic_label, roic_val = ("ROIC", roic) if roic is not None else ("ROE *(ROIC n/a)*", roe)

    return [
        ("Scale", [
            ("Market cap", _fmt_big(f.get("market_cap"), cur)),
            ("Revenue TTM", _fmt_big(f.get("revenue_ttm"), cur)),
            ("EBITDA TTM", _fmt_big(f.get("ebitda_ttm"), cur)),
            ("Net debt", _fmt_big(f.get("net_debt"), cur)),
        ]),
        ("Profitability", [
            (roic_label, fmt_pct(roic_val * 100 if roic_val is not None else None)),
            ("Net margin", fmt_pct(_num(f.get("net_margin_ttm")) * 100
                                   if _num(f.get("net_margin_ttm")) is not None else None)),
            ("Operating margin", fmt_pct(_num(f.get("operating_margin_ttm")) * 100
                                         if _num(f.get("operating_margin_ttm")) is not None else None)),
            ("FCF margin", fmt_pct(ts.get("fcf_margin_pct"))),
        ]),
        ("Valuation", [
            ("P/E", _fmt_x(f.get("pe_ratio"))),
            ("Forward P/E", _fmt_x(f.get("forward_pe"))),
            ("EV/EBITDA", _fmt_x(f.get("ev_ebitda"))),
            ("EV/EBIT", _fmt_x(f.get("ev_ebit"))),
            ("FCF yield", fmt_pct(ts.get("fcf_yield_pct"), 2)),
            ("PEG", _fmt_x(f.get("peg"), 2)),
        ]),
        ("Health", [
            ("Piotroski", (f"{int(_num(data.get('piotroski_fscore')))}/9"
                           if _num(data.get("piotroski_fscore")) is not None else "n/a")),
            ("Altman Z", (f"{_num(data.get('altman_zscore')):.2f}"
                          if _num(data.get("altman_zscore")) is not None else "n/a")),
            ("D/E", _fmt_ratio(f.get("debt_to_equity"))),
            ("Net debt/EBITDA", _fmt_x(f.get("net_debt_ebitda"), 2)),
            ("Quick ratio", _fmt_ratio(f.get("quick_ratio"))),
        ]),
        ("Growth", [
            ("Revenue CAGR 5y", fmt_pct(ts.get("revenue_cagr_5y_pct"))),
            ("EPS CAGR 5y", fmt_pct(_num(f.get("eps_cagr_5y")) * 100
                                    if _num(f.get("eps_cagr_5y")) is not None else None)),
        ]),
        ("Risk / return", [
            ("β 3y", _fmt_ratio(ts.get("beta_3y"))),
            ("α 3y", fmt_pct(ts.get("alpha_ann_pct"))),
            ("Gates passed", (f"{int(_num(data.get('gates_passed')))}/7"
                              if _num(data.get("gates_passed")) is not None else "n/a")),
            ("Cost of equity", fmt_pct(_num((iv.get("capm") or {}).get("cost_of_equity")) * 100
                                       if _num((iv.get("capm") or {}).get("cost_of_equity")) is not None
                                       else None)),
        ]),
    ]


def build_cover(data: dict, fm: dict, body: str) -> str:
    """Page 1: the answer, then the numbers behind it — nothing else.

    Two bands, and the order is the point. The verdict, the price context and the two
    triggers come first because that is the decision; the key-financials strip follows so
    the page stands alone without scrolling into the body. `page-break-after: always`
    makes print/PDF page 1 *be* the wrap-up.

    Values render **blank where absent, never zero** — a cover that prints 0.00 for a
    missing net-debt figure reads as a debt-free company.
    """
    ticker = data.get("ticker") or fm.get("ticker") or "?"
    cur = data.get("currency") or fm.get("currency")
    verdict = (data.get("verdict") or fm.get("verdict") or "").lower()
    score = _num((data.get("scores") or {}).get("composite")) or _num(fm.get("score"))
    iv = data.get("intrinsic_value") or {}
    mos_class = iv.get("mos_class") or fm.get("mos_class")
    go = (data.get("technical") or {}).get("go_no_go") or fm.get("go_no_go")
    verb = action_verb(verdict, mos_class, go)

    stars = star_ratings.compute(data or {})
    star_row = " · ".join(
        f'{esc(d["label"])} {esc(star_ratings.render_stars(d["stars"]))}'
        for _k, _l, _fn in star_ratings.DIMENSIONS
        for d in [stars["dimensions"][_k]] if d["stars"] is not None)

    thesis = extract_label(body, "Thesis")
    risks = extract_label(body, "Risks") or extract_label(body, "Risk")
    bear = fm.get("bear_case_trigger")
    xp = data.get("exit_plan") or {}
    trig = xp.get("thesis_broken_trigger")
    exit_trig = trig.get("text") if isinstance(trig, dict) else trig

    facts = [
        ("Verdict", f'{VERDICT_EMOJI.get(verdict, "")} {VERDICT_LABELS.get(verdict, verdict.upper() or "n/a")}'
                    + (f'<span class="sub"> {score:.2f}/10</span>' if score is not None else "")),
        ("Price", fmt_money(data.get("price_current") or fm.get("price_at_eval"), cur)),
        ("Fair value", fmt_money(fm.get("fair_price"), cur)
                       + (f' <span class="sub">({esc(fm.get("fair_price_basis"))})</span>'
                          if fm.get("fair_price_basis") else "")),
        ("Margin of safety", (f'{esc(mos_class)}' if mos_class else "n/a")
                             + (f' · {fmt_pct(iv.get("mos_pct"), 0)}'
                                if _num(iv.get("mos_pct")) is not None else "")),
        ("Timing", esc(go) if go else "not run"),
    ]
    fact_html = "".join(
        f'<div class="cv-fact"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>'
        for k, v in facts)

    lines = []
    if thesis:
        lines.append(f'<div class="cv-line cv-bull"><b>Thesis</b> {md_inline(thesis)}</div>')
    if risks:
        lines.append(f'<div class="cv-line cv-bear"><b>Risk</b> {md_inline(risks)}</div>')
    if bear:
        lines.append(f'<div class="cv-line cv-bear"><b>Bear trigger</b> {md_inline(bear)}</div>')
    # `exit_plan.thesis_broken_trigger` is frequently copied verbatim from the frontmatter's
    # `bear_case_trigger`. Printing both spent a third of the answer band restating one
    # sentence, on the one page that has no room to waste.
    if exit_trig and _normalise_ws(exit_trig) != _normalise_ws(bear):
        lines.append(f'<div class="cv-line"><b>Exit trigger</b> {md_inline(exit_trig)}</div>')

    # Measured, not guessed: at A4 print width (726px content, 1039px height at 96dpi)
    # four real covers landed at 887–954px, i.e. 84–152px spare, and 84px is about four
    # lines of prose. The prose is the only variable part, so it gets a budget. Exceeding
    # it does not truncate — clipping a bear trigger mid-sentence is worse than a cover
    # that runs 1–2 lines long — it logs, so a systematic drift is visible rather than
    # discovered in a PDF months later.
    prose_chars = sum(len(x) for x in (thesis, risks, bear, exit_trig) if x)
    if prose_chars > COVER_PROSE_BUDGET_CHARS:
        log(f"cover prose {prose_chars} chars > {COVER_PROSE_BUDGET_CHARS} budget — "
            f"the printed cover may run onto a second page")

    groups = []
    for title, rows in _cover_groups(data, fm):
        cells = "".join(f'<div class="cv-m"><span>{md_inline(k)}</span>'
                        f'<b>{esc(v)}</b></div>' for k, v in rows)
        groups.append(f'<div class="cv-grp"><h4>{esc(title)}</h4>{cells}</div>')

    stars_html = (f'<div class="cv-stars">{star_row}'
                  + (f' · <b>{stars["overall"]}/5</b>' if stars.get("overall") is not None else "")
                  + "</div>") if star_row else ""

    return (
        f'<section class="cover" id="cover">'
        f'<div class="cv-verb">{esc(verb)}</div>'
        f'<div class="cv-tk">{esc(data.get("company_name") or ticker)} '
        f'<span class="sub">· {esc(ticker)}{_external_links(ticker)}</span></div>'
        f'<div class="cv-facts">{fact_html}</div>'
        f'{stars_html}'
        f'{"".join(lines)}'
        f'<h3 class="cv-h">Key financials</h3>'
        f'<div class="cv-groups">{"".join(groups)}</div>'
        f'</section>')


def build_stars(data: dict) -> str:
    """The ⭐ quality card — five dimensions, 1-5 stars, from published bands.

    Deterministic Python end to end (`docs/STAR_RATINGS.md` is the contract), overlay-only:
    no star touches the composite or the verdict. A dimension with too little data renders
    **n/a**, never one star — absence and a damning judgement must not look the same.
    """
    res = star_ratings.compute(data or {})
    dims = res.get("dimensions") or {}
    if not res.get("rated_dimensions"):
        return ""
    rows = []
    for key, _label, _fn in star_ratings.DIMENSIONS:
        d = dims.get(key) or {}
        n = d.get("stars")
        glyphs = star_ratings.render_stars(n)
        cls = "stars-na" if n is None else "stars-on"
        note = "" if n is not None else '<span class="sub"> — insufficient data</span>'
        rows.append(f'<tr><td class="sname">{esc(d.get("label") or key)}</td>'
                    f'<td class="{cls}">{esc(glyphs)}</td>'
                    f'<td class="num sub">{d.get("coverage", 0):.0%} coverage{note}</td></tr>')
    overall = res.get("overall")
    head = (f'<div class="stars-overall">Overall <b>{overall}</b>/5 '
            f'<span class="sub">across {res["rated_dimensions"]} rated dimensions</span></div>'
            if overall is not None else
            '<p class="sub">Fewer than three dimensions could be rated — no overall shown.</p>')
    note = ('<p class="sub">Computed from the bands published in <code>docs/STAR_RATINGS.md</code>. '
            'Qualitative overlay — <b>no star enters the composite or the verdict</b>.</p>')
    return _card("⭐ Quality ratings", f'{head}<table class="stars">{"".join(rows)}</table>{note}',
                 "stars", new="v4.3")


_LEAN_CLASS = {"BULL": "bull", "BEAR": "bear", "EQUILIBRADO": "even"}


def build_thesis_duel(body: str) -> str:
    """The v4.2 §0 thesis duel — bull/bear table + the LEAN verdict.

    Present in every report since v4.2 and absent from the HTML entirely, which is
    one of the three gaps that made an HTML-only switch lossy. Returns "" for the
    pre-v4.2 reports that have no duel, so re-rendering the back catalogue is safe.
    """
    chunk = extract_section(body, r"Bull\s*vs\s*Bear")
    rows = parse_md_table(chunk) if chunk else []
    lean = extract_callout(body, "abstract")
    if not rows and not lean:
        return ""

    inner = ""
    if len(rows) >= 2:
        head = rows[0]
        # The leading cell of the header row is empty by design (it labels the row
        # axis, not a column), so a 3-column table is the expected shape.
        cols = head[1:] if len(head) >= 3 else head
        body_rows = ""
        for r in rows[1:]:
            if len(r) < len(cols) + 1:
                continue
            label = md_inline(r[0])
            cells = "".join(f'<td class="duel-{i}">{md_inline(c)}</td>'
                            for i, c in enumerate(r[1:len(cols) + 1]))
            body_rows += f'<tr><th class="duel-lbl">{label}</th>{cells}</tr>'
        if body_rows:
            hdr = "".join(f"<th>{md_inline(c)}</th>" for c in cols)
            inner += f'<table class="duel"><tr><th></th>{hdr}</tr>{body_rows}</table>'

    if lean:
        title, rest = lean
        verdict = ""
        m = re.search(r"MAIS\s+PROV[ÁA]VEL\s*:\s*(.+)$", title, re.IGNORECASE)
        if m:
            verdict = re.sub(r"\*+", "", m.group(1)).strip()
        key = next((k for k in _LEAN_CLASS if k in verdict.upper()), "")
        # The italic boilerplate that follows the reasoning explains the rule to the
        # reader of the .md; in a card with its own caption it is noise, so only the
        # first substantive line is carried over.
        reason = next((r for r in rest if not r.startswith("*")), "")
        inner += (f'<div class="lean {_LEAN_CLASS.get(key, "even")}">'
                  f'<span class="lean-k">MAIS PROVÁVEL</span> '
                  f'<b>{md_inline(verdict or "—")}</b>'
                  f'{("<div class=\"lean-why\">" + md_inline(reason) + "</div>") if reason else ""}'
                  f'</div>')
        inner += ('<p class="sub">Leitura narrativa — não entra no composite, não altera o '
                  'veredicto e nunca é expressa em percentagem.</p>')
    return _card("⚔️ Thesis duel — bull vs bear", inner, "duel", new="v4.2") if inner else ""


_SWOT_QUADRANTS = [
    ("threat", "⚠️ Threats / Risks", r"threat"),
    ("strength", "✅ Strengths", r"strength"),
    ("weakness", "🔸 Weaknesses", r"weakness"),
    ("opportunity", "🚀 Opportunities", r"opportunit"),
]


SWOT_LABEL_MAX_CHARS = 30
_SWOT_DECOR = re.compile(r"\*\([^)]*\)\*|[*`_]|[^\w\s/&-]", re.UNICODE)


def _swot_label(cell: str) -> str | None:
    """The quadrant a cell NAMES, or None if it is content.

    A label is a name — "⚠️ **Threats / Risks** *(leads · deepest)*" is 15 characters
    once the decoration comes off. A quadrant's content is a paragraph. So the test is
    "does this reduce to a short name that matches", not "does the keyword appear
    anywhere", which is what the first version asked and which misread real reports:
    MPWR's threats body opens *"**Valuation is the primary threat**: 83.34× P/E…"*, so
    900 characters of analysis were classified as a header and the quadrant vanished.

    Stripping first, then bounding, is what makes the bound tight enough to be safe —
    a raw-length bound loose enough to admit the decorated label also admits a short
    sentence that happens to mention the word.
    """
    if not cell:
        return None
    bare = _SWOT_DECOR.sub("", cell).strip()
    if not bare or len(bare) > SWOT_LABEL_MAX_CHARS:
        return None
    for key, _lbl, pat in _SWOT_QUADRANTS:
        if re.search(pat, bare, re.IGNORECASE):
            return key
    return None


def parse_swot(body: str) -> dict:
    """§2.18a's 2×2 table → {threat, strength, weakness, opportunity} of raw markdown.

    Matched by the LABEL cell rather than by position. The prompt emits
    Threats/Strengths on the first header row and Weaknesses/Opportunities on the
    third, but that ordering is prose written by a model — keying on position would
    turn a reordered table into a report that labels strengths as threats, which is
    worse than showing nothing.

    **Two table layouts are in the corpus, and both must work.** The common one is a
    2×2 grid (label row, content row, label row, content row); four reports from
    2026-08-05 instead use a vertical list, one quadrant per row as
    `| **Strengths** | …content… |`. A parser that only looked down at the next row
    read all four of those as empty and dropped the card. So content is taken from the
    cell to the RIGHT first, then the cell BELOW — in the grid layout the cell to the
    right is the neighbouring *label*, which is rejected as content and falls through
    to the correct one.
    """
    chunk = extract_section(body, r"SWOT")
    rows = parse_md_table(chunk) if chunk else []
    found: dict[str, str] = {}
    for ri, row in enumerate(rows):
        for ci, cell in enumerate(row):
            key = _swot_label(cell)
            if not key or key in found:
                continue
            right = row[ci + 1] if ci + 1 < len(row) else ""
            below = rows[ri + 1][ci] if (ri + 1 < len(rows) and ci < len(rows[ri + 1])) else ""
            for cand in (right, below):
                if cand and _swot_label(cand) is None:
                    found[key] = cand
                    break
    return found


_SWOT_ITEM_SPLIT = re.compile(r"<br\s*/?>", re.IGNORECASE)
# The tag as prompts/06_swot.md emits it, plus the separator it is followed by.
# Bold for MATERIAL and italic for minor is the markdown a reader sees in
# Obsidian; the class is what the HTML styles on.
# The letter/digit lookahead stops "Materially different capital structure" being
# read as a tag and truncated to "ly different…". It is spelled out rather than
# written \b because underscore IS a word character, so \b would reject the
# perfectly valid `__MATERIAL__`. The dash/colon separator is MANDATORY for the
# same class of reason: without it, an item legitimately opening "Material
# weakness in controls" would lose its first word.
_SWOT_TAG = re.compile(
    r"^\s*(?:[*_]{1,2})?\s*(MATERIAL|minor)(?![A-Za-z0-9])\s*"
    r"(?:[*_]{1,2})?\s*[-–—:]\s*",
    re.IGNORECASE)


def split_swot_items(cell: str) -> list[tuple[str | None, str]]:
    """A SWOT cell → [(materiality, text)], materiality in {"material","minor",None}.

    Splits on the literal `<br>` the prompt emits — chosen because it is the one
    line break that renders inside BOTH an Obsidian table cell and the HTML card.
    A cell with no `<br>` yields one item, and a cell whose items carry no tag
    yields None for every materiality, which is how the 40 pre-v4.3 reports on
    disk keep rendering as the prose their author actually wrote.
    """
    out: list[tuple[str | None, str]] = []
    for raw in _SWOT_ITEM_SPLIT.split(cell or ""):
        # NOT _normalise_ws — that lowercases, because it exists to compare two
        # prose strings. This text is displayed.
        txt = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not txt:
            continue
        m = _SWOT_TAG.match(txt)
        if m:
            out.append((m.group(1).lower(), txt[m.end():].strip()))
        else:
            out.append((None, txt))
    return out


def build_swot(body: str) -> str:
    """SWOT as a 2×2 card, Threats first — matching the prompt's own weighting.

    Like the Sankey and the duel, this content existed only in the markdown. Threats
    lead because `prompts/06_swot.md` weights them double, and a card that opened with
    Strengths would quietly invert the emphasis the analysis was written with.
    """
    quads = parse_swot(body)
    if not quads:
        return ""
    cells, tagged_any = [], False
    for key, label, _pat in _SWOT_QUADRANTS:
        txt = quads.get(key)
        if not txt:
            continue
        items = split_swot_items(txt)
        if any(m for m, _ in items):
            tagged_any = True
            lis = "".join(
                f'<li class="swot-{mat or "untagged"}">{md_inline(t)}</li>'
                for mat, t in items)
            inner = f"<ul class=\"swot-items\">{lis}</ul>"
        else:
            # Untagged prose — every report written before v4.3 tags. Rendering
            # one <li> per sentence would invent a structure the analyst did not
            # write, so it stays a paragraph.
            inner = f"<p>{md_inline(txt)}</p>"
        cells.append(f'<div class="swot-q swot-{key}"><h3>{esc(label)}</h3>'
                     f'{inner}</div>')
    if not cells:
        return ""
    note = ('<p class="sub">Qualitative overlay — no score enters the composite. '
            'Threats lead by design.'
            + (' <b>MATERIAL</b> = would change the verdict or the position size.'
               if tagged_any else '') + '</p>')
    return _card("SWOT", f'<div class="swot-grid">{"".join(cells)}</div>{note}',
                 "swot", new="v4.3")


def build_sankey(body: str, out_dir: Path, ticker: str, fm: dict):
    """The money-engine Sankey, rendered to PNG and embedded. Returns (html, bytes_used).

    170 deep reports carry a ```mermaid `sankey-beta` block that Obsidian renders and
    the HTML — the artifact that is actually delivered — did not. This is where that
    gap closes.

    Fallback-first, three ways: no diagram in the body, mermaid disabled, or a failed
    render all return ("", 0). The fence still appears inside the collapsed "Full
    written analysis" appendix, so the reader loses the picture, never the numbers.
    """
    src = mermaid_render.find_sankey(body or "")
    if not src:
        return "", 0
    date = fm.get("date") or ""
    safe = (ticker or "").replace("/", "_")
    png = out_dir / "IMG" / f"{date}_{safe}_sankey.png"
    if not mermaid_render.render(src, png):
        return "", 0
    try:
        raw = png.read_bytes()
    except OSError:
        return "", 0
    if not raw or len(raw) > IMG_BUDGET_BYTES:
        # A single image must never eat the whole budget and starve the charts.
        log(f"sankey PNG {len(raw)} B exceeds the image budget — dropped")
        return "", 0
    b64 = base64.b64encode(raw).decode("ascii")
    fig = (f'<figure style="margin:4px 0 0"><img class="chart" alt="Money-flow Sankey" '
           f'src="data:image/png;base64,{b64}">'
           f'<figcaption class="sub">Revenue → costs → net income → capital allocation. '
           f'Hues are assigned by the renderer and carry no meaning; read the diagram '
           f'left to right.</figcaption></figure>')
    return _card("Money engine", fig, "sankey", new="v4.3"), len(raw)


def build_charts(md_path: Path, out_dir: Path, ticker: str, fm: dict, used: int = 0):
    """Base64-embed the render_charts PNGs under IMG_BUDGET_BYTES. Returns (html, dropped).

    `used` carries bytes already spent by earlier images (the Sankey) so the budget is
    one shared allowance rather than one-per-builder — otherwise adding images silently
    multiplies the cap the spec fixed at 1.5 MB.
    """
    date = fm.get("date") or (md_path.stem.split("_")[0] if "_" in md_path.stem else "")
    safe = (ticker or "").replace("/", "_")
    img_dir = out_dir / "IMG"
    dropped, blocks = [], []
    labels = {"price": "Price & moving averages", "ni_pe": "Net income vs P/E",
              "ebitda_fcf": "EBITDA & FCF history", "relperf": "Relative performance 30m",
              "dcf": "DCF fan", "peers": "Peer comparison", "radar": "Score radar",
              "peers5y": "5y total return vs competitors (EUR)",
              "evolution": "Long-horizon evolution", "segments": "Revenue segments"}
    for key in CHART_ORDER:
        p = img_dir / f"{date}_{safe}_{key}.png"
        if not p.exists():
            continue
        raw = p.read_bytes()
        if used + len(raw) > IMG_BUDGET_BYTES:
            dropped.append(key)
            continue
        used += len(raw)
        b64 = base64.b64encode(raw).decode("ascii")
        blocks.append(f'<figure style="margin:10px 0"><img class="chart" alt="{esc(labels.get(key,key))}" '
                      f'src="data:image/png;base64,{b64}"><figcaption class="sub">{esc(labels.get(key,key))}</figcaption></figure>')
    if not blocks:
        return "", dropped
    note = f'<p class="sub">Charts omitted for size budget: {", ".join(dropped)}.</p>' if dropped else ""
    return _card("Charts", "".join(blocks) + note, "charts"), dropped


def run_host():
    """Hostname of the machine that produced this report — stamped so it is
    obvious which machine ran the job (the laptop or a VM host)."""
    import platform
    try:
        return platform.node() or "unknown"
    except Exception:
        return "unknown"


def run_user():
    """The account that produced this report. Paired with the hostname so a report found
    later can be traced to the run that made it, not just to the machine."""
    import getpass
    try:
        return getpass.getuser() or "unknown"
    except Exception:
        return "unknown"


def build_footer(data, fm):
    model = data.get("model_name") or "Claude Opus 4.8"
    asof = (data.get("fetched_at") or fm.get("date") or "")[:10]
    src = "yfinance / Alpha Vantage / stockanalysis (ground-truth); commentary by the model."
    # The version is read from `version.py`, the single source — never a literal here. The
    # SKILL.md H1 drifted a whole version precisely because a version lived in prose, and
    # this watermark is what makes a skipped bump visible on the face of every report.
    return (f'<footer>Horizon 1–5 years · Quality Compounder + Piotroski + Altman · data: {esc(src)}<br>'
            f'Analysis written by {esc(model)} · as-of {esc(asof)} · bsdias©2026 '
            f'· host: {esc(run_host())} · user: {esc(run_user())} '
            f'· skill v{esc(version.version_string())}</footer>')


NAV_ITEMS = [("tldr", "TL;DR"), ("duel", "Bull vs Bear"), ("stars", "⭐ Ratings"),
             ("exit", "Exit Plan"),
             ("val", "Valuation"), ("vcompare", "Methods compared"),
             ("metrics", "Metric families"), ("flags", "Red Flags"),
             ("lens", "Category lens"), ("ret", "Return profile"), ("op", "Opinion panel"), ("news", "News & sentiment"),
             ("peer", "Peers"), ("swot", "SWOT"), ("sankey", "Money engine"),
             ("charts", "Charts")]


def build_nav(present_ids):
    links = "".join(f'<a href="#{aid}">{esc(lbl)}</a>' for aid, lbl in NAV_ITEMS if aid in present_ids)
    return f'<nav>{links}<div class="tag">BD FINANCE</div></nav>'


# ===================================================================
# Assembly
# ===================================================================
def render(md_text: str, data: dict, md_path: Path, out_dir: Path, icon_b64: str) -> str:
    fm, body = split_frontmatter(md_text)
    ticker = data.get("ticker") or fm.get("ticker") or "?"

    header = build_header(data, fm, icon_b64)
    hero = build_hero(data)
    disc = '<div class="disc">🤖 Auto-generated · <b>not investment advice.</b> Verify all figures before acting.</div>'

    # The cover sits OUTSIDE <main>, directly under the header, because the plan's
    # requirement is that printed page 1 *is* the wrap-up. Left inside <main> it landed on
    # page 2 behind the hero radar and metric tiles — verified by print-media screenshot,
    # which is the only way to see it.
    cover = build_cover(data, fm, body)

    cards = []
    cards.append(build_tldr(fm, body, data))
    duel = build_thesis_duel(body)
    if duel:
        cards.append(duel)
    stars = build_stars(data)
    if stars:
        cards.append(stars)
    for fn in (build_exit, build_valuation, build_valuation_compare,
               build_metric_families, build_redflags, build_lens,
               build_return_profile, build_opinion, build_news_sentiment, build_peers):
        html_ = fn(data)
        if html_:
            cards.append(html_)
    swot = build_swot(body)
    if swot:
        cards.append(swot)
    # The Sankey is embedded before the charts so it competes for the SAME 1.5 MB
    # budget rather than adding to it; on a tight report a low-priority chart is
    # dropped, which is the behaviour the budget already defines.
    sankey_html, sankey_bytes = build_sankey(body, out_dir, ticker, fm)
    if sankey_html:
        cards.append(sankey_html)
    charts_html, _ = build_charts(md_path, out_dir, ticker, fm, used=sankey_bytes)
    if charts_html:
        cards.append(charts_html)
    # bull/bear + full written analysis appendix
    thesis = extract_label(body, "Thesis")
    risks = extract_label(body, "Risks") or extract_label(body, "Risk")
    if thesis or risks:
        two = ('<div class="two">'
               f'<div class="side bull"><h3>▲ Bull</h3><ul><li>{esc(thesis or "—")}</li></ul></div>'
               f'<div class="side bear"><h3>▼ Bear — risks</h3><ul><li>{esc(risks or "—")}</li></ul></div></div>')
        cards.append(_card("Thesis & risks", two, "thesis"))
    cards.append(f'<details><summary>📄 Full written analysis</summary><div class="md">{md_to_html(body)}</div></details>')

    present = {aid for aid, _ in NAV_ITEMS if f'id="{aid}"' in "".join(cards)}
    nav = build_nav(present)
    footer = build_footer(data, fm)

    body_html = (f'<div class="wrap">{header}{disc}{cover}{hero}{nav}'
                 f'<main>{"".join(cards)}</main>{footer}</div>')
    template = TEMPLATE.read_text(encoding="utf-8")
    company = data.get("company_name") or ticker
    title = f"BD Finance — {ticker} ({company})"
    return template.replace("{{TITLE}}", esc(title)).replace("{{BODY}}", body_html)


_VERDICT_SUFFIXES = ("great", "invest", "review", "fair", "reject")
# Deep reports are named `_<verdict>.html`; screens are named `_screen.html`. Matching
# verdicts only hid every screen from the hub — on a normal day that is 4 of 5 reports.
# The suffix is just a filename token: the authoritative verdict is the sibling .md's
# frontmatter, which is why `screen` is admitted here and resolved below.
_REPORT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})_(.+)_(" + "|".join((*_VERDICT_SUFFIXES, "screen")) + r")\.html$")


def index_reports(out_dir: Path, date: str) -> list[dict]:
    """Discover the day's rendered report HTMLs for the index hub — deep AND screen.
    Reads each sibling .md's frontmatter (frozen contract) for verdict/score → action
    verb, and carries `mode` so a screen is never mistaken for a deep-dive.
    Sorted by score desc (None last), then ticker."""
    rows = []
    for p in sorted(out_dir.glob(f"{date}_*.html")):
        m = _REPORT_RE.match(p.name)
        if not m:
            continue
        ticker, suffix = m.group(2), m.group(3)
        verdict = suffix if suffix in _VERDICT_SUFFIXES else ""
        fm = {}
        md = p.with_suffix(".md")
        if md.exists():
            try:
                fm, _ = split_frontmatter(md.read_text(encoding="utf-8"))
            except Exception:
                fm = {}
        try:
            score = float(fm.get("score"))
        except (TypeError, ValueError):
            score = None
        resolved = (fm.get("verdict") or verdict or "review").lower()
        verb = action_verb(resolved, fm.get("mos_class"), fm.get("go_no_go"))
        mode = (fm.get("mode") or ("screen" if suffix == "screen" else "deep")).lower()
        rows.append({"ticker": fm.get("ticker") or ticker, "verdict": resolved,
                     "score": score, "action": verb, "mode": mode, "href": p.name})
    rows.sort(key=lambda r: (-(r["score"] if r["score"] is not None else -1), r["ticker"]))
    return rows


def refresh_cumulative_index(out_dir: Path) -> str | None:
    """Rebuild the cumulative `index.html` from every report on disk. Returns its path,
    or None if it could not be built.

    Delegates to `docs/_build_index.py`, which already knows how to scan the whole folder
    — reimplementing that scan here would give the vault two indexers that drift apart,
    which is the shape of the bug this is fixing.

    **Never raises.** Phase 6 is the step the 2026-08-15 timeout skipped, so it must be
    cheap and it must not be able to take a run down after the reports are already on disk.
    """
    script = out_dir / "docs" / "_build_index.py"
    if not script.exists():
        log(f"cumulative index skipped — {script} not found")
        return None
    import subprocess
    try:
        proc = subprocess.run([sys.executable, str(script)], cwd=str(out_dir),
                              capture_output=True, text=True, timeout=180)
    except Exception as exc:  # noqa: BLE001 — an index refresh must never end a run
        log(f"cumulative index failed ({type(exc).__name__}: {exc})")
        return None
    target = out_dir / "index.html"
    if proc.returncode != 0 or not target.exists():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        log(f"cumulative index failed (rc={proc.returncode}): {tail[-1] if tail else 'no output'}")
        return None
    log(f"cumulative index refreshed ({target.stat().st_size // 1024} KB)")
    return str(target)


def build_index_html(out_dir: Path, date: str, icon_b64: str) -> str:
    rows = index_reports(out_dir, date)
    header = (
        '<header>'
        f'<div class="brand">{("<img class=\"brand-icon\" alt=\"BD Finance\" src=\"data:image/png;base64,%s\">" % icon_b64) if icon_b64 else ""}'
        '<div class="brand-txt"><span class="wm">BD <b>Finance</b></span><small>EQUITY RESEARCH</small></div></div>'
        f'<div class="hdr-mid"><div class="tk">Daily reports</div>'
        f'<div class="sub">Quality Compounder · {esc(date)}</div></div>'
        '<div class="hdr-right"></div></header>')
    if rows:
        cards = []
        for r in rows:
            vclass = r["verdict"] if r["verdict"] in VERDICT_LABELS else "review"
            score_txt = f'{r["score"]:.1f}/10' if r["score"] is not None else "n/a"
            tier = ('<span class="idx-tier">SCREEN</span>'
                    if r.get("mode") == "screen" else "")
            cards.append(
                f'<a class="idx-card" href="{esc(r["href"])}">'
                f'<div class="idx-tk">{esc(r["ticker"])}{tier}</div>'
                f'<div class="verdict {vclass}">{esc(VERDICT_LABELS.get(r["verdict"],"REVIEW"))}</div>'
                f'<div class="idx-meta">Quality <b>{esc(score_txt)}</b> · <b>{esc(r["action"])}</b></div></a>')
        inner = f'<div class="idx-grid">{"".join(cards)}</div>'
    else:
        inner = '<div class="nabox">No reports rendered for this date yet.</div>'
    footer = f'<footer>{len(rows)} report(s) · as-of {esc(date)} · bsdias©2026</footer>'
    style = ('<style>.idx-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px}'
             '.idx-card{display:block;text-decoration:none;color:inherit;background:var(--card);border:1px solid var(--line);'
             'border-radius:12px;padding:14px 16px;box-shadow:var(--shadow)}.idx-card:hover{border-color:var(--bd-green)}'
             '.idx-tk{font-size:18px;font-weight:800;margin-bottom:8px}.idx-card .verdict{font-size:12px}'
             '.idx-tier{font-size:9px;font-weight:700;letter-spacing:.7px;margin-left:7px;padding:2px 5px;'
             'border:1px solid var(--line);border-radius:4px;color:var(--muted);vertical-align:2px}'
             '.idx-meta{font-size:12.5px;color:var(--muted);margin-top:8px}</style>')
    body_html = f'<div class="wrap" style="grid-template-columns:1fr">{header}<main>{style}{_card("Today’s reports", inner, "reports")}</main>{footer}</div>'
    template = TEMPLATE.read_text(encoding="utf-8")
    return template.replace("{{TITLE}}", esc(f"BD Finance — reports {date}")).replace("{{BODY}}", body_html)


def load_icon_b64() -> str:
    try:
        return base64.b64encode(ICON.read_bytes()).decode("ascii")
    except Exception as e:
        log(f"brand icon unavailable: {e}")
        return ""


def run(md_path: Path, analysis_json: Path, out_path: Path | None, out_dir: Path) -> Path:
    md_text = md_path.read_text(encoding="utf-8")
    data = json.loads(analysis_json.read_text(encoding="utf-8")) if analysis_json and analysis_json.exists() else {}
    html_out = render(md_text, data, md_path, out_dir, load_icon_b64())
    target = out_path or md_path.with_suffix(".html")
    target.write_text(html_out, encoding="utf-8")
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a deep report (md + analysis JSON) → self-contained HTML")
    ap.add_argument("--md", default=None, help="path to the report .md")
    ap.add_argument("--analysis-json", default=None, help="path to the analyze_ticker JSON (for the structured cards)")
    ap.add_argument("--out", default=None, help="output .html path (default: alongside the .md)")
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT), help="StocksDaily root (for IMG/ charts)")
    ap.add_argument("--index", default=None, metavar="DATE",
                    help="build the daily index.html hub for DATE (YYYY-MM-DD) from OUT_DIR reports; ignores --md")
    args = ap.parse_args()

    if args.index:
        # v4.3: `index.html` — the file the bookmark points at — is now the CUMULATIVE
        # index, and the per-date hub moves to `_index_{date}.html`.
        #
        # The two files were never duplicates, and that was the actual bug behind "the
        # index is out of date". `index.html` was `--index {date}` output, a single-date
        # hub *overwritten every day*, so yesterday's reports vanished from it. The
        # cumulative index lived at `_index.html`, built by `docs/_build_index.py`, which
        # nothing scheduled — it had been stale since 2026-08-06.
        try:
            out_dir = Path(args.out_dir)
            target = Path(args.out) if args.out else (out_dir / f"_index_{args.index}.html")
            target.write_text(build_index_html(out_dir, args.index, load_icon_b64()), encoding="utf-8")
        except Exception as e:
            log(f"FATAL(index): {type(e).__name__}: {e}")
            print(json.dumps({"error": str(e), "error_type": type(e).__name__}))
            return 0
        cumulative = None if args.out else refresh_cumulative_index(Path(args.out_dir))
        print(json.dumps({"index": str(target), "cumulative_index": cumulative,
                          "n_reports": len(index_reports(Path(args.out_dir), args.index))},
                         ensure_ascii=False))
        return 0

    if not args.md:
        ap.error("--md is required unless --index is given")

    try:
        md_path = Path(args.md)
        aj = Path(args.analysis_json) if args.analysis_json else None
        target = run(md_path, aj, Path(args.out) if args.out else None, Path(args.out_dir))
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        print(json.dumps({"error": str(e), "error_type": type(e).__name__}))
        return 0  # non-fatal: the md report is already on disk
    size_kb = target.stat().st_size / 1024
    print(json.dumps({"html": str(target), "size_kb": round(size_kb, 1)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
