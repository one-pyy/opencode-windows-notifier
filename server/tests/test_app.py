from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from opencode_windows_notifier.app import EventPayload, create_app
from opencode_windows_notifier.config import ConfigState, EventPresentation, ServerConfig


def valid_config() -> dict[str, object]:
    path = Path(__file__).parents[1] / "config.example.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["token"] = "secret"
    return config


def make_client(tmp_path: Path):
    config = ServerConfig.model_validate(valid_config())
    state = ConfigState(tmp_path / "config.json", config)
    calls: list[tuple[EventPayload, EventPresentation]] = []

    class FakeNotifier:
        def notify(self, payload: EventPayload, presentation: EventPresentation) -> None:
            calls.append((payload, presentation))

        def catalog(self) -> dict[str, str]:
            return {
                "alias:SystemAsterisk": "Windows Asterisk",
                "alias:SystemExclamation": "Windows Exclamation",
                "alias:SystemQuestion": "Windows Question",
                "alias:SystemHand": "Windows Critical Stop",
            }

        def preview(self, source: str) -> None:
            del source

    client = TestClient(create_app(state, FakeNotifier()))
    return client, calls


def protocol_sample() -> dict[str, object]:
    path = Path(__file__).parents[2] / "protocol" / "event-v1.example.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_valid_event_returns_204_and_uses_current_mapping(tmp_path: Path) -> None:
    client, calls = make_client(tmp_path)
    response = client.post(
        "/v1/events",
        headers={"Authorization": "Bearer secret"},
        json=protocol_sample(),
    )

    assert response.status_code == 204
    assert response.content == b""
    assert len(calls) == 1
    assert calls[0][0].event.value == "complete"
    assert calls[0][1].toast is True


def test_missing_or_wrong_token_returns_401_without_notification(tmp_path: Path) -> None:
    client, calls = make_client(tmp_path)
    assert client.post("/v1/events", json=protocol_sample()).status_code == 401
    assert client.post(
        "/v1/events",
        headers={"Authorization": "Bearer wrong"},
        json=protocol_sample(),
    ).status_code == 401
    assert calls == []


def test_invalid_payload_uses_fastapi_422(tmp_path: Path) -> None:
    client, calls = make_client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    invalid_payloads = [
        {**protocol_sample(), "event": "unknown"},
        {**protocol_sample(), "unexpected": True},
        {**protocol_sample(), "timestamp": "2026-07-17T00:00:00"},
        {**protocol_sample(), "duration_ms": -1},
        {**protocol_sample(), "message": " "},
        {**protocol_sample(), "duration_ms": None},
    ]
    for payload in invalid_payloads:
        assert client.post("/v1/events", headers=headers, json=payload).status_code == 422
    assert calls == []


def test_two_identical_events_are_both_processed(tmp_path: Path) -> None:
    client, calls = make_client(tmp_path)
    headers = {"Authorization": "Bearer secret"}
    assert client.post("/v1/events", headers=headers, json=protocol_sample()).status_code == 204
    assert client.post("/v1/events", headers=headers, json=protocol_sample()).status_code == 204
    assert len(calls) == 2
