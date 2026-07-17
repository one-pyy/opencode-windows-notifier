from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

from opencode_windows_notifier.config import ConfigState, ServerConfig, default_config_path


def valid_config() -> dict[str, object]:
    events = {
        event: {
            "toast": event != "subagent_complete",
            "sound": {"enabled": event != "subagent_complete", "source": "alias:SystemAsterisk"},
        }
        for event in ("permission", "question", "complete", "subagent_complete", "error", "cancelled")
    }
    return {"listen_host": "0.0.0.0", "listen_port": 8765, "token": "secret", "events": events}


def test_default_config_path_uses_local_app_data() -> None:
    assert default_config_path({"LOCALAPPDATA": "C:/Users/test/AppData/Local"}) == Path(
        "C:/Users/test/AppData/Local/opencode-windows-notifier/config.json"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra=True),
        lambda value: value.update(token=""),
        lambda value: value.update(listen_port=0),
        lambda value: value["events"].pop("cancelled"),
        lambda value: value["events"]["complete"]["sound"].update(source="wav:../escape.wav"),
    ],
)
def test_server_config_is_strict(mutation) -> None:
    value = valid_config()
    mutation(value)
    with pytest.raises(ValidationError):
        ServerConfig.model_validate(value)


def test_replace_events_updates_file_and_memory(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config = ServerConfig.model_validate(valid_config())
    config_path.write_text(config.model_dump_json(), encoding="utf-8")
    state = ConfigState(config_path, config)
    events = config.model_dump(mode="python")["events"]
    events["subagent_complete"]["toast"] = True

    state.replace_events(events, {"alias:SystemAsterisk"})

    assert state.current().events["subagent_complete"].toast is True
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["events"]["subagent_complete"]["toast"] is True
    assert saved["token"] == "secret"


def test_current_remains_available_while_replacement_file_is_prepared(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config = ServerConfig.model_validate(valid_config())
    config_path.write_text(config.model_dump_json(), encoding="utf-8")
    state = ConfigState(config_path, config)
    events = config.model_dump(mode="python")["events"]
    events["complete"]["toast"] = False
    started = threading.Event()
    release = threading.Event()
    failures: list[BaseException] = []
    write_temporary = state._write_temporary

    def slow_write(candidate: ServerConfig) -> Path:
        started.set()
        if not release.wait(timeout=2):
            raise TimeoutError("replacement test timed out")
        return write_temporary(candidate)

    def replace() -> None:
        try:
            state.replace_events(events, {"alias:SystemAsterisk"})
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(state, "_write_temporary", slow_write)
    worker = threading.Thread(target=replace)
    worker.start()
    try:
        assert started.wait(timeout=1)
        assert state.current().events["complete"].toast is True
    finally:
        release.set()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert failures == []
    assert state.current().events["complete"].toast is False


def test_replace_events_preserves_old_state_when_replace_fails(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config = ServerConfig.model_validate(valid_config())
    original = config.model_dump_json()
    config_path.write_text(original, encoding="utf-8")
    state = ConfigState(config_path, config)
    events = config.model_dump(mode="python")["events"]
    events["complete"]["toast"] = False

    def fail_replace(_source, _destination) -> None:
        raise OSError("disk error")

    monkeypatch.setattr("opencode_windows_notifier.config.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk error"):
        state.replace_events(events, {"alias:SystemAsterisk"})

    assert state.current().events["complete"].toast is True
    assert config_path.read_text(encoding="utf-8") == original


def test_replace_events_rejects_unknown_sound_without_writing(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config = ServerConfig.model_validate(valid_config())
    original = config.model_dump_json()
    config_path.write_text(original, encoding="utf-8")
    state = ConfigState(config_path, config)

    with pytest.raises(ValueError, match="unknown sound ID"):
        state.replace_events(config.events, {"alias:SystemHand"})

    assert config_path.read_text(encoding="utf-8") == original
