from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, TypeVar

from telethon import TelegramClient, errors, events, types, utils
from telethon.sessions import StringSession

from .db import Database
from .filters import MessageFields, classify_media, evaluate_filters


log = logging.getLogger(__name__)
T = TypeVar("T")


class DeferredFloodWait(Exception):
    def __init__(self, seconds: int):
        self.seconds = seconds
        super().__init__(f"FloodWait deferred for {seconds} seconds")


def display_name(entity: Any) -> str:
    return utils.get_display_name(entity) or getattr(entity, "title", None) or str(getattr(entity, "id", "未知"))


def entity_type(entity: Any) -> str:
    if isinstance(entity, types.Channel):
        return "channel" if getattr(entity, "broadcast", False) else "supergroup"
    if isinstance(entity, types.Chat):
        return "group"
    return "private"


class TelegramManager:
    def __init__(self, db: Database, max_concurrent_rules: int = 10, inline_flood_wait_seconds: int = 60):
        self.db = db
        self.max_concurrent_rules = max(1, max_concurrent_rules)
        self.inline_flood_wait_seconds = inline_flood_wait_seconds
        self.clients: dict[int, TelegramClient] = {}
        self.login_clients: dict[int, TelegramClient] = {}
        self.pending_albums: set[tuple[int, int, int]] = set()
        self.sent_messages: dict[tuple[int, int, int], None] = {}
        self.tasks: set[asyncio.Task[Any]] = set()
        self.rule_slots = asyncio.Semaphore(self.max_concurrent_rules)
        self.deferred_worker: asyncio.Task[Any] | None = None

    async def start(self) -> None:
        for account in self.db.accounts():
            if account["enabled"] and account["session_string"]:
                await self.connect(account["id"])
        if not self.deferred_worker or self.deferred_worker.done():
            self.deferred_worker = self._spawn(self._deferred_loop())

    async def stop(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        clients = {*self.clients.values(), *self.login_clients.values()}
        if clients:
            await asyncio.gather(*(client.disconnect() for client in clients), return_exceptions=True)
        self.clients.clear()
        self.login_clients.clear()
        self.tasks.clear()
        self.deferred_worker = None

    def _client(self, account: dict[str, Any]) -> TelegramClient:
        session = StringSession(account.get("session_string") or "")
        return TelegramClient(session, int(account["api_id"]), account["api_hash"])

    async def connect(self, account_id: int) -> None:
        account = self.db.account(account_id)
        if not account or not account["enabled"] or account["archived"]:
            return
        await self.disconnect(account_id, update_status=False)
        client: TelegramClient | None = None
        try:
            client = self._client(account)
            await client.connect()
            if not await client.is_user_authorized():
                self.db.update_account(account_id, status="logged_out", status_detail="需要重新登录")
                await client.disconnect()
                return

            async def handle_message(event: events.NewMessage.Event, aid: int = account_id) -> None:
                await self._on_message(aid, event)

            client.add_event_handler(handle_message, events.NewMessage())
            me = await client.get_me()
            self.clients[account_id] = client
            self.db.update_account(
                account_id,
                status="online",
                status_detail=None,
                telegram_user_id=me.id,
                telegram_name=display_name(me),
                session_string=client.session.save(),
            )
        except Exception as exc:
            if client:
                await client.disconnect()
            self.db.update_account(account_id, status="error", status_detail=str(exc)[:300])
            log.exception("Failed to connect account %s", account_id)

    async def disconnect(self, account_id: int, update_status: bool = True) -> None:
        client = self.clients.pop(account_id, None)
        login_client = self.login_clients.pop(account_id, None)
        if client:
            await client.disconnect()
        if login_client and login_client is not client:
            await login_client.disconnect()
        if update_status:
            account = self.db.account(account_id)
            if account and not account["archived"]:
                self.db.update_account(account_id, status="disabled" if not account["enabled"] else "offline")

    async def toggle(self, account_id: int) -> None:
        account = self.db.account(account_id)
        if not account:
            return
        enabled = not bool(account["enabled"])
        self.db.update_account(account_id, enabled=enabled)
        if enabled:
            await self.connect(account_id)
        else:
            await self.disconnect(account_id)

    async def start_login(self, account_id: int) -> str:
        account = self.db.account(account_id)
        if not account:
            raise ValueError("账号不存在")
        await self.disconnect(account_id, update_status=False)
        client = self._client({**account, "session_string": ""})
        try:
            await client.connect()
            sent = await client.send_code_request(account["phone"])
        except Exception:
            await client.disconnect()
            raise
        self.login_clients[account_id] = client
        self.db.update_account(account_id, status="code_required", status_detail="验证码已发送")
        return sent.phone_code_hash

    async def submit_code(self, account_id: int, code: str) -> str:
        account = self.db.account(account_id)
        client = self.login_clients.get(account_id)
        if not account or not client:
            raise ValueError("登录流程已过期，请重新发送验证码")
        try:
            await client.sign_in(phone=account["phone"], code=code)
        except errors.SessionPasswordNeededError:
            self.db.update_account(account_id, status="password_required", status_detail="需要两步验证密码")
            return "password_required"
        await self._finish_login(account_id, client)
        return "complete"

    async def submit_password(self, account_id: int, password: str) -> None:
        client = self.login_clients.get(account_id)
        if not client:
            raise ValueError("登录流程已过期，请重新发送验证码")
        await client.sign_in(password=password)
        await self._finish_login(account_id, client)

    async def _finish_login(self, account_id: int, client: TelegramClient) -> None:
        me = await client.get_me()
        session = client.session.save()
        await client.disconnect()
        self.login_clients.pop(account_id, None)
        self.db.update_account(
            account_id,
            session_string=session,
            enabled=1,
            status="offline",
            status_detail=None,
            telegram_user_id=me.id,
            telegram_name=display_name(me),
        )
        await self.connect(account_id)

    async def logout(self, account_id: int) -> None:
        client = self.clients.get(account_id)
        if client:
            try:
                await client.log_out()
            finally:
                self.clients.pop(account_id, None)
        await self.disconnect(account_id, update_status=False)
        self.db.update_account(account_id, session_string=None, status="logged_out", status_detail=None)

    async def resolve_chat(self, account_id: int, chat_id: int) -> dict[str, Any]:
        client = self.clients.get(account_id)
        if not client or not client.is_connected():
            raise ValueError("该账号未在线，请先完成登录并启用账号")
        try:
            entity = await client.get_entity(chat_id)
        except Exception as exc:
            raise ValueError(f"无法访问 Chat ID {chat_id}：{exc}") from exc
        kind = entity_type(entity)
        if kind == "private":
            raise ValueError("V1 仅支持频道和群组，不支持私聊")
        return {"id": utils.get_peer_id(entity), "name": display_name(entity), "type": kind}

    def _spawn(self, coroutine: Awaitable[Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def _deferred_loop(self) -> None:
        while True:
            try:
                jobs = self.db.claim_deferred_jobs(limit=self.max_concurrent_rules)
                if jobs:
                    await asyncio.gather(*(self._resume_deferred(job) for job in jobs))
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Deferred job worker failed; retrying")
                await asyncio.sleep(5)

    async def _resume_deferred(self, job: dict[str, Any]) -> None:
        try:
            completed = await self._run_rule(
                job["account_id"],
                job["rule_id"],
                job["source_chat_id"],
                job["source_message_id"],
                job["grouped_id"],
                deferred_job_id=job["id"],
            )
        except asyncio.CancelledError:
            self.db.reschedule_deferred_job(job["id"], 0)
            raise
        if completed:
            self.db.delete_deferred_job(job["id"])

    async def _run_rule(
        self,
        account_id: int,
        rule_id: int,
        chat_id: int,
        message_id: int,
        grouped_id: int | None,
        deferred_job_id: int | None = None,
    ) -> bool:
        async with self.rule_slots:
            return await self._process_rule(
                account_id, rule_id, chat_id, message_id, grouped_id, deferred_job_id=deferred_job_id
            )

    def health(self) -> dict[str, int]:
        return {
            "connected_accounts": len(self.clients),
            "active_tasks": max(0, len(self.tasks) - int(self.deferred_worker in self.tasks)),
            "deferred_jobs": self.db.deferred_job_count(),
            "deferred_worker_running": int(bool(self.deferred_worker and not self.deferred_worker.done())),
        }

    async def _on_message(self, account_id: int, event: events.NewMessage.Event) -> None:
        message = event.message
        chat_id = event.chat_id
        if message.out or chat_id is None or isinstance(await event.get_chat(), types.User):
            return
        if (account_id, chat_id, message.id) in self.sent_messages:
            self.sent_messages.pop((account_id, chat_id, message.id), None)
            return
        grouped_id = message.grouped_id
        if grouped_id:
            key = (account_id, chat_id, grouped_id)
            if key in self.pending_albums:
                return
            self.pending_albums.add(key)
            await asyncio.sleep(1)
            self.pending_albums.discard(key)
        self.db.record_source_event(account_id, chat_id, message.id, grouped_id)
        rules = self.db.rules_for_source(account_id, chat_id)
        for rule in rules:
            self._spawn(self._run_rule(account_id, rule["id"], chat_id, message.id, grouped_id))

    async def _fetch_messages(
        self, client: TelegramClient, chat_id: int, message_id: int, grouped_id: int | None
    ) -> list[Any]:
        if not grouped_id:
            message = await client.get_messages(chat_id, ids=message_id)
            return [message] if message else []
        nearby = await client.get_messages(
            chat_id, limit=60, min_id=max(0, message_id - 30), max_id=message_id + 31
        )
        return sorted((m for m in nearby if m.grouped_id == grouped_id), key=lambda m: m.id)

    async def _process_rule(
        self,
        account_id: int,
        rule_id: int,
        chat_id: int,
        message_id: int,
        grouped_id: int | None,
        deferred_job_id: int | None = None,
    ) -> bool:
        started = time.monotonic()
        rule = self.db.rule(rule_id)
        account = self.db.account(account_id)
        if not rule or not account or not rule["enabled"] or not account["enabled"]:
            return True
        log_data: dict[str, Any] = {
            "account_id": account_id,
            "account_label": account["label"],
            "source_chat_id": chat_id,
            "source_message_id": message_id,
            "rule_id": rule_id,
            "rule_name": rule["name"],
            "target_chat_id": rule["target_chat_id"],
            "filter_results": [],
        }
        try:
            if rule["delay_seconds"] and deferred_job_id is None:
                await asyncio.sleep(rule["delay_seconds"])
                rule = self.db.rule(rule_id)
                if not rule or not rule["enabled"] or rule["account_id"] != account_id:
                    return True
            client = self.clients.get(account_id)
            if not client:
                raise RuntimeError("账号客户端未连接")
            messages = await self._fetch_messages(client, chat_id, message_id, grouped_id)
            if not messages:
                log_data["result"] = "deleted"
                return True
            primary = next((m for m in messages if m.message), messages[0])
            sender = await primary.get_sender()
            sender_name = display_name(sender) if sender else ""
            sender_username = getattr(sender, "username", None) or ""
            sender_id = getattr(sender, "id", None) or primary.sender_id
            fields = MessageFields(primary.message or "", sender_name, sender_username, sender_id)
            log_data.update(sender_id=sender_id, sender_name=sender_name, sender_username=sender_username)
            passed, filter_results = evaluate_filters(rule["filters"], fields)
            log_data["filter_results"] = filter_results
            if not passed:
                log_data["result"] = "filtered"
                return True

            candidates = messages
            if grouped_id and rule["captioned_media_only"]:
                candidates = [primary] if primary.message else []
            selected = [
                m for m in candidates if classify_media(m) is None or classify_media(m) in rule["allowed_media"]
            ]
            changed = len(selected) != len(messages)
            text = primary.message or ""
            if not selected and not text:
                log_data["result"] = "filtered"
                return True

            mode = rule["send_mode"]
            if not selected or (mode == "auto" and changed):
                mode = "copy"
            if mode in ("forward", "auto"):
                try:
                    sent = await self._retry(
                        lambda: client.forward_messages(rule["target_chat_id"], selected, from_peer=chat_id)
                    )
                    actual_mode = "forward"
                except errors.ChatForwardsRestrictedError:
                    if mode != "auto":
                        raise
                    sent = await self._copy(client, rule["target_chat_id"], selected, text, primary)
                    actual_mode = "copy"
            else:
                sent = await self._copy(client, rule["target_chat_id"], selected, text, primary)
                actual_mode = "copy"
            self._remember_sent(account_id, rule["target_chat_id"], sent)
            log_data.update(result="success", actual_mode=actual_mode)
            return True
        except DeferredFloodWait as exc:
            if deferred_job_id is None:
                self.db.defer_job(exc.seconds, account_id, rule_id, chat_id, message_id, grouped_id)
            else:
                self.db.reschedule_deferred_job(deferred_job_id, exc.seconds)
            log_data.update(result="deferred", error=f"FloodWait: retry scheduled in {exc.seconds} seconds")
            return False
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_data.update(result="failed", error=f"{type(exc).__name__}: {str(exc)[:500]}")
            log.exception("Rule %s failed for message %s", rule_id, message_id)
            return True
        finally:
            if "result" in log_data:
                log_data["duration_ms"] = int((time.monotonic() - started) * 1000)
                self.db.record_log(log_data)

    async def _copy(
        self, client: TelegramClient, target: int, messages: list[Any], text: str, primary: Any
    ) -> Any:
        media_messages = [message for message in messages if classify_media(message) is not None]
        if not media_messages:
            return await self._retry(
                lambda: client.send_message(target, text, formatting_entities=getattr(primary, "entities", None))
            )
        if len(media_messages) == 1 and classify_media(media_messages[0]) == "other":
            return await self._retry(lambda: client.send_message(target, media_messages[0]))
        with TemporaryDirectory(prefix="tfor-") as directory:
            files: list[str] = []
            for index, message in enumerate(media_messages):
                path = Path(directory) / f"{index}-{Path(self._filename(message)).name}"
                downloaded = await self._retry(
                    lambda m=message, p=path: client.download_media(m, file=str(p))
                )
                if downloaded:
                    files.append(str(downloaded))
            if not files:
                if text:
                    return await self._retry(lambda: client.send_message(target, text))
                raise RuntimeError("媒体下载失败")
            kwargs: dict[str, Any] = {"caption": text or None}
            if len(files) == 1:
                kwargs["formatting_entities"] = getattr(primary, "entities", None)
                kwargs["voice_note"] = classify_media(media_messages[0]) == "voice"
            return await self._retry(lambda: client.send_file(target, files if len(files) > 1 else files[0], **kwargs))

    @staticmethod
    def _filename(message: Any) -> str:
        file = getattr(message, "file", None)
        name = getattr(file, "name", None)
        if name:
            return name
        extension = getattr(file, "ext", None) or ""
        return f"telegram-{message.id}{extension}"

    async def _retry(self, operation: Callable[[], Awaitable[T]]) -> T:
        attempt = 0
        flood_waits = 0
        while True:
            try:
                return await operation()
            except errors.FloodWaitError as exc:
                if exc.seconds > self.inline_flood_wait_seconds:
                    raise DeferredFloodWait(exc.seconds) from exc
                flood_waits += 1
                if flood_waits > 3:
                    raise
                await asyncio.sleep(exc.seconds)
            except (OSError, asyncio.TimeoutError, errors.ServerError):
                attempt += 1
                if attempt > 3:
                    raise
                await asyncio.sleep(min(2 ** (attempt - 1), 5))

    def _remember_sent(self, account_id: int, target: int, sent: Any) -> None:
        for message in sent if isinstance(sent, list) else [sent]:
            if message and getattr(message, "id", None):
                key = (account_id, target, message.id)
                self.sent_messages.pop(key, None)
                self.sent_messages[key] = None
        while len(self.sent_messages) > 5000:
            self.sent_messages.pop(next(iter(self.sent_messages)))
