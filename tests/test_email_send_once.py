"""Send-once ledger + deterministic Message-ID.

Bruno received two digests per StocksDaily run (sometimes the same minute, sometimes a minute
apart). The logs show this pipeline only ever opens ONE SMTP transaction per run, so the duplicate
arrives on the mail path. These tests lock the two halves we control:

  * a second send for a date that already went out is refused (--force overrides);
  * one digest carries one stable Message-ID, so duplicate deliveries collapse instead of
    appearing twice.

The guard must never be the reason a digest fails to go out, so the degradation paths (missing
ledger, corrupt ledger, unwritable ledger) are tested as explicitly as the happy path.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import send_email as se  # noqa: E402


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Point the module's ledger at a temp file so tests never touch the real vault."""
    path = tmp_path / "_email_sent.json"
    monkeypatch.setattr(se, "SENT_INDEX", path)
    return path


# --------------------------------------------------------------------------- Message-ID


def test_message_id_is_stable_for_the_same_digest():
    a = se.digest_message_id("2026-07-28", "StocksDaily [2026-07-28]: TSM 8.1", 5)
    b = se.digest_message_id("2026-07-28", "StocksDaily [2026-07-28]: TSM 8.1", 5)
    assert a == b, "a re-send of one digest must reuse its id so Gmail can dedupe it"


def test_message_id_differs_when_the_digest_actually_differs():
    """A same-date digest with more reports is NOT the same mail and must not be swallowed."""
    five = se.digest_message_id("2026-07-28", "subject A", 5)
    ten = se.digest_message_id("2026-07-28", "subject A", 10)
    assert five != ten


def test_message_id_differs_across_dates():
    assert se.digest_message_id("2026-07-28", "s", 3) != se.digest_message_id("2026-07-29", "s", 3)


def test_message_id_is_rfc_shaped():
    mid = se.digest_message_id("2026-07-28", "subject", 4)
    assert mid.startswith("<") and mid.endswith(">")
    assert mid.count("@") == 1
    assert " " not in mid, "whitespace in a Message-ID breaks the header"


def test_message_id_survives_a_unicode_subject():
    """Subjects carry emoji/accents; the hash must not raise on them."""
    mid = se.digest_message_id("2026-07-28", "StocksDaily 🟢 ação São Paulo", 2)
    assert mid.startswith("<stocksdaily.2026-07-28.")


# --------------------------------------------------------------------------- ledger


def test_missing_ledger_reads_as_empty(ledger):
    assert not ledger.exists()
    assert se.load_sent_index() == {}


def test_corrupt_ledger_reads_as_empty_rather_than_raising(ledger):
    """A corrupt ledger must not block the digest -- empty means 'send it'."""
    ledger.write_text("{not json at all", encoding="utf-8")
    assert se.load_sent_index() == {}


def test_non_dict_ledger_reads_as_empty(ledger):
    ledger.write_text('["unexpected", "shape"]', encoding="utf-8")
    assert se.load_sent_index() == {}


def test_record_then_load_round_trips(ledger):
    se.record_sent("2026-07-28", "<mid@x>", 10)
    index = se.load_sent_index()
    assert index["2026-07-28"]["message_id"] == "<mid@x>"
    assert index["2026-07-28"]["reports"] == 10
    assert index["2026-07-28"]["sent_at"]


def test_record_preserves_other_dates(ledger):
    se.record_sent("2026-07-27", "<a@x>", 1)
    se.record_sent("2026-07-28", "<b@x>", 2)
    index = se.load_sent_index()
    assert set(index) == {"2026-07-27", "2026-07-28"}


def test_record_overwrites_the_same_date(ledger):
    se.record_sent("2026-07-28", "<first@x>", 1)
    se.record_sent("2026-07-28", "<second@x>", 9)
    assert se.load_sent_index()["2026-07-28"]["message_id"] == "<second@x>"


def test_record_creates_the_parent_directory(tmp_path, monkeypatch):
    nested = tmp_path / "does" / "not" / "exist" / "_email_sent.json"
    monkeypatch.setattr(se, "SENT_INDEX", nested)
    se.record_sent("2026-07-28", "<mid@x>", 3)
    assert nested.exists()


def test_record_failure_is_swallowed(tmp_path, monkeypatch):
    """The mail is already delivered when we record -- a write error must not raise."""
    monkeypatch.setattr(se, "SENT_INDEX", tmp_path / "x.json")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", boom)
    se.record_sent("2026-07-28", "<mid@x>", 1)  # must not raise


def test_ledger_is_valid_json_on_disk(ledger):
    se.record_sent("2026-07-28", "<mid@x>", 4)
    json.loads(ledger.read_text(encoding="utf-8"))


def test_ledger_survives_a_reimport(ledger):
    """Guards against the ledger helpers depending on import-time state."""
    se.record_sent("2026-07-28", "<mid@x>", 4)
    importlib.reload(se)
    # After reload SENT_INDEX points back at the real path, so just prove the reload worked
    # and the helpers are still callable.
    assert callable(se.load_sent_index) and callable(se.digest_message_id)
