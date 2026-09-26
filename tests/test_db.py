import asyncio
from pathlib import Path

from tfor.db import Database
from tfor.telegram import TelegramManager


def make_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test.db")
    db.initialize()
    return db


def test_duplicate_rules_are_preserved_and_account_archive_disables_them(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    account_id = db.create_account("A", "+100", 123, "hash")
    data = {
        "name": "same route",
        "account_id": account_id,
        "source_chat_id": -1001,
        "source_name": "Source",
        "source_type": "channel",
        "target_chat_id": -1002,
        "target_name": "Target",
        "target_type": "group",
        "send_mode": "auto",
        "delay_seconds": 0,
        "allowed_media": ["photo"],
        "enabled": 1,
    }
    first = db.save_rule(data, [])
    second = db.save_rule(data, [])

    assert first != second
    assert len(db.rules_for_source(account_id, -1001)) == 2

    db.archive_account(account_id)

    assert db.account(account_id)["archived"] == 1
    assert all(rule["enabled"] == 0 for rule in db.rules(account_id))


def test_processing_log_stores_metadata_without_message_body(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    db.record_log(
        {
            "account_id": 1,
            "account_label": "A",
            "source_chat_id": -1001,
            "source_message_id": 99,
            "sender_id": 7,
            "sender_name": "Sender",
            "sender_username": "sender",
            "rule_id": 3,
            "rule_name": "Rule",
            "target_chat_id": -1002,
            "filter_results": [{"field": "text", "outcome": "REJECT"}],
            "result": "filtered",
            "actual_mode": None,
            "error": None,
            "duration_ms": 12,
        }
    )

    item = db.logs()[0]
    assert item["source_message_id"] == 99
    assert item["filter_results"] == [{"field": "text", "outcome": "REJECT"}]
    assert "text" not in item or "message" not in item


def test_dashboard_distinguishes_source_messages_from_rule_executions(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    db.record_source_event(1, -1001, 10, None)
    base = {
        "account_id": 1,
        "account_label": "A",
        "source_chat_id": -1001,
        "source_message_id": 10,
        "sender_id": 7,
        "sender_name": "Sender",
        "sender_username": "sender",
        "rule_name": "Rule",
        "target_chat_id": -1002,
        "filter_results": [],
        "result": "success",
        "actual_mode": "forward",
        "error": None,
        "duration_ms": 10,
    }
    db.record_log({**base, "rule_id": 1})
    db.record_log({**base, "rule_id": 2})

    stats = db.dashboard()

    assert stats["received"] == 1
    assert stats["executions"] == 2


def test_invalid_account_session_is_isolated_instead_of_crashing_startup(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    account_id = db.create_account("Broken", "+100", 123, "hash")
    db.update_account(account_id, session_string="not-a-valid-session")
    manager = TelegramManager(db)

    asyncio.run(manager.start())

    account = db.account(account_id)
    assert account["status"] == "error"
    assert "valid string" in account["status_detail"]
