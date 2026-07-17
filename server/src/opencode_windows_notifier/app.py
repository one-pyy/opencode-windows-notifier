from __future__ import annotations

import hmac
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Protocol

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import EVENT_NAMES, ConfigState, EventPresentation


class EventName(str, Enum):
    permission = "permission"
    question = "question"
    complete = "complete"
    subagent_complete = "subagent_complete"
    error = "error"
    cancelled = "cancelled"


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: EventName
    timestamp: datetime
    session_title: str | None
    project_name: str | None
    duration_ms: int | None = Field(default=None, ge=0)
    message: str = Field(min_length=1)

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
            raise ValueError("timestamp must include the UTC timezone")
        return timestamp

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        if not message.strip():
            raise ValueError("message must not be blank")
        return message

    @model_validator(mode="after")
    def validate_completion_duration(self) -> EventPayload:
        if self.event in {EventName.complete, EventName.subagent_complete} and self.duration_ms is None:
            raise ValueError("completion events require duration_ms")
        return self


class ConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: dict[EventName, EventPresentation]

    @model_validator(mode="after")
    def validate_complete_map(self) -> ConfigurationUpdate:
        if {event.value for event in self.events} != EVENT_NAMES:
            raise ValueError("events must contain exactly the six supported event names")
        return self


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1)


class FavoritesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    favorites: tuple[str, ...]

    @field_validator("favorites")
    @classmethod
    def validate_unique_favorites(cls, favorites: tuple[str, ...]) -> tuple[str, ...]:
        if len(favorites) != len(set(favorites)):
            raise ValueError("favorites must not contain duplicate sound IDs")
        return favorites


class NotifierBackend(Protocol):
    def notify(self, payload: EventPayload, presentation: EventPresentation) -> None: ...

    def catalog(self) -> Mapping[str, str]: ...

    def preview(self, source: str) -> None: ...

    def stop_preview(self) -> None: ...

    def audio_file(self, source: str) -> Path | None: ...


EVENT_DETAILS = {
    EventName.permission: ("权限请求", "OpenCode 正在等待授权后继续。"),
    EventName.question: ("提问", "OpenCode 需要你的回答后才能继续。"),
    EventName.complete: ("完成", "主会话已完成实际工作。"),
    EventName.subagent_complete: ("子agent完成", "隐藏或委派的子代理已完成。"),
    EventName.error: ("ERROR", "会话因发生错误而停止。"),
    EventName.cancelled: ("被取消", "会话已被用户取消或中止。"),
}

OPENCODE_SOUND_SERIES = {
    "alert": ("Alert", 10),
    "bip-bop": ("Bip Bop", 10),
    "nope": ("Nope", 12),
    "staplebops": ("Staplebops", 7),
    "yup": ("Yup", 6),
}

OPENCODE_DEFAULT_LABELS = {
    "opencode-bip-bop-01.wav": "Bip Bop 01（官方默认 / 完成）",
    "opencode-bip-bop-03.wav": "Bip Bop 03（官方问题）",
    "opencode-staplebops-06.wav": "Staplebops 06（官方权限）",
    "opencode-nope-03.wav": "Nope 03（官方错误）",
    "opencode-yup-01.wav": "Yup 01（官方子代理完成）",
}

EXTERNAL_SOUND_GROUPS = {
    "obsydian-interface-": "ObsydianX · Interface SFX Pack 1",
    "kenney-interface-": "Kenney · Interface Sounds",
    "kenney-ui-": "Kenney · UI Audio",
    "robin-ui-": "Robin Lamb · UI Notifications",
}

SOUND_LABEL_WORDS = {
    "mouseclick": "Mouse Click",
    "mouserelease": "Mouse Release",
    "rollover": "Roll Over",
}


def opencode_sound_option(sound_id: str, filename: str) -> dict[str, str] | None:
    for series, (display_name, maximum) in OPENCODE_SOUND_SERIES.items():
        prefix = f"opencode-{series}-"
        if not filename.startswith(prefix) or not filename.endswith(".wav"):
            continue

        index = filename[len(prefix) : -len(".wav")]
        if len(index) != 2 or not index.isdigit() or not 1 <= int(index) <= maximum:
            return None
        return {
            "id": sound_id,
            "label": OPENCODE_DEFAULT_LABELS.get(filename, f"{display_name} {index}"),
            "group": f"OpenCode · {display_name}",
        }
    return None


def external_sound_option(sound_id: str, filename: str) -> dict[str, str] | None:
    for prefix, group in EXTERNAL_SOUND_GROUPS.items():
        if not filename.startswith(prefix) or not filename.endswith(".wav"):
            continue

        stem = filename[len(prefix) : -len(".wav")]
        label = " ".join(
            SOUND_LABEL_WORDS.get(part, part.capitalize())
            for part in stem.split("-")
        )
        return {"id": sound_id, "label": label, "group": group}
    return None


