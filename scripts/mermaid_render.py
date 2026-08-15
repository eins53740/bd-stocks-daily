"""mermaid_render.py — mermaid source → transparent PNG, via mermaid-cli.

WHY this exists. `prompts/01_business_model.md` asks every deep dive for a
```mermaid `sankey-beta` money-engine diagram, and 170 reports on disk carry one.
Obsidian renders it; the **HTML report — the primary artifact — does not**, because
`render_report.py` has no mermaid handling at all. So the single best picture of how
a dollar of revenue becomes retained earnings is invisible in the format that is
actually delivered. This module closes that.

WHY it can never break the daily job. Same contract as `chart_browser.py`: every
entry point returns None/False instead of raising, and the caller falls back to
today's behaviour (the fenced block stays as text). Set BD_MERMAID=0 to force that
fallback. A missing `mmdc`, a cold Chromium, a malformed diagram and a timeout are
all the same outcome — no image, no exception, run continues.

WHY the cache is not optional. Each render spawns a headless Chromium: measured
**7.3 s cold / 3.6 s warm** on this laptop against a 30-minute job budget with
~6 minutes of headroom. A company's money engine barely moves between runs, so
renders are keyed by a hash of (source + config + renderer version) and a re-run of
the same ticker costs a file read. The cache is content-addressed, so a changed
diagram simply misses and re-renders — there is no staleness window to reason about.

Pure stdlib, so `render_report.py` keeps its no-matplotlib/no-pandas property.
The ink colours are duplicated from `chart_theme` rather than imported for that
reason, and `tests/test_mermaid_render.py` asserts the two never drift apart.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Mid-tone ink, copied from chart_theme.INK_* — see the module docstring for why this
# is a copy and not an import. chart_theme's reasoning applies unchanged: the PNG is
# transparent, so it must read on a light HTML report AND a dark Obsidian theme, which
# rules out near-black. test_mermaid_render.py fails if these drift from the source.
INK = "#787772"
INK_SECONDARY = "#84837d"

# Bumping this invalidates every cached PNG. Bump it whenever the config or the CLI
# flags below change, or old renders survive a theme change and the report shows a
# mix of two visual systems with nothing to explain why.
RENDERER_VERSION = "1"

DEFAULT_WIDTH = 1400
DEFAULT_HEIGHT = 760
RENDER_TIMEOUT_S = 90     # cold Chromium measured ~7 s; 90 s is a hang guard, not a budget

CACHE_DIRNAME = "_mermaid"


def log(msg: str) -> None:
    print(f"[mermaid_render] {msg}", file=sys.stderr, flush=True)


def enabled() -> bool:
    """False when the operator has switched mermaid rendering off."""
    val = (os.environ.get("BD_MERMAID", "1") or "1").strip().lower()
    return val not in ("0", "false", "no", "off")


def find_mmdc() -> str | None:
    """Locate the globally-installed mermaid-cli. Never `npx -y` — a scheduled job
    must not resolve, download and execute a package at 13:30."""
    for name in ("mmdc", "mmdc.cmd"):
        p = shutil.which(name)
        if p:
            return p
    return None


# ---------------------------------------------------------------------------
# Source extraction (pure — unit-tested without a browser)
# ---------------------------------------------------------------------------
def diagram_kind(source: str) -> str:
    """The diagram type of a mermaid source — "sankey-beta", "flowchart", "graph".

    Reading the first line blindly is wrong for two variants that are both present in
    the 114 sankeys on disk, and both were found by running this over the whole corpus
    rather than over one sample:

    - a `---` YAML config front-matter block (`2026-08-12_FAE.MC_review.md`)
    - an `%%{init: {...}}%%` directive line (`2026-06-15_SFTBY_fair.md`)

    Either one returns "---" or "%%{init:" as the kind, and the money engine silently
    goes missing from exactly the reports that fussed most over the diagram.
    """
    lines = (source or "").split("\n")
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s or (s.startswith("%%") and s.endswith("%%")):
            i += 1
            continue
        if s == "---":
            i += 1
            while i < len(lines) and lines[i].strip() != "---":
                i += 1
            i += 1  # step over the closing ---
            continue
        return s.split()[0].lower()
    return ""


def extract_mermaid_blocks(md_text: str) -> list[tuple[str, str]]:
    """Every ```mermaid fence in a markdown document, as (kind, source).

    `kind` is the diagram's first non-empty token — "sankey-beta", "flowchart",
    "graph" — which is what lets a caller pick out the money engine without
    rendering the lot. Returned in document order.

    Deliberately a line scanner, not a regex: a fenced block can contain anything,
    including other backticks, and a non-greedy regex over 60 KB of report prose
    was measurably easier to get subtly wrong than a 20-line loop.
    """
    blocks: list[tuple[str, str]] = []
    lines = (md_text or "").split("\n")
    i, n = 0, len(lines)
    while i < n:
        stripped = lines[i].strip()
        if stripped.startswith("```") and stripped[3:].strip().lower() == "mermaid":
            i += 1
            buf: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # step over the closing fence
            src = "\n".join(buf).strip()
            if src:
                blocks.append((diagram_kind(src), src))
        else:
            i += 1
    return blocks


