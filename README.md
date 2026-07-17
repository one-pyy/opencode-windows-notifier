# OpenCode Windows Notifier

OpenCode Windows Notifier forwards attention-worthy OpenCode events from WSL
to a small Windows service. Windows then shows a native Toast, plays a selected
sound, performs both actions, or stays silent according to its local event
mapping.

The first release supports permission requests, questions, main-session
completion, subagent completion, errors, and cancellation. It has no event
history, reverse control, offline queue, remote administration, or automatic
startup.

## Status

The plugin and Windows service are implemented. Automated tests, real HTTP
requests, and desktop/mobile browser checks pass. Native Windows Toast/WAV and
real OpenCode-in-WSL end-to-end checks still require a Windows machine.

## How it works

```text
OpenCode in WSL -> TypeScript plugin -> POST /v1/events
                                      -> Windows FastAPI service
                                      -> Toast and/or WAV/system sound
```

The plugin decides whether an OpenCode event represents permission, question,
completion, error, or cancellation. The Windows configuration page decides
how each event is presented.

## Requirements

- Windows 10 or 11 with Python 3.11+.
- WSL with OpenCode and Bun.
- A checkout on a Windows drive so Windows and WSL can access the same project,
  for example `C:\src\opencode-windows-notifier` and
  `/mnt/c/src/opencode-windows-notifier`.

## Windows receiver

Open PowerShell in the repository root:

```powershell
py -3.11 -m venv .\server\.venv
.\server\.venv\Scripts\python.exe -m pip install -e .\server

$ConfigDir = Join-Path $env:LOCALAPPDATA "opencode-windows-notifier"
New-Item -ItemType Directory -Force $ConfigDir | Out-Null
Copy-Item .\server\config.example.json (Join-Path $ConfigDir "config.json")

$Token = [Convert]::ToHexString(
  [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
)
$Token
```

Edit `%LOCALAPPDATA%\opencode-windows-notifier\config.json` and replace the
example token with the generated value. Keep `listen_host` as `0.0.0.0` when
WSL must reach the service.

Start the receiver manually:

```powershell
.\server\.venv\Scripts\python.exe -m opencode_windows_notifier
```

Open `http://127.0.0.1:8765` in Windows. The page changes only the six event
presentation mappings; it never exposes the token or listen address.

## WSL plugin

Install the plugin dependencies from WSL:

```bash
cd /mnt/c/src/opencode-windows-notifier/plugin
bun install --frozen-lockfile
mkdir -p ~/.config/opencode
cp config.example.json ~/.config/opencode/opencode-windows-notifier.json
```

Find the Windows host address used by the default WSL networking mode:

```bash
ip route show default | awk '/default/ {print $3; exit}'
```

Edit `~/.config/opencode/opencode-windows-notifier.json`:

```json
{
  "server_url": "http://WINDOWS_HOST:8765",
  "token": "THE-SAME-TOKEN-AS-WINDOWS",
  "timeout_ms": 500
}
```

With WSL mirrored networking, `http://127.0.0.1:8765` may work directly.

Register the absolute TypeScript entry path in the OpenCode `plugin` array:

```jsonc
{
  "plugin": [
    "/mnt/c/src/opencode-windows-notifier/plugin/src/index.ts"
  ]
}
```

Restart OpenCode after changing the plugin configuration.

## Custom sounds

Place direct `.wav` files in `opencode-windows-notifier/sounds/`. Refresh the
Windows configuration page, choose the new sound, use **Play** to preview it,
then save. Subdirectories, MP3 files, arbitrary paths, and uploads are not
supported.

## Security

- `POST /v1/events` always requires the shared Bearer token.
- The configuration page and configuration APIs accept loopback clients only.
- If the receiver listens on `0.0.0.0`, restrict TCP port `8765` to the WSL
  subnet with Windows Firewall.
- Never commit either real configuration file or its token.

## Verify

From the repository root in WSL, send the shared protocol sample:

```bash
curl -i \
  -H "Authorization: Bearer THE-SAME-TOKEN-AS-WINDOWS" \
  -H "Content-Type: application/json" \
  --data-binary @protocol/event-v1.example.json \
  http://WINDOWS_HOST:8765/v1/events
```

The expected response is `204 No Content`. Then verify on the real target:

1. Open the local page and confirm all six events and sound choices appear.
2. Run one main session and one subagent; each should emit one completion.
3. Enable `subagent_complete` in the page and confirm the next subagent uses it.
4. Trigger permission, question, error, and double-Esc cancellation events.
5. Preview and save a project WAV, then confirm the next matching event uses it.
6. Stop the Windows service and confirm OpenCode continues without blocking.

Developer commands and the full contract are indexed in
`opencode-windows-notifier/.sisyphus/docs/INDEX.md`.
