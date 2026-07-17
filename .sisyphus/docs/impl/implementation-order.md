# 实现顺序与验收标准（未实现，已锁定）

## 实现原则

每一步先通过本步验证再继续。实现若发现六类事件、状态机或接口契约不成立，必须停止并回到用户确认，不得自行扩展功能。

## 实现顺序

1. 建立许可证、第三方来源说明、两端项目骨架、`sounds/` 和最小协议样例。 → verify: 目录与依赖边界符合 docs，协议样例可被两端测试读取。
2. 实现插件 state 和六类事件映射。 → verify: `busy/retry → idle`、错误/取消抑制、父子会话、权限去重和 deprecated idle 忽略测试通过。
3. 实现插件配置与 fire-and-forget sender。 → verify: URL/token/timeout 校验、204 成功、超时、连接失败、非 2xx、无重试和日志限频测试通过。
4. 实现 Windows 配置、事件模型、Bearer 鉴权和 `/v1/events`。 → verify: FastAPI TestClient 覆盖 `204/401/422`，合法事件按当前映射调用 notifier。
5. 实现 Toast、系统声音、项目 WAV catalog 和试听。 → verify: mock 测试覆盖双通道开关、alias、WAV、路径拒绝和部分失败隔离。
6. 实现 loopback 配置 API 和原生单页前端。 → verify: 本机读取/保存/试听、远程 403、完整映射校验、原子保存和立即生效测试通过。
7. 完成 README 和真实 Windows + WSL 联调。 → verify: 按测试文档的 6 项手工验证全部通过。

## 锁定项

- 六类事件：permission、question、complete、subagent_complete、error、cancelled。
- 只消费 `session.status`，不消费 deprecated `session.idle`。
- `busy/retry → idle` 完成条件和 `cancelled` 统一语义。
- WSL 发送全部六类逻辑事件，Windows 决定呈现。
- `/v1/events` 最小载荷和 Bearer 鉴权。
- 500ms 默认超时、无重试、非阻塞。
- 无 event ID、无 schema version 字段、无服务端去重。
- Windows 本地配置页、三个配置 API、项目 `sounds/` 和试听。
- 配置能力仅限 loopback。
- 单向通知、无历史、无反向控制。

## 可调项

- 内部函数和类型名称。
- 测试文件拆分。
- Toast 图标、页面样式和非语义文案。
- 日志格式。

改变事件枚举、wire payload、鉴权、配置位置或用户可见语义时，必须先更新 docs 并由用户确认。

## 首版验收标准

### 功能

- 主会话完成、子代理完成、错误、权限、问题和取消都能到达 Windows。
- 同一次运行只产生一个终态事件；取消或错误后没有完成通知。
- 子代理默认静默，网页开启后下一事件立即生效。
- Toast 和声音可独立开关，声音支持系统别名和项目 WAV。
- Windows 服务不可用时 OpenCode 正常运行。

### 安全与配置

- 错误或缺失令牌不能触发事件通知。
- 配置页面和 API 从非 loopback 访问时返回 403。
- 真实令牌和配置不出现在 Git、响应或日志。
- `0.0.0.0` 监听文档要求防火墙限制范围。

### 质量

- TypeScript 类型检查和插件单测通过。
- Python 单测通过。
- 上游 MIT 归属完整。
- README 手动步骤在真实 Windows + WSL 环境验证。
- 验证完成前 docs 状态保持“未实现”。

## 首版不包含

- 其他事件类型。
- Windows 自动启动。
- 通知历史或管理后台。
- 远程配置。
- 可靠队列、离线补发或服务端去重。
- 前端框架、Toast 按钮或回调。
- WAV 文件管理、MP3、音量、混音或声音队列。
