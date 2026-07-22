"""
Unit tests for render_charts.validate_segments — the pure schema validator for
the _segments/<TICKER>.json contract consumed by chart_revenue_segments.

Network-free: importing render_charts sets matplotlib's Agg backend at module
load (no display needed) and pulls in the sibling technical_score constants.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from render_charts import validate_segments  # noqa: E402


def _valid() -> dict:
    return {
        "fiscal_years": ["FY2023", "FY2024", "FY2025"],
        "currency": "USD",
        "segments": [
            {"name": "Data Center", "values": [15000.0, 47500.0, 115000.0]},
            {"name": "Gaming", "values": [9000.0, 10400.0, None]},
        ],
        "source_url": "https://example.com/10-k",
        "extracted_at": "2026-07-15T00:00:00Z",
    }


def test_valid_dict_returns_empty():
    assert validate_segments(_valid()) == []


def test_valid_without_optional_metadata():
    d = _valid()
    del d["currency"]
    del d["source_url"]
    del d["extracted_at"]
    # Cosmetic keys are optional — still valid for charting.
    assert validate_segments(d) == []


def test_not_a_dict():
    assert validate_segments(["nope"]) == ["not a dict"]


def test_missing_required_keys():
    problems = validate_segments({})
    assert any("missing key: fiscal_years" in p for p in problems)
    assert any("missing key: segments" in p for p in problems)


def test_fiscal_years_wrong_length():
    d = _valid()
    d["fiscal_years"] = ["FY2024", "FY2025"]
    problems = validate_segments(d)
    assert any("fiscal_years must be a list of length 3" in p for p in problems)


def test_empty_segments():
    d = _valid()
    d["segments"] = []
    problems = validate_segments(d)
    assert any("segments must be a non-empty list" in p for p in problems)


def test_segment_missing_name():
    d = _valid()
    d["segments"][0].pop("name")
    problems = validate_segments(d)
    assert any("segment[0] missing name" in p for p in problems)


def test_segment_values_wrong_length():
    d = _valid()
    d["segments"][1]["values"] = [1.0, 2.0]
    problems = validate_segments(d)
    assert any("segment[1] values must be a list of length 3" in p for p in problems)


def test_segment_values_non_numeric():
    d = _valid()
    d["segments"][0]["values"] = [1.0, "big", None]
    problems = validate_segments(d)
    assert any("segment[0].values[1] not numeric-or-null" in p for p in problems)
