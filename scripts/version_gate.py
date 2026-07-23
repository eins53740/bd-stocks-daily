"""
version_gate.py — v4.1 roadmap item 10: the `--version {v3, v4}` report-version gate.

The skill can be run at an earlier *report version* alongside `--ticker` / `--mode`.
Because v4 is **overlay-only on schema 2.2** (the same schema v3.1 used), "v3" is
exactly "v4 minus the v4 overlay nodes". The **deterministic** composite inputs
(gates, Piotroski, Altman, valuation, peer, growth, market) are identical in both,
so the score is materially unchanged. Caveat: the 8%-weight **management** component
is LLM-sourced from the analysis JSON, which carries the overlay blocks under v4 but
not v3 — so the composite is *materially*, not *bitwise*, identical (the LLM mgmt
read is non-deterministic run-to-run anyway). Only which overlay cards render changes.

The **latest shipped version is always the default** — a rule, not a hard-coded
value: `LATEST = VERSIONS[-1]`. When a new report version ships, append it to
`VERSIONS` and the default follows automatically. The enum starts at `v3`: v1/v2
predate schema 2.2 (different composite weights + gate set) and are reachable only
via git tags + worktrees, never this flag.

This module is the single source of truth the SKILL.md orchestrator reads to decide
which Phase-2.x / 5.7 overlay nodes to SKIP for a given `--version`. Pure stdlib.
"""
from __future__ import annotations

import argparse
import json
import sys

# Ordered oldest → newest. The default is always the last entry.
VERSIONS = ["v3", "v4"]
LATEST = VERSIONS[-1]

# The v4 overlay nodes — everything v4 added on top of the v3.1 report shape. Running
# `--version v3` skips exactly these; the resulting analysis JSON carries none of the
# `json_key`s below, and the report falls back to the v3.1 markdown-primary shape.
# NB: none of these feeds the composite (that is computed at node 2 + finalize_score),
# so the 0-10 score is identical with or without them — the overlay-only invariant.
V4_OVERLAY_NODES = [
    {"node": "2.3", "script": "valuation_bands.py", "json_key": "valuation_bands"},
    {"node": "2.3", "script": "intrinsic_value.py", "json_key": "intrinsic_value"},
    {"node": "2.4", "script": "red_flags.py", "json_key": "red_flags"},
    {"node": "2.55", "script": "exit_plan.py", "json_key": "exit_plan"},
    {"node": "2.56", "script": "alpha_beta.py", "json_key": "alpha_beta"},
    {"node": "2.57", "script": "watchlist.py", "json_key": None},  # writes _watchlist.csv, no JSON key
    {"node": "2.58", "script": "second_opinion.py", "json_key": "opinion_panel"},
    {"node": "2.59", "script": "news_sentiment.py", "json_key": "news_sentiment"},
    {"node": "5.7", "script": "render_report.py", "json_key": None},  # HTML render + metric families
]

# Composite-bearing keys that must NEVER be gated. (top_strip is a *display* strip,
# not a composite input — alpha_beta legitimately augments it with overlay-only β/α;
# so it is deliberately NOT protected here.)
PROTECTED_KEYS = {"scores", "verdict", "gates_detail"}


def resolve_version(arg: str | None) -> str:
    """Normalise the flag to a known version. None / empty / unknown → LATEST."""
    if arg is None:
        return LATEST
    v = str(arg).strip().lower()
    if not v.startswith("v"):
        v = "v" + v
    return v if v in VERSIONS else LATEST


def is_known(arg: str | None) -> bool:
    if arg is None:
        return True
    v = str(arg).strip().lower()
    if not v.startswith("v"):
        v = "v" + v
    return v in VERSIONS


def nodes_to_skip(version: str | None) -> list[dict]:
    """The overlay nodes to SKIP for this version. Empty for the latest (full run)."""
    v = resolve_version(version)
    if v == "v4":
        return []
    if v == "v3":
        return list(V4_OVERLAY_NODES)
    return []  # any future version defaults to the full run


def overlay_keys_absent(version: str | None) -> list[str]:
    """The additive JSON keys that must be ABSENT from the analysis JSON for `version`
    (used by the regression test to prove a v3 run drops every overlay)."""
    return sorted({n["json_key"] for n in nodes_to_skip(version) if n["json_key"]})


def gate(version: str | None) -> dict:
    v = resolve_version(version)
    skip = nodes_to_skip(v)
    return {
        "requested": version,
        "version": v,
        "is_latest": v == LATEST,
        "known": is_known(version),
        "skip_nodes": sorted({n["node"] for n in skip}),
        "skip_scripts": [n["script"] for n in skip],
        "skip_json_keys": overlay_keys_absent(v),
        "note": ("full pipeline (latest)" if not skip
                 else f"v3.1 report shape — skips {len(skip)} v4 overlay nodes; composite identical"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve the --version report gate (v3|v4, default latest)")
    ap.add_argument("--version", default=None, help="v3 | v4 (default: latest = %s)" % LATEST)
    ap.add_argument("--list", action="store_true", help="list known versions and exit")
    args = ap.parse_args()
    if args.list:
        print(json.dumps({"versions": VERSIONS, "latest": LATEST}, indent=2))
        return 0
    print(json.dumps(gate(args.version), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
