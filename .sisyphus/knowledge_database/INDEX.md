# opencode-windows-notifier — Knowledge Database Index

Project: opencode-windows-notifier/
Purpose: 记录本项目推进中可复用的设计决策、实现陷阱、问题修复和长期维护经验。

## Summary

当前知识库记录 Windows-only Python 通知依赖与 WSL/Linux 开发验证之间的长期边界，以及 OpenCode legacy 插件入口不能暴露 helper 等额外运行时导出的加载陷阱。最新实现状态、接口和验收要求维护在 `opencode-windows-notifier/.sisyphus/docs/`；这里仅解释可复用的安装与运行时判断方法。

---

## Decisions

## Issues

[issues/2026-07-17_win11toast-linux-development-install.md] — Windows-only WinRT 依赖需使用平台标记，并通过动态导入与 mock 支持 WSL/Linux 开发测试 #windows #python #dependency #testing #trap
[issues/2026-07-19_legacy-plugin-entry-runtime-exports.md] — Legacy 插件入口的额外函数导出会被误当插件执行，造成副作用成功后 hook 仍报错 #plugin #opencode #typescript #runtime #trap

## Learnings

## Tutorials

## Problems