def sound_option(sound_id: str, label: str) -> dict[str, str]:
    if sound_id.startswith("alias:"):
        return {"id": sound_id, "label": label, "group": "Windows 系统音效"}

    filename = sound_id.removeprefix("wav:")
    if option := opencode_sound_option(sound_id, filename):
        return option
    if option := external_sound_option(sound_id, filename):
        return option
    return {"id": sound_id, "label": label, "group": "自定义 WAV"}


def default_static_file() -> Path:
    return Path(__file__).with_name("static") / "index.html"


def default_audition_file() -> Path:
    return Path(__file__).with_name("static") / "audition.html"


def create_app(
    config_state: ConfigState,
    notifier: NotifierBackend,
    static_file: Path | None = None,
    audition_file: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="OpenCode Windows Notifier", docs_url=None, redoc_url=None)
    bearer = HTTPBearer(auto_error=False)
    static_file = static_file or default_static_file()
    audition_file = audition_file or default_audition_file()

    available_sound_ids = set(notifier.catalog())
    configured_sound_ids = {
        presentation.sound.source for presentation in config_state.current().events.values()
    }
    if unknown_sound_ids := configured_sound_ids - available_sound_ids:
        raise ValueError(f"unknown configured sound ID: {sorted(unknown_sound_ids)[0]}")
    if unknown_favorites := set(config_state.current().favorites) - available_sound_ids:
        raise ValueError(f"unknown favorite sound ID: {sorted(unknown_favorites)[0]}")

    def authorize(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        token = config_state.current().token
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not hmac.compare_digest(credentials.credentials, token)
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    @app.post("/v1/events", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(authorize)])
    def receive_event(payload: EventPayload) -> Response:
        presentation = config_state.current().events[payload.event.value]
        notifier.notify(payload, presentation)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    def require_loopback(request: Request) -> None:
        client_host = request.client.host if request.client else None
        if client_host not in {"127.0.0.1", "::1"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local access only")

    def configuration_response() -> dict[str, object]:
        current = config_state.current()
        return {
            "events": {
                event.value: {
                    "label": EVENT_DETAILS[event][0],
                    "description": EVENT_DETAILS[event][1],
                    **current.events[event.value].model_dump(mode="json"),
                }
                for event in EventName
            },
            "sounds": [
                sound_option(sound_id, label)
                for sound_id, label in notifier.catalog().items()
            ],
            "favorites": list(current.favorites),
        }

    local_only = [Depends(require_loopback)]

    @app.get("/", dependencies=local_only, response_class=FileResponse)
    def configuration_page() -> FileResponse:
        return FileResponse(static_file)

    @app.get("/audition", dependencies=local_only, response_class=FileResponse)
    def audition_page() -> FileResponse:
        return FileResponse(audition_file)

    @app.get("/v1/config", dependencies=local_only)
    def get_configuration() -> dict[str, object]:
        return configuration_response()

    @app.put("/v1/config", dependencies=local_only)
    def update_configuration(update: ConfigurationUpdate) -> dict[str, object]:
        event_map = {event.value: presentation for event, presentation in update.events.items()}
        try:
            config_state.replace_events(event_map, set(notifier.catalog()))
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
        return configuration_response()

    @app.put("/v1/favorites", dependencies=local_only)
    def update_favorites(update: FavoritesUpdate) -> dict[str, object]:
        try:
            updated = config_state.replace_favorites(update.favorites, set(notifier.catalog()))
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
        return {"favorites": list(updated.favorites)}

    @app.get("/v1/audio", dependencies=local_only, response_class=FileResponse)
    def get_audio(source: str) -> FileResponse:
        path = notifier.audio_file(source)
        if path is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="该声音不是可由浏览器播放的 WAV 文件。",
            )
        return FileResponse(path, media_type="audio/wav")

    @app.post("/v1/preview", dependencies=local_only, status_code=status.HTTP_204_NO_CONTENT)
    def preview_sound(preview: PreviewRequest) -> Response:
        if preview.source not in notifier.catalog():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="未知声音 ID")
        try:
            notifier.preview(preview.source)
        except (OSError, RuntimeError, ValueError) as error:
            if preview.source.startswith("alias:"):
                detail = "无法播放 Windows 系统音效；该声音可能在 Windows 声音方案中被设为“无”。"
            else:
                detail = "无法播放 WAV 文件；请检查文件是否存在且 Windows 音量未静音。"
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/v1/preview/stop", dependencies=local_only, status_code=status.HTTP_204_NO_CONTENT)
    def stop_preview() -> Response:
        try:
            notifier.stop_preview()
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="无法停止当前系统音效。",
            ) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app
