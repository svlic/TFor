from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    api_id INTEGER NOT NULL,
                    api_hash TEXT NOT NULL,
                    session_string TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    archived INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'logged_out',
                    status_detail TEXT,
                    telegram_user_id INTEGER,
                    telegram_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    account_id INTEGER NOT NULL REFERENCES accounts(id),
                    source_chat_id INTEGER NOT NULL,
                    source_name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    target_chat_id INTEGER NOT NULL,
                    target_name TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    send_mode TEXT NOT NULL CHECK(send_mode IN ('auto','forward','copy')),
                    delay_seconds INTEGER NOT NULL DEFAULT 0,
                    allowed_media TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS filter_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_id INTEGER NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('blacklist','whitelist')),
                    field TEXT NOT NULL CHECK(field IN ('text','sender_name','sender_username','sender_id')),
                    match_mode TEXT NOT NULL CHECK(match_mode IN ('contains','exact','regex')),
                    values_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS processing_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    account_id INTEGER NOT NULL,
                    account_label TEXT NOT NULL,
                    source_chat_id INTEGER NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    sender_id INTEGER,
                    sender_name TEXT,
                    sender_username TEXT,
                    rule_id INTEGER NOT NULL,
                    rule_name TEXT NOT NULL,
                    target_chat_id INTEGER NOT NULL,
                    filter_results TEXT NOT NULL DEFAULT '[]',
                    result TEXT NOT NULL,
                    actual_mode TEXT,
                    error TEXT,
                    duration_ms INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_logs_created ON processing_logs(created_at);
                CREATE INDEX IF NOT EXISTS idx_logs_message ON processing_logs(account_id, source_chat_id, source_message_id);
                CREATE TABLE IF NOT EXISTS source_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    account_id INTEGER NOT NULL,
                    source_chat_id INTEGER NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    grouped_id INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_events_created ON source_events(created_at);
                """
            )

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def setting(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def save_settings(self, values: dict[str, str]) -> None:
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                values.items(),
            )

    def accounts(self, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE archived = 0"
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(f"SELECT * FROM accounts {where} ORDER BY id DESC")]

    def account(self, account_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._dict(conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())

    def create_account(self, label: str, phone: str, api_id: int, api_hash: str) -> int:
        now = utcnow()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO accounts(label,phone,api_id,api_hash,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (label, phone, api_id, api_hash, now, now),
            )
            return int(cur.lastrowid)

    def update_account(self, account_id: int, **values: Any) -> None:
        if not values:
            return
        values["updated_at"] = utcnow()
        columns = ", ".join(f"{key} = ?" for key in values)
        with self.connect() as conn:
            conn.execute(f"UPDATE accounts SET {columns} WHERE id = ?", (*values.values(), account_id))

    def archive_account(self, account_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE accounts SET archived=1, enabled=0, status='archived', updated_at=? WHERE id=?",
                (utcnow(), account_id),
            )
            conn.execute("UPDATE rules SET enabled=0, updated_at=? WHERE account_id=?", (utcnow(), account_id))

    def rules(self, account_id: int | None = None, enabled_only: bool = False) -> list[dict[str, Any]]:
        conditions: list[str] = []
        args: list[Any] = []
        if account_id is not None:
            conditions.append("r.account_id = ?")
            args.append(account_id)
        if enabled_only:
            conditions.extend(("r.enabled = 1", "a.enabled = 1", "a.archived = 0"))
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT r.*, a.label account_label FROM rules r JOIN accounts a ON a.id=r.account_id {where} ORDER BY r.id DESC",
                args,
            ).fetchall()
        return [self._decode_rule(dict(r)) for r in rows]

    def rules_for_source(self, account_id: int, source_chat_id: int) -> list[dict[str, Any]]:
        return [r for r in self.rules(account_id, True) if r["source_chat_id"] == source_chat_id]

    def rule(self, rule_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT r.*, a.label account_label FROM rules r JOIN accounts a ON a.id=r.account_id WHERE r.id=?",
                (rule_id,),
            ).fetchone()
            if not row:
                return None
            result = self._decode_rule(dict(row))
            result["filters"] = [
                self._decode_filter(dict(item))
                for item in conn.execute("SELECT * FROM filter_steps WHERE rule_id=? ORDER BY position,id", (rule_id,))
            ]
        return result

    @staticmethod
    def _decode_rule(rule: dict[str, Any]) -> dict[str, Any]:
        rule["allowed_media"] = json.loads(rule["allowed_media"])
        return rule

    @staticmethod
    def _decode_filter(step: dict[str, Any]) -> dict[str, Any]:
        step["values"] = json.loads(step.pop("values_json"))
        return step

    def save_rule(self, data: dict[str, Any], filters: list[dict[str, Any]], rule_id: int | None = None) -> int:
        now = utcnow()
        fields = (
            "name", "account_id", "source_chat_id", "source_name", "source_type", "target_chat_id",
            "target_name", "target_type", "send_mode", "delay_seconds", "allowed_media", "enabled",
        )
        values = [json.dumps(data[key]) if key == "allowed_media" else data[key] for key in fields]
        with self.connect() as conn:
            if rule_id is None:
                placeholders = ",".join("?" for _ in fields)
                cur = conn.execute(
                    f"INSERT INTO rules({','.join(fields)},created_at,updated_at) VALUES({placeholders},?,?)",
                    (*values, now, now),
                )
                rule_id = int(cur.lastrowid)
            else:
                assignments = ",".join(f"{field}=?" for field in fields)
                conn.execute(f"UPDATE rules SET {assignments},updated_at=? WHERE id=?", (*values, now, rule_id))
                conn.execute("DELETE FROM filter_steps WHERE rule_id=?", (rule_id,))
            for position, step in enumerate(filters):
                conn.execute(
                    "INSERT INTO filter_steps(rule_id,position,kind,field,match_mode,values_json,enabled) VALUES(?,?,?,?,?,?,?)",
                    (rule_id, position, step["kind"], step["field"], step["match_mode"], json.dumps(step["values"]), step["enabled"]),
                )
        return rule_id

    def set_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE rules SET enabled=?, updated_at=? WHERE id=?", (enabled, utcnow(), rule_id))

    def delete_rule(self, rule_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))

    def record_source_event(self, account_id: int, chat_id: int, message_id: int, grouped_id: int | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO source_events(created_at,account_id,source_chat_id,source_message_id,grouped_id) VALUES(?,?,?,?,?)",
                (utcnow(), account_id, chat_id, message_id, grouped_id),
            )

    def record_log(self, data: dict[str, Any]) -> None:
        fields = (
            "created_at", "account_id", "account_label", "source_chat_id", "source_message_id", "sender_id",
            "sender_name", "sender_username", "rule_id", "rule_name", "target_chat_id", "filter_results",
            "result", "actual_mode", "error", "duration_ms",
        )
        data.setdefault("created_at", utcnow())
        data["filter_results"] = json.dumps(data.get("filter_results", []), ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                f"INSERT INTO processing_logs({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",
                [data.get(field) for field in fields],
            )

    def logs(self, *, result: str = "", rule_id: int | None = None, account_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
        conditions: list[str] = []
        args: list[Any] = []
        for column, value in (("result", result), ("rule_id", rule_id), ("account_id", account_id)):
            if value not in (None, ""):
                conditions.append(f"{column}=?")
                args.append(value)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        args.append(min(max(limit, 1), 1000))
        with self.connect() as conn:
            rows = conn.execute(f"SELECT * FROM processing_logs {where} ORDER BY id DESC LIMIT ?", args).fetchall()
        result_rows = []
        for row in rows:
            item = dict(row)
            item["filter_results"] = json.loads(item["filter_results"])
            result_rows.append(item)
        return result_rows

    def dashboard(self) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with self.connect() as conn:
            account = conn.execute(
                "SELECT COUNT(*) total, COALESCE(SUM(status='online'),0) online FROM accounts WHERE archived=0"
            ).fetchone()
            rules = conn.execute("SELECT COUNT(*) total, COALESCE(SUM(enabled),0) enabled FROM rules").fetchone()
            received = conn.execute("SELECT COUNT(*) count FROM source_events WHERE created_at>=?", (since,)).fetchone()[0]
            stats = dict(conn.execute(
                """SELECT COUNT(*) executions,
                COALESCE(SUM(result='filtered'),0) filtered,
                COALESCE(SUM(result='success' AND actual_mode='forward'),0) forwarded,
                COALESCE(SUM(result='success' AND actual_mode='copy'),0) copied,
                COALESCE(SUM(result='failed'),0) failed
                FROM processing_logs WHERE created_at>=?""",
                (since,),
            ).fetchone())
            errors = [dict(r) for r in conn.execute(
                "SELECT * FROM processing_logs WHERE error IS NOT NULL ORDER BY id DESC LIMIT 8"
            )]
        return {"accounts": dict(account), "rules": dict(rules), "received": received, **stats, "errors": errors}

    def cleanup(self, retention_days: int = 3) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self.connect() as conn:
            conn.execute("DELETE FROM processing_logs WHERE created_at < ?", (cutoff,))
            conn.execute("DELETE FROM source_events WHERE created_at < ?", (cutoff,))
