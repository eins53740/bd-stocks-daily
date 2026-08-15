"""Browser-rendered charts (option C) — HTML/CSS/SVG screenshotted by Chromium.

WHY a second renderer exists. matplotlib cannot reach web typography, gradient
fills, true rounded bar caps or soft shadows; a browser can, and playwright +
Chromium are already installed on this machine for the pdfgen toolchain, so this
costs no new dependency. It is deliberately scoped to the TWO charts a reader
actually studies — the EBITDA/FCF history and the relative-performance line. The
radar, DCF, peers and segments charts gain too little to justify widening the
surface.

WHY it can never break the daily job. Every entry point returns False instead of
raising, and `render_charts.py` falls straight back to the matplotlib version on
False. The unattended 17:00 run therefore degrades to exactly its previous output
if Chromium is missing, slow, or blocked. Set BD_CHARTS_BROWSER=0 to force the
matplotlib path.

Colours come from `chart_theme` so the two renderers cannot drift apart: the theme
stays the single visual system, and this module is one more consumer of it.
"""
from __future__ import annotations

import os
from pathlib import Path

import chart_theme as th

DEVICE_SCALE = 2          # retina-density PNG; the report embeds at 1x
LAUNCH_TIMEOUT_MS = 20000  # cold Chromium start measured ~8s on this laptop


def log(msg: str) -> None:
    print(f"[chart_browser] {msg}", flush=True)


def enabled() -> bool:
    """False when the operator has switched the browser path off."""
    val = (os.environ.get("BD_CHARTS_BROWSER", "1") or "1").strip().lower()
    return val not in ("0", "false", "no", "off")


def _money(x: float) -> str:
    ax = abs(x)
    if ax >= 1e12:
        return f"{x / 1e12:.1f}T"
    if ax >= 1e9:
        return f"{x / 1e9:.1f}B"
    if ax >= 1e6:
        return f"{x / 1e6:.0f}M"
    if ax >= 1e3:
        return f"{x / 1e3:.0f}k"
    return f"{x:,.0f}"


def _shell(body: str, w: int, h: int) -> str:
    """The page chrome shared by every browser chart."""
    return f"""<!doctype html><meta charset="utf-8"><style>
* {{ box-sizing:border-box; margin:0; padding:0 }}
body {{ width:{w}px; height:{h}px; background:transparent; color:{th.INK};
  font-family:"Segoe UI Variable Text","Segoe UI",Inter,system-ui,sans-serif;
  -webkit-font-smoothing:antialiased }}
.wrap {{ padding:20px 24px 0 }}
h1 {{ font-size:22px; font-weight:700; letter-spacing:-.35px }}
h1 span {{ color:{th.INK_MUTED}; font-weight:400 }}
.sub {{ font-size:12px; color:{th.INK_SECONDARY}; margin-top:4px; line-height:1.4 }}
svg {{ position:absolute; left:0; top:0 }}
.grid {{ stroke:{th.GRID}; stroke-width:1 }}
.ytick {{ fill:{th.INK_MUTED}; font-size:11px; text-anchor:end }}
.xtick {{ fill:{th.INK_SECONDARY}; font-size:11.5px; text-anchor:middle }}
.axlab {{ fill:{th.INK_MUTED}; font-size:10px; font-weight:600; letter-spacing:1.1px;
  text-anchor:middle }}
.zero {{ stroke:{th.AXIS}; stroke-width:1 }}
.foot {{ position:absolute; left:24px; bottom:9px; font-size:10.5px; color:{th.INK_MUTED} }}
.lg {{ display:flex; gap:18px; margin-top:12px; font-size:11.5px; color:{th.INK_SECONDARY};
  align-items:center; flex-wrap:wrap }}
.lg i {{ display:inline-block; width:22px; height:3px; border-radius:2px; margin-right:6px;
  vertical-align:3px }}
.lg .bx {{ height:11px; border-radius:2px }}
.pill rect {{ fill:none; stroke-width:1.4 }}
.pill text {{ font-size:12px; font-weight:700; text-anchor:middle }}
</style>{body}"""


