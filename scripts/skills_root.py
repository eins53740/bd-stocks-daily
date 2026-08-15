"""skills_root.py — one place that knows where the skills live (v4.3 wave 5).

**30 files across three skills and `C:\\Github\\.scripts\\` hard-code
`C:\\Users\\bsdias\\.claude\\skills\\bd-...`.** Three of them are worse than a path
constant: `run_prefilter.py` **imports `analyze_ticker` in-process**, `growth_analyze.py`
shells out to it by absolute path, and `pick_earnings_review_targets.py` imports
`listings.REGISTRY`. Move a module and the weekly pool build breaks — silently, on a
Monday, which is exactly the ten-week frozen-bat failure `SCHEDULING.md` records.

Wave 5 packages these skills as a plugin. Installed plugins live in **versioned**
directories (`...\\equity-research\\0.1.2\\`), so any path baked in today breaks on the
next version bump. This module is the indirection that has to exist first.

RESOLUTION ORDER, and the fallback is the point:

  1. `%BD_SKILLS_ROOT%` if set and it exists;
  2. the parent of the directory containing this file (so a skill that moves *together*
     with its siblings needs no configuration at all);
  3. the current absolute path, hard-coded — **so behaviour today is unchanged**.

Introducing this changes nothing about how the system runs right now. That is deliberate:
the cutover is a separate, reversible step, taken behind a green run of every scheduled
job from the packaged location, and it is not made by installing this file.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "BD_SKILLS_ROOT"

#: The path everything used before this module existed. Retained as the last resort so
#: that an unconfigured machine behaves exactly as it did.
LEGACY_ROOT = Path(r"C:\Users\bsdias\.claude\skills")


def skills_root() -> Path:
    """The directory that contains `bd-stocks-daily`, `bd-stocks-prefilter`, ..."""
    env = os.environ.get(ENV_VAR)
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    here = Path(__file__).resolve()
    # .../<root>/bd-stocks-daily/scripts/skills_root.py -> <root>
    candidate = here.parent.parent.parent
    if (candidate / "bd-stocks-daily").is_dir():
        return candidate
    return LEGACY_ROOT


def skill_dir(name: str) -> Path:
    return skills_root() / name


def scripts_dir(name: str) -> Path:
    return skill_dir(name) / "scripts"


def script(name: str, filename: str) -> Path:
    return scripts_dir(name) / filename


def resolution_report() -> dict:
    """What resolved, and why — for a startup log line, so a wrong root is visible on
    the first run rather than on the first failure."""
    env = os.environ.get(ENV_VAR)
    root = skills_root()
    derived = Path(__file__).resolve().parent.parent.parent
    if env and Path(env).is_dir():
        why = f"{ENV_VAR}={env}"
    elif (derived / "bd-stocks-daily").is_dir():
        # Checked BEFORE comparing against LEGACY_ROOT: on an unmoved install the two
        # are the same path, and reporting "legacy fallback" there would suggest the
        # indirection is not working when it is.
        why = "derived from this file's location"
    else:
        why = "legacy absolute fallback (unconfigured — this is the pre-v4.3 behaviour)"
    return {"root": str(root), "reason": why,
            "daily": str(scripts_dir("bd-stocks-daily")),
            "exists": (root / "bd-stocks-daily").is_dir()}


if __name__ == "__main__":
    import json
    print(json.dumps(resolution_report(), indent=2))
