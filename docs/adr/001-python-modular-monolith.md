# ADR-001：采用 Python 模块化单体和服务端渲染管理面

- 状态：Proposed
- 日期：2026-09-26
- 相关提交：[`616b9e2`](https://github.com/svlic/TFor/commit/616b9e2dcbd634a50640d576440d63ec80fffb56)、[`cd59c27`](https://github.com/svlic/TFor/commit/cd59c270eb34c6b801aa1f126978646dc5912d61)、[`e03d2a7`](https://github.com/svlic/TFor/commit/e03d2a7d130c1e6870cdd403a54e523a2a68d0fb)

## 背景

项目面向小规模使用，基本不会超过 10 个 Telegram 账号和 100 条规则。最初仓库只有项目名称，没有既有应用架构。

## 决策

采用 Python 模块化单体。单个应用进程承载 FastAPI HTTP 服务、Jinja2 服务端页面、Telegram Client 生命周期、消息处理任务、SQLite 数据访问和日志清理。

FastAPI 与 Jinja2 是 AI 在“足够轻量即可”的约束下作出的实现选型，不代表项目对这两个框架有不可替换的业务依赖。当前不引入独立 SPA、API 服务、worker 或消息队列。

## 可确认的实现事实

- FastAPI lifespan 初始化数据库、启动 Telegram 客户端和日志清理任务，并在退出时断开客户端。
- 管理界面通过 Jinja2 和少量原生 JavaScript 服务端渲染。
- Uvicorn 直接加载 `tfor.main:app`。

## 后果

- 部署和本地运行简单，适合当前规模。
- Web、Telegram 和后台任务共享故障域与事件循环。
- 进程重启会同时影响管理面和转发面。
- 如果未来拆分服务，需要重新定义任务所有权、状态同步和部署拓扑。

## 未决问题

- Telegram 处理服务未来是否应与 Web 管理进程拆分，尚未决定。