def _screenshot(html: str, out_path: Path, w: int, h: int) -> bool:
    tmp = Path(out_path).with_suffix(".tmp.html")
    try:
        tmp.write_text(html, encoding="utf-8")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(timeout=LAUNCH_TIMEOUT_MS)
            try:
                pg = b.new_page(viewport={"width": w, "height": h},
                                device_scale_factor=DEVICE_SCALE)
                pg.goto(tmp.as_uri())
                pg.wait_for_timeout(220)   # let fonts settle before the capture
                # omit_background keeps the PNG alpha channel, matching the
                # matplotlib path: one image that reads on a light or dark page.
                pg.screenshot(path=str(out_path), omit_background=True)
            finally:
                b.close()
        ok = Path(out_path).is_file() and Path(out_path).stat().st_size > 0
        if ok:
            # Same palette quantisation the matplotlib path gets. It matters MORE here: a Chromium
            # screenshot is truecolour and these are the two largest charts in the whole report
            # (ebitda_fcf 383 KB, relperf 286 KB — together ~20% of all PNG bytes). Measured
            # 2026-08-03: 383 -> 66 KB and 286 -> 66 KB. Without this call they were the only
            # charts left untouched, because they never pass through chart_theme.save().
            th.quantize_png(out_path)
        return ok
    except Exception as e:
        log(f"screenshot failed, falling back to matplotlib: {e}")
        return False
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _nice_ticks(vmin: float, vmax: float, n: int = 4) -> list[float]:
    """Round-ish gridline values spanning the range. Deliberately simple: the axis
    is decoration for a shape the reader is scanning, not a measuring instrument."""
    if not (vmax > vmin):
        return [vmax]
    span = vmax - vmin
    raw = span / n
    mag = 10 ** int(f"{raw:e}".split("e")[1])
    for m in (1, 2, 2.5, 5, 10):
        if raw <= mag * m:
            step = mag * m
            break
    else:
        step = mag * 10
    out, v = [], (int(vmin / step) + (1 if vmin > 0 else 0)) * step
    while v <= vmax and len(out) < n + 2:
        out.append(v)
        v += step
    return out or [vmax]


