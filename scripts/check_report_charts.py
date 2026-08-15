"""
check_report_charts.py — did the report actually embed the charts we rendered?

`render_charts.py` writes PNGs to `IMG/`; the report body then has to reference
them. Nothing enforced the second half, so charts were being generated and
silently dropped: on 2026-08-05 all three deep reports (KLAC, WKL.AS, ZTS) had a
`_relperf.png` on disk that no report ever linked. From the reader's side that is
indistinguishable from the chart not existing — except it also cost the render.

This is the gate. Run it after writing a report; it exits non-zero and prints the
exact markdown lines to paste when something is missing.

  python check_report_charts.py --report "<path to the .md>"
  python check_report_charts.py --audit          # sweep every report on disk

Deliberately dumb: filesystem + regex, no yfinance, no LLM. A gate that can fail
for its own reasons is not a gate.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

OUT_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
IMG_DIRNAME = "IMG"

# Chart kind -> the caption the report template uses. Keys are the exact suffixes
# render_charts.py writes ({date}_{ticker}_{kind}.png) and the captions match
# SKILL.md's template lines, so a pasted fix line is byte-identical to what the
# report should have contained.
CHART_CAPTIONS = {
    "price": "Price 1Y",
    "radar": "Radar",
    "peers": "Peers",
    "dcf": "DCF",
    "ebitda_fcf": "EBITDA & FCF",
    "ni_pe": "Net income vs P/E",
    "relperf": "Relative 2.5y",
    "segments": "Revenue sources",
}

REPORT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+?)(?:_(growth))?_([a-z]+)\.md$")
# Screens get the metrics strip only — no charts. Nothing to gate.
SCREEN_SUFFIX = "screen"

# Where each chart belongs, as ordered anchor patterns: insert immediately AFTER
# the first line that matches. Patterns mirror the SKILL.md template so a
# backfilled image lands where a freshly written report would have put it.
# Later patterns are progressively looser fallbacks for older report layouts.
# Each entry is (regex, "after"|"before"). The metrics-strip trio sits between
# the strip and `## 1.` in the template, so when the strip note is absent (older
# layouts) they anchor BEFORE the §1 heading rather than falling to the tail —
# a price chart printed after the deep dive is technically embedded and
# practically useless.
ANCHORS: dict[str, list[tuple[str, str]]] = {
    "ebitda_fcf": [(r"^\(Fonte: bloco `top_strip`", "after"),
                   (r"^## 1\. Sum[áa]rio", "before")],
    "price":      [(r"^!\[EBITDA & FCF\]\(IMG/", "after"),
                   (r"^\(Fonte: bloco `top_strip`", "after"),
                   (r"^## 1\. Sum[áa]rio", "before")],
    "relperf":    [(r"^!\[Price 1Y\]\(IMG/", "after"),
                   (r"^\(Fonte: bloco `top_strip`", "after"),
                   (r"^## 1\. Sum[áa]rio", "before")],
    "radar":      [(r"^### Score breakdown\s*$", "after")],
    "peers":      [(r"^### Peer ranking snapshot\s*$", "after")],
    "segments":   [(r"^### 2\.1[\s.]", "after"), (r"^## 2\. Deep dive", "after")],
    "dcf":        [(r"^\*\*e\) DCF", "after"), (r"^### 2\.11[\s.]", "after")],
    "ni_pe":      [(r"^\*\*Tese quebrada se\*\*", "after"),
                   (r"^### 2\.12[\s.]", "after")],
}

# Template order, so several images resolving to the same anchor line come out
# in the sequence a hand-written report would have used.
CHART_ORDER = ["ebitda_fcf", "price", "relperf", "radar", "peers",
               "segments", "dcf", "ni_pe"]

# Last resort: insert BEFORE the first of these, i.e. at the end of the analysis
# body but above the closing sections. Never append after the signature.
TAIL_MARKERS = [r"^## 3\. Links", r"^## 4\. Macro", r"^## 5\. ",
                r"^---\s*$", r"^\*Analysis written by"]


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def charts_on_disk(report: Path) -> dict[str, Path]:
    """{kind: png_path} for every chart rendered for this report's date+ticker."""
    m = REPORT_RE.match(report.name)
    if not m:
        return {}
    date_str, ticker, _growth, _suffix = m.groups()
    img = report.parent / IMG_DIRNAME
    if not img.is_dir():
        # An archived report sits one level down; its charts stayed at the root.
        img = report.parent.parent / IMG_DIRNAME
    if not img.is_dir():
        return {}
    stem = f"{date_str}_{ticker}_"
    found = {}
    for p in img.glob(f"{stem}*.png"):
        kind = p.stem[len(stem):]
        if kind:
            found[kind] = p
    return found


