# ADR-009：采用单主机部署并将认证交给部署环境

- 状态：Proposed
- 日期：2026-09-26
- 相关提交：[`e03d2a7`](https://github.com/svlic/TFor/commit/e03d2a7d130c1e6870cdd403a54e523a2a68d0fb)、[`cd59c27`](https://github.com/svlic/TFor/commit/cd59c270eb34c6b801aa1f126978646dc5912d61)

## 背景

当前规模适合单主机运行，没有指定反向代理、认证网关或多实例要求。

## 决策

V1 采用单主机、单容器、单 Uvicorn 进程部署。SQLite 数据目录挂载到宿主机，容器使用 `restart: unless-stopped`。

应用不实现管理员认证。公网部署可以由外部网关提供访问控制，但这只是部署建议，不是应用强制检查；当前不指定 Nginx、Caddy、Cloudflare Access 或 VPN。

未来不明确禁止多进程或多实例，但当前架构不宣称支持它们。启用之前必须先解决 Telegram Client 所有权、进程内任务、持久队列和幂等问题。

## 可确认的实现事实

- Docker 基础镜像为 `python:3.11-slim`。
- Compose 只定义一个服务，并将 `./data` 挂载到 `/app/data`。
- `/health` 执行 SQLite `quick_check`、校验 schema 版本，并返回连接账号数、活动任务数、持久延后任务数和队列 worker 状态；数据库异常时返回 HTTP 503。
- README 明确提示公网部署应配置外部访问控制。

## 后果

- 部署简单，但裸露 8000 端口时任何访问者都能管理 Telegram 账号和规则。
- 健康检查可以发现数据库损坏或迁移版本不一致，但账号离线不会使整个服务判定为不健康。
- 当前运行时状态使水平扩展存在重复监听和重复发送风险。

## 未决问题

- 多实例需求和时间点尚未确定。
- 备份、升级和回滚目标尚未提供。
