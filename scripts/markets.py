"""
markets.py — Global-market metadata + free price cross-check (Phase 6).

Pure, network-free helpers (suffix→currency/region map, Stooq symbol mapping,
Stooq CSV parsing, local→EUR conversion) plus one thin network function
(fetch_stooq_eod) that the Layer-1 validation path in analyze_ticker.py calls
for non-US tickers. Everything except fetch_stooq_eod is deterministic and
unit-tested with static fixtures (no network).

Coverage target (Phase 6 global expansion):
  Taiwan (.TW/.TWO), China Shanghai/Shenzhen (.SS/.SZ), Hong Kong (.HK),
  India (.NS/.BO), South Korea (.KS/.KQ), Japan (.T/.JP), plus the existing
  Europe + US/Canada suffixes already in the universe.

Accounting-standard caveats per market (IFRS / US-GAAP / JP-GAAP / China-GAAP)
are surfaced into analyze_ticker's data_warnings so the LLM narrative can flag
them. yfinance coverage and currency handling differ by market — see
docs/MARKET_COVERAGE_v3.md.
"""
from __future__ import annotations

import io


# ------------------------- Suffix → currency / region / accounting -------------------------
# Yahoo exchange suffix -> (region, currency, accounting_standard, exchange_label).
# US tickers have no suffix and are handled by the bare-symbol default below.
_SUFFIX_META: dict[str, tuple[str, str, str, str]] = {
    # ---- Asia (Phase 6 expansion) ----
    "TW": ("TW", "TWD", "IFRS", "Taiwan Stock Exchange"),
    "TWO": ("TW", "TWD", "IFRS", "Taipei Exchange (TPEx)"),
    "SS": ("CN", "CNY", "China-GAAP", "Shanghai Stock Exchange"),
    "SZ": ("CN", "CNY", "China-GAAP", "Shenzhen Stock Exchange"),
    "HK": ("HK", "HKD", "IFRS", "Hong Kong Stock Exchange"),
    "NS": ("IN", "INR", "IND-AS", "NSE India"),
    "BO": ("IN", "INR", "IND-AS", "BSE India"),
    "KS": ("KR", "KRW", "K-IFRS", "KOSPI"),
    "KQ": ("KR", "KRW", "K-IFRS", "KOSDAQ"),
    "T": ("JP", "JPY", "JP-GAAP/IFRS", "Tokyo Stock Exchange"),
    "JP": ("JP", "JPY", "JP-GAAP/IFRS", "Tokyo Stock Exchange"),
    # ---- Europe (existing universe) ----
    "AS": ("NL", "EUR", "IFRS", "Euronext Amsterdam"),
    "PA": ("FR", "EUR", "IFRS", "Euronext Paris"),
    "BR": ("BE", "EUR", "IFRS", "Euronext Brussels"),
    "LS": ("PT", "EUR", "IFRS", "Euronext Lisbon"),
    "MC": ("ES", "EUR", "IFRS", "BME (Madrid)"),
    "MI": ("IT", "EUR", "IFRS", "Borsa Italiana"),
    "DE": ("DE", "EUR", "IFRS", "XETRA"),
    "F": ("DE", "EUR", "IFRS", "Frankfurt"),
    "HE": ("FI", "EUR", "IFRS", "Nasdaq Helsinki"),
    "CO": ("DK", "DKK", "IFRS", "Nasdaq Copenhagen"),
    "ST": ("SE", "SEK", "IFRS", "Nasdaq Stockholm"),
    "OL": ("NO", "NOK", "IFRS", "Oslo Bors"),
    "WA": ("PL", "PLN", "IFRS", "Warsaw Stock Exchange"),
    "L": ("UK", "GBP", "IFRS", "London Stock Exchange"),
    "IR": ("IE", "EUR", "IFRS", "Euronext Dublin"),
    "VI": ("AT", "EUR", "IFRS", "Wiener Borse"),
    "SW": ("CH", "CHF", "IFRS", "SIX Swiss"),
    "TO": ("CA", "CAD", "IFRS", "Toronto Stock Exchange"),
    "HA": ("DE", "EUR", "IFRS", "Hanover (secondary)"),
    # ---- v4.3 expansion: suffixes already present in _universe.yaml but unmapped ----
    # Every one of these was resolving to INTL/USD, which silently broke to_eur()
    # FX conversion, region_of() and the accounting caveat. 241 pool tickers were
    # affected, 200 of them .AX alone -- the second-largest market in the universe
    # after the US.
    "AX": ("AU", "AUD", "IFRS", "ASX"),          # AASB is IFRS-equivalent
    "SI": ("SG", "SGD", "IFRS", "Singapore Exchange (SGX)"),
    "V": ("CA", "CAD", "IFRS", "TSX Venture"),
    "MX": ("MX", "MXN", "IFRS", "Bolsa Mexicana (BMV)"),
    # .SA is BRAZIL and .SR is SAUDI ARABIA. They are easy to transpose and the
    # universe holds both (WEGE3/RENT3/RADL3.SA; 2222/1120.SR), so mapping SA to
    # SAR would corrupt the currency of three Brazilian names.
    "SA": ("BR", "BRL", "IFRS", "B3 Sao Paulo"),
    "SR": ("SAU", "SAR", "IFRS", "Tadawul (Saudi)"),
    "JK": ("ID", "IDR", "IFRS", "Indonesia Stock Exchange (IDX)"),
    "BD": ("HU", "HUF", "IFRS", "Budapest Stock Exchange"),
}

