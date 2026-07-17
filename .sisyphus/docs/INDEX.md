# opencode-windows-notifier — Docs Index

Project: opencode-windows-notifier/
Purpose: 记录 OpenCode WSL 事件投递到 Windows Toast 与声音服务的最小需求、架构、协议、实现约束和验收标准。

## Summary

本项目已实现 WSL TypeScript 插件、Windows FastAPI 服务、中文原生配置页、独立音效试听页、收藏持久化、两级声音选择、430 个内置唯一音效、许可证、README 和 Windows uv 部署脚本。内置库包含 OpenCode 45 个当前音效及四个经许可核验的 CC0 UI 音效集合；重复编码和重复发行版不重复收录。插件 23 项测试与类型检查通过，服务 37 项测试通过。Windows 原生 Toast/WAV、试听页实际体验和真实 OpenCode WSL 六事件联调由用户在目标 Windows 环境手工验收，不代表代码仍有未实现模块。

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

- [opencode-windows-notifier/.sisyphus/docs/architecture/system.md](architecture/system.md) — 已实现：WSL 事件桥接、Windows 呈现和本地配置边界。

## 模式与抽象

- [opencode-windows-notifier/.sisyphus/docs/patterns/protocol-and-configuration.md](patterns/protocol-and-configuration.md) — 已实现：六类事件、最小 HTTP 载荷、两端配置和三个管理 API。
- [opencode-windows-notifier/.sisyphus/docs/patterns/testing.md](patterns/testing.md) — 已实现：自动测试与桌面浏览器验证完成，保留目标环境手工验收清单。

## 实现参考

- [opencode-windows-notifier/.sisyphus/docs/impl/plugin.md](impl/plugin.md) — 已实现：六事件状态机、配置和非阻塞 HTTP sender。
- [opencode-windows-notifier/.sisyphus/docs/impl/windows-server.md](impl/windows-server.md) — 已实现：服务、中文配置页、独立试听页、收藏、声音分组和通知后端。
- [opencode-windows-notifier/.sisyphus/docs/impl/implementation-order.md](impl/implementation-order.md) — 已实现：步骤 1–7 完成，环境手工验收独立记录。