def charts_referenced(report: Path) -> set[str]:
    """Chart kinds the report body actually links."""
    try:
        text = report.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    m = REPORT_RE.match(report.name)
    if not m:
        return set()
    date_str, ticker, _g, _s = m.groups()
    stem = re.escape(f"{date_str}_{ticker}_")
    return set(re.findall(rf"{stem}([A-Za-z0-9_]+)\.png", text))


def audit_report(report: Path) -> dict:
    """Compare rendered vs referenced. `orphans` are the actionable failure."""
    m = REPORT_RE.match(report.name)
    is_screen = bool(m) and m.group(4) == SCREEN_SUFFIX
    on_disk = charts_on_disk(report)
    referenced = charts_referenced(report)
    orphans = sorted(set(on_disk) - referenced)
    # A reference with no file is a broken image in Obsidian — the opposite bug,
    # worth the same alarm.
    broken = sorted(referenced - set(on_disk))
    return {
        "report": report.name,
        "is_screen": is_screen,
        "rendered": sorted(on_disk),
        "referenced": sorted(referenced),
        "orphans": orphans,
        "broken_links": broken,
        "ok": not orphans and not broken,
    }


def fix_lines(report: Path, orphans: list[str]) -> list[str]:
    """The markdown to paste, one line per unembedded chart."""
    m = REPORT_RE.match(report.name)
    if not m:
        return []
    date_str, ticker, _g, _s = m.groups()
    out = []
    for kind in orphans:
        caption = CHART_CAPTIONS.get(kind, kind.replace("_", " ").title())
        out.append(f"![{caption}]({IMG_DIRNAME}/{date_str}_{ticker}_{kind}.png)")
    return out


def _anchor_index(lines: list[str], kind: str) -> int | None:
    """Insertion index for this chart, or None if no anchor matched.

    Returns the index to insert AT (i.e. the block lands immediately before
    whatever currently occupies it), already adjusted for after/before mode.
    """
    for pat, mode in ANCHORS.get(kind, []):
        rx = re.compile(pat)
        for i, ln in enumerate(lines):
            if rx.search(ln):
                return i + 1 if mode == "after" else i
    return None


def _tail_index(lines: list[str]) -> int:
    """Index to insert BEFORE when no anchor matched — above the closing
    sections, never after the signature."""
    for pat in TAIL_MARKERS:
        rx = re.compile(pat)
        for i, ln in enumerate(lines):
            if rx.search(ln):
                return max(i - 1, 0)
    return len(lines)


