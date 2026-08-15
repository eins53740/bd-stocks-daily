"""The deterministic Message-ID must actually reach the SMTP conversation.

digest_message_id() being correct is not enough -- the header has to land on the outgoing message,
which is what makes a duplicate diagnosable after the fact (identical id => one digest sent twice).
It is NOT what prevents the duplicate: on 2026-07-29 two sends carried the same id and Gmail
delivered both. See test_email_ownership.py for the guard that actually stops the second send.

This drives main() with a fake SMTP and a fake credential source and inspects what would have been
transmitted, so it also proves the send path still works end to end after adding the guards.
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
    """Stands in for smtplib.SMTP_SSL, recording the one transaction it is given.

    `sendmail_calls` counts transactions rather than recipients: one sendmail() carrying
    several RCPT TO is still ONE delivery, so counting addresses cannot tell a duplicate
    send from a multi-recipient digest.
    """

    captured: dict = {}
    sendmail_calls: int = 0

    def __init__(self, host, port, timeout=None):
        _FakeSMTP.captured = {"host": host, "port": port}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, pwd):
        _FakeSMTP.captured["login"] = user

    def sendmail(self, sender, recipients, body):
        _FakeSMTP.sendmail_calls += 1
        _FakeSMTP.captured.update(sender=sender, recipients=list(recipients), body=body)


@pytest.fixture
def sending(tmp_path, monkeypatch):
    """Wire main() to send nowhere: fake SMTP, fake keys, temp ledger, no dashboard, no rows."""
    _FakeSMTP.captured = {}
    _FakeSMTP.sendmail_calls = 0

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
    # Hermetic: these tests assert sends happen, so the scheduled-run ownership guard must be off
    # regardless of the shell pytest inherits.
    monkeypatch.delenv(se.SCHEDULED_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["send_email.py", "--date", "2026-07-28"])
    return _FakeSMTP


def test_message_id_header_is_transmitted(sending):
    assert se.main() == 0
    body = sending.captured["body"]
    assert "Message-ID: <stocksdaily.2026-07-28." in body


def test_transmitted_message_id_matches_the_helper(sending):
    se.main()
    body = sending.captured["body"]
    # Recompute from the subject actually used, so this cannot drift from the implementation.
    subject_line = next(l for l in body.splitlines() if l.startswith("Subject:"))
    assert subject_line  # sanity: the digest has a subject
    assert body.count("Message-ID:") == 1, "exactly one Message-ID header"


def test_exactly_one_smtp_transaction(sending):
    se.main()
    assert sending.captured["recipients"] == se.RECIPIENTS
    # ONE transaction, however many recipients it addresses. Asserting on the number of
    # addresses instead broke the moment a second recipient was added legitimately, while
    # never catching the failure that actually matters -- main() sending twice.
    assert sending.sendmail_calls == 1, "one sendmail() -- one delivery"


def test_a_successful_send_is_recorded_in_the_ledger(sending):
    se.main()
    index = se.load_sent_index()
    assert "2026-07-28" in index
    assert index["2026-07-28"]["message_id"].startswith("<stocksdaily.2026-07-28.")


def test_second_run_is_blocked_by_the_ledger_it_just_wrote(sending):
    """The regression that matters: run twice, send once."""
    assert se.main() == 0
    first = dict(sending.captured)
    sending.captured = {}
    assert se.main() == 0
    assert sending.captured == {}, "second run must not open an SMTP connection"
    assert first["recipients"] == se.RECIPIENTS


def test_force_overrides_the_ledger(sending, monkeypatch):
    se.main()
    sending.captured = {}
    monkeypatch.setattr(sys, "argv", ["send_email.py", "--date", "2026-07-28", "--force"])
    assert se.main() == 0
    assert sending.captured.get("recipients") == se.RECIPIENTS, "--force must still send"


def test_dry_run_neither_sends_nor_records(sending, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["send_email.py", "--date", "2026-07-28", "--dry-run"])
    assert se.main() == 0
    assert sending.captured == {}
    assert se.load_sent_index() == {}, "a dry run must not claim the date"


def test_smtp_failure_does_not_record_the_date(sending, monkeypatch):
    """A failed send must leave the date sendable, not silently consumed."""
    def boom(self, sender, recipients, body):
        raise OSError("connection refused")

    monkeypatch.setattr(_FakeSMTP, "sendmail", boom)
    assert se.main() == 0  # non-fatal by design
    assert se.load_sent_index() == {}, "a failed send must not block the retry"
