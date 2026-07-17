# 测试策略（半实现：自动验证完成，实机验收待执行）

## 测试目标

测试只证明原始需求：插件不误报完成、不重复发送逻辑事件、网络失败不影响 OpenCode，Windows 能安全接收并按本地配置显示 Toast 或播放声音。

## 当前验证状态

- 插件 22 项 Bun 测试通过，TypeScript 类型检查通过。
- Windows 服务 23 项 pytest 测试通过，生产源码与测试均无 LSP 错误。
- 真实 HTTP 页面/配置请求返回 200，协议样例事件返回 204。
- Playwright 已验证桌面与 390px 移动布局、六事件渲染、试听、保存、刷新持久化、无横向溢出和零 console error。
- Windows Toast、winsound WAV 与真实 OpenCode WSL 六项手工联调尚未执行；Linux 验证使用注入的 mock 通知后端，不得视为实机通过。

## 插件端必测

### 会话状态

- 未观察到 `busy/retry` 时收到 `session.status: idle`，不发送完成事件。
- `busy → idle` 发送一次 `complete`。
- `busy → retry → busy → idle` 仍只发送一次完成事件。
- `busy → session.error → idle` 只发送 `error`。
- `MessageAbortedError` 和 `AbortError` 都只发送 `cancelled`。
- deprecated `session.idle` 被忽略。
- 连续两轮 `busy → idle` 分别发送两次完成事件。

### 父子会话与交互事件

- `session.created/updated` 的 `parentID` 能区分 `complete` 和 `subagent_complete`。
- `session.deleted` 清理会话状态。
- `permission.asked` 与 `permission.ask` 在 1 秒内只发送一次 `permission`。
- question hook 发送一次 `question`。
- 不产生首版六类之外的事件。

### 配置与 HTTP

- 缺失、损坏、空令牌、无效 URL 和越界 timeout 会停用插件。
- 配置路径来自用户目录或显式覆盖，不使用 `PluginInput.directory`。
- 请求使用 `/v1/events`、Bearer header 和最小载荷。
- hook 不等待 HTTP 完成。
- 500ms 超时、连接拒绝和非 2xx 不重试、不产生未处理 rejection。
- 连续失败日志最多每 30 秒一次。

## Windows 服务必测

### 事件接收

- 合法令牌和载荷返回 `204`。
- 缺失或错误令牌返回 `401`。
- 未知事件或非法字段由 FastAPI 返回 `422`。
- 两个合法请求分别执行，不存在服务端去重状态。

### 呈现与声音

- `toast: true` 调用 `win11toast.notify`，`toast: false` 不调用。
- `sound.enabled: true` 根据 `alias:` 或 `wav:` 调用 `winsound`。
- `sound.enabled: false` 不播放，但保留 source。
- Toast 和声音任一失败不阻止另一通道，也不使服务退出。
- 非 WAV、子目录、绝对路径、`..` 和未枚举声音不能进入 catalog 或试听。

### 本地配置页

- `GET /`、`GET/PUT /v1/config`、`POST /v1/preview` 对 loopback 可用，对非 loopback 返回 `403`。
- `GET /v1/config` 返回六类事件、说明、当前映射和声音列表。
- `PUT /v1/config` 要求完整六事件映射。
- 保存成功后文件和内存配置同时更新，下一事件立即使用新配置。
- 原子写入失败时旧文件和旧配置保持不变。
- 试听只播放声音，不修改配置、不显示 Toast。

## 协议契约测试

`opencode-windows-notifier/protocol/event-v1.example.json` 必须同时通过 TypeScript 载荷测试和 Windows Pydantic 模型测试。事件枚举或字段变化时，两端测试和 docs 必须在同一变更中更新。

## 手工集成验证

1. 在 Windows 手动启动服务并打开本地配置页，确认六类事件和声音列表可见。
2. 从 WSL 发送带令牌的固定样例，确认 Windows 按当前映射 Toast/播放声音。
3. 执行一轮主会话和一轮子代理任务，确认各只产生一次对应完成事件；子代理默认静默，网页开启后生效。
4. 触发权限、问题和双 Esc 取消，确认事件与声音正确，取消后没有完成通知。
5. 把项目 WAV 选为某事件声音，试听并保存，确认下一事件立即使用该 WAV。
6. 停止 Windows 服务后运行 OpenCode，确认 OpenCode 不被阻塞且警告限频。

## 不必自动化测试

- Toast 和页面的像素级样式。
- 用户 WAV 的音质。
- 通知中心历史、远程管理、自动启动和文件上传；首版不实现这些能力。