def fix_report(report: Path, dry_run: bool = True) -> dict:
    """Backfill unembedded charts and drop dead image links.

    Insertions are resolved against the ORIGINAL line numbering and applied
    bottom-up, so earlier indices stay valid while the file grows underneath.

    Dead links are removed rather than re-rendered on purpose: the analysis JSON
    behind an old report is long gone from `_tmp`, and re-running the pipeline
    today would draw *today's* prices into a report dated months ago. A missing
    chart is a gap; a chart showing the wrong period is a lie.
    """
    audit = audit_report(report)
    if audit["is_screen"] or audit["ok"]:
        return {**audit, "inserted": [], "removed": [], "changed": False}

    m = REPORT_RE.match(report.name)
    date_str, ticker, _g, _s = m.groups()
    # newline="" on BOTH ends, or Python rewrites every line terminator in the
    # file: read_text() normalises to \n and write_text() then translates back to
    # os.linesep, turning a 7-line insert into a 551-line diff. These reports are
    # LF; whatever they are, they come out as they went in.
    # Path.read_text(newline=...) is 3.13+; this runs on 3.12, so open() it is.
    with report.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        text = fh.read()
    eol = "\r\n" if "\r\n" in text else "\n"
    trailing = text.endswith(("\n", "\r"))
    lines = text.splitlines()

    # --- removals: dead image links (the caption/prose below them stays; on the
    # segment cases it is the paragraph that explains why the data is absent).
    removed = []
    if audit["broken_links"]:
        keep = []
        for ln in lines:
            hit = next((k for k in audit["broken_links"]
                        if f"{date_str}_{ticker}_{k}.png" in ln and ln.lstrip().startswith("![")),
                       None)
            if hit:
                removed.append(ln.strip())
                continue
            keep.append(ln)
        lines = keep

    # --- insertions: group by anchor so co-located images stay in template order
    by_anchor: dict[int, list[str]] = {}
    tail = _tail_index(lines)
    for kind in CHART_ORDER:
        if kind not in audit["orphans"]:
            continue
        idx = _anchor_index(lines, kind)
        at = idx if idx is not None else tail
        caption = CHART_CAPTIONS.get(kind, kind.replace("_", " ").title())
        by_anchor.setdefault(at, []).append(
            f"![{caption}]({IMG_DIRNAME}/{date_str}_{ticker}_{kind}.png)")

    inserted = []
    for at in sorted(by_anchor, reverse=True):
        block: list[str] = []
        for img in by_anchor[at]:
            block += ["", img]
            inserted.append(img)
        # Blank-line hygiene is decided locally, at the seam. A global
        # "collapse 3+ newlines" pass would silently reformat parts of the
        # report this fix never touched.
        if at < len(lines) and lines[at].strip() != "":
            block.append("")
        if at > 0 and lines[at - 1].strip() == "" and block and block[0] == "":
            block.pop(0)
        lines[at:at] = block

    new_text = eol.join(lines) + (eol if trailing else "")
    changed = new_text != text
    if changed and not dry_run:
        with report.open("w", encoding="utf-8", newline="") as fh:
            fh.write(new_text)
    return {**audit, "inserted": inserted, "removed": removed, "changed": changed}


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate: every rendered chart must be embedded")
    ap.add_argument("--report", help="path to a single report .md")
    ap.add_argument("--audit", action="store_true", help="sweep every report under OUT_DIR")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fix", action="store_true",
                    help="backfill unembedded charts and drop dead image links")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --fix, show what would change without writing")
    args = ap.parse_args()

    if args.report:
        reports = [Path(args.report)]
    elif args.audit:
        reports = sorted(p for p in OUT_DIR.glob("*.md") if REPORT_RE.match(p.name))
    else:
        ap.error("pass --report <path> or --audit")

    if args.fix:
        fixed = [fix_report(p, dry_run=args.dry_run) for p in reports if p.exists()]
        touched = [f for f in fixed if f["changed"]]
        verb = "would change" if args.dry_run else "changed"
        for f in touched:
            print(f"\n{'~' if args.dry_run else '✓'} {f['report']}")
            for img in f["inserted"]:
                print(f"    + {img}")
            for ln in f["removed"]:
                print(f"    - {ln}   (dead link — PNG never rendered)")
        n_ins = sum(len(f["inserted"]) for f in touched)
        n_rem = sum(len(f["removed"]) for f in touched)
        print(f"\n{verb}: {len(touched)} report(s) · +{n_ins} image(s) · -{n_rem} dead link(s)")
        return 0

    results = [audit_report(p) for p in reports if p.exists()]
    failing = [r for r in results if not r["ok"] and not r["is_screen"]]

    if args.json:
        print(json.dumps({"checked": len(results), "failing": len(failing),
                          "results": results}, indent=2))
        return 1 if failing else 0

    for r in failing:
        print(f"\n✗ {r['report']}")
        if r["orphans"]:
            print(f"  {len(r['orphans'])} chart(s) rendered but NOT embedded: "
                  f"{', '.join(r['orphans'])}")
            print("  paste these into the report:")
            for line in fix_lines(OUT_DIR / r["report"], r["orphans"]):
                print(f"    {line}")
        if r["broken_links"]:
            print(f"  {len(r['broken_links'])} broken image link(s) — "
                  f"referenced but no PNG: {', '.join(r['broken_links'])}")

    checked = sum(1 for r in results if not r["is_screen"])
    if failing:
        print(f"\n{len(failing)}/{checked} deep report(s) FAILED the chart gate")
        return 1
    print(f"OK — {checked} deep report(s), every rendered chart is embedded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
