from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from opencode_windows_notifier.app import EventPayload, create_app
from opencode_windows_notifier.config import ConfigState, EventPresentation, ServerConfig


OPENCODE_SERIES_COUNTS = {
    "alert": ("Alert", 10),
    "bip-bop": ("Bip Bop", 10),
    "nope": ("Nope", 12),
    "staplebops": ("Staplebops", 7),
    "yup": ("Yup", 6),
}


class FakeNotifier:
    def __init__(self, sounds_directory: Path) -> None:
        self.notifications: list[tuple[EventPayload, EventPresentation]] = []
        self.previews: list[str] = []
        self.stops = 0
        self.sounds_directory = sounds_directory

    def notify(self, payload: EventPayload, presentation: EventPresentation) -> None:
        self.notifications.append((payload, presentation))

    def catalog(self) -> dict[str, str]:
        catalog = {
            "alias:SystemAsterisk": "Windows 提示音",
            "alias:SystemExclamation": "Windows 警告音",
            "alias:SystemQuestion": "Windows 询问音",
            "alias:SystemHand": "Windows 严重错误音",
            "wav:obsydian-interface-back-style-1-001.wav": "obsydian-interface-back-style-1-001",
            "wav:kenney-interface-click-001.wav": "kenney-interface-click-001",
            "wav:kenney-ui-mouseclick-001.wav": "kenney-ui-mouseclick-001",
            "wav:robin-ui-negative-sound.wav": "robin-ui-negative-sound",
            "wav:custom.wav": "custom",
        }
        for series, (_display_name, count) in OPENCODE_SERIES_COUNTS.items():
            for index in range(1, count + 1):
                filename = f"opencode-{series}-{index:02d}.wav"
                catalog[f"wav:{filename}"] = filename.removesuffix(".wav")
        return catalog

    def preview(self, source: str) -> None:
        self.previews.append(source)

    def stop_preview(self) -> None:
        self.stops += 1

    def audio_file(self, source: str) -> Path | None:
        if source not in self.catalog() or not source.startswith("wav:"):
            return None
        return self.sounds_directory / source.removeprefix("wav:")


class ClientAddress:
    def __init__(self, app: ASGIApp, host: str) -> None:
        self.app = app
        self.host = host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope = {**scope, "client": (self.host, 50000)}
        await self.app(scope, receive, send)


def setup(tmp_path: Path, client_host: str = "127.0.0.1"):
    example_path = Path(__file__).parents[1] / "config.example.json"
    config_data = json.loads(example_path.read_text(encoding="utf-8"))
    config_data["token"] = "secret"
    config = ServerConfig.model_validate(config_data)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json(), encoding="utf-8")
    state = ConfigState(config_path, config)
    sounds_directory = tmp_path / "sounds"
    sounds_directory.mkdir()
    (sounds_directory / "custom.wav").write_bytes(b"RIFF-audio")
    notifier = FakeNotifier(sounds_directory)
    static_file = tmp_path / "index.html"
    static_file.write_text("<h1>Notifier settings</h1>", encoding="utf-8")
    audition_file = tmp_path / "audition.html"
    audition_file.write_text("<h1>Sound audition</h1>", encoding="utf-8")
    client = TestClient(
        ClientAddress(create_app(state, notifier, static_file, audition_file), client_host)
    )
    return client, state, notifier, config_path


