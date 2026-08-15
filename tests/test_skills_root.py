"""Tests for the Wave 5 path indirection.

30 files hard-code the skills path and three of them COUPLE IN-PROCESS
(`run_prefilter` imports `analyze_ticker`, `growth_analyze` shells out to it,
`pick_earnings_review_targets` imports `listings.REGISTRY`). Installed plugins live in
VERSIONED directories, so a path baked in today breaks on the next version bump. These
pin the one property that makes the change safe to land before the cutover: **with
nothing configured, it resolves exactly where it did before.**
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import skills_root as sr  # noqa: E402


def test_an_unconfigured_machine_resolves_where_it_always_did(monkeypatch):
    monkeypatch.delenv(sr.ENV_VAR, raising=False)
    assert (sr.skills_root() / "bd-stocks-daily").is_dir()
    assert sr.script("bd-stocks-daily", "analyze_ticker.py").is_file()


def test_the_env_var_wins_when_it_points_somewhere_real(tmp_path, monkeypatch):
    (tmp_path / "bd-stocks-daily" / "scripts").mkdir(parents=True)
    monkeypatch.setenv(sr.ENV_VAR, str(tmp_path))
    assert sr.skills_root() == tmp_path
    assert sr.scripts_dir("bd-stocks-daily") == tmp_path / "bd-stocks-daily" / "scripts"


def test_an_env_var_pointing_nowhere_is_ignored_rather_than_obeyed(monkeypatch):
    """A stale variable must not be able to break every scheduled job at once."""
    monkeypatch.setenv(sr.ENV_VAR, r"C:\this\does\not\exist")
    assert (sr.skills_root() / "bd-stocks-daily").is_dir()


def test_the_resolution_is_reportable_so_a_wrong_root_shows_up_early(monkeypatch):
    monkeypatch.delenv(sr.ENV_VAR, raising=False)
    rep = sr.resolution_report()
    assert rep["exists"] is True
    assert rep["reason"]
    json.dumps(rep)          # must be loggable as-is


def test_the_report_does_not_cry_legacy_on_an_unmoved_install(monkeypatch):
    """Derived and legacy are the SAME path on an unmoved install; reporting 'legacy
    fallback' there would suggest the indirection is not working when it is."""
    monkeypatch.delenv(sr.ENV_VAR, raising=False)
    assert sr.resolution_report()["reason"] == "derived from this file's location"


@pytest.mark.parametrize("module,attr", [
    ("run_prefilter", "DAILY_SCRIPTS"),
    ("run_prefilter", "GROWTH_SCRIPTS"),
])
def test_the_prefilter_coupling_points_resolve(module, attr):
    sys.path.insert(0, str(SCRIPTS.parent.parent / "bd-stocks-prefilter" / "scripts"))
    mod = __import__(module)
    assert getattr(mod, attr).is_dir()


def test_the_growth_subprocess_target_resolves():
    sys.path.insert(0, str(SCRIPTS.parent.parent / "bd_stocks_daily_growth" / "scripts"))
    import growth_analyze  # noqa: PLC0415
    assert growth_analyze.DAILY_ANALYZE.is_file()


def test_the_plugin_manifest_is_valid_and_lists_every_skill():
    manifest = SCRIPTS.parent.parent / "bd-finance" / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["version"] == "4.3.0"
    for skill in data["skills"]:
        assert (SCRIPTS.parent.parent / skill).is_dir(), f"{skill} does not exist"
    assert "bd-stocks-monitor" in data["skills"]


def test_the_local_marketplace_points_at_the_plugin():
    mk = SCRIPTS.parent.parent / "bd-finance" / ".claude-plugin" / "marketplace.json"
    data = json.loads(mk.read_text(encoding="utf-8"))
    assert data["plugins"][0]["name"] == "bd-finance"
