"""
macro_fred.py — the §6 regime gauges, from FRED, as ground truth (roadmap **R2**).

§6 of `_macro/<date>.md` has been rendering *"Not available"* since it was written, and not
because the data is hard to get: the prompt asked the LLM to **WebFetch** the Buffett
Indicator and the M2 series, and an LLM that cannot reach a source correctly refuses to
estimate one. The gap was never a missing number, it was a missing *pinned source*.

FRED has both, behind a clean public JSON API and a key that already exists
(`api_key_fred`). That also moves them to the right side of the ground-truth rule
(`SKILL.md:56`): these are structured numbers, so they belong to a Python helper, and the
LLM should be formatting them rather than sourcing them.

TWO GAUGES, EACH DEGRADING ALONE — one dead series must never blank the section:

  **M2 liquidity regime** — `M2SL`, monthly, Billions of Dollars. Level, YoY change, and
  the 3-month annualised rate, which is what actually turns first. Regime is banded, and
  the bands are published here rather than living in a prompt.

  **Buffett Indicator** — `NCBEILQ027S` ÷ `GDP`. The numerator is *Nonfinancial Corporate
  Business; Corporate Equities; Liability, Level* — the market value of US corporate
  equities, and the series the ratio is conventionally built from on FRED.

UNITS ARE ASSERTED, NOT ASSUMED. `NCBEILQ027S` is published in **millions** of dollars and
`GDP` in **billions**: multiplying them straight through gives a Buffett Indicator wrong by
a factor of **1000**, and 190 000 % looks so obviously broken that it would be caught —
while a subtler pairing would not. So the units string is read from the series metadata on
every run and converted explicitly; anything unrecognised returns an error instead of a
number. The same discipline that made GBp-vs-GBP a caught bug rather than a published one.

The two series also END ON DIFFERENT DATES (the equities series lags GDP by a quarter), so
the ratio is computed on the latest quarter BOTH cover, and that quarter is reported beside
it. A ratio silently mixing Q1 equities with Q2 GDP is a different statistic.

WHAT IS DELIBERATELY NOT HERE: §7's index-level forward-profit horizons (3m/6m/1Y/2Y/3Y).
Forward *earnings estimates* are a licensed product — FactSet, LSEG, S&P — and no free,
pinnable API publishes them. Scraping a page that reprints them is not a pinned source, it
is a page that changes. §7 therefore keeps saying "not available", which is the honest
answer and not an oversight.

Modes mirror `macro_breadth.py`:
  --fetch    print the {regime} JSON to stdout, write nothing
  --update   merge the additive `regime` key into `_macro/<date>.json`
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

OUT_DIR = Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily\_macro")
KEYS_PATH = Path(r"C:\Github\BD\Finance\BD_Finance\config\api_keys.txt")

FRED_ROOT = "https://api.stlouisfed.org/fred"
TIMEOUT_S = 20

M2_SERIES = "M2SL"
EQUITIES_SERIES = "NCBEILQ027S"   # market value of US corporate equities (millions USD)
GDP_SERIES = "GDP"                # billions USD

#: Unit strings FRED actually returns, mapped to a multiplier onto BILLIONS of dollars.
#: An unrecognised unit is an error, never a guess — see the module docstring.
_UNIT_TO_BILLIONS = {
    "billions of dollars": 1.0,
    "billions of u.s. dollars": 1.0,
    "millions of dollars": 1e-3,
    "millions of u.s. dollars": 1e-3,
    "thousands of dollars": 1e-6,
    "thousands of u.s. dollars": 1e-6,
}

#: M2 regime bands on the YoY rate, in percent. Published here so the classification is
#: reproducible and arguable, rather than a word an LLM picked. The contraction band is
#: not symmetric on purpose: M2 falling at all is rare and historically significant,
#: while 0-4% growth is unremarkable.
M2_BANDS = (
    (-1e9, 0.0, "contracting"),
    (0.0, 4.0, "flat"),
    (4.0, 8.0, "expanding"),
    (8.0, 1e9, "rapidly expanding"),
)


def clean_key(value) -> str | None:
    """Strip whitespace and surrounding quotes from a key, or None if there is nothing.

    Not cosmetic. A key stored as `"abc..."` is 34 characters instead of 32 and FRED
    answers **400 Bad Request**, which reads like a revoked key rather than a stray pair
    of quotes — it cost a live run an hour once.
    """
    if value is None:
        return None
    out = str(value).strip()
    for quote in ('"', "'"):
        if len(out) >= 2 and out.startswith(quote) and out.endswith(quote):
            out = out[1:-1].strip()
    return out or None


def read_api_key(path: Path = KEYS_PATH) -> str | None:
    """The FRED key from `api_keys.txt`, cleaned. None on any problem — a missing key is
    a gauge that says "not available", never an exception that fails the macro run."""
    try:
        sys.path.insert(0, str(path.parent.parent))
        from api_keys_reader import api_keys_reader  # noqa: PLC0415
        return clean_key(api_keys_reader(str(path)).get("api_key_fred"))
    except Exception:
        return None


def _get(endpoint: str, params: dict) -> dict:
    url = f"{FRED_ROOT}/{endpoint}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as fh:
        return json.loads(fh.read().decode("utf-8"))


def fetch_series(series_id: str, api_key: str, limit: int = 40) -> dict:
    """`{series_id, units, frequency, observations: [(date, value)], error}`.

    Observations are newest-first and NaN placeholders (FRED writes `"."`) are dropped
    rather than coerced to zero.
    """
    out = {"series_id": series_id, "units": None, "frequency": None,
           "observations": [], "error": None}
    try:
        meta = _get("series", {"series_id": series_id, "api_key": api_key,
                               "file_type": "json"})["seriess"][0]
        out["units"] = meta.get("units")
        out["frequency"] = meta.get("frequency_short")
        obs = _get("series/observations", {
            "series_id": series_id, "api_key": api_key, "file_type": "json",
            "sort_order": "desc", "limit": limit})["observations"]
        for row in obs:
            raw = row.get("value")
            if raw in (None, "", "."):
                continue
            try:
                out["observations"].append((row["date"], float(raw)))
            except (TypeError, ValueError):
                continue
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


# --- pure functions: no network below this line ------------------------------

def to_billions(value, units) -> float | None:
    """Convert to billions of dollars, or None when the unit is not one we know.

    Returning None on an unknown unit is the whole point. `NCBEILQ027S` is in millions and
    `GDP` in billions; a helper that shrugged and passed the number through would publish
    a Buffett Indicator off by 1000x.
    """
    if value is None or units is None:
        return None
    mult = _UNIT_TO_BILLIONS.get(str(units).strip().lower())
    if mult is None:
        return None
    try:
        return float(value) * mult
    except (TypeError, ValueError):
        return None


def classify_m2(yoy_pct) -> str | None:
    if yoy_pct is None:
        return None
    for lo, hi, label in M2_BANDS:
        if lo <= yoy_pct < hi:
            return label
    return None


def _at(observations, months_back: int):
    """The observation `months_back` entries back in a newest-first monthly series."""
    if not observations or len(observations) <= months_back:
        return None, None
    return observations[months_back]


def m2_regime(series: dict) -> dict:
    """Level, YoY, 3-month annualised, and a banded regime label."""
    out = {"gauge": "m2_liquidity", "source": f"FRED {M2_SERIES}",
           "as_of": None, "level_usd_bn": None, "yoy_pct": None,
           "three_month_annualised_pct": None, "regime": None, "error": None}
    if series.get("error"):
        out["error"] = series["error"]
        return out
    obs = series.get("observations") or []
    if not obs:
        out["error"] = "no observations returned"
        return out

    as_of, latest = obs[0]
    out["as_of"] = as_of
    level = to_billions(latest, series.get("units"))
    if level is None:
        out["error"] = f"unrecognised units {series.get('units')!r}; refusing to publish"
        return out
    out["level_usd_bn"] = round(level, 1)

    _d12, v12 = _at(obs, 12)
    if v12:
        out["yoy_pct"] = round((latest / v12 - 1.0) * 100.0, 2)
    _d3, v3 = _at(obs, 3)
    if v3:
        out["three_month_annualised_pct"] = round(((latest / v3) ** 4 - 1.0) * 100.0, 2)
    out["regime"] = classify_m2(out["yoy_pct"])
    return out


def _by_date(observations) -> dict:
    return {d: v for d, v in (observations or [])}


def buffett_indicator(equities: dict, gdp: dict) -> dict:
    """Market value of US corporate equities ÷ GDP, on a quarter BOTH series cover."""
    out = {"gauge": "buffett_indicator",
           "source": f"FRED {EQUITIES_SERIES} / FRED {GDP_SERIES}",
           "as_of": None, "ratio_pct": None, "equities_usd_bn": None,
           "gdp_usd_bn": None, "error": None}
    for part in (equities, gdp):
        if part.get("error"):
            out["error"] = f"{part['series_id']}: {part['error']}"
            return out

    eq_by, gdp_by = _by_date(equities.get("observations")), _by_date(gdp.get("observations"))
    common = sorted(set(eq_by) & set(gdp_by), reverse=True)
    if not common:
        # Not a failure to explain away: the two series genuinely lag each other, and a
        # ratio built from two different quarters is a different statistic.
        out["error"] = ("no quarter is covered by both series "
                        f"({EQUITIES_SERIES} ends {max(eq_by, default='?')}, "
                        f"{GDP_SERIES} ends {max(gdp_by, default='?')})")
        return out

    quarter = common[0]
    eq_bn = to_billions(eq_by[quarter], equities.get("units"))
    gdp_bn = to_billions(gdp_by[quarter], gdp.get("units"))
    if eq_bn is None or gdp_bn is None:
        out["error"] = (f"unrecognised units (equities {equities.get('units')!r}, "
                        f"GDP {gdp.get('units')!r}); refusing to publish")
        return out
    if gdp_bn <= 0:
        out["error"] = "GDP is not positive; refusing to divide"
        return out

    out["as_of"] = quarter
    out["equities_usd_bn"] = round(eq_bn, 1)
    out["gdp_usd_bn"] = round(gdp_bn, 1)
    out["ratio_pct"] = round(eq_bn / gdp_bn * 100.0, 1)
    return out


FORWARD_PROFIT_NOTE = (
    "Index-level forward-profit horizons (3m/6m/1Y/2Y/3Y) stay NOT AVAILABLE. Forward "
    "earnings estimates are a licensed product (FactSet, LSEG, S&P) and no free, pinnable "
    "API publishes them; scraping a page that reprints them is not a pinned source. "
    "Recorded as roadmap N6 rather than estimated."
)


def build(api_key: str | None) -> dict:
    """The whole `regime` block. Each gauge carries its own error."""
    if not api_key:
        err = "api_key_fred not found; both FRED gauges unavailable"
        return {"m2": {"gauge": "m2_liquidity", "error": err},
                "buffett": {"gauge": "buffett_indicator", "error": err},
                "forward_profit_note": FORWARD_PROFIT_NOTE}
    return {
        "m2": m2_regime(fetch_series(M2_SERIES, api_key)),
        "buffett": buffett_indicator(
            fetch_series(EQUITIES_SERIES, api_key, limit=12),
            fetch_series(GDP_SERIES, api_key, limit=12)),
        "forward_profit_note": FORWARD_PROFIT_NOTE,
    }


def merge_into(block: dict, target: Path) -> Path:
    """Additive merge of `regime` into `_macro/<date>.json` — never touches `metrics`."""
    data = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data["regime"] = block
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--fetch", action="store_true", help="print JSON, write nothing")
    ap.add_argument("--update", action="store_true",
                    help="merge `regime` into _macro/<date>.json")
    ap.add_argument("--date", default=None)
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()
    if not (args.fetch or args.update):
        ap.error("one of --fetch / --update is required")

    block = build(read_api_key())
    print(json.dumps(block, indent=2))
    if args.update:
        day = args.date or date.today().isoformat()
        target = merge_into(block, Path(args.out_dir) / f"{day}.json")
        print(f"merged into {target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
