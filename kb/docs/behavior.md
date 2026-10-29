# 业务语义与修改边界

修改相关模块时阅读；本文描述当前实现，不替代代码和测试。行为变化时同步维护本文。

## 账号与规则

实现：`tfor/main.py`、`tfor/db.py`、`tfor/telegram.py`；测试：`tests/test_db.py`。

- 每条规则绑定单个账号，由该账号访问来源和目标；仅支持群组和频道。允许重复规则，不添加目标去重或规则唯一约束。
- 账号移除采用归档：停用账号及关联规则但保留数据；恢复时还原各规则归档前的启用状态。修改手机号、API ID 或 API Hash 会清除旧 Session，要求重新登录。

## 过滤与相册

实现：`tfor/filters.py`、`tfor/main.py:parse_filters`、`tfor/telegram.py:_process_rule`；测试：`tests/test_filters.py`、`tests/test_telegram.py`。

- 过滤步骤按顺序执行，步骤内多值为 ANY；黑名单命中或白名单未命中即短路拒绝。保存时校验正则。
- 匹配前仅从待匹配字段移除 U+200B、U+200C、U+200D、U+2060、U+FEFF；不改原始消息、普通空白或配置值。包含、完全匹配和正则匹配均忽略大小写。
- 相册正文过滤只检查第一条非空 Caption（主 Caption），不是逐条检查。媒体筛选移除主 Caption 所属媒体时，不单独发送该 Caption。
- `captioned_media_only` 仅影响相册：只保留主 Caption 所属媒体，再应用媒体类型筛选；相册无 Caption 则不发送。普通单条消息不受此选项影响。

## 发送与调度

实现：`tfor/telegram.py`；测试：`tests/test_telegram.py`。

- `forward` 不自动降级；`copy` 重新发送；`auto` 仅在筛选改变消息集合（媒体类型或相册 Caption 选项），或转发遇到 `ChatForwardsRestrictedError` 时改用 Copy，其他错误不能触发降级。
- 同一来源消息的即时规则共享消息或相册读取；普通延迟任务到期、持久化任务恢复时，重新读取规则和源消息，源消息不存在则不发送。
- 全局规则并发与普通任务数量均有上限，后者对入口施加背压；普通延迟不占规则执行槽。媒体 Copy 另受全局及单账号上限约束，普通 Forward 和纯文本发送不强制单账号串行。
- Telethon 自动 FloodWait 等待已关闭，由应用统一处理：短等待在任务内重试，长等待写入 SQLite `deferred_jobs`；Slow Mode 等待按账号与目标聊天共享。
- 普通延迟任务仅在内存中；不保证严格顺序或 exactly-once，故障重放可能重复发送。
- 下载再上传的媒体使用 `TemporaryDirectory` 并确保清理，不改成整份媒体常驻内存。后台任务须纳入启动、取消和退出管理。

## 存储与统计

实现：`tfor/db.py`、`tfor/config.py`；测试：`tests/test_db.py`。

- SQLite 使用标准库 `sqlite3`、短连接、外键和 WAL；SQL 值使用绑定参数。
- `source_events` 统计收到的源消息事件，`processing_logs` 统计规则执行，不能混用。两者目前均保留 3 天（`LOG_RETENTION_DAYS`）。