# --------------------------------------------------------------- EBITDA & FCF
def render_ebitda_fcf(fin_history: dict, out_path: Path) -> bool:
    """Two stacked panels: EBITDA bars + FCF area, each with a TTM trend line and a
    shaded forecast tail. Mirrors chart_ebitda_fcf's content exactly — same series,
    same TTM definition, same forecast caveat — so the two renderers are
    interchangeable and only the finish differs."""
    if not enabled():
        return False
    try:
        s = (fin_history or {}).get("series") or {}
        labels = [str(x) for x in (s.get("labels") or [])]
        eb = [None if v is None else float(v) for v in (s.get("ebitda") or [])]
        fc = [None if v is None else float(v) for v in (s.get("fcf") or [])]
        if not labels or (not any(v is not None for v in eb)
                          and not any(v is not None for v in fc)):
            return False
        f = fin_history.get("forecast") or {}
        f_labels = [str(x) for x in (f.get("labels") or [])]
        f_eb = [float(v) for v in (f.get("ebitda") or [])]
        f_fc = [float(v) for v in (f.get("fcf") or [])]
        if len(f_eb) != len(f_labels) or len(f_fc) != len(f_labels):
            f_labels, f_eb, f_fc = [], [], []

        ticker = fin_history.get("ticker", "")
        currency = fin_history.get("currency", "")
        source = fin_history.get("source", "?")
        n_q = fin_history.get("quarters_available", len(labels))

        # Vertical budget, top-down: header+legend (~160) | panel 1 | gap | panel 2 |
        # x-tick row (+25) | footer (~24). Shrinking H without shrinking panel 2 put
        # the year labels on top of the footnote, so the two are sized together.
        W, H = 1240, 772
        PAD_L, PAD_R = 70, 26
        P1_T, P1_H = 172, 270
        P2_T, P2_H = 484, 204
        n_h, n_f = len(labels), len(f_labels)
        n = n_h + n_f
        plot_w = W - PAD_L - PAD_R
        step = plot_w / max(1, n)
        bw = min(step * 0.62, 22)
        all_labels = labels + f_labels

        eb_all = [v for v in eb if v is not None] + f_eb
        fc_all = [v for v in fc if v is not None] + f_fc
        eb_max = max(eb_all + [0]) * 1.14 or 1.0
        fc_min = min(fc_all + [0])
        fc_max = max(fc_all + [0]) * 1.14 or 1.0
        fc_lo = fc_min * 1.14 if fc_min < 0 else 0.0

        def x_of(i):
            return PAD_L + step * (i + 0.5)

        def y1(v):
            return P1_T + P1_H - (v / eb_max) * P1_H

        def y2(v):
            return P2_T + P2_H - ((v - fc_lo) / (fc_max - fc_lo)) * P2_H

        parts = []
        for vals, yf, top, hh in ((eb_all, y1, P1_T, P1_H), (fc_all, y2, P2_T, P2_H)):
            for tv in _nice_ticks(fc_lo if yf is y2 else 0.0,
                                  fc_max if yf is y2 else eb_max):
                y = yf(tv)
                if top - 1 <= y <= top + hh + 1:
                    parts.append(f'<line class="grid" x1="{PAD_L}" y1="{y:.1f}" '
                                 f'x2="{W - PAD_R}" y2="{y:.1f}"/>')
                    parts.append(f'<text class="ytick" x="{PAD_L - 9}" '
                                 f'y="{y + 4:.1f}">{_money(tv)}</text>')
        if fc_min < 0:
            parts.append(f'<line class="zero" x1="{PAD_L}" y1="{y2(0):.1f}" '
                         f'x2="{W - PAD_R}" y2="{y2(0):.1f}"/>')

        if n_f:
            bx = x_of(n_h) - step / 2
            for top, hh in ((P1_T, P1_H), (P2_T, P2_H)):
                parts.append(f'<rect x="{bx:.1f}" y="{top}" width="{W - PAD_R - bx:.1f}" '
                             f'height="{hh}" rx="6" fill="{th.PRIMARY}" fill-opacity=".07"/>')
                parts.append(f'<line x1="{bx:.1f}" y1="{top}" x2="{bx:.1f}" '
                             f'y2="{top + hh}" stroke="{th.INK_MUTED}" stroke-width="1" '
                             f'stroke-dasharray="3 3"/>')
            # Sits below the panel top so it cannot collide with the last-value
            # pill, which lands just left of the band.
            parts.append(f'<text class="axlab" x="{(bx + W - PAD_R) / 2:.1f}" '
                         f'y="{P1_T + 38}">FORECAST {n_f}Q</text>')

        # Bars: rounded at the data end, square on the baseline. A rect with rx
        # rounds all four corners, which detaches the bar from its axis.
        def bar(cx, v):
            r = min(4.0, bw / 2)
            h = (v / eb_max) * P1_H
            y, base = y1(v), P1_T + P1_H
            x0, x1 = cx - bw / 2, cx + bw / 2
            if h <= r:
                return (f'M{x0:.1f},{y:.1f} L{x1:.1f},{y:.1f} '
                        f'L{x1:.1f},{base:.1f} L{x0:.1f},{base:.1f} Z')
            return (f'M{x0:.1f},{base:.1f} L{x0:.1f},{y + r:.1f} '
                    f'Q{x0:.1f},{y:.1f} {x0 + r:.1f},{y:.1f} '
                    f'L{x1 - r:.1f},{y:.1f} Q{x1:.1f},{y:.1f} {x1:.1f},{y + r:.1f} '
                    f'L{x1:.1f},{base:.1f} Z')

        for i, v in enumerate(eb):
            if v is not None:
                parts.append(f'<path d="{bar(x_of(i), v)}" fill="url(#gb)"/>')
        for j, v in enumerate(f_eb):
            parts.append(f'<path d="{bar(x_of(n_h + j), v)}" fill="url(#gf)" '
                         f'stroke="{th.PRIMARY}" stroke-width=".8" stroke-dasharray="2.5 2"/>')

        def poly(idx_vals, yf, cls, extra=""):
            pts = " ".join(f"{x_of(i):.1f},{yf(v):.1f}" for i, v in idx_vals)
            return f'<polyline points="{pts}" class="{cls}" {extra}/>'

        ttm_e = th.trailing_avg(eb)
        pts_e = [(i, v) for i, v in enumerate(ttm_e) if v is not None]
        if pts_e:
            parts.append(poly(pts_e, y1, "", f'fill="none" stroke="{th.INK}" '
                              'stroke-width="2.1" stroke-linejoin="round" '
                              'stroke-linecap="round" filter="url(#soft)"'))

        hist_fc = [(i, v) for i, v in enumerate(fc) if v is not None]
        if hist_fc:
            area = (f'M{x_of(hist_fc[0][0]):.1f},{y2(max(fc_lo, 0)):.1f} '
                    + " ".join(f'L{x_of(i):.1f},{y2(v):.1f}' for i, v in hist_fc)
                    + f' L{x_of(hist_fc[-1][0]):.1f},{y2(max(fc_lo, 0)):.1f} Z')
            parts.append(f'<path d="{area}" fill="url(#ga)"/>')
            parts.append(poly(hist_fc, y2, "", f'fill="none" stroke="{th.AQUA}" '
                              'stroke-width="1.9" stroke-linejoin="round" stroke-linecap="round"'))
        if f_fc and hist_fc:
            tail = [(hist_fc[-1][0], fc[hist_fc[-1][0]])] + \
                   [(n_h + j, v) for j, v in enumerate(f_fc)]
            parts.append(poly(tail, y2, "", f'fill="none" stroke="{th.AQUA}" '
                              'stroke-width="1.9" stroke-dasharray="6 3.5" '
                              'stroke-linecap="round"'))
        ttm_f = th.trailing_avg(fc)
        pts_f = [(i, v) for i, v in enumerate(ttm_f) if v is not None]
        if pts_f:
            parts.append(poly(pts_f, y2, "", f'fill="none" stroke="{th.INK}" '
                              'stroke-width="2.1" stroke-linejoin="round" '
                              'stroke-linecap="round" filter="url(#soft)"'))

        for vals, yf, colour in ((eb, y1, th.PRIMARY), (fc, y2, th.AQUA)):
            idx = next((i for i in range(len(vals) - 1, -1, -1) if vals[i] is not None), None)
            if idx is None:
                continue
            # The pill is border-only (transparent PNG), so the dashed forecast
            # rule would show straight through it — shift it left of the boundary.
            cx = x_of(idx) - (38 if n_f else 0)
            y = yf(vals[idx])
            parts.append(f'<g class="pill"><rect x="{cx - 27:.1f}" y="{y - 30:.1f}" '
                         f'width="54" height="21" rx="10.5" stroke="{colour}"/>'
                         f'<text x="{cx:.1f}" y="{y - 15:.1f}" fill="{colour}">'
                         f'{_money(vals[idx])}</text></g>')

        for i, lab in enumerate(all_labels):
            if lab.endswith("Q1"):
                parts.append(f'<text class="xtick" x="{x_of(i):.1f}" '
                             f'y="{P2_T + P2_H + 25}">{lab[:4]}</text>')
        parts.append(f'<text class="axlab" transform="translate(19,{P1_T + P1_H / 2}) '
                     f'rotate(-90)">EBITDA</text>')
        parts.append(f'<text class="axlab" transform="translate(19,{P2_T + P2_H / 2}) '
                     f'rotate(-90)">FREE CASH FLOW</text>')

        basis = (f.get("basis") or "").replace("_", " ") if f else ""
        foot = ("shaded tail = derived forecast"
                + (f" · basis: {basis}" if basis else "")
                + " — not analyst guidance") if n_f else \
               "no forecast drawn (insufficient quarters)"
        legend = (f'<div class="lg">'
                  f'<span><i class="bx" style="background:{th.PRIMARY}"></i>EBITDA (quarterly)</span>'
                  f'<span><i style="background:{th.AQUA}"></i>FCF (quarterly)</span>'
                  f'<span><i style="background:{th.INK}"></i>TTM ÷ 4 (trend)</span>'
                  + (f'<span><i class="bx" style="background:#9cc4f2"></i>forecast</span>'
                     if n_f else "") + '</div>')

        body = f"""<div class="wrap">
  <h1>{ticker} <span>— EBITDA &amp; free cash flow</span></h1>
  <div class="sub">{n_q} quarters · source {source} · values in {currency} ·
    heavy line = trailing-twelve-month average, which removes fiscal-quarter seasonality</div>
  {legend}
</div>
<svg width="{W}" height="{H}"><defs>
  <linearGradient id="gb" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#4d92e8"/><stop offset="100%" stop-color="{th.PRIMARY}"/></linearGradient>
  <linearGradient id="gf" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#bcd8f7"/><stop offset="100%" stop-color="#9cc4f2"/></linearGradient>
  <linearGradient id="ga" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="{th.AQUA}" stop-opacity=".32"/>
    <stop offset="100%" stop-color="{th.AQUA}" stop-opacity=".03"/></linearGradient>
  <filter id="soft" x="-6%" y="-30%" width="112%" height="180%">
    <feDropShadow dx="0" dy="1.4" stdDeviation="1.5" flood-color="#101010" flood-opacity=".16"/></filter>
</defs>{''.join(parts)}</svg>
<div class="foot">{foot}</div>"""
        return _screenshot(_shell(body, W, H), Path(out_path), W, H)
    except Exception as e:
        log(f"ebitda_fcf build failed, falling back: {e}")
        return False


