r"""
bd_paths.py - the one place that knows where things live on THIS machine.

WHY THIS EXISTS
---------------
The two machines that run this skill family do not share a layout:

    laptop   BD_Finance at  C:\Github\BD\Finance\BD_Finance   vault at C:\BD_Obsidian\...
    vmhost1  BD_Finance at  D:\Github\BD\BD_Finance            vault at D:\BD_Obsidian\...

and `C:\Github\BD` does not exist on vmhost1 at all -- verified 2026-08-18 from a LOCAL
context on that machine, not over SSH (the distinction matters: a network logon cannot
traverse the junctions there and reports False for paths that a local process resolves
fine, so an SSH probe alone proves nothing either way).

Two consequences already cost production:
  * technical_score.py's five imports raised ModuleNotFoundError on vmhost1, so Phase 3.5
    (technical score + GO/NO-GO) was silently failing on the machine that runs the pipeline;
  * run_daily.py's subprocess cwd did not exist there, making the orchestrator a no-op.
Both were fixed in place, each growing its own private resolution list. A third and a fourth
followed. Four near-identical copies of the same six lines is the same fix written four
times, and the fifth time this bites will be somewhere else -- so it lives here now.

The quiet failure mode this protects against: `api_keys_reader()` on a missing file returns
an EMPTY DICT and merely prints a warning. So a dead BD_Finance path does not raise -- it
yields no FRED key, no Alpha Vantage key, no SMTP password, and the run continues looking
healthy while losing data. That is why these resolvers return None rather than a hopeful
default, and why callers must handle None.

RESOLUTION ORDER, always: explicit env var -> the known roots, probing for a file that
proves the layout (a directory that merely exists proves nothing). Same order as
scripts/skills_root.py, deliberately.

Env overrides:  BD_FINANCE_DIR  BD_FINANCE_PARENT  BD_VAULT_STATE
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["bd_finance", "bd_finance_parent", "api_keys_path", "vault_state", "bankbd_db"]

# Ordered laptop-first: it is the interactive machine, so a human running a script by hand
# hits its own layout on the first probe.
_FINANCE_ROOTS = (Path(r"C:\Github\BD\Finance\BD_Finance"), Path(r"D:\Github\BD\BD_Finance"))
_FINANCE_PARENTS = (Path(r"C:\Github\BD\Finance"), Path(r"D:\Github\BD"))
_VAULT_STATES = (Path(r"C:\BD_Obsidian\Personal\Finance\StocksDaily"),
                 Path(r"D:\BD_Obsidian\Personal\Finance\StocksDaily"))


def _from_env(var: str, proof: str | None = None) -> Path | None:
    raw = os.environ.get(var)
    if not raw:
        return None
    p = Path(raw)
    # A stale env var must not be able to break the run: it is ignored, not obeyed. Same rule
    # skills_root.py applies, for the same reason -- one wrong variable should not take out
    # ten scheduled jobs at once.
    ok = (p / proof).exists() if proof else p.is_dir()
    return p if ok else None


def _first(candidates, proof: str) -> Path | None:
    return next((p for p in candidates if p and (p / proof).exists()), None)


def bd_finance() -> Path | None:
    """The BD_Finance package directory, or None if this machine has neither layout.

    Proof file: config/api_keys.txt -- the thing callers actually want from it."""
    return _from_env("BD_FINANCE_DIR", "config/api_keys.txt") or _first(_FINANCE_ROOTS, "config/api_keys.txt")


def bd_finance_parent() -> Path | None:
    """The directory to put on sys.path so `import BD_Finance.technical.rsi` resolves.

    Proof file: BD_Finance/technical/rsi.py -- i.e. a module that is really imported."""
    return (_from_env("BD_FINANCE_PARENT", "BD_Finance/technical/rsi.py")
            or _first(_FINANCE_PARENTS, "BD_Finance/technical/rsi.py"))


def api_keys_path() -> Path | None:
    """Full path to config/api_keys.txt, or None. Callers MUST handle None: passing a
    non-existent path to api_keys_reader() gets an empty dict and a printed warning, which
    reads as 'no keys configured' rather than as the error it is."""
    root = bd_finance()
    return (root / "config" / "api_keys.txt") if root else None


def vault_state() -> Path | None:
    """The StocksDaily state directory in the Obsidian vault (_log.csv, reports, IMG, caches).

    Proof file: _log.csv."""
    return _from_env("BD_VAULT_STATE", "_log.csv") or _first(_VAULT_STATES, "_log.csv")


def bankbd_db() -> Path | None:
    """The BankBD sqlite database, or None. Its parent differs per machine the same way."""
    for parent in (p for p in (_from_env("BD_FINANCE_PARENT"),) + _FINANCE_PARENTS if p):
        db = parent / "BankBD" / "bankbd.db"
        if db.exists():
            return db
    return None


if __name__ == "__main__":
    for fn in (bd_finance, bd_finance_parent, api_keys_path, vault_state, bankbd_db):
        print(f"{fn.__name__:<20} {fn()}")
