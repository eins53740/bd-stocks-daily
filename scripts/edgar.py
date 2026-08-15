"""SEC EDGAR official filings for US listings — 8-K / 10-Q / 10-K (v4.3, Phase 1.5).

Ground-truth numbers only, same rule as everywhere else: this module returns filing
METADATA and, on request, structured **XBRL facts**. Both are structured data from a
Python helper, so both are legal as ground truth. Filing *prose* is fetched separately
and feeds the narrative path only — it is never parsed for numbers, so this creates no
new exception to the ground-truth rule (SKILL.md).

WHY THIS EXISTS
  `SKILL.md` used to instruct "avoid SEC EDGAR direct URLs — they 403", and
  `get_narrative.py` exists precisely because of that. The 403 is not a block: it is
  SEC's declared policy of refusing requests without a User-Agent identifying the
  caller. Measured 2026-08-15 from this machine:
      no User-Agent  -> HTTP 403
      with one       -> HTTP 200
  on all three endpoints. So the blocker was a missing header, for the whole time the
  skill was routing around it.

TWO ENDPOINTS, VERY DIFFERENT COSTS (measured, same day)
  submissions   166 KB   0.28 s   -> filing list. Cheap; safe to refresh often.
  companyfacts  5.6 MB   2.74 s   -> every XBRL fact ever filed. Expensive.

  Hence two different TTLs, and `--facts` is opt-in. Note this deliberately departs
  from the v4.3 plan, which specified a single 30-day TTL for both: a 30-day TTL on
  submissions would hide a brand-new 8-K for up to a month, and catching 8-K
  catalysts early is most of the point of reading filings at all.

RATE LIMIT
  SEC asks for <=10 requests/second. With caching this module makes 1-2 requests per
  ticker per day, so the limit is never approached; `_throttle()` enforces it anyway
  because a retry loop is exactly where it would otherwise be breached.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import markets  # noqa: E402  (sibling helper — suffix_of)

OUT_DIR_DEFAULT = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily")

# SEC requires a User-Agent that identifies the caller with a contact address. A
# generic browser string is against their stated policy and is what gets an IP
# throttled; this is the honest form they ask for.
UA = "BD Finance Research bruno.dias@secil.pt"

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/{doc}"
FILING_INDEX_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}"

DEFAULT_FORMS = ("10-K", "10-Q", "8-K")
SUBMISSIONS_TTL_DAYS = 1     # cheap, and a new 8-K must not wait a month to surface
FACTS_TTL_DAYS = 30          # 5.6 MB; the facts themselves only move on a new filing
TICKER_MAP_TTL_DAYS = 30
MIN_REQUEST_INTERVAL_S = 0.11   # SEC asks <=10 req/s

# 8-K item codes worth surfacing as catalysts. Deliberately not the full list — these
# are the ones that change a thesis. 4.02 in particular is a serious red flag: the
# company is saying previously issued statements can no longer be relied upon.
EIGHT_K_ITEMS = {
    "1.01": "material agreement entered",
    "1.02": "material agreement terminated",
    "2.01": "acquisition or disposition completed",
    "2.02": "results of operations (earnings release)",
    "2.03": "new financial obligation",
    "2.04": "obligation accelerated",
    "2.05": "exit or disposal costs",
    "2.06": "material impairment",
    "3.01": "delisting notice / listing rule failure",
    "4.01": "auditor changed",
    "4.02": "PRIOR FINANCIALS NOT RELIABLE",
    "5.02": "director or officer departure/appointment",
    "5.03": "fiscal year change",
    "7.01": "Regulation FD disclosure",
    "8.01": "other events",
}

_last_request_at = 0.0


def log(msg: str) -> None:
    print(f"[edgar] {msg}", file=sys.stderr)


# ===================================================================
# Pure helpers (no I/O — these are what the tests cover)
# ===================================================================
def pad_cik(cik) -> str:
    """1234 -> 'CIK0000001234'. Accepts int, '1234', or an already-padded string.

    EDGAR's JSON APIs require the zero-padded 10-digit form; the Archives paths
    require the *unpadded* integer. Getting these the wrong way round 404s, so both
    conversions live here rather than being inlined at each call site."""
    s = str(cik).strip().upper()
    if s.startswith("CIK"):
        s = s[3:]
    return "CIK" + s.zfill(10)


def cik_int(cik) -> str:
    """'CIK0000051143' -> '51143' (Archives paths use the unpadded integer)."""
    s = str(cik).strip().upper()
    if s.startswith("CIK"):
        s = s[3:]
    return str(int(s))


def cik_from_map(ticker_map, ticker: str) -> str | None:
    """Resolve a ticker to a padded CIK from SEC's company_tickers.json.

    That file is a dict keyed by row number, each value {cik_str, ticker, title}.
    Matching is case-insensitive; SEC stores tickers upper-case.
    """
    if not isinstance(ticker_map, dict) or not ticker:
        return None
    want = str(ticker).strip().upper()
    for row in ticker_map.values():
        if isinstance(row, dict) and str(row.get("ticker", "")).upper() == want:
            return pad_cik(row.get("cik_str"))
    return None


def filing_url(cik, accession: str, primary_doc: str) -> str:
    """Direct URL to a filing's primary document.

    The accession number is dashed in the JSON ('0000051143-26-000078') but the
    Archives directory that holds it is undashed. This is the single most common way
    to build a 404 against EDGAR."""
    return ARCHIVE_URL.format(cik_int=cik_int(cik),
                              acc=str(accession).replace("-", ""),
                              doc=primary_doc)


def describe_items(items: str) -> list:
    """8-K 'items' string -> readable catalyst labels, unknown codes passed through.

    The field arrives as e.g. '2.02,9.01' or '5.02'. Unknown codes are kept verbatim
    rather than dropped: an unrecognised item is still evidence that something was
    disclosed, and silently swallowing it would be the wrong failure."""
    out = []
    for raw in str(items or "").split(","):
        code = raw.strip()
        if not code:
            continue
        out.append(f"{code}: {EIGHT_K_ITEMS[code]}" if code in EIGHT_K_ITEMS else code)
    return out


def pick_filings(submissions, forms=DEFAULT_FORMS, per_form: int = 3) -> list:
    """Most recent `per_form` filings of each requested form, newest first.

    `filings.recent` is stored as PARALLEL ARRAYS, not a list of records — form[i]
    belongs with filingDate[i], accessionNumber[i] and so on. Zipping them wrongly
    silently attributes one filing's date to another filing, which is the kind of bug
    that looks like working code, so the reassembly is isolated here and tested.

    Only `filings.recent` is read (the newest 1000 filings). Older filings live in
    separate paginated files; for "what did they last report" that is never needed,
    and fetching them would multiply the request count for no analytical gain.
    """
    if not isinstance(submissions, dict):
        return []
    recent = ((submissions.get("filings") or {}).get("recent")) or {}
    if not isinstance(recent, dict):
        return []
    form_col = recent.get("form") or []
    if not form_col:
        return []

    def col(name):
        c = recent.get(name) or []
        return list(c) + [None] * (len(form_col) - len(c))   # tolerate short columns

    dates, periods = col("filingDate"), col("reportDate")
    accs, docs, items = col("accessionNumber"), col("primaryDocument"), col("items")
    cik = submissions.get("cik")

    wanted = {str(f).upper() for f in forms}
    counts, out = {}, []
    for i, form in enumerate(form_col):
        f = str(form).upper()
        if f not in wanted or counts.get(f, 0) >= per_form:
            continue
        counts[f] = counts.get(f, 0) + 1
        rec = {
            "form": form,
            "filed": dates[i],
            "period": periods[i],
            "accession": accs[i],
            "url": filing_url(cik, accs[i], docs[i]) if cik and accs[i] and docs[i] else None,
        }
        if f == "8-K":
            rec["items"] = describe_items(items[i])
        out.append(rec)
    # `recent` is already newest-first; sort defensively on the date we display.
    out.sort(key=lambda r: (r.get("filed") or ""), reverse=True)
    return out


def latest_of(filings: list, form: str) -> dict | None:
    """The newest filing of one form, or None."""
    for f in filings:
        if str(f.get("form", "")).upper() == str(form).upper():
            return f
    return None


def is_us_listing(ticker: str) -> bool:
    """EDGAR covers SEC registrants. A Yahoo suffix means a non-US venue.

    Note the honest limit: a bare symbol is a *necessary* not sufficient condition —
    some SEC registrants are foreign private issuers filing 20-F/40-F rather than
    10-K. Those return no 10-K/10-Q and are reported as such rather than as an error.
    """
    return markets.suffix_of(ticker) == ""


def cache_is_fresh(path: Path, ttl_days: int, now: float | None = None) -> bool:
    """Whether a cache file exists and is younger than its TTL."""
    try:
        if not path.exists():
            return False
        age_s = (now if now is not None else time.time()) - path.stat().st_mtime
        return age_s < ttl_days * 86400
    except OSError:
        return False


def summarise_facts(facts, tags=None) -> dict:
    """Pull a few headline US-GAAP annual facts out of companyfacts.

    A cross-check on yfinance, not a replacement: these are the numbers the company
    itself filed. Only annual (`fp == 'FY'`, form 10-K) figures are taken, because
    mixing quarterly and annual frames is how a 4x error gets into a comparison.
    """
    tags = tags or ["Revenues", "NetIncomeLoss", "Assets", "Liabilities",
                    "StockholdersEquity", "CashAndCashEquivalentsAtCarryingValue"]
    gaap = ((facts or {}).get("facts") or {}).get("us-gaap") or {}
    out = {}
    for tag in tags:
        entry = gaap.get(tag)
        if not isinstance(entry, dict):
            continue
        best = None
        for unit_rows in (entry.get("units") or {}).values():
            for row in unit_rows or []:
                if row.get("fp") != "FY" or row.get("form") != "10-K":
                    continue
                if row.get("val") is None or not row.get("end"):
                    continue
                if best is None or row["end"] > best["end"]:
                    best = row
        if best:
            out[tag] = {"value": best["val"], "period_end": best["end"],
                        "fy": best.get("fy")}
    return out


def strip_html(html: str) -> str:
    """Inline-XBRL filing HTML -> readable plain text.

    Deliberately regex-based rather than a parser dependency: the suite is stdlib-only
    and network-free, and the goal here is *narrative prose for an LLM to read*, not a
    faithful DOM. Script/style blocks are dropped whole (their contents are not prose),
    entities are decoded, and whitespace is collapsed -- a modern 10-Q is mostly inline
    XBRL tags wrapping the same words, so collapsing is what makes it legible.
    """
    import html as html_mod
    import re
    if not html:
        return ""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    # Block-level tags become newlines so paragraphs and table rows do not run together.
    text = re.sub(r"(?i)<(br|/p|/div|/tr|/h[1-6]|/li)\s*/?>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip()


def _normalise_punct(text: str) -> str:
    """Typographic punctuation -> ASCII, strictly one character for one.

    Filers write "Management's Discussion" with U+2019, not an ASCII apostrophe.
    Matched against an ASCII heading that never hits -- measured on IBM's 10-Q, where
    the MD&A sat at offset 165694 and the extractor silently fell back to the head of
    the document instead.

    Every mapping here MUST stay length-preserving, because callers slice the
    normalised string and expect the offsets to line up with the original.
    """
    for src, dst in (("’", "'"), ("‘", "'"), ("“", '"'),
                     ("”", '"'), ("–", "-"), ("—", "-"),
                     (" ", " ")):
        text = text.replace(src, dst)
    return text


# Inline-XBRL filings open with a hidden context block of taxonomy URIs and axis
# names. It is the first thing in the extracted text and it is not prose, so a naive
# "first N characters" fallback hands an LLM several pages of
# "http://fasb.org/us-gaap/2026#CostOfRevenue".
_XBRL_NOISE = ("http://fasb.org/", "http://www.xbrl.org/", "us-gaap/", "srt/",
               "xbrl.sec.gov/")


def first_prose(text: str, max_chars: int = 12000, window: int = 1500) -> str:
    """Head of the document, skipping the inline-XBRL boilerplate.

    Scans forward in windows and returns from the first one that reads like prose --
    measured by how little of it is taxonomy URIs. Falls back to the plain head if
    nothing qualifies, because some truncated text still beats none.
    """
    if not text:
        return ""
    step = max(200, window // 2)
    for start in range(0, min(len(text), 400_000), step):
        chunk = text[start:start + window]
        if not chunk.strip():
            continue
        noise = sum(chunk.count(marker) for marker in _XBRL_NOISE)
        # A prose window has few or no taxonomy references and real sentence density.
        if noise <= 1 and chunk.count(" ") > window / 12:
            return text[start:start + max_chars].strip()
    return text[:max_chars].strip()


def find_section(text: str, headings, max_chars: int = 12000) -> str | None:
    """Slice out the first matching narrative section of a filing.

    `headings` are tried in order; the first that matches wins. Matching is loose
    ("item 7" / "item 7." / "ITEM 7 -") because filers format item headings freely.

    Returns None rather than a guess when nothing matches -- handing the LLM an
    arbitrary 12 000 characters from the middle of a filing and calling it "MD&A"
    would be worse than admitting the section was not found.
    """
    import re
    if not text:
        return None
    text = _normalise_punct(text)          # length-preserving, so offsets still hold
    low = text.lower()
    for h in headings:
        # Match on FLEXIBLE WHITESPACE, not the literal heading. IBM's 10-Q writes the
        # body heading as "Item 2.  Management's..." (two spaces) while the contents
        # page uses one, so an exact-string match found only the contents page --
        # measured, after the apostrophe fix had already been applied.
        pattern = r"\s+".join(re.escape(tok)
                              for tok in _normalise_punct(h).lower().split())
        hits = [m.start() for m in re.finditer(pattern, low)]
        if not hits:
            continue
        # Every item heading appears at least twice: once in the table of contents,
        # once as the real section. The contents entry comes first, so prefer the
        # last occurrence and fall back to the only one when there is a single hit.
        for start in (hits[-1], hits[0]):
            chunk = text[start:start + max_chars].strip()
            # A contents entry is a line of dot leaders and page numbers followed by
            # more of the same. Require real sentence density before accepting it.
            if len(chunk) > 400 and _looks_like_prose(chunk[:1200]):
                return chunk
    return None


def _looks_like_prose(chunk: str) -> bool:
    """Distinguish a real section from a table-of-contents block.

    A contents page is short lines ending in page numbers; a section is sentences.
    Two cheap signals separate them: average line length, and how often a line ends
    in a bare number."""
    lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
    if not lines:
        return False
    numeric_tail = sum(1 for ln in lines if ln.rstrip().rstrip(".").isdigit())
    avg_len = sum(len(ln) for ln in lines) / len(lines)
    return not (numeric_tail >= len(lines) / 3 or avg_len < 25)


def fetch_filing_text(url: str, max_chars: int = 12000, timeout: int = 40) -> str | None:
    """Download a filing's primary document and return bounded readable text.

    Bounded on purpose. IBM's latest 10-Q is 3.67 MB of HTML (measured); handing that
    to an LLM is neither affordable nor useful. This returns the MD&A/business section
    when it can be located, else the head of the document, always capped.

    NARRATIVE ONLY. Nothing here may be parsed for numbers -- the ground-truth rule
    stands, and filing figures come from XBRL (`summarise_facts`) or the Phase 2 JSON.
    """
    _throttle()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310
            raw = resp.read()
    except Exception as e:                                           # noqa: BLE001
        log(f"filing text fetch failed: {type(e).__name__}: {e}")
        return None
    text = strip_html(raw.decode("utf-8", "replace"))
    if not text:
        return None
    section = find_section(text, [
        "Item 2. Management's Discussion",     # 10-Q MD&A
        "Item 7. Management's Discussion",     # 10-K MD&A
        "Management's Discussion and Analysis",
        "Item 1. Business",
        "Item 1A. Risk Factors",
    ], max_chars=max_chars)
    return section or first_prose(text, max_chars=max_chars)


# ===================================================================
# I/O
# ===================================================================
def _throttle() -> None:
    global _last_request_at
    wait = MIN_REQUEST_INTERVAL_S - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def http_get_json(url: str, timeout: int = 30):
    """GET + parse JSON with the required User-Agent. None on any failure.

    Never raises: EDGAR is an enrichment, and a dead network must degrade the report,
    never abort the pipeline."""
    _throttle()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Accept-Encoding": "gzip, deflate"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:                                          # noqa: BLE001
        log(f"GET failed {url.split('?')[0]}: {type(e).__name__}: {e}")
        return None


def _read_cache(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                               # noqa: BLE001
        return None


def _write_cache(path: Path, payload) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as e:
        log(f"cache write failed: {e}")


def resolve_cik(ticker: str, cache_dir: Path) -> str | None:
    """Ticker -> padded CIK, via a cached copy of SEC's ticker map (~800 KB)."""
    path = cache_dir / "_ticker_map.json"
    data = _read_cache(path) if cache_is_fresh(path, TICKER_MAP_TTL_DAYS) else None
    if data is None:
        data = http_get_json(TICKER_MAP_URL)
        if data:
            _write_cache(path, data)
    return cik_from_map(data, ticker)