def event_payload() -> dict[str, object]:
    path = Path(__file__).parents[2] / "protocol" / "event-v1.example.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_loopback_can_read_page_and_configuration(tmp_path: Path) -> None:
    client, _state, _notifier, _config_path = setup(tmp_path)
    assert client.get("/").status_code == 200
    response = client.get("/v1/config")

    assert response.status_code == 200
    body = response.json()
    assert list(body["events"]) == [
        "permission",
        "question",
        "complete",
        "subagent_complete",
        "error",
        "cancelled",
    ]
    assert body["events"]["permission"]["description"]
    assert body["events"]["permission"]["label"] == "权限请求"
    assert body["events"]["complete"]["description"] == "主会话已完成实际工作。"
    assert {sound["label"] for sound in body["sounds"]} >= {
        "Windows 提示音",
        "custom",
    }
    assert {sound["id"] for sound in body["sounds"]} >= {
        "alias:SystemAsterisk",
        "wav:opencode-alert-01.wav",
        "wav:opencode-yup-06.wav",
        "wav:obsydian-interface-back-style-1-001.wav",
        "wav:kenney-interface-click-001.wav",
        "wav:kenney-ui-mouseclick-001.wav",
        "wav:robin-ui-negative-sound.wav",
        "wav:custom.wav",
    }
    sounds = {sound["id"]: sound for sound in body["sounds"]}
    assert sounds["alias:SystemAsterisk"]["group"] == "Windows 系统音效"
    for series, (display_name, count) in OPENCODE_SERIES_COUNTS.items():
        series_sounds = [
            sound
            for sound_id, sound in sounds.items()
            if sound_id.startswith(f"wav:opencode-{series}-")
        ]
        assert len(series_sounds) == count
        assert {sound["group"] for sound in series_sounds} == {f"OpenCode · {display_name}"}

    assert sounds["wav:opencode-alert-01.wav"]["label"] == "Alert 01"
    assert sounds["wav:opencode-bip-bop-01.wav"]["label"] == "Bip Bop 01（官方默认 / 完成）"
    assert sounds["wav:opencode-bip-bop-03.wav"]["label"] == "Bip Bop 03（官方问题）"
    assert sounds["wav:opencode-nope-03.wav"]["label"] == "Nope 03（官方错误）"
    assert sounds["wav:opencode-staplebops-06.wav"]["label"] == "Staplebops 06（官方权限）"
    assert sounds["wav:opencode-yup-01.wav"]["label"] == "Yup 01（官方子代理完成）"
    assert sounds["wav:opencode-yup-06.wav"]["label"] == "Yup 06"
    assert sounds["wav:obsydian-interface-back-style-1-001.wav"] == {
        "id": "wav:obsydian-interface-back-style-1-001.wav",
        "label": "Back Style 1 001",
        "group": "ObsydianX · Interface SFX Pack 1",
    }
    assert sounds["wav:kenney-interface-click-001.wav"] == {
        "id": "wav:kenney-interface-click-001.wav",
        "label": "Click 001",
        "group": "Kenney · Interface Sounds",
    }
    assert sounds["wav:kenney-ui-mouseclick-001.wav"] == {
        "id": "wav:kenney-ui-mouseclick-001.wav",
        "label": "Mouse Click 001",
        "group": "Kenney · UI Audio",
    }
    assert sounds["wav:robin-ui-negative-sound.wav"] == {
        "id": "wav:robin-ui-negative-sound.wav",
        "label": "Negative Sound",
        "group": "Robin Lamb · UI Notifications",
    }
    assert sounds["wav:custom.wav"]["group"] == "自定义 WAV"
    assert "token" not in body
    assert body["favorites"] == []


def test_static_configuration_page_is_chinese() -> None:
    static_file = (
        Path(__file__).parents[1]
        / "src"
        / "opencode_windows_notifier"
        / "static"
        / "index.html"
    )
    page = static_file.read_text(encoding="utf-8")

    assert '<html lang="zh-CN">' in page
    assert "OpenCode Windows 通知" in page
    assert "事件呈现方式" in page
    assert "保存设置" in page
    assert "试听" in page
    assert 'className = "sound-series"' in page
    assert 'className = "sound-source"' in page
    assert 'const favoriteGroup = "收藏"' in page
    assert 'document.createElement("optgroup")' not in page


def test_static_audition_page_has_requested_controls() -> None:
    static_file = (
        Path(__file__).parents[1]
        / "src"
        / "opencode_windows_notifier"
        / "static"
        / "audition.html"
    )
    page = static_file.read_text(encoding="utf-8")

    assert '<html lang="zh-CN">' in page
    assert "音效试听" in page
    assert "从当前逐一播放" in page
    assert "上一个" in page
    assert "暂停" in page
    assert "下一个" in page
    assert "★" in page
    assert "sequenceGapMs = 500" in page


def test_non_loopback_is_forbidden_from_all_configuration_routes(tmp_path: Path) -> None:
    client, state, _notifier, _config_path = setup(tmp_path, "192.0.2.10")
    events = state.current().model_dump(mode="json")["events"]
    assert client.get("/").status_code == 403
    assert client.get("/audition").status_code == 403
    assert client.get("/v1/config").status_code == 403
    assert client.put("/v1/config", json={"events": events}).status_code == 403
    assert client.put("/v1/favorites", json={"favorites": []}).status_code == 403
    assert client.get("/v1/audio", params={"source": "wav:custom.wav"}).status_code == 403
    assert client.post("/v1/preview", json={"source": "alias:SystemAsterisk"}).status_code == 403
    assert client.post("/v1/preview/stop").status_code == 403


