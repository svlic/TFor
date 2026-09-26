from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import (
    BASE_DIR,
    DATABASE_PATH,
    INLINE_FLOOD_WAIT_SECONDS,
    LOG_LEVEL,
    LOG_RETENTION_DAYS,
    MAX_CONCURRENT_COPIES,
    MAX_CONCURRENT_COPIES_PER_ACCOUNT,
    MAX_CONCURRENT_RULES,
    MAX_PENDING_RULES,
    MEDIA_TYPES,
)
from .db import Database
from .telegram import TelegramManager


logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)
db = Database(DATABASE_PATH)
manager = TelegramManager(
    db,
    max_concurrent_rules=MAX_CONCURRENT_RULES,
    inline_flood_wait_seconds=INLINE_FLOOD_WAIT_SECONDS,
    max_pending_rules=MAX_PENDING_RULES,
    max_concurrent_copies=MAX_CONCURRENT_COPIES,
    max_concurrent_copies_per_account=MAX_CONCURRENT_COPIES_PER_ACCOUNT,
)
templates = Jinja2Templates(directory=BASE_DIR / "tfor" / "templates")


async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        db.cleanup(LOG_RETENTION_DAYS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.initialize()
    db.cleanup(LOG_RETENTION_DAYS)
    await manager.start()
    cleanup_task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        await manager.stop()


app = FastAPI(title="TFor", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "tfor" / "static"), name="static")


def page(request: Request, name: str, **context: object) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"active": request.url.path, **context})


def redirect(path: str, message: str = "", error: str = "") -> RedirectResponse:
    separator = "&" if "?" in path else "?"
    if message:
        path += f"{separator}message={quote(message)}"
    elif error:
        path += f"{separator}error={quote(error)}"
    return RedirectResponse(path, status_code=303)


@app.get("/health")
async def health() -> JSONResponse:
    try:
        database = db.health()
        if not database["ok"]:
            return JSONResponse({"status": "error", "database": database}, status_code=503)
        return JSONResponse({"status": "ok", "database": database, "runtime": manager.health()})
    except Exception:
        log.exception("Health check failed")
        return JSONResponse({"status": "error", "database": {"ok": False}}, status_code=503)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return page(request, "dashboard.html", stats=db.dashboard())


@app.get("/accounts", response_class=HTMLResponse)
async def accounts(request: Request) -> HTMLResponse:
    all_accounts = db.accounts(include_archived=True)
    return page(
        request,
        "accounts.html",
        accounts=[account for account in all_accounts if not account["archived"]],
        archived_accounts=[account for account in all_accounts if account["archived"]],
        default_api_id=db.setting("default_api_id"),
        default_api_hash=db.setting("default_api_hash"),
    )


@app.post("/accounts")
async def create_account(
    label: str = Form(...), phone: str = Form(...), api_id: int = Form(...), api_hash: str = Form(...)
) -> RedirectResponse:
    account_id = db.create_account(label.strip(), phone.strip(), api_id, api_hash.strip())
    return redirect(f"/accounts?open_login={account_id}", "账号已创建，请发送验证码完成登录")


@app.post("/accounts/{account_id}/edit")
async def edit_account(
    account_id: int,
    label: str = Form(...),
    phone: str = Form(...),
    api_id: int = Form(...),
    api_hash: str = Form(...),
) -> RedirectResponse:
    account = db.account(account_id)
    if not account:
        return redirect("/accounts", error="账号不存在")
    credentials_changed = (
        api_id != account["api_id"] or api_hash != account["api_hash"] or phone.strip() != account["phone"]
    )
    db.update_account(account_id, label=label.strip(), phone=phone.strip(), api_id=api_id, api_hash=api_hash.strip())
    if credentials_changed:
        await manager.disconnect(account_id, update_status=False)
        db.update_account(account_id, session_string=None, status="logged_out", status_detail="登录凭据已更改，请重新登录")
    return redirect("/accounts", "账号配置已保存")


@app.post("/accounts/{account_id}/login/start")
async def login_start(account_id: int) -> RedirectResponse:
    try:
        await manager.start_login(account_id)
        return redirect(f"/accounts?open_login={account_id}", "验证码已发送")
    except Exception as exc:
        return redirect(f"/accounts?open_login={account_id}", error=str(exc))