def find_sankey(md_text: str) -> str | None:
    """The money-engine diagram, or None. First sankey wins — the prompt asks for
    exactly one, and picking the first keeps behaviour defined if a future prompt
    asks for two."""
    for kind, src in extract_mermaid_blocks(md_text):
        if kind.startswith("sankey"):
            return src
    return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def build_config() -> dict:
    """mermaid config as a dict, so the cache key can hash it.

    Only the TEXT is themed. `cScale0..N` was tried and **measured to have no effect
    on sankey-beta** — that renderer takes its node hues from a hard-coded d3 scheme —
    so this config does not pretend to control them, and the prompt's legend was
    corrected to stop describing colours the diagram never had.
    """
    return {
        "theme": "base",
        "themeVariables": {
            "fontFamily": '"Segoe UI Variable Text","Segoe UI",Inter,system-ui,sans-serif',
            "fontSize": "15px",
            "textColor": INK,
            "primaryTextColor": INK,
            "secondaryTextColor": INK_SECONDARY,
            "lineColor": INK_SECONDARY,
        },
        "sankey": {"showValues": True, "linkColor": "gradient", "nodeAlignment": "justify"},
    }


def cache_key(source: str, config: dict, width: int, height: int) -> str:
    """Content address for a render. Everything that can change a pixel goes in.

    The source is stripped here, matching what `render()` actually hands to mmdc.
    Doing it in only one of the two places is how a cache silently never hits: a
    caller reconstructing the key from its own copy of the source gets a different
    hash for a byte-identical diagram. (Found by the test that reconstructs it.)
    """
    blob = json.dumps(
        {"v": RENDERER_VERSION, "src": (source or "").strip(), "cfg": config,
         "w": width, "h": height},
        sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def render(source: str, out_png: Path, *, width: int = DEFAULT_WIDTH,
           height: int = DEFAULT_HEIGHT, cache_dir: Path | None = None,
           timeout_s: int = RENDER_TIMEOUT_S) -> bool:
    """Render `source` to `out_png`. True on success, False on ANY failure.

    Never raises: the daily job's contract is that a diagram is a nice-to-have and a
    missing one degrades the report rather than ending the run.
    """
    if not enabled():
        log("disabled via BD_MERMAID — skipping")
        return False
    source = (source or "").strip()
    if not source:
        return False
    out_png = Path(out_png)

    cfg = build_config()
    key = cache_key(source, cfg, width, height)
    cache_dir = Path(cache_dir) if cache_dir else (out_png.parent / CACHE_DIRNAME)
    cached = cache_dir / f"{key}.png"
    if cached.exists() and cached.stat().st_size > 0:
        try:
            out_png.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, out_png)
            log(f"cache hit {key} → {out_png.name}")
            return True
        except OSError as exc:
            log(f"cache copy failed ({exc}) — re-rendering")

    mmdc = find_mmdc()
    if not mmdc:
        log("mermaid-cli (mmdc) not found on PATH — diagram skipped")
        return False

    tmp = Path(tempfile.mkdtemp(prefix="bd_mermaid_"))
    try:
        src_file = tmp / "diagram.mmd"
        cfg_file = tmp / "config.json"
        png_file = tmp / "out.png"
        src_file.write_text(source, encoding="utf-8")
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        cmd = [mmdc, "-i", str(src_file), "-o", str(png_file), "-c", str(cfg_file),
               "-b", "transparent", "-w", str(width), "-H", str(height)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        if proc.returncode != 0 or not png_file.exists() or png_file.stat().st_size == 0:
            # mmdc exits 0 on some failures and writes nothing, so the file check is
            # load-bearing and not belt-and-braces.
            err = (proc.stderr or proc.stdout or "").strip().splitlines()
            log(f"mmdc failed (rc={proc.returncode}): {err[-1] if err else 'no output'}")
            return False
        out_png.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(png_file, out_png)
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(png_file, cached)
        except OSError as exc:
            log(f"cache write failed ({exc}) — render still delivered")
        log(f"rendered {out_png.name} ({out_png.stat().st_size // 1024} KB, key {key})")
        return True
    except subprocess.TimeoutExpired:
        log(f"mmdc timed out after {timeout_s}s — diagram skipped")
        return False
    except Exception as exc:  # noqa: BLE001 — fallback-first by design
        log(f"unexpected failure ({type(exc).__name__}: {exc}) — diagram skipped")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def render_from_markdown(md_path: Path, out_png: Path, *, kind: str = "sankey",
                         **kw) -> bool:
    """Convenience: pull the first `kind` diagram out of a markdown file and render it."""
    try:
        text = Path(md_path).read_text(encoding="utf-8")
    except OSError as exc:
        log(f"cannot read {md_path} ({exc})")
        return False
    for k, src in extract_mermaid_blocks(text):
        if k.startswith(kind.lower()):
            return render(src, out_png, **kw)
    return False


# ---------------------------------------------------------------------------
# CLI — used to convert the committed doc diagrams (plan item 2.3)
# ---------------------------------------------------------------------------
def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Render mermaid diagrams to transparent PNGs.")
    ap.add_argument("input", help="a .mmd file, or a .md file to extract diagrams from")
    ap.add_argument("-o", "--out", required=True,
                    help="output PNG (single diagram) or output DIRECTORY (--all)")
    ap.add_argument("--all", action="store_true",
                    help="render every mermaid block found, into --out as a directory")
    ap.add_argument("--kind", default="", help="only render diagrams of this kind, e.g. sankey")
    ap.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    ap.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    args = ap.parse_args()

    src_path = Path(args.input)
    if not src_path.exists():
        log(f"input not found: {src_path}")
        return 1

    if src_path.suffix.lower() == ".mmd":
        blocks = [("", src_path.read_text(encoding="utf-8"))]
    else:
        blocks = extract_mermaid_blocks(src_path.read_text(encoding="utf-8"))
    if args.kind:
        blocks = [b for b in blocks if b[0].startswith(args.kind.lower())]
    if not blocks:
        log("no matching mermaid blocks found")
        return 1

    ok = 0
    if args.all:
        out_dir = Path(args.out)
        for idx, (kind, src) in enumerate(blocks, start=1):
            name = f"{src_path.stem}_{idx:02d}{('_' + kind) if kind else ''}.png"
            if render(src, out_dir / name, width=args.width, height=args.height):
                ok += 1
    else:
        ok = int(render(blocks[0][1], Path(args.out), width=args.width, height=args.height))
    log(f"{ok}/{len(blocks) if args.all else 1} diagram(s) rendered")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
