# TFor

带 Web 控制台的多账号 Telegram 消息转发平台。

## Docker Compose 部署（推荐）

需要 Docker Engine 和 Docker Compose 插件。发布镜像为 `ghcr.io/svlic/tfor`，支持 **linux/amd64** 和 **linux/arm64**（64 位 ARM，不含 ARMv7）；Docker 会自动选择主机对应的架构。

```bash
git clone https://github.com/svlic/TFor.git
cd TFor
cp .env.example .env
# 按需编辑 .env 后启动
docker compose pull
docker compose up -d --no-build
docker compose logs -f --tail=100
```

镜像需先由下文的 GitHub Actions 成功发布；尚未发布时可使用本地构建方式。GHCR 软件包需设为 Public 才能匿名拉取；私有包需要先使用具备 `read:packages` 权限的凭据执行 `docker login ghcr.io`。

默认仅监听宿主机 `127.0.0.1:8000`。在服务器本机访问 `http://127.0.0.1:8000`，或通过 SSH 隧道、带访问控制的反向代理访问。系统**没有登录认证**，不要直接暴露到公网。需要从局域网访问时，可在 `.env` 中设置 `TFOR_BIND_ADDRESS=0.0.0.0`，并通过防火墙限制来源。

Compose 会自动读取同目录的 `.env`，并传入支持的应用配置：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TFOR_IMAGE` | `ghcr.io/svlic/tfor:latest` | 镜像地址；生产部署建议固定版本标签或 digest |
| `TFOR_BIND_ADDRESS` | `127.0.0.1` | 宿主机端口绑定地址 |
| `TFOR_PUBLISHED_PORT` | `8000` | 宿主机端口，例如改为 `8080` |

日志级别和任务并发等参数见下方“配置”。容器内固定监听 `0.0.0.0:8000`，数据库固定使用 `/app/data/tfor.db`，不使用 `.env` 中的 `TFOR_HOST`、`TFOR_PORT` 和 `TFOR_DATABASE_PATH`。

### 数据持久化与更新

`./data` 挂载到容器的 `/app/data`，首次启动自动创建数据库。重建容器或执行 `docker compose down` 不会删除宿主机的 `./data`。该目录含账号凭据和可复用 Session，请限制访问，勿提交或公开。升级前先停机备份，数据库升级会在启动时自动执行：

```bash
docker compose pull
docker compose stop
tar -czf "tfor-data-$(date +%Y%m%d-%H%M%S).tar.gz" data
docker compose up -d --no-build
```

备份同样含敏感数据，请妥善保存。保持单实例运行，不要增加副本或 Uvicorn worker，以免重复监听和发送消息。

### 从源码构建

不依赖 GHCR，直接在项目目录构建当前主机架构的镜像并启动：

```bash
docker compose build --pull
docker compose up -d --no-build --pull never
```

### GitHub Actions 多架构镜像

工作流位于 `.github/workflows/docker.yml`，使用 Buildx + QEMU 一次构建 `linux/amd64` 和 `linux/arm64`，发布到 `ghcr.io/<仓库所有者>/tfor`（仓库名与所有者自动转为小写）。Fork 或更改仓库名后，请相应修改 `.env` 的 `TFOR_IMAGE`。

- 推送到 `main`：发布 `latest` 和 `sha-<短提交号>` 标签。
- 推送版本标签（例如 `v1.2.3`）：发布 `1.2.3`、`1.2` 和提交标签。
- 提交针对 `main` 的 Pull Request：只验证双架构构建，不登录仓库、不推送镜像。
- 在 Actions 页面手动运行：构建并发布所选分支或标签；默认分支会更新 `latest`。

发布使用 GitHub 自动提供的 `GITHUB_TOKEN`，无需另配 Docker Hub 密钥。请确保仓库允许 Actions 写入 Packages；首次发布后在 GHCR 软件包设置中确认可见性。工作流文件提交到 GitHub 后才会执行。

## 本地 Python 运行

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
set -a
. ./.env
set +a
uvicorn tfor.main:app --host 127.0.0.1 --port 8000
```

访问 `http://localhost:8000`。首次启动会自动创建 SQLite 数据库。应用本身不会自动读取 `.env`，上述命令显式将其导出到环境变量。

## 配置

- `TFOR_DATABASE_PATH`：SQLite 文件路径，默认 `./data/tfor.db`
- `TFOR_HOST` / `TFOR_PORT`：Docker 启动时使用的监听地址与端口
- `TFOR_LOG_LEVEL`：日志级别，默认 `INFO`
- `TFOR_MAX_CONCURRENT_RULES`：同时执行的规则数上限，默认 `10`
- `TFOR_MAX_PENDING_RULES`：内存中等待或执行的普通规则任务上限，默认 `1000`；达到上限后对消息入口施加背压
- `TFOR_MAX_CONCURRENT_COPIES`：全局同时下载并重新上传媒体的 Copy 任务上限，默认 `4`
- `TFOR_MAX_CONCURRENT_COPIES_PER_ACCOUNT`：单账号同时执行的媒体 Copy 任务上限，默认 `2`
- `TFOR_INLINE_FLOOD_WAIT_SECONDS`：进程内直接等待 FloodWait 的最大秒数，默认 `60`；更长等待会写入 SQLite 延后队列

也可以在“系统设置”中配置新账号默认使用的 Telegram `api_id` / `api_hash`。

过滤流水线的值按一行一个填写，任意一个值命中即可（ANY）。输入框默认可显示约 5 行内容，需要查看更多行时可拖动右下角向下扩高。

所有过滤字段在执行包含、完全匹配或正则匹配前，都会先移除 Unicode 默认可忽略字符（零宽字符、软连字符、双向控制符、变体选择符、隐藏标签、韩文填充符等）及非空白的 C0/C1 控制字符，再进行 NFKC 规范化。例如 `ＡＢＣ`、`𝐀𝐁𝐂` 可匹配 `ABC`，`🉑️` 可匹配 `可`，分解形式的重音字符会合成为等价字符。不间断空格、全角空格等兼容空白会转换为普通空格，但不会删除空格、合并连续空白或移除换行、制表符。不会抹除有语义的重音、元音符号，也不会混同拉丁字母与西里尔字母等跨语言相似字母。

此处理对黑白名单均生效，仅影响匹配，不修改原始消息、转发内容或保存的规则。包含和完全匹配的配置值也执行相同规范化；仅含可移除字符的配置值视为不命中，避免空字符串误匹配所有消息。**正则表达式本身不做规范化**，以免改变语法或转义；正则应针对规范化后的文本编写，例如全角冒号 `：` 用 `:` 匹配，`🉑` 用 `可` 匹配，空白仍可用 `\s` 匹配。

规则的正文过滤对相册只检查第一条非空 Caption。规则可按媒体类型过滤相册，媒体被过滤后不会单独发送其 Caption。也可启用“相册仅发送带 Caption 的媒体”：启用后，同一相册中只有主 Caption 所属的媒体会被发送；没有 Caption 的相册不会发送。该选项不影响普通单条消息。

普通 Forward 和文本发送允许在全局规则上限内并发，不额外强制单账号串行。同一来源消息的即时规则共享消息或相册读取；延迟规则到期后仍重新读取。媒体 Copy 另受全局和单账号并发上限约束。应用统一处理 Telethon 的 FloodWait：短等待在当前任务内重试，长等待持久化，Slow Mode 等待按账号与目标聊天共享。

## 测试

```bash
pytest
```
