# WSL OpenCode 插件实现参考（半实现：代码与自动测试完成，待真实联调）

## 职责

插件把 OpenCode 原始事件转换为六类稳定逻辑事件，并在后台全部发送到 Windows。插件不显示通知、不播放声音、不保存历史，也不读取 Windows 呈现配置。

## 文件边界

- `opencode-windows-notifier/plugin/src/config.ts`：读取并验证 URL、token 和 timeout。
- `opencode-windows-notifier/plugin/src/state.ts`：会话活动状态、父子关系和权限时间去重。
- `opencode-windows-notifier/plugin/src/sender.ts`：最小载荷与 HTTP 投递。
- `opencode-windows-notifier/plugin/src/index.ts`：OpenCode hooks 和事件映射。

## 上游复用

以 `mohak34/opencode-notifier` 的 MIT 实现为参考，只复用：

- 父子会话识别。
- 错误后抑制完成事件。
- 权限双入口的 1 秒去重。
- 会话标题读取与固定消息格式化。

不复制本地通知、声音、bell、命令、终端聚焦、全局 turn state、synthetic client event 或 deprecated idle 兼容逻辑。复制代码时必须在 `LICENSE` 和 `THIRD_PARTY_NOTICES.md` 保留归属。

## 配置

默认读取 `~/.config/opencode/opencode-windows-notifier.json`，可由 `OPENCODE_WINDOWS_NOTIFIER_CONFIG_PATH` 覆盖。

`PluginConfig` 只包含：

- `serverUrl`
- `token`
- `timeoutMs`

未知键或无效值使插件记录一次错误并返回空 hooks，不得使 OpenCode 启动失败。配置基于用户 home 解析，不得使用 `PluginInput.directory`。

## 会话状态

`state.ts` 为每个已知 session 保存：

```ts
interface SessionState {
  title: string | null
  isChild: boolean | null
  active: boolean
  startedAtMs: number | null
}
```

状态转换：

- `session.status: busy`：若未活动，设 `active = true` 并记录开始时间。
- `session.status: retry`：保持活动；若此前未活动，按新活动开始处理。
- `session.status: idle`：仅当 `active = true` 时关闭活动并发送一次 `complete` 或 `subagent_complete`。
- `session.error`：立即设 `active = false`；abort 名称发送 `cancelled`，其他错误发送 `error`。随后 idle 因不活动而被忽略。
- deprecated `session.idle`：不处理。
- `session.deleted`：删除状态。

首版不使用 generation、idle timer、sequence 或定时清理。当前 OpenCode 在错误后发布 idle，`active = false` 已自然抑制重复完成。

## 父子会话

- `session.created/updated` 的 `info.parentID` 是父子关系真相源。
- metadata 未知时，完成前允许调用 `client.session.get` 补查标题和 `parentID`。
- 查询失败时保留已知判断；完全未知按主会话发送，标题为 `null`。

父子信息只用于选择 `complete` 或 `subagent_complete`，不进入 HTTP 载荷。

## 事件映射

| OpenCode 输入 | 输出 |
|---|---|
| 活动主会话 `session.status: idle` | `complete` |
| 活动子会话 `session.status: idle` | `subagent_complete` |
| 普通 `session.error` | `error` |
| `MessageAbortedError` / `AbortError` | `cancelled` |
| `permission.asked` / `permission.ask` | `permission`，1 秒内合并 |
| `tool.execute.before` + `question` | `question` |

其他输入不产生通知事件。

## 最小载荷

`sender.ts` 构造：

```ts
interface EventPayload {
  event: "permission" | "question" | "complete" | "subagent_complete" | "error" | "cancelled"
  timestamp: string
  session_title: string | null
  project_name: string | null
  duration_ms: number | null
  message: string
}
```

- 项目名来自 `PluginInput.directory` basename；这里表达宿主上下文是正确用途。
- `duration_ms` 来自当前活动开始时间，只用于完成事件。
- 固定消息模板只使用事件、会话标题和项目名，不提供用户模板配置。

## HTTP sender

```ts
function sendEvent(config: PluginConfig, payload: EventPayload): void
```

- fire-and-forget，调用方不 await。
- 使用 `AbortController` 和 timer 实现超时。
- 固定 POST `/v1/events`，使用 JSON 和 Bearer token。
- 不重试。
- Promise 必须捕获全部 rejection。
- 网络、超时和非 2xx 警告按目标地址 30 秒限频。

## 插件入口

1. 加载配置；失败时返回 `{}`。
2. 创建内存 state 和 sender。
3. 返回 `event`、`permission.ask`、`tool.execute.before` hooks。
4. hooks 只等待必要的 OpenCode metadata 查询，不等待 HTTP。

## 测试要点

覆盖 `opencode-windows-notifier/.sisyphus/docs/patterns/testing.md` 的插件端必测项。状态测试直接输入事件序列，不使用真实 timer 或网络。
