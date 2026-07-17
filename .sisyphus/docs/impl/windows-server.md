# Windows 通知服务实现参考（半实现：代码与本地验证完成，待 Windows 实机验收）

## 职责

Windows 服务验证六类事件请求，按本地事件映射显示 Toast 或播放声音，并提供仅限 Windows 本机的配置页面和试听能力。

服务不查询 OpenCode、不推断会话状态、不做事件去重、不保存历史，也不提供远程管理或反向控制。

## 文件边界

- `opencode-windows-notifier/server/src/opencode_windows_notifier/__main__.py`：解析 `--config` 并启动 Uvicorn。
- `opencode-windows-notifier/server/src/opencode_windows_notifier/app.py`：Pydantic 载荷、事件端点、loopback 配置 API 和静态页面。
- `opencode-windows-notifier/server/src/opencode_windows_notifier/config.py`：严格配置模型、内存配置和原子保存。
- `opencode-windows-notifier/server/src/opencode_windows_notifier/notifier.py`：Toast、声音 catalog、播放和试听。
- `opencode-windows-notifier/server/src/opencode_windows_notifier/static/index.html`：原生单页前端。

不创建独立 models、dedupe 或 admin 模块。

## 运行环境

Python 3.11+。

运行依赖：FastAPI、Uvicorn、`win11toast`。开发依赖：pytest、httpx。

首版只提供手动命令：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m opencode_windows_notifier
```

`__main__.py` 加载配置后把 host 和 port 交给 `uvicorn.run`。默认配置位于 `%LOCALAPPDATA%\opencode-windows-notifier\config.json`。

## 配置状态

`config.py` 使用严格 Pydantic 模型验证：

- `listen_host`
- `listen_port`
- 非空 `token`
- 完整六事件映射
- 每个事件的 `toast`、`sound.enabled` 和 `sound.source`

配置对象保存在一个带窄 `threading.Lock` 的状态容器中，提供读取当前配置和替换事件映射两个操作。无需通用 ConfigStore 抽象或 snapshot 类型。

保存事件映射时：

1. 验证完整六事件映射和声音 ID。
2. 基于当前配置生成新 JSON，不允许网页修改 host、port 或 token。
3. 在配置目录写临时文件并 flush。
4. 用 `os.replace` 替换原文件。
5. 成功后在 lock 内替换内存配置。

失败时旧文件和旧内存配置继续生效。

## `POST /v1/events`

`app.py` 直接定义六事件枚举和最小 Pydantic 载荷。

处理顺序：

1. 用 `HTTPBearer(auto_error=False)` 读取凭据。
2. 用 `hmac.compare_digest` 与配置 token 比较；失败返回 `401`。
3. 让 FastAPI 使用默认 Pydantic 校验；非法载荷返回 `422`。
4. 读取当前事件映射并调用 notifier。
5. 返回 `204 No Content`。

`win11toast.notify` 和 `winsound` 都使用非阻塞路径；事件端点直接调用 notifier 后返回 `204`。通知异常在 notifier 内捕获，不改变服务存活。

## 通知后端

`notifier.py` 根据事件映射分别处理两个通道：

- `toast = true`：调用 `win11toast.notify`，Toast 自身设为静音。
- `sound.enabled = true`：调用 `winsound.PlaySound`。

Toast 标题为 `OpenCode — <project_name>`；项目名为空时为 `OpenCode`。正文直接使用 payload `message`。

系统声音：

```python
winsound.PlaySound(name, winsound.SND_ALIAS | winsound.SND_ASYNC)
```

项目 WAV：

```python
winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
```

Toast 和声音分别捕获异常，一个失败不阻止另一个。新异步声音允许替换上一声音；首版不排队、不混音。

## 声音 catalog

- 系统声音来自代码内白名单，ID 为 `alias:<name>`。
- 项目声音每次读取配置时扫描 `opencode-windows-notifier/sounds/` 的直接 `.wav`，ID 为 `wav:<filename>`。
- 只接受 `Path.name` 等于原值的文件名，拒绝目录、绝对路径和 `..`。
- preview 与真实通知共用同一解析和播放函数。

## 本地配置页

`static/index.html` 内含必要 CSS 和 JavaScript，不使用 Node 或前端框架。

每个事件一行，显示：

- 事件名与说明。
- Toast checkbox。
- Sound checkbox。
- 声音 select。
- 试听按钮。

页面提供保存按钮，不提供上传、删除、token、监听地址或 WSL 配置。

## 本地配置 API

- `GET /`：配置页。
- `GET /v1/config`：六事件说明、当前映射和声音 catalog。
- `PUT /v1/config`：原子保存完整六事件映射并立即应用。
- `POST /v1/preview`：播放 catalog 中的一个声音。

这些路由只允许 `request.client.host` 为 `127.0.0.1` 或 `::1`；其他来源返回 `403`。首版不提供远程 token 登录。

## 日志与运行

- 使用标准 `logging`，记录启动地址、事件类型和通知错误。
- 不记录 token、Authorization header 或完整配置。
- 使用 Uvicorn 默认单 worker；不增加多 worker 协调设计。
- 进程关闭时无需等待异步声音。

## 测试要点

覆盖 `opencode-windows-notifier/.sisyphus/docs/patterns/testing.md` 的 Windows 端必测项。自动测试 mock Toast 和声音；真实呈现只在 Windows 手工联调验证。
