"""Run analyze_ticker.py via subprocess, extract the JSON block, write it to _tmp."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--mode", required=True, choices=["deep", "screen"])
    ap.add_argument("--date", required=True)
    ap.add_argument("--out-dir", default=r"C:\BD_Obsidian\Personal\Finance\StocksDaily\_tmp")
    args = ap.parse_args()

    script = Path(__file__).parent / "analyze_ticker.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--ticker", args.ticker, "--mode", args.mode],
        cwd=r"C:\Github\BD\Finance\BD_Finance",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = proc.stdout
    if not out:
        print(f"FAIL no stdout. stderr={proc.stderr[:500]}", file=sys.stderr)
        sys.exit(1)

    # Find the JSON object spanning {...} — greedy match from first { to last }
    m = re.search(r"\{[\s\S]*\}", out)
    if not m:
        print(f"FAIL no JSON in output. head={out[:300]}", file=sys.stderr)
        sys.exit(1)

    blob = m.group(0)
    data = json.loads(blob)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = args.ticker.replace("/", "_").replace("\\", "_")
    out_path = out_dir / f"{args.date}_{safe}.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # analyze_ticker exits 1 and prints {"error": ...} when it refuses to score -- notably the
    # throttle gate that stops a rate-limited (429) fetch being scored as a real "reject". That
    # JSON parses perfectly, so without this check the artifact was written, "OK wrote ..." was
    # printed with composite=None, and this process exited 0: the gate was fully neutralised on
    # the daily path while still working for the prefilter and growth ones. The blob is kept on
    # disk for diagnosis, but the exit code must say the analysis did NOT happen.
    if proc.returncode != 0 or "error" in data:
        print(f"FAIL analyze_ticker rc={proc.returncode} ticker={args.ticker} "
              f"error={data.get('error')}", file=sys.stderr)
        sys.exit(2)

    print(f"OK wrote {out_path}")
    print(f"   composite={data.get('scores',{}).get('composite')} verdict={data.get('verdict')} gates={data.get('gates_passed')}/7")


if __name__ == "__main__":
    main()
