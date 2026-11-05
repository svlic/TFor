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

## Docker

```bash
docker compose up -d --build
```
