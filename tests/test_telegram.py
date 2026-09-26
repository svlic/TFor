import asyncio
from pathlib import Path
from types import SimpleNamespace

from telethon import errors

from tfor.db import Database
from tfor.telegram import DeferredFloodWait, TelegramManager


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
        messages: list[object] | asyncio.Task[list[object]] | None = None,
    ) -> bool:
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(0.01)
        self.running -= 1
        return True


def test_rule_processing_respects_concurrency_limit(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.initialize()
    manager = TrackingManager(db)

    async def run() -> None:
        await asyncio.gather(*(manager._run_rule(1, index, -1, index, None) for index in range(6)))

    asyncio.run(run())

    assert manager.peak == 2


def test_rule_delay_does_not_hold_a_processing_slot(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    delayed_rule_id = 1
    immediate_rule_id = 2
    original_rule = db.rule
    db.rule = lambda rule_id: {"delay_seconds": 0.03 if rule_id == delayed_rule_id else 0}  # type: ignore[method-assign]

    class DelayTrackingManager(TelegramManager):
        def __init__(self) -> None:
            super().__init__(db, max_concurrent_rules=1)
            self.order: list[int] = []

        async def _process_rule(
            self,
            account_id: int,
            rule_id: int,
            chat_id: int,
            message_id: int,
            grouped_id: int | None,
            deferred_job_id: int | None = None,
            messages: list[object] | asyncio.Task[list[object]] | None = None,
        ) -> bool:
            self.order.append(rule_id)
            return True

    manager = DelayTrackingManager()

    async def run() -> None:
        delayed = asyncio.create_task(manager._run_rule(1, delayed_rule_id, -1, 1, None))
        await asyncio.sleep(0)
        immediate = asyncio.create_task(manager._run_rule(1, immediate_rule_id, -1, 2, None))
        await asyncio.gather(delayed, immediate)

    try:
        asyncio.run(run())
    finally:
        db.rule = original_rule  # type: ignore[method-assign]

    assert manager.order == [immediate_rule_id, delayed_rule_id]


def test_pending_rule_limit_applies_backpressure(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")

    class BlockingManager(TelegramManager):
        def __init__(self) -> None:
            super().__init__(db, max_concurrent_rules=2, max_pending_rules=2)
            self.release = asyncio.Event()

        async def _run_rule(self, *_: object, **__: object) -> bool:
            await self.release.wait()
            return True

    manager = BlockingManager()

    async def run() -> None:
        await manager._schedule_rule(1, 1, -1, 1, None, None)
        await manager._schedule_rule(1, 2, -1, 2, None, None)
        blocked = asyncio.create_task(manager._schedule_rule(1, 3, -1, 3, None, None))
        await asyncio.sleep(0)

        assert manager.pending_rule_count == 2
        assert blocked.done() is False

        manager.release.set()
        await blocked
        await asyncio.gather(*list(manager.tasks))

    asyncio.run(run())

    assert manager.pending_rule_count == 0


def test_media_copy_limits_are_global_and_per_account(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")

    class CopyTrackingManager(TelegramManager):
        def __init__(self) -> None:
            super().__init__(db, max_concurrent_copies=4, max_concurrent_copies_per_account=2)
            self.running = 0
            self.running_by_account: dict[int, int] = {}
            self.peak = 0
            self.peak_by_account: dict[int, int] = {}

        async def _copy(
            self,
            client: object,
            target: int,
            messages: list[object],
            text: str,
            primary: object,
            account_id: int | None = None,
        ) -> object:
            assert account_id is not None
            self.running += 1
            self.running_by_account[account_id] = self.running_by_account.get(account_id, 0) + 1
            self.peak = max(self.peak, self.running)
            self.peak_by_account[account_id] = max(
                self.peak_by_account.get(account_id, 0), self.running_by_account[account_id]
            )
            await asyncio.sleep(0.02)
            self.running -= 1
            self.running_by_account[account_id] -= 1
            return SimpleNamespace(id=target)

    manager = CopyTrackingManager()
    media = SimpleNamespace(media=object(), photo=object())

    async def run() -> None:
        await asyncio.gather(
            *(
                manager._limited_copy(account_id, object(), -1000 - index, [media], "", media)  # type: ignore[arg-type]
                for account_id in (1, 2)
                for index in range(3)
            )
        )

    asyncio.run(run())

    assert manager.peak == 4
    assert manager.peak_by_account == {1: 2, 2: 2}


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


def test_client_uses_one_rpc_retry_layer_and_disables_automatic_flood_sleep(tmp_path: Path) -> None:
    manager = TelegramManager(Database(tmp_path / "test.db"))

    async def run() -> None:
        client = manager._client({"session_string": "", "api_id": 123, "api_hash": "hash"})

        assert client._request_retries == 3
        assert client.flood_sleep_threshold == 0

    asyncio.run(run())


def test_long_slow_mode_wait_is_shared_by_target(tmp_path: Path) -> None:
    manager = TelegramManager(Database(tmp_path / "test.db"), inline_flood_wait_seconds=0)
    calls = 0

    async def flooded() -> None:
        nonlocal calls
        calls += 1
        raise errors.SlowModeWaitError(request=None, capture=30)

    async def should_not_run() -> None:
        nonlocal calls
        calls += 1

    async def run() -> None:
        try:
            await manager._retry(flooded, slow_mode_key=(1, -1002))
        except DeferredFloodWait as exc:
            assert exc.seconds == 30
        else:
            raise AssertionError("长 SlowModeWait 应转为延后任务")

        try:
            await manager._retry(should_not_run, slow_mode_key=(1, -1002))
        except DeferredFloodWait as exc:
            assert 1 <= exc.seconds <= 30
        else:
            raise AssertionError("同一目标应共享 SlowMode 等待时间")

    asyncio.run(run())

    assert calls == 1


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


def test_immediate_album_rules_share_one_message_fetch(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.initialize()
    account_id = db.create_account("A", "+100", 123, "hash")
    rule = {
        "name": "album route",
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
        "captioned_media_only": 0,
        "enabled": 1,
    }
    db.save_rule(rule, [])
    db.save_rule({**rule, "name": "second album route", "target_chat_id": -1003}, [])
    fetches = 0
    forwards = 0

    async def get_sender() -> None:
        return None

    album = [
        SimpleNamespace(
            id=10,
            message="caption",
            sender_id=7,
            grouped_id=999,
            media=object(),
            photo=object(),
            get_sender=get_sender,
        ),
        SimpleNamespace(
            id=11,
            message="",
            sender_id=7,
            grouped_id=999,
            media=object(),
            photo=object(),
            get_sender=get_sender,
        ),
    ]

    class ForwardClient:
        async def get_messages(self, *_: object, **__: object) -> list[object]:
            nonlocal fetches
            fetches += 1
            return album

        async def forward_messages(self, *_: object, **__: object) -> object:
            nonlocal forwards
            forwards += 1
            return SimpleNamespace(id=100 + forwards)

    async def get_chat() -> object:
        return object()

    event = SimpleNamespace(chat_id=-1001, message=SimpleNamespace(out=False, id=10, grouped_id=999), get_chat=get_chat)
    manager = TelegramManager(db)
    manager.clients[account_id] = ForwardClient()  # type: ignore[assignment]

    async def run() -> None:
        await manager._on_message(account_id, event)
        await asyncio.gather(*list(manager.tasks))

    asyncio.run(run())

    assert fetches == 1
    assert forwards == 2


def test_filtered_media_does_not_send_its_caption(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.initialize()
    account_id = db.create_account("A", "+100", 123, "hash")
    rule_id = db.save_rule(
        {
            "name": "video only",
            "account_id": account_id,
            "source_chat_id": -1001,
            "source_name": "Source",
            "source_type": "channel",
            "target_chat_id": -1002,
            "target_name": "Target",
            "target_type": "group",
            "send_mode": "copy",
            "delay_seconds": 0,
            "allowed_media": ["video"],
            "captioned_media_only": 0,
            "enabled": 1,
        },
        [],
    )
    sent_captions: list[str | None] = []

    class CopyClient:
        async def download_media(self, message: object, file: str) -> str:
            path = Path(file)
            path.write_bytes(b"media")
            return str(path)

        async def send_file(self, target: int, file: str, **kwargs: object) -> object:
            assert target == -1002
            sent_captions.append(kwargs.get("caption"))  # type: ignore[arg-type]
            return SimpleNamespace(id=101)

        async def send_message(self, *_: object, **__: object) -> object:
            raise AssertionError("被过滤媒体的 Caption 不应单独发送")

    async def get_sender() -> None:
        return None

    photo = SimpleNamespace(
        id=10,
        message="photo caption",
        sender_id=7,
        media=object(),
        photo=object(),
        file=SimpleNamespace(name="photo.jpg", ext=".jpg"),
        entities=None,
        get_sender=get_sender,
    )
    video = SimpleNamespace(
        id=11,
        message="",
        sender_id=7,
        media=object(),
        photo=None,
        video=object(),
        file=SimpleNamespace(name="video.mp4", ext=".mp4"),
        entities=None,
        get_sender=get_sender,
    )
    manager = TelegramManager(db)
    manager.clients[account_id] = CopyClient()  # type: ignore[assignment]

    async def fetch_album(*_: object) -> list[object]:
        return [photo, video]

    manager._fetch_messages = fetch_album  # type: ignore[method-assign]
    completed = asyncio.run(manager._process_rule(account_id, rule_id, -1001, 10, 999))

    assert completed is True
    assert sent_captions == [None]

    async def fetch_photo(*_: object) -> list[object]:
        return [photo]

    manager._fetch_messages = fetch_photo  # type: ignore[method-assign]
    asyncio.run(manager._process_rule(account_id, rule_id, -1001, 10, None))

    assert sent_captions == [None]
    assert db.logs()[0]["result"] == "filtered"


def test_album_filters_check_only_the_primary_caption(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.initialize()
    account_id = db.create_account("A", "+100", 123, "hash")
    rule_id = db.save_rule(
        {
            "name": "primary caption",
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
            "captioned_media_only": 0,
            "enabled": 1,
        },
        [
            {
                "kind": "blacklist",
                "field": "text",
                "match_mode": "contains",
                "values": ["secondary blocked"],
                "enabled": True,
            }
        ],
    )
    forwarded: list[object] = []

    class ForwardClient:
        async def forward_messages(self, target: int, messages: list[object], from_peer: int) -> object:
            forwarded.extend(messages)
            return SimpleNamespace(id=101)

    async def get_sender() -> None:
        return None

    messages = [
        SimpleNamespace(id=10, message="", sender_id=7, media=object(), photo=object(), get_sender=get_sender),
        SimpleNamespace(
            id=11, message="primary caption", sender_id=7, media=object(), photo=object(), get_sender=get_sender
        ),
        SimpleNamespace(
            id=12, message="secondary blocked", sender_id=7, media=object(), photo=object(), get_sender=get_sender
        ),
    ]
    manager = TelegramManager(db)
    manager.clients[account_id] = ForwardClient()  # type: ignore[assignment]

    async def fetch_messages(*_: object) -> list[object]:
        return messages

    manager._fetch_messages = fetch_messages  # type: ignore[method-assign]
    completed = asyncio.run(manager._process_rule(account_id, rule_id, -1001, 10, 999))

    assert completed is True
    assert forwarded == messages
    assert db.logs()[0]["result"] == "success"


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
