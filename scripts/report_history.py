"""
report_history.py — "This company has been here before."

Two jobs, one idea: the newest report for a company is the only one that should
be surfaced, and it should carry the record of everything it replaced.

  --block     emit the markdown "Histórico de avaliações" section for a report
              being written now (every PRIOR evaluation of the same company,
              across every listing, with a deterministic delta summary)
  --archive   move superseded report files into `_archive/` so the folder, the
              dashboard glob and the digest all show one row per company

Why both live here: they read the same supersede rule, and a rule implemented
twice is a rule that will disagree with itself. `_log.csv` keeps every row —
history and backtesting need them — only the rendered *files* get collapsed.

Nothing here calls the network or an LLM. The per-evaluation summary is lifted
verbatim out of the older report (its TL;DR thesis line, or a screen's one-liner)
and the trend sentence is arithmetic on `_log.csv`. That keeps this runnable
inside the 30-minute daily budget at zero token cost.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import listings  # noqa: E402

OUT_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")
LOG = OUT_DIR / "_log.csv"
ARCHIVE = OUT_DIR / "_archive"

# {date}_{TICKER}_{suffix}.md, or {date}_{TICKER}_growth_{suffix}.md for the
# growth lens. Tickers hold dots and dashes (NOVO-B.CO); the verdict suffix is
# always lowercase alpha, so the split is unambiguous. The lazy `.+?` stops at
# the first split that lets the rest of the pattern match, which is the ticker.
#
# The `_growth_` arm is load-bearing, not cosmetic: /bd_stocks_daily_growth
# evaluates the SAME tickers as this skill under a different model (gate-5 is
# bypassed there by design). Without a lens split, archiving would treat a
# growth verdict as a superseded quality verdict and file it away — deleting
# the second opinion, which is the whole point of running two lenses.
REPORT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+?)(?:_(growth))?_([a-z]+)\.md$")

# Deep reports carry a TL;DR callout with an explicit thesis line.
_THESIS_RE = re.compile(r"^>\s*\*\*(?:Thesis|Tese)\*\*:\s*(.+?)\s*$", re.M)
# Screens carry a one-line verdict paragraph right under the callout header.
_SCREEN_RE = re.compile(r"^>\s*\[!info\]\s*Screen[^\n]*\n>\s*(.+?)\s*$", re.M)

VERDICT_STYLE = {
    "great": "🟢🟢 GREAT BUY", "invest": "🟢 GOOD BUY", "review": "🟡 WATCH",
    "fair": "🟠 FAIR", "reject": "🔴 DO NOT BUY",
}

MAX_SUMMARY_CHARS = 180


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Supersede rule — the single definition
# --------------------------------------------------------------------------- #
def rank(date_str: str, mode: str) -> tuple[str, int]:
    """Sort key deciding which evaluation is the current one.

    Later date wins; within one date a `deep` beats a `screen`, because a
    same-day pair is always the Phase 5.5 cascade (a screen scoring >= 7.5
    triggers a deep-dive on the same ticker) and the deep is that same work
    carried to completion.
    """
    return (date_str or "", 1 if (mode or "").strip().lower() == "deep" else 0)


def mode_of(suffix: str) -> str:
    """Filename suffix -> evaluation mode. Screens are named `_screen`;
    everything else is named for its verdict and is therefore a deep."""
    return "screen" if suffix == "screen" else "deep"


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
def load_log(path: Path | None = None) -> list[dict]:
    # Resolved at call time, not bound as a default, so tests can point the module
    # at a fixture directory.
    path = path or LOG
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def scan_reports(root: Path | None = None) -> list[dict]:
    """Every report .md at the root of StocksDaily (never inside `_archive/`)."""
    root = root or OUT_DIR
    out = []
    for p in sorted(root.glob("*.md")):
        m = REPORT_RE.match(p.name)
        if not m:
            continue
        date_str, ticker, growth, suffix = m.groups()
        out.append({
            "path": p, "date": date_str, "ticker": ticker, "suffix": suffix,
            "lens": "growth" if growth else "quality",
            "mode": mode_of(suffix), "company": listings.company_key(ticker),
        })
    return out


def extract_summary(path: Path) -> str | None:
    """The one-line gist of a past report, lifted verbatim from the report itself.

    Deep reports: the TL;DR `**Thesis**` line. Screens: the verdict one-liner
    under the `[!info] Screen rápido` header. Anything else (12 of 355 reports
    as of 2026-08-05, all early-format screens) yields None and the caller falls
    back to the log's `notes`.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for pattern in (_THESIS_RE, _SCREEN_RE):
        m = pattern.search(text)
        if m:
            s = re.sub(r"\s+", " ", m.group(1)).strip()
            # Strip Obsidian/markdown emphasis so the table cell stays readable.
            s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
            if len(s) > MAX_SUMMARY_CHARS:
                s = s[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"
            return s
    return None


def _f(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
def history_for(ticker: str, current_date: str | None = None,
                rows: list[dict] | None = None,
                reports: list[dict] | None = None) -> list[dict]:
    """Every PRIOR evaluation of this company, oldest first.

    Company-level and listing-blind on purpose: seven TSMC evaluations split
    across TSM and 2330.TW are one company's history, and showing them as two
    unrelated streaks is exactly the duplication this is meant to end.
    """
    rows = load_log() if rows is None else rows
    reports = scan_reports() if reports is None else reports
    company = listings.company_key(ticker)

    # Quality-lens files only: `_log.csv` holds quality evaluations (the growth
    # lens keeps its own `_growth_log.csv`), so indexing growth reports here
    # could link a quality row to a growth report that happens to share a date.
    by_key = {(r["date"], r["ticker"], r["mode"]): r
              for r in reports if r.get("lens", "quality") == "quality"}
    # A same-(date,ticker) screen and deep share a log row shape; index the .md
    # by mode too so each history line links to its own file.
    out = []
    for r in rows:
        t = (r.get("ticker") or "").strip()
        if listings.company_key(t) != company:
            continue
        d = (r.get("date") or "").strip()
        if current_date and rank(d, r.get("mode", "")) >= rank(current_date, "deep"):
            continue  # not prior — it is this run, or somehow ahead of it
        rep = by_key.get((d, t, (r.get("mode") or "").strip().lower()))
        summary = extract_summary(rep["path"]) if rep else None
        if not summary:
            note = (r.get("notes") or "").strip()
            summary = note if note and "=" not in note else None
        out.append({
            "date": d,
            "ticker": t,
            "mode": (r.get("mode") or "").strip().lower(),
            "score": _f(r.get("score")),
            "verdict": (r.get("verdict") or "").strip().lower(),
            "gates_passed": r.get("gates_passed") or "",
            "price": _f(r.get("price_at_eval")),
            "currency": (r.get("currency") or "").strip(),
            "round": r.get("round") or "",
            "link": rep["path"].stem if rep else None,
            "archived": bool(rep) and rep["path"].parent.name == ARCHIVE.name,
            "summary": summary,
        })
    out.sort(key=lambda h: rank(h["date"], h["mode"]))
    return out


def trend_sentence(hist: list[dict], current_score: float | None,
                   current_verdict: str | None,
                   current_price: float | None = None,
                   current_currency: str | None = None) -> str:
    """One deterministic paragraph on what changed across the whole record.

    Price deltas are computed ONLY between same-currency evaluations — a TWD
    home line and a USD ADR quote the same company at a 30x different number,
    and subtracting them would manufacture a 3000% "move".
    """
    if not hist:
        return ""
    scored = [h for h in hist if h["score"] is not None]
    bits: list[str] = []

    n = len(hist)
    first, last = hist[0], hist[-1]
    span = f"desde {first['date']}"
    listings_seen = sorted({h["ticker"] for h in hist} | ({last["ticker"]}))
    venue = (f" (em {len(listings_seen)} cotações: {', '.join(listings_seen)})"
             if len(listings_seen) > 1 else "")
    bits.append(f"**{n}** avaliação(ões) anterior(es) {span}{venue}.")

    if scored and current_score is not None:
        prev = scored[-1]["score"]
        delta = current_score - prev
        arrow = "▲" if delta > 0.05 else ("▼" if delta < -0.05 else "▬")
        lo = min(h["score"] for h in scored)
        hi = max(h["score"] for h in scored)
        bits.append(
            f"Score {arrow} {prev:.2f} → **{current_score:.2f}** ({delta:+.2f}); "
            f"amplitude histórica {lo:.2f}–{hi:.2f}."
        )

    verdicts = [h["verdict"] for h in hist if h["verdict"]]
    if verdicts and current_verdict:
        if all(v == current_verdict for v in verdicts):
            bits.append(f"Veredicto **estável** em `{current_verdict}` em todas as rondas.")
        else:
            chain = " → ".join(dict.fromkeys(verdicts + [current_verdict]))
            bits.append(f"Veredicto mudou: {chain}.")

    if current_price is not None and current_currency:
        same_ccy = [h for h in hist
                    if h["price"] and h["currency"] == current_currency]
        if same_ccy:
            p0 = same_ccy[0]
            move = (current_price / p0["price"] - 1) * 100
            bits.append(
                f"Preço {move:+.1f}% desde {p0['date']} "
                f"({p0['price']:,.2f} → {current_price:,.2f} {current_currency})."
            )

    return " ".join(bits)


def render_block(ticker: str, current_date: str,
                 current_score: float | None = None,
                 current_verdict: str | None = None,
                 current_price: float | None = None,
                 current_currency: str | None = None,
                 rows: list[dict] | None = None,
                 reports: list[dict] | None = None) -> str:
    """The markdown section appended to a freshly written report. '' when this
    is the company's first evaluation — a history table of one empty row is
    noise, not information."""
    hist = history_for(ticker, current_date, rows=rows, reports=reports)
    if not hist:
        return ""

    company = listings.company_name(ticker) or ticker
    out = [
        "## 5. Histórico de avaliações",
        "",
        f"> [!info] Este report **substitui** todas as avaliações anteriores de "
        f"{company}. Os ficheiros antigos foram movidos para `_archive/` e "
        f"continuam a abrir pelos links abaixo.",
        "",
        trend_sentence(hist, current_score, current_verdict,
                       current_price, current_currency),
        "",
        "| Data | Ticker | Modo | Score | Veredicto | Gates | Preço | Resumo |",
        "|------|--------|------|-------|-----------|-------|-------|--------|",
    ]
    for h in reversed(hist):  # newest of the old ones first
        verdict = VERDICT_STYLE.get(h["verdict"], h["verdict"] or "—")
        score = f"{h['score']:.2f}" if h["score"] is not None else "—"
        price = (f"{h['price']:,.2f} {h['currency']}".strip()
                 if h["price"] is not None else "—")
        link = f"[[{h['link']}]]" if h["link"] else h["date"]
        summary = h["summary"] or "—"
        out.append(
            f"| {link} | {h['ticker']} | {h['mode']} | {score} | {verdict} | "
            f"{h['gates_passed'] or '—'}/7 | {price} | {summary} |"
        )
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Archive
# --------------------------------------------------------------------------- #
def plan_archive(reports: list[dict] | None = None) -> list[dict]:
    """Which report files are superseded, and by what. Pure — moves nothing.

    Keyed on (company, lens): a quality report never supersedes a growth report
    on the same company, because they answer different questions.
    """
    reports = scan_reports() if reports is None else reports
    current: dict[tuple, dict] = {}
    for r in reports:
        c = (r["company"], r["lens"])
        if c not in current or rank(r["date"], r["mode"]) > rank(
                current[c]["date"], current[c]["mode"]):
            current[c] = r
    return [
        {"report": r, "superseded_by": current[(r["company"], r["lens"])]}
        for r in reports if r is not current[(r["company"], r["lens"])]
    ]


def _rewrite_img_paths(text: str) -> str:
    """`![](IMG/x.png)` resolves relative to the file, so a report moved one
    level down needs `../IMG/`. The HTML sibling inlines its charts as base64
    and needs no such fix."""
    return re.sub(r"\]\((IMG/)", "](../IMG/", text)


def do_archive(dry_run: bool = False, archive_dir: Path | None = None) -> dict:
    archive_dir = archive_dir or ARCHIVE
    plan = plan_archive()
    moved, failed = [], []
    if plan and not dry_run:
        archive_dir.mkdir(parents=True, exist_ok=True)
    for item in plan:
        src: Path = item["report"]["path"]
        dst = archive_dir / src.name
        try:
            if not dry_run:
                text = _rewrite_img_paths(src.read_text(encoding="utf-8", errors="replace"))
                dst.write_text(text, encoding="utf-8")
                src.unlink()
                # The Phase-F HTML sibling travels with its .md — leaving it at
                # the root would keep a dead deep-link alive in the screener.
                html_src = src.with_suffix(".html")
                if html_src.exists():
                    shutil.move(str(html_src), str(archive_dir / html_src.name))
            moved.append({"file": src.name,
                          "superseded_by": item["superseded_by"]["path"].name})
        except OSError as exc:
            failed.append({"file": src.name, "error": f"{type(exc).__name__}: {exc}"})
            log(f"  ERROR archiving {src.name}: {exc}")
    return {"archived": len(moved), "failed": len(failed), "dry_run": dry_run,
            "archive_dir": str(archive_dir), "moved": moved, "errors": failed}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Report history block + supersede archiver")
    ap.add_argument("--ticker")
    ap.add_argument("--date", help="the date of the report being written")
    ap.add_argument("--score", type=float)
    ap.add_argument("--verdict")
    ap.add_argument("--price", type=float)
    ap.add_argument("--currency")
    ap.add_argument("--block", action="store_true", help="print the markdown history section")
    ap.add_argument("--json", action="store_true", help="print the history as JSON")
    ap.add_argument("--archive", action="store_true", help="move superseded reports to _archive/")
    ap.add_argument("--dry-run", action="store_true", help="with --archive, only report the plan")
    args = ap.parse_args()

    if args.archive:
        result = do_archive(dry_run=args.dry_run)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        log(f"{'would archive' if args.dry_run else 'archived'} {result['archived']} "
            f"superseded report(s); {result['failed']} error(s)")
        return 1 if result["failed"] else 0

    if not args.ticker:
        ap.error("--ticker is required unless --archive is used")
    today = args.date or datetime.now().strftime("%Y-%m-%d")

    if args.json:
        print(json.dumps(history_for(args.ticker, today), indent=2,
                         ensure_ascii=False, default=str))
        return 0

    print(render_block(args.ticker, today, args.score, args.verdict,
                       args.price, args.currency))
    return 0


if __name__ == "__main__":
    sys.exit(main())
