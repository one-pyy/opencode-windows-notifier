from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Mapping, Set
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EVENT_NAMES = frozenset(
    {"permission", "question", "complete", "subagent_complete", "error", "cancelled"}
)


class SoundConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool
    source: str = Field(min_length=1)

    @field_validator("source")
    @classmethod
    def validate_source(cls, source: str) -> str:
        if source.startswith("alias:") and source.removeprefix("alias:"):
            return source

        if source.startswith("wav:"):
            filename = source.removeprefix("wav:")
            if (
                filename
                and filename.lower().endswith(".wav")
                and filename not in {".", ".."}
                and "/" not in filename
                and "\\" not in filename
                and ".." not in Path(filename).parts
            ):
                return source

        raise ValueError("sound source must be an alias ID or direct WAV filename")


class EventPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    toast: bool
    sound: SoundConfig


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    listen_host: str = Field(min_length=1)
    listen_port: int = Field(ge=1, le=65535)
    token: str = Field(min_length=1)
    events: dict[str, EventPresentation]

    @field_validator("token")
    @classmethod
    def validate_token(cls, token: str) -> str:
        if not token.strip():
            raise ValueError("token must not be blank")
        return token

    @model_validator(mode="after")
    def validate_event_map(self) -> ServerConfig:
        if set(self.events) != EVENT_NAMES:
            raise ValueError("events must contain exactly the six supported event names")
        return self


def default_config_path(environment: Mapping[str, str] = os.environ) -> Path:
    local_app_data = environment.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "opencode-windows-notifier" / "config.json"
    return Path.home() / "AppData" / "Local" / "opencode-windows-notifier" / "config.json"


def load_server_config(path: Path) -> ServerConfig:
    return ServerConfig.model_validate_json(path.read_text(encoding="utf-8"))


class ConfigState:
    def __init__(self, path: Path, config: ServerConfig) -> None:
        self._path = path
        self._config = config
        self._state_lock = threading.Lock()
        self._write_lock = threading.Lock()

    def current(self) -> ServerConfig:
        with self._state_lock:
            return self._config.model_copy(deep=True)

    def replace_events(
        self,
        events: Mapping[str, EventPresentation | Mapping[str, Any]],
        valid_sound_ids: Set[str],
    ) -> ServerConfig:
        with self._write_lock:
            with self._state_lock:
                current = self._config.model_dump(mode="python")
            candidate = ServerConfig.model_validate(
                {
                    **current,
                    "events": dict(events),
                }
            )
            for presentation in candidate.events.values():
                if presentation.sound.source not in valid_sound_ids:
                    raise ValueError(f"unknown sound ID: {presentation.sound.source}")

            temporary_path = self._write_temporary(candidate)
            try:
                with self._state_lock:
                    os.replace(temporary_path, self._path)
                    self._config = candidate
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise
            return candidate.model_copy(deep=True)

    def _write_temporary(self, config: ServerConfig) -> Path:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(config.model_dump(mode="json"), temporary_file, indent=2)
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            return temporary_path
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