@app.post("/accounts/{account_id}/login/code")
async def login_code(account_id: int, code: str = Form(...)) -> RedirectResponse:
    try:
        state = await manager.submit_code(account_id, code.strip())
        if state == "password_required":
            return redirect(f"/accounts?open_login={account_id}", "请输入两步验证密码")
        return redirect("/accounts", "Telegram 登录成功")
    except Exception as exc:
        return redirect(f"/accounts?open_login={account_id}", error=str(exc))


@app.post("/accounts/{account_id}/login/password")
async def login_password(account_id: int, password: str = Form(...)) -> RedirectResponse:
    try:
        await manager.submit_password(account_id, password)
        return redirect("/accounts", "Telegram 登录成功")
    except Exception as exc:
        return redirect(f"/accounts?open_login={account_id}", error=str(exc))


@app.post("/accounts/{account_id}/toggle")
async def toggle_account(account_id: int) -> RedirectResponse:
    await manager.toggle(account_id)
    return redirect("/accounts", "账号状态已更新")


@app.post("/accounts/{account_id}/reconnect")
async def reconnect_account(account_id: int) -> RedirectResponse:
    await manager.connect(account_id)
    account = db.account(account_id)
    if account and account["status"] == "online":
        return redirect("/accounts", "重连成功")
    return redirect("/accounts", error=(account or {}).get("status_detail") or "重连失败")


@app.post("/accounts/{account_id}/logout")
async def logout_account(account_id: int) -> RedirectResponse:
    await manager.logout(account_id)
    return redirect(f"/accounts?open_login={account_id}", "原会话已退出，请重新登录")


@app.post("/accounts/{account_id}/archive")
async def archive_account(account_id: int) -> RedirectResponse:
    await manager.disconnect(account_id, update_status=False)
    db.archive_account(account_id)
    return redirect("/accounts", "账号已归档，关联规则已全部停用")


@app.post("/accounts/{account_id}/restore")
async def restore_account(account_id: int) -> RedirectResponse:
    account = db.account(account_id)
    if not account or not account["archived"]:
        return redirect("/accounts", error="归档账号不存在")
    db.restore_account(account_id)
    if account["session_string"]:
        await manager.connect(account_id)
        return redirect("/accounts", "账号和原有规则已恢复")
    return redirect(f"/accounts?open_login={account_id}", "账号和原有规则已恢复，请重新登录")


@app.get("/rules", response_class=HTMLResponse)
async def rules(request: Request) -> HTMLResponse:
    return page(request, "rules.html", rules=db.rules())


@app.get("/rules/new", response_class=HTMLResponse)
async def new_rule(request: Request) -> HTMLResponse:
    return page(
        request,
        "rule_form.html",
        rule=None,
        accounts=[a for a in db.accounts() if a["status"] == "online"],
        media_types=MEDIA_TYPES,
    )


@app.get("/rules/{rule_id}/edit", response_class=HTMLResponse)
async def edit_rule(request: Request, rule_id: int) -> HTMLResponse:
    rule = db.rule(rule_id)
    if not rule:
        return page(request, "not_found.html", status_code=404)
    return page(request, "rule_form.html", rule=rule, accounts=db.accounts(), media_types=MEDIA_TYPES)


