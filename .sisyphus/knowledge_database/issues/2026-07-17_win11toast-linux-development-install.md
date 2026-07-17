## win11toast-linux-development-install
Date: 2026-07-17

### Symptom

在 WSL/Linux 中安装 Windows 通知服务的开发环境时，`uv pip install -e '.[dev]'` 会尝试从源码构建 `winrt-windows-*`，最终出现：

```text
ValueError: Unsupported compiler: unix
```

### Trigger Conditions

Python 项目把 `win11toast` 声明为无平台限制的运行依赖，同时又需要在 WSL/Linux 运行协议、FastAPI、配置和 mock 通知测试。`win11toast` 依赖 Windows Runtime 扩展，这些扩展只能在 Windows 构建或安装。

### Resolution

对纯 Windows 呈现依赖使用 PEP 508 平台标记，例如：

```toml
"win11toast>=0.36,<1; sys_platform == 'win32'"
```

生产代码在创建真实 Windows 后端时再动态导入 `win11toast` 和 `winsound`；跨平台自动测试向 notifier 注入 mock Toast/声音 callable。这样 Windows 安装仍获得真实依赖，WSL/Linux 可以验证协议、状态、HTTP 和配置逻辑，也不会把 mock 测试误报为 Windows 实机验收。

Tags: #windows #python #dependency #testing #trap
