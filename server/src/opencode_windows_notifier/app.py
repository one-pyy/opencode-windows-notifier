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


class NotifierBackend(Protocol):
    def notify(self, payload: EventPayload, presentation: EventPresentation) -> None: ...

    def catalog(self) -> Mapping[str, str]: ...

    def preview(self, source: str) -> None: ...


EVENT_DETAILS = {
    EventName.permission: ("Permission", "OpenCode is waiting for permission to continue."),
    EventName.question: ("Question", "OpenCode needs an answer before it can proceed."),
    EventName.complete: ("Session complete", "A main OpenCode session finished real work."),
    EventName.subagent_complete: ("Subagent complete", "A hidden or delegated subagent finished."),
    EventName.error: ("Error", "A session stopped because an error occurred."),
    EventName.cancelled: ("Cancelled", "A session was cancelled or aborted by the user."),
}


def default_static_file() -> Path:
    return Path(__file__).with_name("static") / "index.html"


def create_app(
    config_state: ConfigState,
    notifier: NotifierBackend,
    static_file: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="OpenCode Windows Notifier", docs_url=None, redoc_url=None)
    bearer = HTTPBearer(auto_error=False)
    static_file = static_file or default_static_file()

    available_sound_ids = set(notifier.catalog())
    configured_sound_ids = {
        presentation.sound.source for presentation in config_state.current().events.values()
    }
    if unknown_sound_ids := configured_sound_ids - available_sound_ids:
        raise ValueError(f"unknown configured sound ID: {sorted(unknown_sound_ids)[0]}")

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
                {"id": sound_id, "label": label}
                for sound_id, label in notifier.catalog().items()
            ],
        }

    local_only = [Depends(require_loopback)]

    @app.get("/", dependencies=local_only, response_class=FileResponse)
    def configuration_page() -> FileResponse:
        return FileResponse(static_file)

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

    @app.post("/v1/preview", dependencies=local_only, status_code=status.HTTP_204_NO_CONTENT)
    def preview_sound(preview: PreviewRequest) -> Response:
        if preview.source not in notifier.catalog():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown sound ID")
        notifier.preview(preview.source)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app
