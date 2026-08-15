## legacy-plugin-entry-runtime-exports
Date: 2026-07-19

### Symptom

插件的主要副作用已经成功发生，但 OpenCode 随后仍从同一个 hook 抛出类似 `emit is not a function` 的错误。以 notifier 为例，Windows 已收到 `question` 通知，WSL 端的 `question` 工具调用仍报错。

### Trigger Conditions

使用 legacy 路径直接加载 TypeScript 插件入口时，入口模块除了真正的插件函数，还导出了测试 helper 或其他运行时值。OpenCode legacy loader 会遍历入口模块的全部运行时导出，并把每个导出解析为插件；函数 helper 因而会被错误地按 `PluginInput` 调用并注册一套参数不完整的 hooks。相同函数引用会被去重，但不同 helper 函数不会。

### Resolution

让插件入口模块只保留一个运行时函数导出。将 hook 构造器、类型和其他可测试逻辑移入内部模块，测试直接导入内部模块。增加入口导出面测试，断言入口模块只有一个函数值，防止后续为测试方便重新导出 helper。

Tags: #plugin #opencode #typescript #runtime #trap
