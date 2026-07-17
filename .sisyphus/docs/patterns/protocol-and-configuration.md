# 协议、配置与代码规范（未实现，已锁定）

## 目标目录结构

```text
opencode-windows-notifier/
├── plugin/
│   ├── src/
│   │   ├── index.ts
│   │   ├── config.ts
│   │   ├── state.ts
│   │   └── sender.ts
│   ├── tests/
│   ├── config.example.json
│   ├── package.json
│   └── tsconfig.json
├── server/
│   ├── src/opencode_windows_notifier/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── app.py
│   │   ├── config.py
│   │   ├── notifier.py
│   │   └── static/index.html
│   ├── tests/
│   ├── config.example.json
│   └── pyproject.toml
├── sounds/
│   └── README.md
├── protocol/
│   └── event-v1.example.json
├── LICENSE
├── THIRD_PARTY_NOTICES.md
└── README.md
```

不得创建独立 dedupe、admin、models、utils 或 helpers 模块。小型协议模型放在 `app.py`，配置状态放在 `config.py`，声音 catalog 放在 `notifier.py`。

## 事件类型

首版只支持：

- `permission`
- `question`
- `complete`
- `subagent_complete`
- `error`
- `cancelled`

插件发送全部六类事件。Windows 默认呈现前五类主会话事件；`subagent_complete` 默认 Toast 和声音均关闭。

## HTTP 契约

### 事件端点

```http
POST /v1/events
Authorization: Bearer <shared-token>
Content-Type: application/json
```

### 最小载荷

```json
{
  "event": "complete",
  "timestamp": "2026-07-17T00:00:00.000Z",
  "session_title": "Implement notifier",
  "project_name": "opencode",
  "duration_ms": 18342,
  "message": "Session has finished: Implement notifier"
}
```

字段约束：

- `event`：六类事件之一。
- `timestamp`：带时区的 UTC ISO 8601 时间。
- `session_title`：允许 `null`。
- `project_name`：允许 `null`，默认仅发送宿主目录 basename。
- `duration_ms`：完成类事件为非负整数，其他事件允许 `null`。
- `message`：非空用户可见文本。

`/v1/events` 已承担版本边界，载荷不重复携带 schema version。Windows 不消费 session ID、parent ID、agent name 或 event ID，因此这些字段不进入协议。

`opencode-windows-notifier/protocol/event-v1.example.json` 是两端契约测试样例。

### 响应

- `204 No Content`：事件已按当前 Windows 映射处理或静默接收。
- `401 Unauthorized`：Bearer 令牌缺失或错误。
- `422 Unprocessable Entity`：使用 FastAPI 默认的请求校验响应。

首版不定义成功响应模型，也不改写 FastAPI 默认校验状态码。

## WSL 插件配置

默认路径：

```text
~/.config/opencode/opencode-windows-notifier.json
```

可用 `OPENCODE_WINDOWS_NOTIFIER_CONFIG_PATH` 覆盖路径。

```json
{
  "server_url": "http://172.20.48.1:8765",
  "token": "replace-with-a-long-random-token",
  "timeout_ms": 500
}
```

规则：

- `server_url` 不含 `/v1/events`，插件固定追加该路径。
- `token` 必填。
- `timeout_ms` 默认 500，范围 100..2000。
- 未知键报错；插件配置不包含事件、Toast 或声音开关。
- 配置无效时插件记录一次错误并停用自身，不影响 OpenCode。
- 首版不热重载，修改后重启 OpenCode。

## Windows 服务配置

默认路径：

```text
%LOCALAPPDATA%\opencode-windows-notifier\config.json
```

可用 `python -m opencode_windows_notifier --config <path>` 覆盖路径。

```json
{
  "listen_host": "0.0.0.0",
  "listen_port": 8765,
  "token": "replace-with-the-same-long-random-token",
  "events": {
    "permission": { "toast": true, "sound": { "enabled": true, "source": "alias:SystemExclamation" } },
    "question": { "toast": true, "sound": { "enabled": true, "source": "alias:SystemQuestion" } },
    "complete": { "toast": true, "sound": { "enabled": true, "source": "alias:SystemAsterisk" } },
    "subagent_complete": { "toast": false, "sound": { "enabled": false, "source": "alias:SystemAsterisk" } },
    "error": { "toast": true, "sound": { "enabled": true, "source": "alias:SystemHand" } },
    "cancelled": { "toast": true, "sound": { "enabled": false, "source": "alias:SystemAsterisk" } }
  }
}
```

声音 source：

- `alias:<name>`：受控 Windows 系统声音别名。
- `wav:<filename>`：`opencode-windows-notifier/sounds/` 的直接 `.wav` 文件。

`sound.enabled` 与 source 分开保存，使取消勾选后仍保留上次选择。

服务启动时验证端口、非空令牌、完整六事件映射和声音 source。`wav:` 只允许单个文件名，不允许路径分隔符、绝对路径或 `..`。无效配置使服务以非零状态退出。

## 本地配置页与 API

FastAPI 直接提供一个原生 HTML/CSS/JavaScript 页面。每个事件显示事件名、说明、Toast checkbox、Sound checkbox、声音 select 和试听按钮。

页面只管理六类事件的呈现映射，不修改监听地址、端口、令牌或 WSL 配置。

### Routes

- `GET /`：返回配置页面。
- `GET /v1/config`：返回六类事件说明、当前映射和声音列表。
- `PUT /v1/config`：验证完整六事件映射，原子写入配置并立即应用。
- `POST /v1/preview`：播放一个已枚举声音，不修改配置、不显示 Toast。

`GET /` 和三个配置能力只允许实际 TCP 客户端地址为 `127.0.0.1` 或 `::1`。其他来源直接返回 `403`，不提供令牌登录或远程管理模式。

保存流程：先验证新映射，在配置同目录写临时文件，再用 `os.replace` 原子替换。只有文件替换成功后才更新进程内配置；失败时旧文件和旧配置继续生效。

## 声音 catalog

- 系统声音来自代码内白名单。
- WAV 每次读取配置页时扫描 `opencode-windows-notifier/sounds/` 的直接 `.wav` 文件。
- API 只返回声音 ID 和显示名，不返回任意文件路径。
- 试听只接受当前 catalog 中的声音 ID。
- 首版不上传、删除、重命名或扫描子目录。

## 鉴权与安全

- 只有 `POST /v1/events` 使用共享 Bearer 令牌。
- 使用 `HTTPBearer(auto_error=False)` 和 `hmac.compare_digest`。
- 配置页面及配置 API 只接受 loopback，不读取远程 token。
- 真实配置与令牌不进入 Git、响应或日志。

## 错误处理

### 插件

- 配置错误：记录一次并停用插件。
- 会话标题查询失败：发送 `null` 标题，不丢失事件。
- 网络失败、非 2xx 或超时：限频警告，不重试、不抛回 OpenCode。
- fire-and-forget Promise 必须捕获 rejection。

### Windows

- 鉴权或协议错误不调用通知后端。
- Toast 和声音分别捕获异常；一个失败不阻止另一个。
- 配置保存失败保留旧配置。

## 日志与命名

- 日志只记录时间、级别、事件类型和结果，不记录 token 或完整配置。
- TypeScript 使用 `camelCase` / `PascalCase`，Python 使用 `snake_case` / `PascalCase`，wire payload 使用 `snake_case`。
- 状态判断只在插件 state/index，HTTP 只在 sender，Windows 呈现只在 notifier。
