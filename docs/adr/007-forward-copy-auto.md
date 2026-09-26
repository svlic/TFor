# ADR-007：提供 Forward、Copy 和 Auto 发送模式

- 状态：Proposed
- 日期：2026-09-26
- 相关提交：[`616b9e2`](https://github.com/svlic/TFor/commit/616b9e2dcbd634a50640d576440d63ec80fffb56)、[`cd59c27`](https://github.com/svlic/TFor/commit/cd59c270eb34c6b801aa1f126978646dc5912d61)

## 背景

Telegram 原生转发可以保留来源信息，但来源可能禁止转发；Copy 可以绕开该限制和媒体筛选后的结构变化，但会产生下载、内存和重新上传成本。

## 决策

提供三种发送模式：

- `forward`：始终请求 Telegram 原生转发；失败时不自动 Copy。
- `copy`：重新发送文本或下载并上传媒体。
- `auto`：优先 Forward；只有媒体筛选改变原结构或 Telegram 明确禁止转发时才改为 Copy，不用 Copy 掩盖普通权限、网络或目标错误。

Copy 应尽力保留文本格式、caption、文件名、voice 属性和相册语义，不承诺所有 Telegram 类型都能无损复制。

临时错误最多重试 3 次；FloodWait 按 Telegram 指定时间等待。默认不超过 60 秒的 FloodWait 在原 task 中等待，更长等待写入 SQLite 持久队列，并在到期后重放整条规则。部分发送成功后重放导致重复是可接受的退化行为。

## 可确认的实现事实

- Auto 只捕获 `ChatForwardsRestrictedError` 进行失败降级。
- Copy 把媒体下载到独立临时目录，发送完成后删除，避免把整份媒体保存在 Python 内存中。
- 媒体被类型过滤后不会单独发送其 Caption；如果相册主 Caption 所属媒体被过滤，其余媒体发送时也不携带该 Caption。
- 规则可选择只发送相册中带 Caption 的媒体；该选择改变相册结构，因此 Auto 使用 Copy。显式 Forward 仍原生转发选中的单条媒体。
- 当前没有单文件大小或临时磁盘总量限制；媒体 Copy 除全局规则上限外，还受默认全局 4、单账号 2 的独立并发上限约束。纯文本 Copy 不占媒体 Copy 槽。
- `TFOR_INLINE_FLOOD_WAIT_SECONDS` 控制进程内等待阈值，SQLite `deferred_jobs` 保存更长等待。
- Telethon 客户端关闭自动 FloodWait 休眠，并单独负责有限的 RPC 服务端错误重试；应用负责 FloodWait 和网络错误，避免重试叠加。Slow Mode 等待在内存中按账号与目标聊天共享。
- 已发送消息 ID 只在内存中短暂保存，用于降低回流风险。

## 后果

- 三种模式清晰区分来源保留、可发送性和资源成本。
- 大媒体或高并发 Copy 仍可能造成较高临时磁盘、带宽和耗时。
- 持久任务通过租约避免正常运行时重复认领，但没有 exactly-once 保证；进程故障后允许重放。

## 未决问题

- 单文件、单相册和全局允许的媒体大小及临时磁盘上限是多少？
- 是否需要跨重启持久化防回流或幂等状态？
