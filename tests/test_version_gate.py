"""
Unit tests for v4.1 roadmap item 10 — version_gate.py.

The report-version flag `--version {v3, v4}`: latest is always the default, v3 skips
exactly the v4 overlay nodes, and the composite-bearing keys are never gated (the
byte-identical guarantee).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import version_gate as vg  # noqa: E402


# ------------------------- latest-is-default (dynamic rule) -------------------------
def test_latest_is_last_version():
    assert vg.LATEST == vg.VERSIONS[-1]  # rule, not a hard-coded value


def test_resolve_defaults_to_latest():
    assert vg.resolve_version(None) == vg.LATEST
    assert vg.resolve_version("") == vg.LATEST
    assert vg.resolve_version("v9") == vg.LATEST      # unknown → latest
    assert vg.resolve_version("bogus") == vg.LATEST


def test_resolve_accepts_bare_and_prefixed():
    assert vg.resolve_version("v3") == "v3"
    assert vg.resolve_version("3") == "v3"            # bare number tolerated
    assert vg.resolve_version("V4") == "v4"           # case-insensitive


def test_is_known():
    assert vg.is_known(None) and vg.is_known("v3") and vg.is_known("v4")
    assert not vg.is_known("v2") and not vg.is_known("v1")   # pre-schema-2.2, not via flag


# ------------------------- node skipping -------------------------
def test_v4_skips_nothing():
    assert vg.nodes_to_skip("v4") == []
    assert vg.nodes_to_skip(None) == []               # default = latest = full run


def test_v3_skips_all_v4_overlays():
    skip = vg.nodes_to_skip("v3")
    scripts = {n["script"] for n in skip}
    assert scripts == {"valuation_bands.py", "intrinsic_value.py", "red_flags.py",
                       "exit_plan.py", "alpha_beta.py", "watchlist.py",
                       "second_opinion.py", "news_sentiment.py", "render_report.py"}
    nodes = {n["node"] for n in skip}
    assert nodes == {"2.3", "2.4", "2.55", "2.56", "2.57", "2.58", "2.59", "5.7"}


def test_v3_overlay_keys_absent():
    keys = vg.overlay_keys_absent("v3")
    assert set(keys) == {"valuation_bands", "intrinsic_value", "red_flags", "exit_plan",
                         "alpha_beta", "opinion_panel", "news_sentiment"}
    # watchlist / render_report have no additive JSON key
    assert "watchlist" not in keys and "render_report" not in keys


# ------------------------- composite byte-identical guarantee -------------------------
def test_composite_bearing_keys_never_gated():
    gated = set(vg.overlay_keys_absent("v3"))
    assert not (gated & vg.PROTECTED_KEYS)            # scores/verdict/top_strip never skipped


# ------------------------- gate() summary -------------------------
def test_gate_v3_summary():
    g = vg.gate("v3")
    assert g["version"] == "v3" and g["is_latest"] is False and g["known"] is True
    assert "2.59" in g["skip_nodes"] and "news_sentiment" in g["skip_json_keys"]


def test_gate_default_is_latest_full():
    g = vg.gate(None)
    assert g["version"] == vg.LATEST and g["is_latest"] is True
    assert g["skip_nodes"] == [] and g["skip_json_keys"] == []
