# 项目协作指南

本文件适用于整个仓库。交流、文档和界面文案优先使用中文，代码标识符沿用英文。

## 项目与代码入口

TFor 是带 Web 控制台的多账号 Telegram 消息转发平台，使用 Telegram 用户账号而非 Bot。
当前为 Python 模块化单体：单个 Uvicorn 进程承载 Web、Telegram Client 和异步后台任务。

| 路径 | 职责 |
| --- | --- |
| `tfor/main.py` | FastAPI 路由、表单校验、Jinja2 页面和应用生命周期 |
| `tfor/telegram.py` | 账号登录与连接、消息处理、相册、发送、重试和延后任务 |
| `tfor/db.py` | SQLite schema、迁移、数据访问、日志与统计 |
| `tfor/filters.py` | 过滤流水线和媒体类型识别 |
| `tfor/config.py` | 环境变量、路径与运行常量 |
| `tfor/templates/`、`tfor/static/` | Jinja2 模板、原生 JavaScript 和 CSS；无前端构建步骤 |
| `tests/` | pytest 测试，按 db、filters、telegram、web 划分 |
| `docs/adr/` | 架构背景、取舍和未决问题 |

修改前阅读相关实现和测试。ADR 目前均为 `Proposed`，不是已经正式确认的约束；不要把未决事项当成已实现功能，遇到与代码不符之处应明确指出。

## 环境与常用命令

以 Docker 使用的 Python 3.11 为兼容基线。依赖固定在 `requirements.txt`，`pyproject.toml` 当前仅配置 pytest。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 本地开发：使用独立数据库，默认只监听本机。
TFOR_DATABASE_PATH=/tmp/tfor-dev.db .venv/bin/uvicorn tfor.main:app --host 127.0.0.1 --port 8000
```

- 配置项参见 `.env.example` 与 `tfor/config.py`。配置在模块导入时读取，应在启动 Python 前设置环境变量。
- 应用代码不自动读取 `.env`。仅复制示例文件不会使配置生效；需导出环境变量或显式使用 Uvicorn 的 `--env-file .env`。
- `TFOR_HOST` / `TFOR_PORT` 由 Docker 启动命令读取；直接运行 Uvicorn 时使用 `--host` / `--port`。
- Docker 部署方式见 `README.md`、`Dockerfile` 和 `compose.yaml`。未经授权不要启动或重启已有部署。

## 测试与验证

**不要直接用默认数据库执行 Web 测试。** `tests/test_web.py` 的 `TestClient` 会执行 lifespan，初始化数据库、清理日志并尝试连接已启用且有 Session 的账号。全量测试应使用一次性空数据库：

```bash
test_dir=$(mktemp -d)
TFOR_DATABASE_PATH="$test_dir/tfor.db" .venv/bin/python -m pytest
status=$?
rm -rf -- "$test_dir"
(exit "$status")
```

定向验证时，在同一隔离方式下给 pytest 添加文件路径或 `-k` 表达式，例如 `tests/test_telegram.py`。

- 数据库测试沿用 `tmp_path` 创建独立 SQLite 文件；Telegram 测试使用假客户端，不依赖真实账号、验证码或外网发送。
- 异步测试沿用现有 `asyncio.run()` 模式；当前未配置 pytest-asyncio。
- 行为变更增加能区分正确与错误实现的回归测试；跨模块变更运行全量测试。
- schema 变更同时验证新库初始化和旧库升级，不仅测试空数据库。
- UI 外观变更需要启动隔离环境，检查代表性页面和受影响状态，并查看渲染截图；模板返回 HTTP 200 不等于视觉验证。
- 当前没有配置 lint、formatter 或类型检查命令；不要声称这些检查已通过，也不要为普通修改擅自引入工具链。

## 实现约定与关键语义

- 沿用现有类型注解、四空格缩进和模块分工，在拥有该行为的模块中做最小修改。不要无需求引入 ORM、SPA、独立 worker 或消息队列。
- SQLite 使用标准库 `sqlite3`、短连接、foreign keys 和 WAL。新增 schema 迁移放在 `Database.initialize()`，同步维护 `SCHEMA_VERSION` 和 `PRAGMA user_version`；SQL 参数使用绑定参数。
- 每条规则绑定单个账号，该账号负责 Source 与 Target；仅支持群组和频道，允许重复规则，不添加目标去重或规则唯一约束。
- 账号删除采用归档语义：停用但保留关联规则，恢复时保留各规则归档前的启用状态。登录凭据更改后旧 Session 失效。
- 过滤步骤有序执行，一个步骤内多值为 ANY；blacklist 命中或 whitelist 未命中即短路拒绝。保存时校验正则；日志不包含过滤值或命中内容。
- `forward` 不自动 Copy；`copy` 重新发送；`auto` 仅在媒体筛选改变结构或遇到 `ChatForwardsRestrictedError` 时降级 Copy，不能用降级掩盖其他错误。
- 相册作为整体重取、过滤和发送；延迟后重新读取规则和源消息，源消息已删除时不发送。
- 保留全局规则并发限制。普通延迟任务在内存中，长 FloodWait 写入 SQLite `deferred_jobs`；当前不保证严格顺序或 exactly-once，故障重放可能重复发送。
- Copy 媒体使用临时目录并确保清理，不改成整份媒体常驻内存。新增后台任务必须考虑启动、取消、退出和异常处理。
- `source_events` 统计收到的源消息，`processing_logs` 统计规则执行，两者不能混用。处理日志保留期当前为 3 天。

## 数据与运行安全

- `data/`、`.env`、`*.session` 及数据库可能含手机号、API 凭据和可复用的 `StringSession`；不得提交、输出或用于测试夹具，不要随意读取现有运行数据。
- 验证码和 2FA 密码不持久化；日志不保存正文、caption、过滤值或命中片段。发送者元数据目前允许记录，仍需避免在报告或截图中暴露真实数据。
- 未经明确授权，不使用真实 Telegram 账号测试登录、发送、退出或修改规则，不对现有数据库执行迁移、清理或写入。
- 应用没有管理员认证；对外开放前必须由部署环境提供访问控制。开发预览优先绑定回环地址。
- 当前只按单进程部署验证；不要直接添加 Uvicorn 多 worker 或多副本，会引入重复监听和发送风险。
- 新增或修改配置、运行步骤及用户可见行为时，同步更新相关文档；架构变化需说明与现有 ADR 的关系，不擅自把 `Proposed` 改为 `Accepted`。
