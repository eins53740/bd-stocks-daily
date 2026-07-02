"""
find_reports.py — Best-effort URLs for latest annual/quarterly reports + IR page.

Strategy:
  1. US (no suffix): SEC EDGAR search URL (no API key needed)
  2. Non-US: yfinance info.website → IR guess + investor / investors / shareholders paths
  3. Generic: stockanalysis.com + Yahoo Finance financials page

We don't fetch PDFs — just return URLs. Claude can WebFetch them for narrative in the skill.
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings

# Force UTF-8 on Windows stdout/stderr
for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def is_us_ticker(ticker: str) -> bool:
    """No exchange suffix => US. Yahoo's dash form for US class shares (BRK-B,
    BF-B) is US too; dot-suffix forms stay non-US (.L/.T/... are exchanges)."""
    if "." in ticker:
        return False
    base, _, suffix = ticker.rpartition("-")
    if base and len(suffix) == 1 and suffix.isalpha():
        return True  # class-share letter
    return "-" not in ticker


def edgar_urls(ticker: str) -> dict:
    base = "https://www.sec.gov/cgi-bin/browse-edgar"
    return {
        "edgar_10k": f"{base}?action=getcompany&CIK={ticker}&type=10-K&dateb=&owner=include&count=5",
        "edgar_10q": f"{base}?action=getcompany&CIK={ticker}&type=10-Q&dateb=&owner=include&count=5",
        "edgar_all": f"{base}?action=getcompany&CIK={ticker}&type=&dateb=&owner=include&count=20",
    }


def ir_guesses(website: str) -> list[str]:
    if not website:
        return []
    website = website.rstrip("/")
    return [
        f"{website}/investors",
        f"{website}/investor-relations",
        f"{website}/en/investors",
        f"{website}/shareholders",
        f"{website}/ir",
    ]


def build_links(ticker: str) -> dict:
    out: dict = {"ticker": ticker}

    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as e:
        log(f"yfinance info fail: {e}")
        info = {}

    out["company_name"] = info.get("longName") or info.get("shortName") or ticker
    out["website"] = info.get("website") or ""

    # Ticker base (strip suffix for generic URLs)
    base = ticker.split(".")[0].replace("-", "")

    if is_us_ticker(ticker):
        out.update(edgar_urls(ticker))
    else:
        out["edgar_10k"] = None

    # Generic fallbacks
    out["yahoo_financials"] = f"https://finance.yahoo.com/quote/{ticker}/financials"
    out["yahoo_key_stats"]  = f"https://finance.yahoo.com/quote/{ticker}/key-statistics"
    out["stockanalysis"]    = f"https://stockanalysis.com/stocks/{base.lower()}/financials/"
    out["finviz"]           = f"https://finviz.com/quote.ashx?t={base}"
    out["seeking_alpha"]    = f"https://seekingalpha.com/symbol/{base}"
    out["simply_wall_st"]   = f"https://simplywall.st/stocks/{ticker.lower().replace('.', '-')}"

    # IR guesses (no validation — Claude WebFetches to find the right one)
    out["ir_guesses"] = ir_guesses(out["website"])

    # Annualreports.com slug (best effort)
    slug = (info.get("longName") or ticker).lower().replace(" ", "-").replace(",", "").replace(".", "")
    out["annualreports_com"] = f"https://www.annualreports.com/Company/{slug}"

    out["hint_for_claude"] = (
        "For the deep-dive, WebFetch the SEC EDGAR filing list (US only) or use WebSearch "
        "with queries like: \"{company_name} annual report 2025 filetype:pdf\" and "
        "\"{company_name} investor relations\". Extract NARRATIVE only (tese, riscos, guidance). "
        "Numbers must come from analyze_ticker.py (yfinance ground truth)."
    ).format(company_name=out["company_name"])

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    args = ap.parse_args()
    data = build_links(args.ticker)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
