"""Exactly one process may send the digest on a scheduled run.

The send-once ledger shipped on 2026-07-29 and Bruno still got two digests that evening. The
ledger was not bypassed by accident -- it was overridden on purpose:

  17:26  the quality skill sent the digest ITSELF, logging "Sent manually at 17:27 since this was
         an interactive invocation" while running under `claude -p`;
  17:38  the growth lens wrote its reports -- after that email had already gone;
  17:42  the growth lens re-sent with --force so the Growth section would render;
  17:46  the bat's send was correctly refused by the ledger.

Two emails, one Message-ID (Gmail delivered both -- a repeated Message-ID does NOT suppress
delivery on this route, which was measured, not assumed). The root cause is that SKILL.md asked
the model to work out whether it was on the scheduled or the manual path. It cannot: it concluded
"interactive" while headless. So ownership is now carried by an inherited env var that the parent
process sets, and these tests pin the consequences.

The two tests that would have caught the real incident are
test_skill_send_on_scheduled_path_is_refused and test_force_cannot_lift_the_ownership_guard.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import send_email as se  # noqa: E402


class _FakeSMTP:
    """Records every transaction opened, so "did anything get sent" is answerable exactly."""

    transactions: list = []

    def __init__(self, host, port, timeout=None):
        _FakeSMTP.transactions.append({"host": host, "port": port})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, pwd):
        _FakeSMTP.transactions[-1]["login"] = user

    def sendmail(self, sender, recipients, body):
        _FakeSMTP.transactions[-1].update(
            sender=sender, recipients=list(recipients), body=body
        )


@pytest.fixture
def smtp(tmp_path, monkeypatch):
    """main() wired to send nowhere, with a clean env and a temp ledger."""
    _FakeSMTP.transactions = []

    fake_smtplib = types.ModuleType("smtplib")
    fake_smtplib.SMTP_SSL = _FakeSMTP
    monkeypatch.setitem(sys.modules, "smtplib", fake_smtplib)

    fake_keys = types.ModuleType("api_keys_reader")
    fake_keys.api_keys_reader = lambda _p: {"password_bfsd": "not-a-real-password"}
    monkeypatch.setitem(sys.modules, "api_keys_reader", fake_keys)

    monkeypatch.setattr(se, "regenerate_dashboard", lambda: None)
    monkeypatch.setattr(se, "load_for_date", lambda d: [])
    monkeypatch.setattr(se, "SENT_INDEX", tmp_path / "_email_sent.json")
    monkeypatch.setattr(se, "DASHBOARD", tmp_path / "absent_dashboard.html")
    # Hermetic: never inherit the real scheduled flag from whatever shell runs pytest.
    monkeypatch.delenv(se.SCHEDULED_ENV, raising=False)
    return _FakeSMTP


def run(monkeypatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["send_email.py", "--date", "2026-07-29", *args])
    return se.main()


# --------------------------------------------------------------- not_email_owner (unit)

def test_manual_path_is_always_allowed(smtp):
    assert se.not_email_owner(scheduled_sender=False) is None


def test_scheduled_run_without_the_flag_is_refused(smtp, monkeypatch):
    monkeypatch.setenv(se.SCHEDULED_ENV, "1")
    reason = se.not_email_owner(scheduled_sender=False)
    assert reason and "scheduled-sender" in reason


def test_scheduled_run_with_the_flag_is_allowed(smtp, monkeypatch):
    monkeypatch.setenv(se.SCHEDULED_ENV, "1")
    assert se.not_email_owner(scheduled_sender=True) is None


def test_empty_env_value_counts_as_unset(smtp, monkeypatch):
    """`set STOCKSDAILY_SCHEDULED=` in a bat clears the flag; that must read as manual."""
    monkeypatch.setenv(se.SCHEDULED_ENV, "")
    assert se.not_email_owner(scheduled_sender=False) is None


# --------------------------------------------------------------- main() behaviour

def test_skill_send_on_scheduled_path_is_refused(smtp, monkeypatch):
    """The 17:27 send. A skill spawns send_email.py with no flags; nothing may leave."""
    monkeypatch.setenv(se.SCHEDULED_ENV, "1")
    assert run(monkeypatch) == 0
    assert smtp.transactions == [], "no SMTP transaction may be opened"


def test_force_cannot_lift_the_ownership_guard(smtp, monkeypatch):
    """The 17:42 send -- the duplicate that actually reached the inbox.

    --force is documented as overriding the LEDGER. It must not override ownership, or the
    escape hatch re-opens the exact hole it was used to walk through.
    """
    monkeypatch.setenv(se.SCHEDULED_ENV, "1")
    assert run(monkeypatch, "--force") == 0
    assert smtp.transactions == [], "--force must not send on a non-owner scheduled call"


def test_the_bat_can_still_send(smtp, monkeypatch):
    monkeypatch.setenv(se.SCHEDULED_ENV, "1")
    assert run(monkeypatch, "--scheduled-sender") == 0
    assert len(smtp.transactions) == 1
    assert smtp.transactions[0]["recipients"] == se.RECIPIENTS


def test_manual_run_still_emails_the_user(smtp, monkeypatch):
    """A hand-run deep dive must keep sending -- that is the behaviour Bruno relies on."""
    assert run(monkeypatch) == 0
    assert len(smtp.transactions) == 1


def test_refusal_is_not_a_failure(smtp, monkeypatch, capsys):
    """Exit 0 + machine-readable reason: a blocked send must not fail the skill's run."""
    monkeypatch.setenv(se.SCHEDULED_ENV, "1")
    assert run(monkeypatch) == 0
    payload = capsys.readouterr().out
    assert '"skipped": "not_email_owner"' in payload
    assert '"email_sent": false' in payload


def test_a_refused_call_does_not_consume_the_date(smtp, monkeypatch):
    """Critical ordering property: the blocked skill call must leave the ledger untouched, or the
    bat's later send would be refused as a duplicate and the digest would never arrive."""
    monkeypatch.setenv(se.SCHEDULED_ENV, "1")
    run(monkeypatch)
    assert se.load_sent_index() == {}, "a send that never happened must not be recorded"
    assert run(monkeypatch, "--scheduled-sender") == 0
    assert len(smtp.transactions) == 1, "the bat still gets its one send"


def test_dry_run_is_unaffected_by_ownership(smtp, monkeypatch, capsys):
    monkeypatch.setenv(se.SCHEDULED_ENV, "1")
    assert run(monkeypatch, "--dry-run") == 0
    assert "SUBJECT:" in capsys.readouterr().out
    assert smtp.transactions == [], "dry-run never sends regardless"


# --------------------------------------------------------------- full replay

def test_replay_of_the_2026_07_29_evening(smtp, monkeypatch):
    """The three calls that produced two emails, in order. Now exactly one gets through, and it
    is the last one -- the bat's -- which is the only one that can see the growth reports."""
    monkeypatch.setenv(se.SCHEDULED_ENV, "1")

    run(monkeypatch)                          # 17:27 quality skill, "interactive invocation"
    run(monkeypatch, "--force")               # 17:42 growth lens, forcing a complete digest
    monkeypatch.setattr(                      # by now the growth rows exist on disk
        se, "load_for_date",
        lambda d: [{"ticker": "ALAB", "date": d, "verdict": "watch", "composite": "7.1"}],
    )
    run(monkeypatch, "--scheduled-sender")    # 17:46 bat

    assert len(smtp.transactions) == 1, f"expected 1 email, got {len(smtp.transactions)}"
    assert "ALAB" in smtp.transactions[0]["body"], "the surviving digest is the complete one"