# US default (no suffix).
_US_META = ("US", "USD", "US-GAAP", "US (NYSE/Nasdaq)")

# ------------------------------- Tradability tier -------------------------------
# The brief was "every region IBKR Europe can BUY, plus every region Yahoo can
# MONITOR". That is a union with a distinction, not an intersection: some venues
# quote cleanly on Yahoo but are not reachable from an IBKR Europe retail account.
# Offering those as buyable would be the dishonest outcome, so they are carried as
# an explicit MONITOR-ONLY tier instead of being dropped or silently included.
#
# This is a *coverage* statement, not investment advice, and it is reference data
# that goes stale: brokers add and remove market access. Re-confirm before acting.
_MONITOR_ONLY_REGIONS: frozenset = frozenset({"BR", "SAU", "ID", "HU"})

# Secondary/regional venues that quote the SAME company as a primary listing. They
# are thin, and a thin venue is how roadmap R4 happened: ADS.DE resolved to
# XSTU/Stuttgart, returned a stale price while Xetra had gapped -18% on earnings,
# and the divergence was logged as a yfinance error when the REFERENCE was wrong.
# Identity is handled by listings.py (SSUN.F is already registered as a Samsung
# GDR); this set exists so the price cross-check carries the warning.
_THIN_SECONDARY_SUFFIXES: frozenset = frozenset({"F", "HA", "V"})


def suffix_of(ticker: str) -> str:
    """Return the Yahoo exchange suffix (without dot), or '' for US/no-suffix.

    Dot-form US class shares (BRK.B, BF.B) are NOT exchange suffixes: a single
    trailing letter that isn't a known exchange code resolves to '' (US)."""
    base, dot, suffix = ticker.rpartition(".")
    if not dot:
        return ""
    up = suffix.upper()
    if len(up) == 1 and up not in _SUFFIX_META and base and not base[0].isdigit():
        return ""  # class-share letter, not an exchange
    return up


def market_meta(ticker: str) -> dict:
    """Resolve (region, currency, accounting_standard, exchange) for a ticker.

    Unknown suffixes fall back to a neutral 'INTL'/USD record with a flag so the
    caller can emit a clean data warning rather than mis-reporting currency.
    """
    suffix = suffix_of(ticker)
    if not suffix:
        region, currency, accounting, exchange = _US_META
        return {
            "region": region, "currency": currency,
            "accounting_standard": accounting, "exchange": exchange,
            "suffix": "", "known": True,
        }
    meta = _SUFFIX_META.get(suffix)
    if meta is None:
        return {
            "region": "INTL", "currency": "USD",
            "accounting_standard": "unknown", "exchange": f"unknown ({suffix})",
            "suffix": suffix, "known": False,
        }
    region, currency, accounting, exchange = meta
    return {
        "region": region, "currency": currency,
        "accounting_standard": accounting, "exchange": exchange,
        "suffix": suffix, "known": True,
    }


def region_of(ticker: str) -> str:
    """Region code for a ticker (suffix-driven). US for no suffix."""
    return market_meta(ticker)["region"]


def currency_of(ticker: str) -> str:
    """Reporting/quote currency for a ticker (suffix-driven). USD for no suffix."""
    return market_meta(ticker)["currency"]


