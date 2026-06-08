"""Run finalize_score.py and overwrite the _tmp JSON with the result."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-path", required=True)
    ap.add_argument("--mgmt-score", type=float, required=True)
    args = ap.parse_args()

    script = Path(__file__).parent / "finalize_score.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--json-path", args.json_path, "--mgmt-score", str(args.mgmt_score)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print(f"FAIL exit={proc.returncode} stderr={proc.stderr[:500]}", file=sys.stderr)
        sys.exit(proc.returncode)

    m = re.search(r"\{[\s\S]*\}", proc.stdout)
    if not m:
        print("FAIL no JSON in output", file=sys.stderr)
        sys.exit(1)

    data = json.loads(m.group(0))
    Path(args.json_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"OK saved finalized JSON: composite={data['scores']['composite']} verdict={data['verdict']} mgmt={data['management_score']}")


if __name__ == "__main__":
    main()