def test_save_is_atomic_and_applies_to_the_next_event(tmp_path: Path) -> None:
    client, state, notifier, config_path = setup(tmp_path)
    assert client.put(
        "/v1/favorites",
        json={"favorites": ["wav:custom.wav"]},
    ).status_code == 200
    events = state.current().model_dump(mode="json")["events"]
    events["complete"]["toast"] = False
    events["complete"]["sound"] = {"enabled": True, "source": "wav:custom.wav"}

    response = client.put("/v1/config", json={"events": events})
    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["events"]["complete"]["toast"] is False
    assert saved["favorites"] == ["wav:custom.wav"]
    assert saved["token"] == "secret"

    assert client.post(
        "/v1/events",
        headers={"Authorization": "Bearer secret"},
        json=event_payload(),
    ).status_code == 204
    assert notifier.notifications[0][1].toast is False
    assert notifier.notifications[0][1].sound.source == "wav:custom.wav"


def test_save_requires_all_events_and_known_sounds(tmp_path: Path) -> None:
    client, state, _notifier, _config_path = setup(tmp_path)
    events = state.current().model_dump(mode="json")["events"]
    events.pop("cancelled")
    assert client.put("/v1/config", json={"events": events}).status_code == 422

    events = state.current().model_dump(mode="json")["events"]
    events["complete"]["sound"]["source"] = "wav:missing.wav"
    assert client.put("/v1/config", json={"events": events}).status_code == 422


def test_preview_plays_only_the_enumerated_sound(tmp_path: Path) -> None:
    client, state, notifier, _config_path = setup(tmp_path)
    before = state.current()

    assert client.post("/v1/preview", json={"source": "wav:custom.wav"}).status_code == 204
    assert notifier.previews == ["wav:custom.wav"]
    assert notifier.notifications == []
    assert state.current() == before
    assert client.post("/v1/preview", json={"source": "wav:missing.wav"}).status_code == 422


def test_favorites_are_persisted_and_returned_in_order(tmp_path: Path) -> None:
    client, state, _notifier, config_path = setup(tmp_path)
    favorites = ["wav:custom.wav", "wav:opencode-alert-01.wav"]

    response = client.put("/v1/favorites", json={"favorites": favorites})

    assert response.status_code == 200
    assert response.json() == {"favorites": favorites}
    assert state.current().favorites == tuple(favorites)
    assert json.loads(config_path.read_text(encoding="utf-8"))["favorites"] == favorites
    assert client.get("/v1/config").json()["favorites"] == favorites

    assert client.put(
        "/v1/favorites",
        json={"favorites": ["wav:custom.wav", "wav:custom.wav"]},
    ).status_code == 422
    assert client.put(
        "/v1/favorites",
        json={"favorites": ["wav:missing.wav"]},
    ).status_code == 422


def test_audio_route_serves_only_enumerated_wav_files(tmp_path: Path) -> None:
    client, _state, _notifier, _config_path = setup(tmp_path)

    response = client.get("/v1/audio", params={"source": "wav:custom.wav"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content == b"RIFF-audio"
    assert client.get(
        "/v1/audio",
        params={"source": "alias:SystemAsterisk"},
    ).status_code == 422
    assert client.get(
        "/v1/audio",
        params={"source": "wav:missing.wav"},
    ).status_code == 422


def test_stop_preview_calls_notifier_backend(tmp_path: Path) -> None:
    client, _state, notifier, _config_path = setup(tmp_path)

    assert client.post("/v1/preview/stop").status_code == 204
    assert notifier.stops == 1


def test_preview_playback_failure_returns_readable_422(tmp_path: Path, monkeypatch) -> None:
    client, _state, notifier, _config_path = setup(tmp_path)

    def fail_preview(_source: str) -> None:
        raise RuntimeError("Failed to play sound")

    monkeypatch.setattr(notifier, "preview", fail_preview)
    response = client.post("/v1/preview", json={"source": "alias:SystemAsterisk"})

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "无法播放 Windows 系统音效；该声音可能在 Windows 声音方案中被设为“无”。"
    )