# Per-market data-quality / accounting caveats for the data_warnings list.
# Keyed by region. Absent region => no extra caveat.
_MARKET_CAVEATS: dict[str, str] = {
    "CN": ("China-GAAP statements (A-shares .SS/.SZ): yfinance fundamental coverage is "
           "partial and lags; CNY is managed/illiquid for foreign holders, capital controls apply"),
    "HK": ("Hong Kong (.HK): mix of IFRS and China-GAAP filers; H-share fundamentals "
           "can be sparse on yfinance; HKD is USD-pegged"),
    "JP": ("Japan (.T): JP-GAAP vs IFRS varies by filer; many ratios reported on a "
           "consolidated fiscal-year (Mar) basis — TTM mapping is approximate"),
    "KR": ("South Korea (.KS/.KQ): K-IFRS; chaebol cross-holdings distort ROE/EV; "
           "KRW is large-denomination (watch per-share magnitudes)"),
    "TW": ("Taiwan (.TW/.TWO): IFRS; solid yfinance coverage for large-caps, thinner "
           "for TPEx (.TWO) small-caps"),
    "IN": ("India (.NS/.BO): Ind-AS (IFRS-converged); good large-cap coverage; "
           "promoter-holding structures common — check shareholder concentration"),
    "UK": ("London (.L): shares are usually quoted in GBp (pence) = 1/100 GBP — "
           "yfinance reports GBp/GBX; prices are normalised to GBP before the EUR "
           "conversion (a raw pence value read as GBP would be 100x too high)"),
    # ---- v4.3 expansion ----
    "AU": ("Australia (.AX): AASB is IFRS-equivalent, so ratios are comparable; but "
           "issuers report HALF-YEARLY, not quarterly — the quarterly EBITDA/FCF "
           "series is unavailable for most names and is omitted rather than faked"),
    "SG": ("Singapore (.SI): IFRS (SFRS); the index is REIT- and bank-heavy, so peer "
           "medians drawn from it skew toward yield rather than growth"),
    "CA": ("Canada (.TO/.V): IFRS. .V is TSX Venture — small/micro-cap, thin volume, "
           "and its own index (^JX) is delisted on Yahoo, so relative strength falls "
           "back to the large-cap ^GSPTSE and understates venture volatility"),
    "BR": ("Brazil (.SA): IFRS. NOTE .SA is Sao Paulo (BRL) and .SR is Tadawul (SAR) — "
           "transposing them corrupts the currency. BRL is volatile: local returns and "
           "EUR returns can differ by tens of percent in a year"),
    "SAU": ("Saudi (.SR): IFRS. Tadawul trades Sun-Thu, so the week does not align with "
            "European sessions; yfinance index coverage is thin (^TASI.SR returned 5 "
            "rows in a month when measured), making relative strength unreliable"),
    "MX": ("Mexico (.MX): IFRS. MXN is an EM currency and the peso can move enough in a "
           "year to dominate the equity return — judge performance in EUR, not local"),
    "ID": ("Indonesia (.JK): IFRS-converged (PSAK); yfinance fundamental coverage is "
           "partial; IDR is large-denomination — watch per-share magnitudes"),
    "HU": ("Hungary (.BD): IFRS; a very small market. The BUX index is barely covered by "
           "yfinance (1 row in a month when measured), so treat any relative-strength "
           "or beta figure for .BD as not meaningful"),
}


def is_tradable(ticker: str) -> bool:
    """Whether this venue is reachable from the IBKR Europe account (best effort).

    False means MONITOR-ONLY: quotable and analysable, but do not present it as
    something that can be bought. Unknown suffixes are not tradable either — an
    unresolved market must never be implied to be reachable.
    """
    meta = market_meta(ticker)
    return bool(meta["known"]) and meta["region"] not in _MONITOR_ONLY_REGIONS


def tradability(ticker: str) -> str:
    """'tradable' | 'monitor_only' | 'unknown' — the report-facing label."""
    meta = market_meta(ticker)
    if not meta["known"]:
        return "unknown"
    return "monitor_only" if meta["region"] in _MONITOR_ONLY_REGIONS else "tradable"


def market_caveats(ticker: str) -> list[str]:
    """Accounting-standard / data-coverage / currency caveats for a ticker's market."""
    meta = market_meta(ticker)
    out: list[str] = []
    if not meta["known"]:
        out.append(
            f"unknown exchange suffix '.{meta['suffix']}' — currency/region unresolved, "
            f"defaulting to USD; verify reported figures manually"
        )
        return out
    cav = _MARKET_CAVEATS.get(meta["region"])
    if cav:
        out.append(f"accounting/coverage [{meta['region']}]: {cav}")
    if meta["region"] in _MONITOR_ONLY_REGIONS:
        out.append(
            f"tradability [{meta['region']}]: MONITOR-ONLY — {meta['exchange']} is "
            f"quotable on Yahoo but not reachable from the IBKR Europe account; "
            f"analyse it, do not present it as buyable"
        )
    if meta["suffix"] in _THIN_SECONDARY_SUFFIXES:
        out.append(
            f"venue [{meta['suffix']}]: thin secondary listing — quotes can be stale "
            f"or gap away from the primary line; prefer the primary listing "
            f"(listings.py) and treat a price divergence as a REFERENCE problem "
            f"before calling it a data error"
        )
    return out


