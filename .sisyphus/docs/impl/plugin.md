# WSL OpenCode 插件实现参考（已实现）

## 职责

插件把 OpenCode 原始事件转换为六类稳定逻辑事件，并在后台全部发送到 Windows。插件不显示通知、不播放声音、不保存历史，也不读取 Windows 呈现配置。

## 文件边界

- `opencode-windows-notifier/plugin/src/config.ts`：读取并验证 URL、token 和 timeout。
- `opencode-windows-notifier/plugin/src/hooks.ts`：OpenCode hooks、事件映射和逻辑事件类型。
- `opencode-windows-notifier/plugin/src/state.ts`：会话活动状态、父子关系和权限时间去重。
- `opencode-windows-notifier/plugin/src/sender.ts`：最小载荷与 HTTP 投递。
- `opencode-windows-notifier/plugin/src/index.ts`：只负责加载配置、组装 sender，并默认导出唯一插件入口。

OpenCode legacy 插件加载器会把入口模块中的每个运行时导出都视为插件。`index.ts` 不得导出 helper 或第二个插件函数；可测试 helper 必须放在内部模块中。

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
- `delayMs`

`delayMs` 是停止类通知延迟复查窗口，默认 8000，范围 1000..60000。它必须大于 `opencode-auto-continue` 的 5 秒复查延迟，否则会在会话恢复动作发生前就把通知发出去。

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
- `session.status: idle`：仅当 `active = true` 时关闭活动并进入延迟复查，通过后发送一次 `complete` 或 `subagent_complete`。
- `session.error`：立即设 `active = false`；abort 名称发送 `cancelled`，其他错误进入延迟复查。随后 idle 因不活动而被忽略。
- deprecated `session.idle`：不处理。
- `session.deleted`：删除状态。

首版不使用 generation、idle timer、sequence 或定时清理。当前 OpenCode 在错误后发布 idle，`active = false` 已自然抑制重复完成。

### 停止类通知延迟复查

`complete`、`subagent_complete` 和普通 `error` 不立即发送。`hooks.ts` 抄 `opencode-auto-continue` 的尾部复查形状：

主会话 `complete` 在进入延迟窗口前，先通过 `client.session.children` 查询直属子会话，再用 `client.session.status` 查询状态。任一直属子会话处于 `busy` 或 `retry` 时，丢弃本次完成提醒，不设置定时器或自动补发。全部空闲（状态表中缺失的会话按空闲处理）时继续以下流程；查询失败时沿用原通知流程。此检查不影响 `subagent_complete` 或其他通知。

1. 事件到达时读取 `client.session.messages(...)`，记录尾部 `info.id`，然后设置 `delayMs` 定时器。
2. 定时器到点时再次读取尾部 id。
3. 尾部 id 未变 → 会话确实停止，发送通知；尾部 id 已变 → auto-continue 或用户已推进会话，丢弃该通知。
4. 读取失败时无法验证，直接发送，宁可误报也不漏掉真实停止。
5. 同一 session 的新停止类通知会替换仍在等待的旧定时器。

目的：`opencode-auto-continue` 会在 `session.error` 或空回复 / `finish === "unknown"` / DSML 结束的 `session.idle` 后约 5 秒尝试恢复。立即发送的错误或完成通知因此常是误报。已知残余风险：auto-continue 处于 60 秒冷却期时会把恢复推迟到冷却结束，超过 `delayMs` 的连续失败仍可能误报。

`cancelled` 不受延迟影响，因为 auto-continue 明确排除用户中断错误，不会恢复这类会话。`permission`、`question` 同样即时发送。

## 父子会话

- `session.created/updated` 的 `info.parentID` 是父子关系真相源。
- metadata 未知时，完成前允许调用 `client.session.get` 补查标题和 `parentID`。
- 查询失败时保留已知判断；完全未知按主会话发送，标题为 `null`。

父子信息只用于选择 `complete` 或 `subagent_complete`，不进入 HTTP 载荷。

## 事件映射

| OpenCode 输入 | 输出 |
|---|---|
| 活动主会话 `session.status: idle` | `complete`，延迟复查后发送 |
| 活动子会话 `session.status: idle` | `subagent_complete`，延迟复查后发送 |
| 普通 `session.error` | `error`，延迟复查后发送 |
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
- Windows 连接拒绝、超时和非 2xx 响应全部静默丢弃，不记录 warning，不影响 OpenCode。

## 插件入口

1. 加载配置；失败时返回 `{}`。
2. 创建内存 state 和 sender。
3. 返回 `event`、`permission.ask`、`tool.execute.before` hooks。
4. hooks 只等待必要的 OpenCode metadata 查询，不等待 HTTP；错误延迟复查只等待一次尾部消息读取。

## 测试要点

覆盖 `opencode-windows-notifier/.sisyphus/docs/patterns/testing.md` 的插件端必测项。状态测试直接输入事件序列，不使用真实 timer 或网络。
