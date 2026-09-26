import asyncio
from pathlib import Path
from types import SimpleNamespace

from telethon import errors

from tfor.db import Database
from tfor.telegram import TelegramManager


class TrackingManager(TelegramManager):
    def __init__(self, db: Database) -> None:
        super().__init__(db, max_concurrent_rules=2)
        self.running = 0
        self.peak = 0

    async def _process_rule(
        self,
        account_id: int,
        rule_id: int,
        chat_id: int,
        message_id: int,
        grouped_id: int | None,
        deferred_job_id: int | None = None,
    ) -> bool:
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(0.01)
        self.running -= 1
        return True


def test_rule_processing_respects_concurrency_limit(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    manager = TrackingManager(db)

    async def run() -> None:
        await asyncio.gather(*(manager._run_rule(1, index, -1, index, None) for index in range(6)))

    asyncio.run(run())

    assert manager.peak == 2


def test_sent_message_cache_evicts_oldest_entries(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    manager = TelegramManager(db)

    for message_id in range(5001):
        manager._remember_sent(1, -100, type("Message", (), {"id": message_id})())

    assert len(manager.sent_messages) == 5000
    assert (1, -100, 0) not in manager.sent_messages
    assert (1, -100, 5000) in manager.sent_messages


def test_long_flood_wait_is_persisted_for_later_retry(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.initialize()
    account_id = db.create_account("A", "+100", 123, "hash")
    rule_id = db.save_rule(
        {
            "name": "route",
            "account_id": account_id,
            "source_chat_id": -1001,
            "source_name": "Source",
            "source_type": "channel",
            "target_chat_id": -1002,
            "target_name": "Target",
            "target_type": "group",
            "send_mode": "forward",
            "delay_seconds": 0,
            "allowed_media": [],
            "captioned_media_only": 0,
            "enabled": 1,
        },
        [],
    )

    class FloodedClient:
        async def forward_messages(self, target: int, messages: list[object], from_peer: int) -> None:
            raise errors.FloodWaitError(request=None, capture=120)

    message = SimpleNamespace(message="hello", sender_id=7, media=None)

    async def get_sender() -> None:
        return None

    message.get_sender = get_sender
    manager = TelegramManager(db, inline_flood_wait_seconds=60)
    manager.clients[account_id] = FloodedClient()  # type: ignore[assignment]

    async def fetch_messages(*_: object) -> list[object]:
        return [message]

    manager._fetch_messages = fetch_messages  # type: ignore[method-assign]

    completed = asyncio.run(manager._process_rule(account_id, rule_id, -1001, 99, None))

    assert completed is False
    assert db.deferred_job_count() == 1
    assert db.logs()[0]["result"] == "deferred"


def test_album_can_forward_only_the_media_with_caption(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.initialize()
    account_id = db.create_account("A", "+100", 123, "hash")
    rule_id = db.save_rule(
        {
            "name": "captioned album media",
            "account_id": account_id,
            "source_chat_id": -1001,
            "source_name": "Source",
            "source_type": "channel",
            "target_chat_id": -1002,
            "target_name": "Target",
            "target_type": "group",
            "send_mode": "forward",
            "delay_seconds": 0,
            "allowed_media": ["photo"],
            "captioned_media_only": 1,
            "enabled": 1,
        },
        [],
    )
    forwarded: list[object] = []

    class ForwardClient:
        async def forward_messages(self, target: int, messages: list[object], from_peer: int) -> object:
            assert target == -1002
            assert from_peer == -1001
            forwarded.extend(messages)
            return SimpleNamespace(id=101)

    async def get_sender() -> None:
        return None

    messages = [
        SimpleNamespace(id=10, message="", sender_id=7, media=object(), photo=object(), get_sender=get_sender),
        SimpleNamespace(
            id=11, message="the caption", sender_id=7, media=object(), photo=object(), get_sender=get_sender
        ),
        SimpleNamespace(id=12, message="", sender_id=7, media=object(), photo=object(), get_sender=get_sender),
    ]
    manager = TelegramManager(db)
    manager.clients[account_id] = ForwardClient()  # type: ignore[assignment]

    async def fetch_messages(*_: object) -> list[object]:
        return messages

    manager._fetch_messages = fetch_messages  # type: ignore[method-assign]

    completed = asyncio.run(manager._process_rule(account_id, rule_id, -1001, 10, 999))

    assert completed is True
    assert forwarded == [messages[1]]
    assert db.logs()[0]["actual_mode"] == "forward"

    forwarded.clear()
    messages[1].message = ""
    asyncio.run(manager._process_rule(account_id, rule_id, -1001, 10, 999))

    assert forwarded == []
    assert db.logs()[0]["result"] == "filtered"

    async def fetch_single_message(*_: object) -> list[object]:
        return [messages[0]]

    manager._fetch_messages = fetch_single_message  # type: ignore[method-assign]
    asyncio.run(manager._process_rule(account_id, rule_id, -1001, 10, None))

    assert forwarded == [messages[0]]


def test_copy_uses_temporary_files_instead_of_loading_media_into_memory(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    manager = TelegramManager(db)
    message = SimpleNamespace(
        id=10,
        media=object(),
        photo=object(),
        file=SimpleNamespace(name="photo.jpg", ext=".jpg"),
        entities=None,
    )
    sent_paths: list[Path] = []

    class CopyClient:
        async def download_media(self, _: object, file: str) -> str:
            path = Path(file)
            path.write_bytes(b"image")
            return str(path)

        async def send_file(self, target: int, file: str, **_: object) -> object:
            path = Path(file)
            assert path.exists()
            sent_paths.append(path)
            return SimpleNamespace(id=11)

    result = asyncio.run(manager._copy(CopyClient(), -1002, [message], "caption", message))  # type: ignore[arg-type]

    assert result.id == 11
    assert len(sent_paths) == 1
    assert not sent_paths[0].exists()
