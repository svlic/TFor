# TFor

带 Web 控制台的多账号 Telegram 消息转发平台。

## 快速开始

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn tfor.main:app --host 0.0.0.0 --port 8000
```

访问 `http://localhost:8000`。首次启动会自动创建 SQLite 数据库。系统不包含登录认证，部署到公网时请在外部网关配置访问控制。

## 配置

- `TFOR_DATABASE_PATH`：SQLite 文件路径，默认 `./data/tfor.db`
- `TFOR_HOST` / `TFOR_PORT`：Docker 启动时使用的监听地址与端口
- `TFOR_LOG_LEVEL`：日志级别，默认 `INFO`

也可以在“系统设置”中配置新账号默认使用的 Telegram `api_id` / `api_hash`。

## 测试

```bash
pytest
```

## Docker

```bash
docker compose up -d --build
```
