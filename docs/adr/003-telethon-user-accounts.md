# ADR-003：使用 Telethon 用户账号和 StringSession

- 状态：Proposed
- 日期：2026-09-26
- 相关提交：[`616b9e2`](https://github.com/svlic/TFor/commit/616b9e2dcbd634a50640d576440d63ec80fffb56)、[`cd59c27`](https://github.com/svlic/TFor/commit/cd59c270eb34c6b801aa1f126978646dc5912d61)

## 背景

转发主体必须是 Telegram 用户账号，而不是 Bot。项目需要管理多个账号，并在进程重启后恢复已登录账号。

## 决策

使用 Telethon。每个账号拥有独立手机号、`api_id`、`api_hash`、`StringSession` 和 `TelegramClient`。网页登录支持验证码和可选 2FA；验证码与 2FA 密码不持久化。

当前无需加密 Session。尚未评估 Pyrogram 等替代库，未来可以进行一次兼容性和维护性评估。

账号“删除”应采用可恢复归档语义：归档账号并停用关联规则，不物理删除规则；以后重新激活并登录同一账号时，应允许用户恢复原规则。

## 可确认的实现事实

- 应用启动时连接所有已启用且具有 Session 的账号。
- 活跃客户端和登录中的客户端保存在进程内字典。
- 单个无效 Session 会把对应账号标记为 error，不阻止其他账号启动。
- 修改手机号、`api_id` 或 `api_hash` 会清除原 Session。
- 当前归档操作会隐藏并停用账号，同时记录每条规则归档前的启用状态；管理页面可以恢复账号及原先启用的规则。

## 后果

- 可以使用用户账号已有的群组和频道访问权限。
- 数据库泄露将暴露可复用的 Telegram Session 和 API 凭据。
- Client 生命周期与当前应用进程绑定。
- 恢复账号时会自动恢复归档前启用的规则；原先停用的规则保持停用。

## 未决问题

- 未来评估 Telethon 替代库时，以兼容性、维护活跃度还是迁移成本为主要标准？