# ------------------------- GBp / GBX (LSE pence) normalisation -------------------------
# London-listed shares are usually quoted in GBp (pence) = 1/100 GBP, and
# yfinance reports the quote currency as "GBp" or "GBX" accordingly. If a pence
# price were ever treated as GBP the EUR conversion would be 100x too large.
# normalize_gbx() collapses GBp/GBX prices to GBP so the local->EUR path (which
# uses the EURGBP=X pair) is currency-correct.
_GBX_CODES = frozenset({"GBP", "GBX"})  # uppercased; "GBp" -> "GBP" before lookup


def normalize_gbx(amount, currency: str) -> tuple[float | None, str]:
    """Normalise a GBp/GBX (pence) amount to GBP.

    Returns (amount_in_gbp_or_unchanged, normalised_currency). For GBp/GBX the
    amount is divided by 100 and the currency becomes "GBP". Any other currency
    (including plain GBP) passes through unchanged. `amount` of None passes
    through. The check is case-sensitive on the original ("GBp"/"GBX") because
    yfinance uses exactly those spellings; plain "GBP" is left as-is.
    """
    cur = currency or ""
    is_pence = cur in ("GBp", "GBX")
    if not is_pence:
        return (None if amount is None else float(amount)), cur
    if amount is None:
        return None, "GBP"
    return float(amount) / 100.0, "GBP"


# ------------------------- FX: local -> EUR -------------------------
def eur_fx_pair(currency: str) -> str | None:
    """Yahoo FX pair giving units of `currency` per 1 EUR (e.g. 'EURJPY=X').

    Returns None for EUR itself (rate 1.0) or unknown currency.
    """
    cur = (currency or "").upper()
    if cur in ("", "EUR"):
        return None
    return f"EUR{cur}=X"


def to_eur(amount, currency: str, eur_rate) -> float | None:
    """Convert `amount` in `currency` to EUR.

    `eur_rate` is units of `currency` per 1 EUR (the EURxxx=X quote). EUR amounts
    pass through. Returns None if inputs are missing/zero.
    """
    if amount is None:
        return None
    cur = (currency or "").upper()
    if cur == "EUR":
        return round(float(amount), 6)
    if not eur_rate or eur_rate <= 0:
        return None
    return round(float(amount) / float(eur_rate), 6)


# ------------------------- Stooq EOD price cross-check (Finding D2) -------------------------
# Yahoo suffix -> Stooq symbol suffix. Stooq uses its own exchange codes. The
# interactive stooq.com site is JS-gated, but the CSV endpoint
# https://stooq.com/q/d/l/?s=<sym>&i=d is plain CSV and NOT JS-blocked — no key.
# US tickers: Stooq wants a ".us" suffix (e.g. aapl.us).
_STOOQ_SUFFIX: dict[str, str] = {
    "": "us",      # US (no Yahoo suffix) -> .us on Stooq
    "HK": "hk",
    "T": "jp",     # Tokyo
    "JP": "jp",
    "KS": "kr",
    "KQ": "kr",
    "TW": "tw",
    "TWO": "tw",
    "SS": "cn",    # Shanghai
    "SZ": "cn",    # Shenzhen
    "NS": "in",    # NSE India
    "BO": "in",    # BSE India
    "L": "uk",
    "DE": "de",
    "F": "de",
    "PA": "fr",
    "AS": "nl",
    "MI": "it",
    "MC": "es",
    "LS": "pt",
    "BR": "be",
    "IR": "ie",
    "ST": "se",
    "CO": "dk",
    "OL": "no",
    "HE": "fi",
    "WA": "pl",
    "SW": "ch",
    "VI": "at",
    "TO": "ca",
}


def to_stooq_symbol(ticker: str) -> str | None:
    """Map a Yahoo ticker to a Stooq CSV symbol.

    Examples: 6502.T -> 6502.jp ; 0700.HK -> 0700.hk ; 005930.KS -> 005930.kr ;
    RELIANCE.NS -> reliance.in ; 2330.TW -> 2330.tw ; AAPL -> aapl.us ;
    300750.SZ -> 300750.cn. Returns None for an unmapped suffix.
    """
    base, dot, suffix = ticker.rpartition(".")
    if not dot:
        base, suffix = ticker, ""
    suffix = suffix.upper()
    stooq_sfx = _STOOQ_SUFFIX.get(suffix)
    if stooq_sfx is None:
        return None
    # Stooq symbols are lowercase. Keep numeric base codes as-is (already digits).
    return f"{base.lower()}.{stooq_sfx}"


