r"""
chart_theme.py — one visual system for every PNG produced by render_charts.py.

Before this module each chart carried bare matplotlib defaults: the tab10 hue
cycle, a fully boxed frame, grey dashed-looking grids on both axes, centred bold
titles and dpi=100. Consistent, but consistently dated.

Everything here is styling only — no chart ever changes what it plots.

Palette provenance
------------------
Hues come from the validated reference palette of the `dataviz` skill. The
categorical slots are assigned IN FIXED ORDER and never cycled — a 7th series
folds into "Other" rather than inventing a hue.

The PNGs are TRANSPARENT (2026-07-28), so one image has to read on a light page,
a dark Obsidian theme, a white email client and paper. The palette is therefore
stepped into the DARK lightness band, which is a strict subset of the light band —
see the surfaces block below. Validated with the skill's own checker in BOTH modes:

  6 slots, light  ALL PASS  (contrast WARN on aqua 2.87 → relief obligation)
  6 slots, dark   ALL PASS
  worst adjacent CVD ΔE 9.3 (deutan) · normal-vision ΔE 16.8

The light-mode contrast WARN obliges *relief*: every chart using the lighter hues
ships a legend plus direct value labels. That is why `chart_revenue_segments`
labels its latest-year bars.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

# --- surfaces & ink ---------------------------------------------------------
# THE PNGs ARE TRANSPARENT. A static image cannot respond to the reader's theme —
# Obsidian will not swap it — so instead of choosing a background we draw on none,
# and the image adopts whatever page it lands on: light Obsidian, dark Obsidian, a
# white email client, or paper.
#
# The cost is real and worth stating: ink can no longer be near-black, because
# near-black vanishes on a dark page. Every ink step is now a MID-TONE chosen to
# clear 3:1 against BOTH a light (#fcfcfb) and a dark (#1e1e1e … #262626) surface.
# The theoretical ceiling for a colour equidistant from both is ~3.9:1, so these
# steps pass WCAG AA for large/bold text and non-text contrast, and do NOT reach
# the 4.5:1 body-text threshold on both surfaces simultaneously — no palette can.
# Titles are therefore set bold, and small print leans on INK_MUTED sparingly.
SURFACE = "#fcfcfb"      # the light reference surface: what the browser CSS and the
                         # contrast maths assume, NOT a fill painted into the PNG
INK = "#787772"          # primary ink: titles (bold)   light 4.37 · dark 3.37
INK_SECONDARY = "#84837d"  # axis labels, legends        light 3.70 · dark 3.98
INK_MUTED = "#928f88"    # tick labels, captions         light 3.14 · dark 4.69
GRID = "#a3a29b"         # hairline gridline — drawn at low alpha, so it is meant to
                         # sit below the 3:1 line: it is decoration, not information
AXIS = "#94938c"         # baseline / axis rule          light 3.00 · dark 4.91
RING = "#8b8a84"         # the ring around overlapping marks, replacing the old
                         # surface-coloured knockout (which became a light blob on a
                         # dark page)  light 3.37 · dark 4.37

# --- categorical slots (fixed order, never cycled) -------------------------
# Re-stepped 2026-07-28 into the DARK lightness band L [0.48, 0.67], which is a
# strict SUBSET of the light band [0.43, 0.77] — so one palette now validates on
# both surfaces, which is what a transparent PNG requires. Hue and chroma were
# held; only L moved. Verified with dataviz/scripts/validate_palette.js:
#   6 slots, light: ALL PASS (contrast WARN on #12ab77 2.87 -> relief via the
#            always-present legend + direct labels)
#   6 slots, dark:  ALL PASS
#   worst adjacent CVD dE 9.3 (deutan) · normal-vision 16.8 — both above floor
SERIES = [
    "#2a78d6",  # 1 blue      L 0.575 (unchanged)
    "#e6642f",  # 2 orange    L 0.671 -> 0.657
    "#12ab77",  # 3 aqua      L 0.669 -> 0.657
    "#c98000",  # 4 yellow    L 0.764 -> 0.661  (the biggest move)
    "#d46992",  # 5 magenta   L 0.716 -> 0.658
    "#008300",  # 6 green     L 0.529 (unchanged)
    "#594cba",  # 7 violet    L 0.433 -> 0.491  (was below the dark floor)
    "#e34948",  # 8 red       L 0.623 (unchanged)
]
PRIMARY = SERIES[0]
ACCENT = SERIES[1]
AQUA = SERIES[2]

# A lighter step of the primary hue — used for the same entity extended into a
# forecast, so the forecast keeps the series' identity and lets texture carry
# "this part is estimated".
PRIMARY_LIGHT = "#86b6ef"

# --- status palette (reserved — never used for a series) --------------------
GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"

DPI = 150

# Bars must never fill their slot: the leftover band is the air that separates
# neighbours, replacing the drawn borders the old charts leaned on.
#
# Bar ends are left square on purpose. The house style asks for a 4px rounded
# data-end, but matplotlib can only express a corner radius in DATA units
# (FancyBboxPatch.rounding_size), and these charts put wildly different scales on
# x and y — category positions against billions of currency units. A single
# radius therefore renders as a circle on one axis and a long ellipse on the
# other, turning short bars into lozenges. The separating air below is the
# load-bearing part of the spec; the rounding was cosmetic, so it is dropped
# rather than faked.
BAR_WIDTH = 0.62


def apply_theme() -> None:
    """Install the theme globally. Idempotent; call once per process."""
    mpl.rcParams.update({
        # Typography — the system sans, no display or serif face anywhere.
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Inter", "DejaVu Sans", "Arial", "sans-serif"],
        "font.size": 10,
        "axes.titlesize": 13,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        # Surfaces
        # "none" == transparent. See the surfaces note at the top of this module:
        # the PNG paints no background so it can sit on a light or dark page.
        "figure.facecolor": "none",
        "axes.facecolor": "none",
        "savefig.facecolor": "none",
        "savefig.dpi": DPI,
        "figure.dpi": DPI,
        # Ink
        "text.color": INK,
        "axes.labelcolor": INK_SECONDARY,
        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
        "xtick.labelcolor": INK_MUTED,
        "ytick.labelcolor": INK_MUTED,
        # Frame — drop the box, keep a soft baseline on the two axes that matter.
        "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        # Title: left-aligned and semibold rather than centred and heavy.
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.titlepad": 12,
        "axes.titlecolor": INK,
        # Grid: hairline, solid, recessive, horizontal only. Never dashed —
        # dashing reads as "threshold", which is reserved for reference lines.
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "grid.linestyle": "-",
        "grid.alpha": 1.0,
        "axes.axisbelow": True,
        # Marks
        "lines.linewidth": 2.0,
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
        "lines.markersize": 5.0,          # ≈10px at dpi 150
        "lines.markeredgewidth": 1.4,
        "patch.linewidth": 0,
        # Legend: an identity key, not a boxed panel.
        "legend.frameon": False,
        "legend.labelcolor": INK_SECONDARY,
        "legend.handlelength": 1.6,
        "legend.borderpad": 0.2,
        "legend.columnspacing": 1.4,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.size": 0,
        "ytick.major.size": 0,
    })


def style_axes(ax, title: str | None = None, subtitle: str | None = None,
               ylabel: str | None = None, grid_axis: str = "y",
               legend_row: bool = False) -> None:
    """Apply the per-axes chrome the rcParams cannot express.

    `subtitle` sits under the title in secondary ink — the place for provenance
    and caveats that used to be crammed into the title or a corner annotation.

    Set `legend_row=True` on any axes that also gets a `legend_above`: the title
    block and the legend both want the strip above the plot, so the title/subtitle
    are lifted to leave that row free. Without it the legend prints over the title.
    """
    ax.set_axisbelow(True)
    # Alpha, not a lighter hue: a fixed near-surface grey only recedes against the
    # surface it was picked for. Alpha recedes against whatever is actually behind.
    ax.grid(True, axis=grid_axis, color=GRID, linewidth=0.8, linestyle="-", alpha=0.45)
    if grid_axis == "y":
        ax.grid(False, axis="x")
    elif grid_axis == "x":
        ax.grid(False, axis="y")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_visible(True)
        ax.spines[side].set_color(AXIS)
        ax.spines[side].set_linewidth(0.8)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK_SECONDARY)
    # Vertical budget above the plot, bottom-up: [legend row] [subtitle] [title].
    legend_pad = LEGEND_ROW_PAD if legend_row else 0
    sub_y = 1.015 + (LEGEND_ROW_AXES_FRACTION if legend_row else 0.0)
    if title:
        ax.set_title(title, loc="left", fontsize=13, fontweight="semibold",
                     color=INK, pad=(16 if subtitle else 12) + legend_pad)
    if subtitle:
        # Placed in axes coordinates just above the plot, so it tracks the title
        # without needing a figure-level suptitle.
        ax.text(0.0, sub_y, subtitle, transform=ax.transAxes, ha="left",
                va="bottom", fontsize=9, color=INK_MUTED)


def caption(ax, text: str, color: str | None = None) -> None:
    """Footnote inside the axes, bottom-left — provenance and data caveats."""
    ax.text(0.0, -0.16, text, transform=ax.transAxes, ha="left", va="top",
            fontsize=8, color=color or INK_MUTED)


def marker_kwargs(color: str) -> dict:
    """Line markers carrying the 2px surface ring, so they stay legible where
    they cross their own line or another series."""
    return {
        "marker": "o",
        "markersize": 5.0,
        "markerfacecolor": color,
        "markeredgecolor": RING,
        "markeredgewidth": 1.4,
    }


# Height of the legend strip. Two numbers for the same gap in the two coordinate
# systems that need it: points for the title pad, axes-fraction for the subtitle.
LEGEND_ROW_PAD = 24
LEGEND_ROW_AXES_FRACTION = 0.085


def legend_above(ax, ncol: int = 3, handles=None, labels=None):
    """Legend lifted OUT of the plot area, onto the strip just above it.

    `loc="upper left"` puts the legend box on top of the data — with a rising
    series (the common case for a compounder) it lands squarely on the first bars
    and on the top y-tick label. Matplotlib's own `borderaxespad`/`framealpha`
    dodges only hide the collision behind a translucent panel. Moving the legend
    out of the axes removes it: nothing overlaps, and the plot keeps its full
    height. Frameless, since the strip needs no box to be read as a legend.
    """
    kw = dict(loc="lower left", bbox_to_anchor=(0, 1.01), ncol=ncol, frameon=False,
              fontsize=9, handlelength=1.6, columnspacing=1.4, borderpad=0,
              handletextpad=0.6)
    if handles is not None and labels is not None:
        return ax.legend(handles, labels, **kw)
    return ax.legend(**kw)


def figure_title(fig, title: str, subtitle: str | None = None,
                 top: float = 0.855) -> None:
    """Title/subtitle on the FIGURE, and reserve the top margin for them.

    Use this instead of `style_axes(title=...)` whenever the top axes also carries a
    `legend_above`: both want the strip directly above the axes, and an axes title
    loses — the legend lands on top of it. Hoisting the title to the figure gives
    each its own band. Call AFTER the legends exist so the reserved margin holds.
    """
    fig.subplots_adjust(top=top)
    fig.text(0.008, 0.985, title, fontsize=15, fontweight="bold", color=INK,
             va="top", ha="left")
    if subtitle:
        fig.text(0.008, 0.941, subtitle, fontsize=10, color=INK_SECONDARY,
                 va="top", ha="left")


def value_chip(ax, x, y, text: str, color: str, dy: int = 9, dx: int = 6):
    """Boxed last-value label; `dx`/`dy` are point offsets from the mark.

    The box is border-only (an opaque fill would be a pale blob on a dark page), so
    whatever is behind it shows through — callers near a reference line should pass a
    negative `dx` to move the chip clear of it.

    The reader's first question of any time series is
    "where is it now?" — answering it on the mark costs one annotation and saves a
    trip to the axis. The surface-filled box keeps the text legible even when the
    chip lands on a gridline or another series."""
    return ax.annotate(
        text, xy=(x, y), xytext=(dx, dy), textcoords="offset points",
        fontsize=10.5, fontweight="bold", color=color, zorder=9,
        # Border only: an opaque fill would print as a pale blob on a dark page.
        bbox=dict(boxstyle="round,pad=0.28", facecolor="none", edgecolor=color,
                  linewidth=1.2))


def trailing_avg(values, window: int = 4):
    """Trailing `window`-point mean, aligned right; None until the window fills.

    Quarterly fundamentals are strongly seasonal — a fiscal Q1 dip repeats every
    year — so the raw series reads as a sawtooth and the eye takes the noise for
    the signal. The trailing-twelve-month average is the standard fix and is why
    this lives in the theme rather than in one chart: any quarterly series wants it.
    """
    out = []
    for i in range(len(values)):
        w = values[max(0, i - window + 1):i + 1]
        ok = len(w) == window and all(v is not None and v == v for v in w)  # v==v filters NaN
        out.append(sum(w) / window if ok else None)
    return out


def label_line_end(ax, x, y, text: str, color: str) -> None:
    """Direct label at a line's end — used instead of, or alongside, a legend.

    The dot wears the series colour; the text stays in secondary ink, because a
    light categorical hue is illegible as text on the surface.
    """
    ax.plot([x], [y], linestyle="none", zorder=6, **marker_kwargs(color))
    ax.annotate(text, xy=(x, y), xytext=(6, 0), textcoords="offset points",
                va="center", ha="left", fontsize=9, color=INK_SECONDARY,
                fontweight="semibold")


# A bar may never occupy more than this share of the plot's width. With only a
# handful of categories a "reasonable" width in data units (0.62 of a slot) still
# renders as a 100px slab, which is exactly the heavy look this theme exists to
# remove. Expressing the cap as a fraction of the axes makes it resolution- and
# category-count-independent.
MAX_BAR_AXES_FRACTION = 0.045


def cap_bar_width(ax, desired: float, n_categories: int,
                  max_fraction: float = MAX_BAR_AXES_FRACTION) -> float:
    """Clamp a bar width (data units) so the bar stays visually thin.

    `n_categories` is the number of tick positions the bars span, which is what
    sets the data-to-axes ratio before the axes limits are final.
    """
    try:
        span = max(1, int(n_categories))
        return min(float(desired), max_fraction * span)
    except (TypeError, ValueError):
        return float(desired)


def percent_axis(ax, axis: str = "x", decimals: int = 0) -> None:
    """Format a fractional axis (0.26) as percentages (26%).

    Several metrics arrive as fractions — ROE, margins, FCF yield — while their
    direct labels are written as percentages. Without this the axis and the
    labels disagree on units, which is worse than either alone.
    """
    from matplotlib.ticker import PercentFormatter
    target = ax.xaxis if axis == "x" else ax.yaxis
    target.set_major_formatter(PercentFormatter(xmax=1.0, decimals=decimals))


# PNG palette quantisation: 256 colours, adaptive, alpha preserved. Set 0 to disable.
# Measured 2026-08-03 on a real radar chart: 162 KB -> 38 KB (-77%), and composited against white,
# dark and a saturated orange the RMS difference is 0.86 / 0.88 / 0.76 out of 255 -- imperceptible.
# Charts are flat fills and text, which is exactly what a palette encodes losslessly in practice.
QUANTIZE_COLORS = 256


def quantize_png(path) -> None:
    """Shrink a just-written chart in place, or leave it exactly as it was.

    FASTOCTREE is mandatory here, not a preference: it is the only Pillow method that carries the
    ALPHA channel into the palette (as a PNG tRNS array). These PNGs are transparent by design and
    17% of their pixels are partially transparent -- antialiased text and lines over nothing -- so a
    method that drops alpha would paint a solid box behind every chart. MEDIANCUT refuses RGBA
    outright; verified after a round-trip to disk that FASTOCTREE keeps 81.8% fully-clear pixels.

    Only overwrites when the result is genuinely smaller. Matplotlib's own encoder is already good:
    a plain lossless re-save makes some charts BIGGER (price: 84 -> 96 KB), so "optimising"
    unconditionally would cost disk rather than save it.
    """
    if not QUANTIZE_COLORS:
        return
    p = Path(path)
    try:
        from PIL import Image
    except ImportError:
        print(f"chart_theme: Pillow unavailable, leaving {p.name} unquantised", file=sys.stderr)
        return
    try:
        before = p.stat().st_size
        with Image.open(p) as im:
            q = im.convert("RGBA").quantize(colors=QUANTIZE_COLORS, method=Image.FASTOCTREE)
            buf = io.BytesIO()
            q.save(buf, "PNG", optimize=True)
        data = buf.getvalue()
        if len(data) < before:
            p.write_bytes(data)
    except Exception as e:  # noqa: BLE001
        # A chart that exists beats a chart that is small. Report it -- never swallow silently,
        # or a permanently broken optimisation would look like it was working for months.
        print(f"chart_theme: quantise failed for {p.name} ({type(e).__name__}: {e}) — "
              f"keeping the original", file=sys.stderr)


def save(fig, path, pad: float = 0.35) -> None:
    """Single save path so every PNG lands at the same dpi, padding and (lack of)
    background. `transparent=True` is the whole point: see the surfaces note at the
    top of this module."""
    fig.savefig(path, dpi=DPI, bbox_inches="tight", pad_inches=pad,
                transparent=True)
    plt.close(fig)
    quantize_png(path)
