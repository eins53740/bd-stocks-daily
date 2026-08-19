"""
finalize_score.py - Recompute composite score after LLM supplies Management Quality.

Called at the end of Phase 2.5. Input is the provisional analyze_ticker JSON +
--mgmt-score X.X. Output is the finalised JSON on stdout, AND -- with --update -- written
back to --json-path.

--update exists because stdout alone was a silent failure (roadmap R21). run_daily.py runs
this node, gets rc=0, reports PASS and discards stdout: the management score never landed
and `composite_is_provisional` stayed true on the file every later node reads. The only
thing that made it work was a human remembering to redirect. Same shape as R15 and R17 --
a helper that knows the answer and a channel that drops it -- so the fix is the same as
theirs: write through the caller's own path, do not add a new one.

Only runs for deep mode. Screens never invoke this (their composite is already
final — renormalised over 6 components).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Let Python find the sibling module without forcing a package layout.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_ticker import reweighted_composite, verdict_from_composite  # noqa: E402

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def finalize(data: dict, mgmt_score: float) -> dict:
    mode = data.get("mode", "deep")
    if mode != "deep":
        # Defensive: a screen should never reach this script. Return untouched.
        data["finalize_skipped"] = "mode != deep"
        return data

    component_scores = data.get("scores", {})
    composite = reweighted_composite(component_scores, mgmt=mgmt_score, mode="deep")
    verdict = verdict_from_composite(composite)

    data["management_score"] = round(float(mgmt_score), 2)
    data["management_flag"] = mgmt_score < 7.0
    data["scores"]["management"] = round(float(mgmt_score), 2)
    data["scores"]["composite"] = composite
    data["scores"]["composite_is_provisional"] = False
    data["verdict"] = verdict
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-path", help="Path to analyze_ticker JSON; if omitted, read from stdin")
    ap.add_argument("--mgmt-score", type=float, required=True, help="Management quality score 0-10")
    ap.add_argument("--update", action="store_true",
                    help="Write the finalised JSON back to --json-path (required to persist)")
    args = ap.parse_args()

    if args.update and not args.json_path:
        print("ERROR: --update needs --json-path; there is nothing to write back to.",
              file=sys.stderr)
        return 2

    if args.json_path:
        raw = Path(args.json_path).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    data = json.loads(raw)

    if not 0.0 <= args.mgmt_score <= 10.0:
        print(f"ERROR: --mgmt-score must be in [0, 10], got {args.mgmt_score}", file=sys.stderr)
        return 2

    result = finalize(data, args.mgmt_score)
    blob = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    if args.update:
        # Written before stdout so a broken pipe cannot cost the persist.
        Path(args.json_path).write_text(blob, encoding="utf-8")
    print(blob)
    print(
        f"finalized: mgmt={args.mgmt_score}, composite={result['scores']['composite']}, "
        f"verdict={result['verdict']}, flag={result['management_flag']}"
        + (f", written to {args.json_path}" if args.update else " (stdout only, NOT persisted)"),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
