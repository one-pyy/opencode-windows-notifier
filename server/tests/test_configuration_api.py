from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from opencode_windows_notifier.app import EventPayload, create_app
from opencode_windows_notifier.config import ConfigState, EventPresentation, ServerConfig


class FakeNotifier:
    def __init__(self) -> None:
        self.notifications: list[tuple[EventPayload, EventPresentation]] = []
        self.previews: list[str] = []

    def notify(self, payload: EventPayload, presentation: EventPresentation) -> None:
        self.notifications.append((payload, presentation))

    def catalog(self) -> dict[str, str]:
        return {
            "alias:SystemAsterisk": "Windows Asterisk",
            "alias:SystemExclamation": "Windows Exclamation",
            "alias:SystemQuestion": "Windows Question",
            "alias:SystemHand": "Windows Critical Stop",
            "wav:custom.wav": "custom",
        }

    def preview(self, source: str) -> None:
        self.previews.append(source)


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
    notifier = FakeNotifier()
    static_file = tmp_path / "index.html"
    static_file.write_text("<h1>Notifier settings</h1>", encoding="utf-8")
    client = TestClient(ClientAddress(create_app(state, notifier, static_file), client_host))
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
    assert {sound["id"] for sound in body["sounds"]} >= {
        "alias:SystemAsterisk",
        "wav:custom.wav",
    }
    assert "token" not in body


def test_non_loopback_is_forbidden_from_all_configuration_routes(tmp_path: Path) -> None:
    client, state, _notifier, _config_path = setup(tmp_path, "192.0.2.10")
    events = state.current().model_dump(mode="json")["events"]
    assert client.get("/").status_code == 403
    assert client.get("/v1/config").status_code == 403
    assert client.put("/v1/config", json={"events": events}).status_code == 403
    assert client.post("/v1/preview", json={"source": "alias:SystemAsterisk"}).status_code == 403


def test_save_is_atomic_and_applies_to_the_next_event(tmp_path: Path) -> None:
    client, state, notifier, config_path = setup(tmp_path)
    events = state.current().model_dump(mode="json")["events"]
    events["complete"]["toast"] = False
    events["complete"]["sound"] = {"enabled": True, "source": "wav:custom.wav"}

    response = client.put("/v1/config", json={"events": events})
    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["events"]["complete"]["toast"] is False
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
