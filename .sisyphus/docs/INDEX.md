# opencode-windows-notifier — Docs Index

Project: opencode-windows-notifier/
Purpose: 记录 OpenCode WSL 事件投递到 Windows Toast 与声音服务的最小需求、架构、协议、实现约束和验收标准。

## Summary

本项目当前处于**未实现、设计已锁定**状态：公开 GitHub 仓库和 docs 控制面已经建立，尚无插件或 Windows 服务实现。首版只处理 `permission`、`question`、`complete`、`subagent_complete`、`error` 和 `cancelled` 六类需要用户注意的事件。

系统由 WSL TypeScript 插件和 Windows Python FastAPI 服务组成。插件判断 OpenCode 会话语义并把全部六类逻辑事件非阻塞发送到 Windows；Windows 通过本地单页配置决定每类事件是否 Toast、是否播放系统声音或项目 `sounds/` 中的 WAV。首版不做服务端事件去重、通知历史、远程配置或反向控制。

## 全局约束

- 完成事件只能来自 `session.status` 的真实 `busy/retry → idle`；没有活动状态的 `idle` 必须忽略。
- 首版只使用当前 `session.status`，不消费 deprecated `session.idle`，不承担旧版兼容。
- WSL 插件发送全部六类逻辑事件；是否呈现只能由 Windows 决定。
- HTTP 投递默认 500ms 超时、无重试、非阻塞；Windows 不在线不得影响 OpenCode。
- `POST /v1/events` 始终要求共享 Bearer 令牌。
- 配置页面和配置 API 只允许 Windows loopback 访问，不提供远程管理。
- 自定义声音只能来自 `opencode-windows-notifier/sounds/`，API 不接受任意文件路径。
- 两端真实配置和共享令牌不得提交到 Git，日志不得输出令牌。
- 复制或改造 `mohak34/opencode-notifier` 的 MIT 代码时必须保留许可证和来源说明。

## 需求与架构

- [opencode-windows-notifier/.sisyphus/docs/architecture/system.md](architecture/system.md) — 未实现、已锁定：最小需求、非目标、两端职责和数据流。

## 模式与抽象

- [opencode-windows-notifier/.sisyphus/docs/patterns/protocol-and-configuration.md](patterns/protocol-and-configuration.md) — 未实现、已锁定：六类事件、最小 HTTP 载荷、两端配置和三个管理 API。
- [opencode-windows-notifier/.sisyphus/docs/patterns/testing.md](patterns/testing.md) — 未实现、已锁定：状态机、投递、鉴权、配置和声音的必要测试。

## 实现参考

- [opencode-windows-notifier/.sisyphus/docs/impl/plugin.md](impl/plugin.md) — 未实现、已锁定：四模块 WSL 插件、会话状态和 HTTP 投递。
- [opencode-windows-notifier/.sisyphus/docs/impl/windows-server.md](impl/windows-server.md) — 未实现、已锁定：四模块 Windows 服务、通知后端和本地配置页。
- [opencode-windows-notifier/.sisyphus/docs/impl/implementation-order.md](impl/implementation-order.md) — 未实现、已锁定：七步实现顺序、锁定项和验收标准。
