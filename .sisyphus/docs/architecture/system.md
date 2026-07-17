# 系统需求与架构（半实现：代码与本地验证完成，待实机验收）

## 一句话目标

让 WSL 中运行的 OpenCode 在真正需要用户注意时，通过 HTTP 通知 Windows 显示 Toast、播放对应声音，或同时执行两者。

## 目标用户

首版优先服务作者当前的 WSL + Windows Terminal 环境，同时保留可配置地址、共享令牌和 Windows 呈现映射，供其他 Windows/WSL 用户复用。

## 核心需求

1. 可靠识别权限请求、问题请求、主会话完成、子代理完成、错误和取消。
2. 完成通知必须来自真实活动结束，不能因空闲回放、重复 idle 或隐藏会话状态误报。
3. Windows 不在线时，OpenCode 继续正常运行。
4. Windows 本地页面按事件展示说明，并提供 Toast 开关、声音开关、声音选择和试听。
5. 自定义声音来自项目 `sounds/` 目录中的 WAV。

## 首版事件

- `permission`
- `question`
- `complete`
- `subagent_complete`
- `error`
- `cancelled`

首版不实现启动、用户消息、客户端连接或计划退出通知。没有真实使用需求前，不预留这些事件。

## 明确非目标

- 通知历史、事件数据库或历史页面。
- Windows 到 OpenCode 的反向控制。
- 远程配置页面或局域网管理。
- 离线补发、可靠队列或 exactly-once 投递。
- 服务端事件去重；重复逻辑事件必须在插件源头消除。
- 自动安装、自动启动或 Windows Service。
- WAV 上传、文件管理、MP3、音量控制或声音队列。
- 旧版 deprecated `session.idle` 兼容。

## 系统边界

### WSL 插件

TypeScript OpenCode server plugin 负责：

- 维护主会话和子会话的活动状态。
- 把 `busy/retry → idle` 转换成完成事件。
- 把 abort 错误统一转换成 `cancelled`。
- 合并 `permission.asked` 与 `permission.ask` 的重复权限信号。
- 生成六类最小 HTTP 载荷。
- fire-and-forget 发送短超时请求。

插件不显示通知、不播放声音、不保存历史，也不读取 Windows 呈现配置。

### Windows 服务

Python FastAPI 服务负责：

- 验证事件请求的 Bearer 令牌和 Pydantic 载荷。
- 根据当前事件映射决定 Toast、声音、两者或静默。
- 用 `win11toast` 显示 Toast，用 `winsound` 播放系统声音或项目 WAV。
- 提供仅限 loopback 的本地配置页、配置读取/保存和声音试听。
- 原子保存事件映射并立即用于下一事件。

Windows 不查询 OpenCode，也不重新判断会话语义。

## 核心模块

1. **插件状态与事件入口**：会话状态、父子关系、权限去重和六类事件映射。
2. **插件 HTTP sender**：短超时、无重试、非阻塞投递。
3. **Windows FastAPI 服务**：事件鉴权、载荷校验和本地配置 API。
4. **Windows 通知后端**：Toast、声音 catalog 和试听。
5. **静态配置页**：原生 HTML/CSS/JavaScript，不使用前端框架或构建链。

## 数据流

1. OpenCode 发布 `session.status`、`session.error`、`permission.asked`，或调用 `permission.ask` / question hook。
2. 插件状态判断该输入是否构成六类逻辑事件之一。
3. 插件立即在后台发送 `POST /v1/events`，hook 不等待网络完成。
4. Windows 验证令牌和载荷，读取当前事件映射。
5. Windows 调用 Toast、声音、两者，或直接返回。
6. 用户在 Windows 本地页面修改映射；服务原子保存并立即应用。

## 外部依赖

### 插件端

- `@opencode-ai/plugin`
- 运行时内置 `fetch`
- `mohak34/opencode-notifier` 的 MIT 事件处理实现参考

不依赖 `node-notifier`、`is-wsl` 或任何 WSL 声音工具。

### Windows 端

- Python 3.11+
- FastAPI、Uvicorn、Pydantic
- `win11toast`
- Python 标准库 `winsound`

## 性能与安全约束

- 插件 HTTP 超时默认 500ms，合法范围 100..2000ms。
- 插件不重试；连续失败日志最多每 30 秒一次。
- Windows 事件端点始终验证共享令牌并使用常量时间比较。
- 配置页面、`GET/PUT /v1/config` 和 `POST /v1/preview` 只允许 `127.0.0.1` 或 `::1`。
- Windows 监听 `0.0.0.0` 时，用户必须用防火墙限制访问范围。
- 日志不得记录 Authorization header、完整令牌或完整配置。

## 锁定项与可调项

### 已锁定

- 六类事件和双端职责边界。
- 只消费 `session.status`，忽略 deprecated `session.idle`。
- `cancelled` 统一取消语义。
- 500ms 默认超时、无重试、非阻塞。
- Windows 本地配置页、项目 `sounds/` 和服务端试听。
- 事件端点 Bearer 鉴权；配置能力仅限 loopback。
- 单向通知、无历史、无服务端去重。

### 可调

- 内部函数和类型名称。
- Toast 图标、页面样式和非语义文案。
- 日志格式。
