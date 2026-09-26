# ADR-002：采用 SQLite 和原生 sqlite3 持久化

- 状态：Proposed
- 日期：2026-09-26
- 相关提交：[`616b9e2`](https://github.com/svlic/TFor/commit/616b9e2dcbd634a50640d576440d63ec80fffb56)、[`e03d2a7`](https://github.com/svlic/TFor/commit/e03d2a7d130c1e6870cdd403a54e523a2a68d0fb)

## 背景

项目规模预计不超过 10 个账号和 100 条规则，不需要独立数据库服务。当前也没有备份、恢复或高可用要求。

## 决策

采用单文件 SQLite，直接使用 Python 标准库 `sqlite3`。启用 foreign keys 和 WAL，每次操作建立短连接。当前不引入 PostgreSQL 或 ORM；schema 通过 `PRAGMA user_version` 和应用内顺序迁移演进。

## 可确认的实现事实

- 数据库包含 `settings`、`accounts`、`rules`、`filter_steps`、`processing_logs`、`source_events` 和 `deferred_jobs`。
- 过滤值、媒体类型和过滤结果中的可变列表使用 JSON 文本列。
- 启动时创建基础表，并按 `PRAGMA user_version` 执行增量迁移；当前 schema 版本为 2。
- Docker 部署把 SQLite 文件所在目录挂载到宿主机。
- `settings` 保存默认 `api_id` 和 `api_hash`。
- 每个账号还会保存手机号、独立 `api_id`、`api_hash`、状态和 Telethon `StringSession`。验证码和 2FA 密码不入库。

## 后果

- 运维成本低，符合单主机模型。
- 不支持多个实例安全共享进程内任务所有权，仅凭 WAL 不能使当前应用变成多实例架构。
- 轻量迁移适合当前规模，但复杂回填和不可逆变更仍需独立设计、备份和测试。
- API 凭据和 Session 当前均为明文；决策者不要求对 Session 加密。

## 未决问题

- 暂无。若将来需要多实例、备份保证或复杂查询，应重新评估本决策。
