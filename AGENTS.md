# 项目协作指南

交流、文档和界面文案优先使用中文，代码标识符沿用英文。

## 项目入口

TFor 使用 Telethon 用户账号（非 Bot）转发 Telegram 消息。单个 Uvicorn 进程承载 FastAPI 控制台、Telegram 客户端和后台任务；前端为 Jinja2 + 原生 JS/CSS，无构建步骤。兼容基线为 Docker 使用的 Python 3.11。

| 路径 | 职责 |
| --- | --- |
| `tfor/main.py` | 路由、表单校验、页面和应用生命周期 |
| `tfor/telegram.py` | 登录、连接、消息处理、发送与任务调度 |
| `tfor/db.py` | SQLite schema、迁移、数据访问与统计 |
| `tfor/filters.py` | 过滤流水线与媒体分类 |
| `tfor/config.py` | 环境变量与运行常量 |
| `tfor/templates/`、`tfor/static/` | 页面、脚本与样式 |
| `tests/test_{db,filters,telegram,web}.py` | 对应模块的 pytest 测试 |

- 修改账号、规则、过滤或发送逻辑前，阅读 [业务语义](kb/docs/behavior.md) 及相关实现和测试。
- [ADR](docs/adr/README.md) 记录架构背景，目前均为 `Proposed`，不能代替当前实现或视为已确认约束。
- schema 迁移放在 `Database.initialize()`，同步维护 `SCHEMA_VERSION` 与 `PRAGMA user_version`，验证新库和旧库升级。
- 配置、运行方式或用户可见行为变化时，同步更新相关文档。

## 运行与验证

依赖固定在 `requirements.txt`；当前仅配置 pytest，无 lint、formatter 或类型检查命令。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 使用新建的独立数据库，避免连接真实账号。
TFOR_DATABASE_PATH=/tmp/tfor-dev.db .venv/bin/uvicorn tfor.main:app --host 127.0.0.1 --port 8000
```

配置见 `.env.example` 与 `tfor/config.py`，在模块导入时读取。应用不自动加载 `.env`，需导出变量或使用 `uvicorn --env-file .env`。`TFOR_HOST` / `TFOR_PORT` 仅供 Docker 启动命令使用。

**测试必须使用一次性空数据库。** Web 测试会运行 lifespan：初始化数据库、清理日志并尝试连接已启用且有 Session 的账号。

```bash
test_dir=$(mktemp -d)
TFOR_DATABASE_PATH="$test_dir/tfor.db" .venv/bin/python -m pytest
status=$?
rm -rf -- "$test_dir"
(exit "$status")
```

定向测试在上述 pytest 命令后添加文件路径或 `-k`。数据库测试用 `tmp_path`，Telegram 测试用假客户端，异步测试沿用 `asyncio.run()`；跨模块变更运行全量测试。UI 外观变更需在隔离环境中渲染并检查代表性状态的截图，不能仅检查 HTTP 200。

## 安全边界

- `data/`、`.env`、`*.session` 和数据库可能含手机号、API 凭据及可复用的 `StringSession`；不得泄露、提交或用作测试夹具，不随意读取运行数据。
- 未经明确授权，不操作真实 Telegram 账号、不迁移或写入现有数据库、不启动或重启已有部署。
- 验证码和 2FA 密码不得持久化；日志不得记录正文、Caption、过滤值或命中片段。报告和截图不得暴露真实账号或消息数据。
- 应用无管理员认证，公网访问必须由部署环境提供访问控制；开发预览绑定回环地址。
- 保持单进程部署，不直接增加 Uvicorn worker 或副本，否则可能重复监听和发送。