def fetch(ticker: str, out_dir: Path, want_facts: bool = False,
          per_form: int = 3) -> dict:
    """Full EDGAR block for one ticker. Always returns a dict; never raises."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = {"ticker": ticker, "fetched_at": now_iso}

    if not is_us_listing(ticker):
        return {**base, "available": False,
                "reason": f"{ticker} is not a US listing - no SEC filer"}

    cache_dir = out_dir / "_edgar"
    cik = resolve_cik(ticker, cache_dir)
    if not cik:
        return {**base, "available": False,
                "reason": f"no SEC CIK found for {ticker}"}

    sub_path = cache_dir / f"{cik}.json"
    subs = _read_cache(sub_path) if cache_is_fresh(sub_path, SUBMISSIONS_TTL_DAYS) else None
    if subs is None:
        subs = http_get_json(SUBMISSIONS_URL.format(cik=cik))
        if subs:
            _write_cache(sub_path, subs)
    if not subs:
        return {**base, "available": False, "cik": cik,
                "reason": "SEC submissions endpoint unavailable"}

    filings = pick_filings(subs, per_form=per_form)
    result = {
        **base,
        "available": True,
        "cik": cik,
        "company": subs.get("name"),
        "sic": subs.get("sicDescription"),
        "exchanges": subs.get("exchanges"),
        "fiscal_year_end": subs.get("fiscalYearEnd"),
        "filings": filings,
        "latest_10k": latest_of(filings, "10-K"),
        "latest_10q": latest_of(filings, "10-Q"),
        "latest_8k": latest_of(filings, "8-K"),
    }
    if not filings:
        # A registrant with no 10-K/10-Q is usually a foreign private issuer filing
        # 20-F/40-F. Say which, rather than implying the fetch failed.
        result["note"] = ("no 10-K/10-Q/8-K in the recent filing history - likely a "
                          "foreign private issuer (20-F/40-F) or a non-operating filer")

    if want_facts:
        facts_path = cache_dir / f"{cik}_facts.json"
        facts = _read_cache(facts_path) if cache_is_fresh(facts_path, FACTS_TTL_DAYS) else None
        if facts is None:
            facts = http_get_json(COMPANYFACTS_URL.format(cik=cik))
            if facts:
                _write_cache(facts_path, facts)
        result["xbrl_facts"] = summarise_facts(facts) if facts else {}
        if not facts:
            result["xbrl_note"] = "companyfacts unavailable"
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="SEC EDGAR filings for a US listing")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--facts", action="store_true",
                    help="also fetch XBRL companyfacts (5.6 MB, ~3 s — opt-in)")
    ap.add_argument("--per-form", type=int, default=3,
                    help="how many filings of each form to return (default 3)")
    ap.add_argument("--text", action="store_true",
                    help="also download the latest 10-Q/10-K primary document and "
                         "extract bounded narrative text (one extra request)")
    ap.add_argument("--max-chars", type=int, default=12000,
                    help="cap on extracted filing text (default 12000)")
    args = ap.parse_args()

    result = fetch(args.ticker, Path(args.out_dir), want_facts=args.facts,
                   per_form=args.per_form)

    if args.text and result.get("available"):
        # Prefer the 10-Q (most recent picture); fall back to the 10-K.
        src = result.get("latest_10q") or result.get("latest_10k")
        if src and src.get("url"):
            body = fetch_filing_text(src["url"], max_chars=args.max_chars)
            if body:
                result["filing_text"] = {
                    "form": src["form"], "filed": src["filed"],
                    "period": src.get("period"), "url": src["url"],
                    "chars": len(body), "text": body,
                }
            else:
                result["filing_text_note"] = "primary document could not be read"
        else:
            result["filing_text_note"] = "no 10-Q or 10-K available to read"
    print(json.dumps(result, indent=2, ensure_ascii=False))
    # Exit 0 even when unavailable: this is an enrichment node and a missing EDGAR
    # block must never fail the pipeline (same contract as financial_history.py).
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
