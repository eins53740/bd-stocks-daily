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

try:
    import metrics_glossary as glossary
except ImportError:  # pragma: no cover - only if scripts/ not on path
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("metrics_glossary", Path(__file__).resolve().parent / "metrics_glossary.py")
    glossary = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(glossary)

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
IMG_BUDGET_BYTES = 1_500_000  # ≤~1.5 MB of embedded PNGs per report (spec §11)

VERDICT_LABELS = {"great": "GREAT", "invest": "INVEST", "review": "REVIEW",
                  "fair": "FAIR", "reject": "REJECT"}
VERDICT_EMOJI = {"great": "🟢", "invest": "🟢", "review": "🟡", "fair": "🟠", "reject": "🔴"}
# PNG embedding priority (highest first) — lowest are dropped when over budget.
CHART_ORDER = ["price", "ni_pe", "ebitda_fcf", "relperf", "dcf", "peers", "radar", "segments"]


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


_INLINE = [(re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"),
           (re.compile(r"`(.+?)`"), r"<code>\1</code>"),
           (re.compile(r"==(.+?)=="), r"<mark>\1</mark>")]


def md_to_html(body: str) -> str:
    """Minimal, dependency-free markdown→HTML for the collapsible appendix.
    Handles headings, bold/code/highlight, tables, lists, blockquotes/callouts,
    hr and paragraphs. Not a full parser — enough for the report's own prose."""
    lines = body.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)

    def inline(t):
        t = esc(t)
        for pat, rep in _INLINE:
            t = pat.sub(rep, t)
        return t

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
    aid = f' id="{anchor}"' if anchor else ""
    tag = '<span class="new">NEW · v4</span>' if new else ""
    return (f'<section class="card"{aid}><h2><span class="pip"></span>{esc(title)}{tag}</h2>'
            f'{inner}</section>')


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
        f'<div class="sub">{esc(sector)}{" · " + esc(region) if region else ""} · Quality Compounder · as-of {esc(asof)}</div>'
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
    return _card("Exit Plan", f'<div class="exit-grid">{"".join(boxes)}</div>{yoc_html}', "exit", new=True)


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


def build_charts(md_path: Path, out_dir: Path, ticker: str, fm: dict):
    """Base64-embed the render_charts PNGs under IMG_BUDGET_BYTES. Returns (html, dropped)."""
    date = fm.get("date") or (md_path.stem.split("_")[0] if "_" in md_path.stem else "")
    safe = (ticker or "").replace("/", "_")
    img_dir = out_dir / "IMG"
    used, dropped, blocks = 0, [], []
    labels = {"price": "Price & moving averages", "ni_pe": "Net income vs P/E",
              "ebitda_fcf": "EBITDA & FCF history", "relperf": "Relative performance 30m",
              "dcf": "DCF fan", "peers": "Peer comparison", "radar": "Score radar",
              "segments": "Revenue segments"}
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


def build_footer(data, fm):
    model = data.get("model_name") or "Claude Opus 4.8"
    asof = (data.get("fetched_at") or fm.get("date") or "")[:10]
    src = "yfinance / Alpha Vantage / stockanalysis (ground-truth); commentary by the model."
    return (f'<footer>Horizon 1–5 years · Quality Compounder + Piotroski + Altman · data: {esc(src)}<br>'
            f'Analysis written by {esc(model)} · as-of {esc(asof)} · bsdias©2026 '
            f'· host: {esc(run_host())}</footer>')


NAV_ITEMS = [("tldr", "TL;DR"), ("exit", "Exit Plan"), ("val", "Valuation"),
             ("metrics", "Metric families"), ("flags", "Red Flags"),
             ("ret", "Return profile"), ("op", "Opinion panel"), ("news", "News & sentiment"),
             ("peer", "Peers"), ("charts", "Charts")]


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

    cards = []
    cards.append(build_tldr(fm, body, data))
    for fn in (build_exit, build_valuation, build_metric_families, build_redflags,
               build_return_profile, build_opinion, build_news_sentiment, build_peers):
        html_ = fn(data)
        if html_:
            cards.append(html_)
    charts_html, _ = build_charts(md_path, out_dir, ticker, fm)
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

    body_html = (f'<div class="wrap">{header}{hero}{disc}{nav}<main>{"".join(cards)}</main>{footer}</div>')
    template = TEMPLATE.read_text(encoding="utf-8")
    company = data.get("company_name") or ticker
    title = f"BD Finance — {ticker} ({company})"
    return template.replace("{{TITLE}}", esc(title)).replace("{{BODY}}", body_html)


_REPORT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)_(great|invest|review|fair|reject)\.html$")


def index_reports(out_dir: Path, date: str) -> list[dict]:
    """Discover the day's rendered report HTMLs for the index hub. Reads each
    sibling .md's frontmatter (frozen contract) for verdict/score → action verb.
    Sorted by score desc (None last), then ticker."""
    rows = []
    for p in sorted(out_dir.glob(f"{date}_*.html")):
        m = _REPORT_RE.match(p.name)
        if not m:
            continue
        ticker, verdict = m.group(2), m.group(3)
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
        verb = action_verb(fm.get("verdict") or verdict, fm.get("mos_class"), fm.get("go_no_go"))
        rows.append({"ticker": fm.get("ticker") or ticker, "verdict": (fm.get("verdict") or verdict).lower(),
                     "score": score, "action": verb, "href": p.name})
    rows.sort(key=lambda r: (-(r["score"] if r["score"] is not None else -1), r["ticker"]))
    return rows


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
            cards.append(
                f'<a class="idx-card" href="{esc(r["href"])}">'
                f'<div class="idx-tk">{esc(r["ticker"])}</div>'
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
        try:
            out_dir = Path(args.out_dir)
            target = Path(args.out) if args.out else (out_dir / "index.html")
            target.write_text(build_index_html(out_dir, args.index, load_icon_b64()), encoding="utf-8")
        except Exception as e:
            log(f"FATAL(index): {type(e).__name__}: {e}")
            print(json.dumps({"error": str(e), "error_type": type(e).__name__}))
            return 0
        print(json.dumps({"index": str(target), "n_reports": len(index_reports(Path(args.out_dir), args.index))}, ensure_ascii=False))
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