def parse_filters(raw: str) -> list[dict[str, object]]:
    decoded = json.loads(raw or "[]")
    if not isinstance(decoded, list):
        raise ValueError("过滤配置必须是步骤列表")
    result = []
    for item in decoded:
        if not isinstance(item, dict):
            raise ValueError("过滤步骤格式无效")
        kind = item.get("kind")
        field = item.get("field")
        match_mode = item.get("match_mode")
        if kind not in ("blacklist", "whitelist"):
            raise ValueError("过滤类型无效")
        if field not in ("text", "sender_name", "sender_username", "sender_id"):
            raise ValueError("过滤字段无效")
        if match_mode not in ("contains", "exact", "regex"):
            raise ValueError("匹配方式无效")
        values = [value for line in str(item.get("values", "")).splitlines() if (value := line.strip())]
        if not values:
            continue
        if match_mode == "regex":
            for value in values:
                try:
                    re.compile(value)
                except re.error as exc:
                    raise ValueError(f"正则表达式无效：{value}（{exc}）") from exc
        result.append(
            {
                "kind": kind,
                "field": field,
                "match_mode": match_mode,
                "values": values,
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return result


async def save_rule_from_form(
    rule_id: int | None,
    name: str,
    account_id: int,
    source_chat_id: int,
    target_chat_id: int,
    send_mode: str,
    delay_seconds: int,
    allowed_media: list[str],
    captioned_media_only: bool,
    enabled: bool,
    filters_json: str,
) -> RedirectResponse:
    try:
        if send_mode not in ("auto", "forward", "copy"):
            raise ValueError("发送模式无效")
        if delay_seconds < 0:
            raise ValueError("延迟秒数不能小于 0")
        source = await manager.resolve_chat(account_id, source_chat_id)
        target = await manager.resolve_chat(account_id, target_chat_id)
        db.save_rule(
            {
                "name": name.strip(),
                "account_id": account_id,
                "source_chat_id": source["id"],
                "source_name": source["name"],
                "source_type": source["type"],
                "target_chat_id": target["id"],
                "target_name": target["name"],
                "target_type": target["type"],
                "send_mode": send_mode,
                "delay_seconds": delay_seconds,
                "allowed_media": [m for m in allowed_media if m in MEDIA_TYPES],
                "captioned_media_only": int(captioned_media_only),
                "enabled": int(enabled),
            },
            parse_filters(filters_json),
            rule_id,
        )
        return redirect("/rules", "规则已保存并实时生效")
    except (ValueError, json.JSONDecodeError) as exc:
        path = f"/rules/{rule_id}/edit" if rule_id else "/rules/new"
        return redirect(path, error=str(exc))


@app.post("/rules")
async def create_rule(
    name: str = Form(...), account_id: int = Form(...), source_chat_id: int = Form(...),
    target_chat_id: int = Form(...), send_mode: str = Form(...), delay_seconds: int = Form(0),
    allowed_media: list[str] = Form(default=[]), captioned_media_only: bool = Form(False),
    enabled: bool = Form(False), filters_json: str = Form("[]"),
) -> RedirectResponse:
    return await save_rule_from_form(
        None, name, account_id, source_chat_id, target_chat_id, send_mode, delay_seconds,
        allowed_media, captioned_media_only, enabled, filters_json,
    )


@app.post("/rules/{rule_id}")
async def update_rule(
    rule_id: int, name: str = Form(...), account_id: int = Form(...), source_chat_id: int = Form(...),
    target_chat_id: int = Form(...), send_mode: str = Form(...), delay_seconds: int = Form(0),
    allowed_media: list[str] = Form(default=[]), captioned_media_only: bool = Form(False),
    enabled: bool = Form(False), filters_json: str = Form("[]"),
) -> RedirectResponse:
    return await save_rule_from_form(
        rule_id, name, account_id, source_chat_id, target_chat_id, send_mode, delay_seconds,
        allowed_media, captioned_media_only, enabled, filters_json,
    )


@app.post("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: int) -> RedirectResponse:
    rule = db.rule(rule_id)
    if rule:
        db.set_rule_enabled(rule_id, not bool(rule["enabled"]))
    return redirect("/rules", "规则状态已更新")


@app.post("/rules/{rule_id}/delete")
async def delete_rule(rule_id: int) -> RedirectResponse:
    db.delete_rule(rule_id)
    return redirect("/rules", "规则已删除")


@app.get("/logs", response_class=HTMLResponse)
async def processing_logs(
    request: Request, result: str = "", rule_id: int | None = None, account_id: int | None = None
) -> HTMLResponse:
    return page(
        request, "logs.html", logs=db.logs(result=result, rule_id=rule_id, account_id=account_id),
        rules=db.rules(), accounts=db.accounts(), filters={"result": result, "rule_id": rule_id, "account_id": account_id},
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings(request: Request) -> HTMLResponse:
    return page(
        request, "settings.html", default_api_id=db.setting("default_api_id"),
        default_api_hash=db.setting("default_api_hash"), retention_days=LOG_RETENTION_DAYS,
    )


@app.post("/settings")
async def save_settings(default_api_id: str = Form(""), default_api_hash: str = Form("")) -> RedirectResponse:
    if default_api_id and not default_api_id.isdigit():
        return redirect("/settings", error="默认 api_id 必须是数字")
    db.save_settings({"default_api_id": default_api_id.strip(), "default_api_hash": default_api_hash.strip()})
    return redirect("/settings", "系统设置已保存")
