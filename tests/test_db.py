import asyncio
import sqlite3
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
        "captioned_media_only": 1,
        "enabled": 1,
    }
    first = db.save_rule(data, [])
    second = db.save_rule(data, [])

    assert first != second
    assert len(db.rules_for_source(account_id, -1001)) == 2
    assert db.rule(first)["captioned_media_only"] == 1

    db.archive_account(account_id)

    assert db.account(account_id)["archived"] == 1
    assert all(rule["enabled"] == 0 for rule in db.rules(account_id))


def test_account_restore_preserves_each_rules_previous_enabled_state(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    account_id = db.create_account("A", "+100", 123, "hash")
    data = {
        "name": "route",
        "account_id": account_id,
        "source_chat_id": -1001,
        "source_name": "Source",
        "source_type": "channel",
        "target_chat_id": -1002,
        "target_name": "Target",
        "target_type": "group",
        "send_mode": "auto",
        "delay_seconds": 0,
        "allowed_media": [],
        "captioned_media_only": 0,
        "enabled": 1,
    }
    enabled_rule = db.save_rule(data, [])
    disabled_rule = db.save_rule({**data, "name": "disabled", "enabled": 0}, [])

    db.archive_account(account_id)
    db.restore_account(account_id)

    assert db.account(account_id)["archived"] == 0
    assert db.account(account_id)["status"] == "logged_out"
    assert db.rule(enabled_rule)["enabled"] == 1
    assert db.rule(disabled_rule)["enabled"] == 0


def test_schema_version_and_deferred_job_lifecycle(tmp_path: Path) -> None:
    db = make_db(tmp_path)

    assert db.health() == {"ok": True, "check": "ok", "schema_version": Database.SCHEMA_VERSION}
    job_id = db.defer_job(0, 1, 2, -1001, 99, None)
    jobs = db.claim_deferred_jobs()

    assert [job["id"] for job in jobs] == [job_id]
    assert db.claim_deferred_jobs() == []
    db.reschedule_deferred_job(job_id, 0)
    assert [job["id"] for job in db.claim_deferred_jobs()] == [job_id]
    db.delete_deferred_job(job_id)
    assert db.deferred_job_count() == 0


def test_initialize_migrates_an_unversioned_rules_table(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE rules (id INTEGER PRIMARY KEY)")
    db = Database(path)

    db.initialize()

    with db.connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(rules)")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert "archived_by_account" in columns
    assert "captioned_media_only" in columns
    assert version == Database.SCHEMA_VERSION


def test_initialize_adds_caption_option_to_version_two_database(tmp_path: Path) -> None:
    path = tmp_path / "version-two.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE rules (id INTEGER PRIMARY KEY)")
        conn.execute("PRAGMA user_version = 2")
    db = Database(path)

    db.initialize()

    with db.connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(rules)")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert "captioned_media_only" in columns
    assert version == Database.SCHEMA_VERSION


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
