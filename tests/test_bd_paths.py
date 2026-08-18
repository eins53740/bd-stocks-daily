"""Tests for bd_paths.py -- the per-machine path resolver (roadmap R11).

The behaviour that matters is not "does it find the path on this laptop" but the two rules
that stop it becoming a new failure mode: a STALE env var must be ignored rather than obeyed
(one wrong variable must not take out ten scheduled jobs), and an unresolvable layout must
return None rather than a hopeful default, because api_keys_reader() answers a missing file
with an empty dict and a printed warning -- which reads as "no keys configured" instead of
as the error it is.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _fresh():
    """A fresh module each time: the resolvers read os.environ at call time, but importing
    once and mutating the root tuples across tests would leak between them."""
    spec = importlib.util.spec_from_file_location("bd_paths_under_test", SCRIPTS / "bd_paths.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mod():
    return _fresh()


def _fake_finance(root: Path) -> Path:
    d = root / "BD_Finance"
    (d / "config").mkdir(parents=True)
    (d / "config" / "api_keys.txt").write_text("api_key_x = 1\n", encoding="utf-8")
    (d / "technical").mkdir()
    (d / "technical" / "rsi.py").write_text("# rsi\n", encoding="utf-8")
    return d


def test_env_var_wins_when_it_proves_out(mod, tmp_path, monkeypatch):
    d = _fake_finance(tmp_path)
    monkeypatch.setenv("BD_FINANCE_DIR", str(d))
    assert mod.bd_finance() == d
    assert mod.api_keys_path() == d / "config" / "api_keys.txt"


def test_stale_env_var_is_ignored_not_obeyed(mod, tmp_path, monkeypatch):
    """A path that exists but is NOT a BD_Finance dir must not be accepted."""
    empty = tmp_path / "moved-away"
    empty.mkdir()
    monkeypatch.setenv("BD_FINANCE_DIR", str(empty))
    monkeypatch.setattr(mod, "_FINANCE_ROOTS", ())
    assert mod.bd_finance() is None, "an env var pointing at the wrong dir must not win"


def test_env_var_pointing_nowhere_is_ignored(mod, tmp_path, monkeypatch):
    monkeypatch.setenv("BD_FINANCE_DIR", str(tmp_path / "does-not-exist"))
    monkeypatch.setattr(mod, "_FINANCE_ROOTS", ())
    assert mod.bd_finance() is None


def test_roots_are_probed_in_order_and_the_first_proven_one_wins(mod, tmp_path, monkeypatch):
    second = _fake_finance(tmp_path / "b")
    monkeypatch.delenv("BD_FINANCE_DIR", raising=False)
    monkeypatch.setattr(mod, "_FINANCE_ROOTS", (tmp_path / "a" / "BD_Finance", second))
    assert mod.bd_finance() == second, "an absent first root must fall through, not fail"


def test_returns_none_when_no_layout_matches(mod, monkeypatch):
    for var in ("BD_FINANCE_DIR", "BD_FINANCE_PARENT", "BD_VAULT_STATE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(mod, "_FINANCE_ROOTS", ())
    monkeypatch.setattr(mod, "_FINANCE_PARENTS", ())
    monkeypatch.setattr(mod, "_VAULT_STATES", ())
    assert mod.bd_finance() is None
    assert mod.bd_finance_parent() is None
    assert mod.vault_state() is None
    assert mod.api_keys_path() is None, "no root means no keys path -- never a hopeful default"


def test_parent_probes_the_module_actually_imported(mod, tmp_path, monkeypatch):
    """A directory that merely exists proves nothing: the proof is BD_Finance/technical/rsi.py,
    which is what technical_score.py imports."""
    bare = tmp_path / "bare"
    (bare / "BD_Finance").mkdir(parents=True)
    good = tmp_path / "good"
    _fake_finance(good)
    monkeypatch.delenv("BD_FINANCE_PARENT", raising=False)
    monkeypatch.setattr(mod, "_FINANCE_PARENTS", (bare, good))
    assert mod.bd_finance_parent() == good


def test_vault_state_is_proved_by_the_log_file(mod, tmp_path, monkeypatch):
    bare = tmp_path / "no-log"
    bare.mkdir()
    real = tmp_path / "real"
    real.mkdir()
    (real / "_log.csv").write_text("ticker,date\n", encoding="utf-8")
    monkeypatch.delenv("BD_VAULT_STATE", raising=False)
    monkeypatch.setattr(mod, "_VAULT_STATES", (bare, real))
    assert mod.vault_state() == real


def test_bankbd_db_follows_the_same_per_machine_parent(mod, tmp_path, monkeypatch):
    parent = tmp_path / "p"
    (parent / "BankBD").mkdir(parents=True)
    db = parent / "BankBD" / "bankbd.db"
    db.write_bytes(b"")
    monkeypatch.delenv("BD_FINANCE_PARENT", raising=False)
    monkeypatch.setattr(mod, "_FINANCE_PARENTS", (tmp_path / "absent", parent))
    assert mod.bankbd_db() == db


def test_this_machine_resolves_every_path(mod):
    """Not a unit test -- a canary. If the laptop itself stops resolving, every converted
    script silently falls back to its old literal and the point of R11 is lost."""
    assert mod.bd_finance() is not None
    assert mod.vault_state() is not None


# --- R11 residual: no private resolution lists left in the skill ---------------------

def test_no_module_keeps_its_own_path_candidate_list():
    """Three near-identical lists existed in one skill, and the copy in _run_and_save.py was
    a LIVE FATAL BUG on vmhost1 while the other two were already fixed -- every deep and
    screen died at node 2 on 2026-08-18 because subprocess.run got a cwd that does not exist
    there. That asymmetry is the whole argument for one resolver."""
    from pathlib import Path
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    for name in ("_run_and_save.py", "run_daily.py", "technical_score.py"):
        src = (scripts / name).read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        assert "bd_paths" in src, f"{name} must go through the shared resolver"
        # A literal is allowed ONLY as an `or`-fallback, never as the primary lookup.
        assert 'cwd=r"C:' + chr(92) + 'Github' not in code,             f"{name} still hardcodes a subprocess cwd"
        assert 'os.environ["BD_FINANCE_PARENT"]' not in code, \
            f"{name} still reads the env var directly instead of via bd_paths"


def test_run_daily_resolves_both_roots_on_this_machine():
    # Plain import, not spec_from_file_location: run_daily uses `from __future__ import
    # annotations` with @dataclass, and dataclasses resolves the string annotations through
    # sys.modules -- a module loaded by spec alone is not there yet and the decorator raises.
    import sys
    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import run_daily as rd
    assert rd.CWD.is_dir(), "the launch directory must exist on whatever machine runs this"
    assert (rd.CWD / "config" / "api_keys.txt").exists(), "and must be the real BD_Finance"
    assert rd.OUT_DIR.is_dir()