# ------------------------------------------------------- relative performance
def render_relperf(payload: dict, out_path: Path) -> bool:
    """Indexed-to-100 lines for the subject, its region index and a sector proxy.

    `payload` is produced by render_charts.relperf_payload() so both renderers see
    identical numbers: {"ticker", "series": [{"key","sym","points":[[ms,val],...]}],
    "subtitle", "notes"}.
    """
    if not enabled():
        return False
    try:
        series = [s for s in (payload or {}).get("series") or [] if s.get("points")]
        if not series:
            return False
        ticker = payload.get("ticker", "")
        W, H = 1180, 540
        PAD_L, PAD_R = 66, 92
        P_T, P_H = 150, 330

        xs = [p[0] for s in series for p in s["points"]]
        ys = [p[1] for s in series for p in s["points"]]
        x0, x1 = min(xs), max(xs)
        y0, y1v = min(ys + [100.0]), max(ys + [100.0])
        pad = (y1v - y0) * 0.10 or 1.0
        y0, y1v = y0 - pad, y1v + pad

        def px(v):
            return PAD_L + (v - x0) / max(1, (x1 - x0)) * (W - PAD_L - PAD_R)

        def py(v):
            return P_T + P_H - (v - y0) / (y1v - y0) * P_H

        COLOUR = {"ticker": th.PRIMARY, "bench": "#b8b6ad", "etf": th.ACCENT}
        WIDTH = {"ticker": 2.6, "bench": 1.7, "etf": 1.7}
        parts = []
        for tv in _nice_ticks(y0, y1v, 5):
            y = py(tv)
            parts.append(f'<line class="grid" x1="{PAD_L}" y1="{y:.1f}" '
                         f'x2="{W - PAD_R}" y2="{y:.1f}"/>')
            parts.append(f'<text class="ytick" x="{PAD_L - 9}" y="{y + 4:.1f}">{tv:,.0f}</text>')
        # 100 is the common base, not a gridline — dashed and darker.
        parts.append(f'<line x1="{PAD_L}" y1="{py(100):.1f}" x2="{W - PAD_R}" '
                     f'y2="{py(100):.1f}" stroke="{th.AXIS}" stroke-width="1.2" '
                     f'stroke-dasharray="5 4"/>')

        for s in series:
            key = s.get("key", "etf")
            c, lw = COLOUR.get(key, th.ACCENT), WIDTH.get(key, 1.7)
            pts = " ".join(f"{px(p[0]):.1f},{py(p[1]):.1f}" for p in s["points"])
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{c}" '
                         f'stroke-width="{lw}" stroke-linejoin="round" '
                         f'stroke-linecap="round"'
                         + (' filter="url(#soft)"' if key == "ticker" else "") + '/>')
            lx, ly = px(s["points"][-1][0]), py(s["points"][-1][1])
            parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.6" fill="{c}" '
                         f'stroke="{th.SURFACE}" stroke-width="1.6"/>')
            parts.append(f'<text x="{lx + 8:.1f}" y="{ly + 4:.1f}" font-size="11.5" '
                         f'font-weight="700" fill="{th.INK_SECONDARY}">'
                         f'{s.get("sym", "")} {s["points"][-1][1]:,.0f}</text>')

        parts.append(f'<text class="axlab" transform="translate(19,{P_T + P_H / 2}) '
                     f'rotate(-90)">INDEXED TO 100</text>')

        legend = '<div class="lg">' + "".join(
            f'<span><i style="background:{COLOUR.get(s.get("key"), th.ACCENT)}"></i>'
            f'{s.get("sym", "")}</span>' for s in series) + '</div>'
        notes = " · ".join(payload.get("notes") or [])
        body = f"""<div class="wrap">
  <h1>{ticker} <span>— relative performance, 2.5 years</span></h1>
  <div class="sub">{payload.get('subtitle', '')}</div>
  {legend}
</div>
<svg width="{W}" height="{H}"><defs>
  <filter id="soft" x="-4%" y="-20%" width="108%" height="150%">
    <feDropShadow dx="0" dy="1.3" stdDeviation="1.5" flood-color="#101010" flood-opacity=".15"/></filter>
</defs>{''.join(parts)}</svg>
{f'<div class="foot">{notes}</div>' if notes else ''}"""
        return _screenshot(_shell(body, W, H), Path(out_path), W, H)
    except Exception as e:
        log(f"relperf build failed, falling back: {e}")
        return False
