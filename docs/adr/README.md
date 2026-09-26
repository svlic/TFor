# Architecture Decision Records

本目录记录根据 Git 历史重建的架构决策。现有历史只有 2026-09-26 的 4 个可达提交，且实现提交是开发完成后按 core / web / deployment 重组的逻辑提交，因此无法恢复细粒度的原始决策顺序。

状态说明：

- **Proposed**：已从历史重建并补充了决策者意见，仍待逐份确认。
- **Accepted**：决策者已确认其内容可以作为项目当前架构约束。
- **Superseded**：已被后续 ADR 替代。

| ADR | 标题 | 状态 |
| --- | --- | --- |
| [ADR-001](001-python-modular-monolith.md) | 采用 Python 模块化单体和服务端渲染管理面 | Proposed |
| [ADR-002](002-sqlite-persistence.md) | 采用 SQLite 和原生 sqlite3 持久化 | Proposed |
| [ADR-003](003-telethon-user-accounts.md) | 使用 Telethon 用户账号和 StringSession | Proposed |
| [ADR-004](004-account-bound-rules.md) | 规则绑定单一账号并允许重复配置 | Proposed |
| [ADR-005](005-ordered-filter-pipeline.md) | 采用有序短路过滤流水线 | Proposed |
| [ADR-006](006-in-process-message-processing.md) | 使用进程内异步任务处理消息 | Proposed |
| [ADR-007](007-forward-copy-auto.md) | 提供 Forward、Copy 和 Auto 发送模式 | Proposed |
| [ADR-008](008-privacy-safe-observability.md) | 分离源消息与规则执行指标并最小化日志内容 | Proposed |
| [ADR-009](009-single-host-deployment.md) | 采用单主机部署并将认证交给部署环境 | Proposed |

## 后续需要单独决策的事项

以下事项不是当前实现已经完成的事实；若决定实施，应新增 ADR 或由后续 ADR 取代现有决策：

1. Telegram 处理服务是否从 Web 进程拆分。
2. 多实例运行、任务所有权和幂等机制。
3. 过滤步骤复用、嵌套或更强的可解释性模型。
4. 媒体文件大小、临时磁盘和任务积压限制。

## Git 证据

- [`2bbfadf`](https://github.com/svlic/TFor/commit/2bbfadf5cae47630614fae944dbada0d9476ee4f)：初始 README。
- [`616b9e2`](https://github.com/svlic/TFor/commit/616b9e2dcbd634a50640d576440d63ec80fffb56)：转发核心、数据模型与核心测试。
- [`cd59c27`](https://github.com/svlic/TFor/commit/cd59c270eb34c6b801aa1f126978646dc5912d61)：Web 管理控制台。
- [`e03d2a7`](https://github.com/svlic/TFor/commit/e03d2a7d130c1e6870cdd403a54e523a2a68d0fb)：单主机部署配置与 README。