def stooq_csv_url(stooq_symbol: str) -> str:
    """The Stooq daily-EOD CSV endpoint for a Stooq symbol (no API key)."""
    return f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"


def parse_stooq_csv(text: str) -> dict | None:
    """Parse a Stooq daily-EOD CSV into {date, close, volume} for the last row.

    Stooq CSV header: Date,Open,High,Low,Close,Volume. Returns None when the
    payload is empty, an error sentinel ('N/D'), or has no usable Close.
    """
    if not text:
        return None
    stripped = text.strip()
    # Stooq returns "No data" / "N/D" for unknown symbols or exhausted limits.
    if stripped.upper().startswith("N/D") or "no data" in stripped.lower():
        return None
    # As of mid-2026 Stooq guards the CSV endpoint with a JavaScript proof-of-work
    # challenge (SHA-256 via /__verify) served as an HTML interstitial to clients
    # that don't run JS. That is NOT valid CSV — reject it explicitly so the caller
    # can report the real cause instead of a misleading "no data".
    low = stripped.lower()
    if low.startswith("<!doctype") or low.startswith("<html") or "requires javascript" in low:
        return None
    import csv as _csv

    rows = list(_csv.reader(io.StringIO(stripped)))
    if len(rows) < 2:
        return None
    header = [h.strip().lower() for h in rows[0]]
    try:
        date_i = header.index("date")
        close_i = header.index("close")
    except ValueError:
        return None
    vol_i = header.index("volume") if "volume" in header else None
    last = rows[-1]
    if len(last) <= close_i:
        return None
    try:
        close = float(last[close_i])
    except (ValueError, IndexError):
        return None
    if close <= 0:
        return None
    vol = None
    if vol_i is not None and len(last) > vol_i:
        try:
            vol = float(last[vol_i])
        except (ValueError, IndexError):
            vol = None
    return {"date": last[date_i].strip(), "close": close, "volume": vol}


def stooq_price_check(ticker: str, yf_price, *, _fetcher=None, tol: float = 0.15) -> dict:
    """Layer-1 Stooq EOD *price* cross-check for a (typically non-US) ticker.

    Compares yfinance's price to Stooq's last EOD close. Price-only — Stooq has
    no fundamentals. Best-effort & non-fatal: any failure returns an `error`
    field with empty divergences. `_fetcher(url) -> text` is injectable for tests.
    """
    result = {
        "source": "stooq", "checked": [], "divergences": [],
        "agree": None, "error": None, "stooq_symbol": None, "stooq_price": None,
    }
    sym = to_stooq_symbol(ticker)
    if sym is None:
        result["error"] = f"no Stooq symbol mapping for {ticker}"
        return result
    result["stooq_symbol"] = sym
    url = stooq_csv_url(sym)

    if _fetcher is None:
        def _fetcher(u):  # noqa: ANN001
            import requests
            r = requests.get(
                u, timeout=12,
                headers={"User-Agent": "Mozilla/5.0 (compatible; bd-stocks-daily/1.0)"},
            )
            return r.text if r.status_code == 200 else ""

    try:
        text = _fetcher(url)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
        return result

    parsed = parse_stooq_csv(text)
    if parsed is None:
        low = (text or "").strip().lower()
        if low.startswith(("<!doctype", "<html")) or "requires javascript" in low:
            result["error"] = (
                f"Stooq CSV endpoint served a JS proof-of-work challenge for {sym} "
                f"(JS-gated from this client/IP) — price cross-check unavailable"
            )
        else:
            result["error"] = f"Stooq: no EOD data for {sym}"
        return result
    stooq_price = parsed["close"]
    result["stooq_price"] = stooq_price
    result["stooq_date"] = parsed.get("date")

    if isinstance(yf_price, (int, float)) and yf_price and stooq_price:
        d = abs(yf_price - stooq_price) / max(abs(yf_price), abs(stooq_price))
        result["checked"].append("price")
        if d > tol:
            result["divergences"].append(
                f"price: yfinance {yf_price:g} vs Stooq {stooq_price:g} ({d * 100:.0f}% apart)"
            )
    result["agree"] = len(result["divergences"]) == 0 and len(result["checked"]) > 0
    return result
