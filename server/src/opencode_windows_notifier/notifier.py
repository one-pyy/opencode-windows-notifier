from __future__ import annotations

import logging
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any

from .app import EVENT_DETAILS, EventPayload
from .config import EventPresentation

SYSTEM_SOUNDS = {
    "alias:SystemAsterisk": "Windows 提示音",
    "alias:SystemDefault": "Windows 默认声音",
    "alias:SystemExclamation": "Windows 警告音",
    "alias:SystemHand": "Windows 严重错误音",
    "alias:SystemQuestion": "Windows 询问音",
}

logger = logging.getLogger(__name__)


def default_sounds_directory() -> Path:
    return Path(__file__).resolve().parents[3] / "sounds"


def sound_catalog(sounds_directory: Path) -> dict[str, str]:
    catalog = dict(SYSTEM_SOUNDS)
    root = sounds_directory.resolve()
    if not sounds_directory.is_dir():
        return catalog

    for candidate in sorted(sounds_directory.iterdir(), key=lambda path: path.name.lower()):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if (
            candidate.is_file()
            and candidate.suffix.lower() == ".wav"
            and resolved.parent == root
        ):
            catalog[f"wav:{candidate.name}"] = candidate.stem
    return catalog


class WindowsNotifier:
    def __init__(
        self,
        sounds_directory: Path | None = None,
        toast_backend: Callable[..., Any] | None = None,
        sound_backend: Callable[[str | None, int], Any] | None = None,
        alias_flags: int | None = None,
        filename_flags: int | None = None,
        async_flag: int | None = None,
    ) -> None:
        self.sounds_directory = sounds_directory or default_sounds_directory()

        if toast_backend is None:
            toast_backend = getattr(import_module("win11toast"), "notify")
        assert toast_backend is not None
        self._toast: Callable[..., Any] = toast_backend

        if sound_backend is None:
            winsound = import_module("winsound")
            sound_backend = getattr(winsound, "PlaySound")
            async_flag = getattr(winsound, "SND_ASYNC")
            alias_flags = getattr(winsound, "SND_ALIAS") | async_flag
            filename_flags = getattr(winsound, "SND_FILENAME") | async_flag
        assert sound_backend is not None
        if alias_flags is None or filename_flags is None:
            raise ValueError("sound flags are required with a custom sound backend")
        self._play_sound: Callable[[str | None, int], Any] = sound_backend
        self._alias_flags = alias_flags
        self._filename_flags = filename_flags
        self._async_flag = async_flag or 0

    def catalog(self) -> dict[str, str]:
        return sound_catalog(self.sounds_directory)

    def notify(self, payload: EventPayload, presentation: EventPresentation) -> None:
        if presentation.toast:
            event_label, event_description = EVENT_DETAILS[payload.event]
            session_title = payload.session_title.strip() if payload.session_title else ""
            title = f"{event_label}：{session_title or '未命名会话'}"
            try:
                self._toast(title, event_description, audio={"silent": "true"})
            except Exception:
                logger.exception("Toast notification failed for event %s", payload.event.value)

        if presentation.sound.enabled:
            try:
                self.play(presentation.sound.source)
            except Exception:
                logger.exception("Sound playback failed for event %s", payload.event.value)

    def preview(self, source: str) -> None:
        self.play(source, asynchronous=False)

    def stop_preview(self) -> None:
        self._play_sound(None, 0)

    def audio_file(self, source: str) -> Path | None:
        if source not in self.catalog() or not source.startswith("wav:"):
            return None

        filename = source.removeprefix("wav:")
        path = (self.sounds_directory / filename).resolve()
        if path.parent != self.sounds_directory.resolve() or not path.is_file():
            return None
        return path

    def play(self, source: str, *, asynchronous: bool = True) -> None:
        catalog = self.catalog()
        if source not in catalog:
            raise ValueError(f"unknown sound ID: {source}")

        if source.startswith("alias:"):
            flags = self._alias_flags if asynchronous else self._alias_flags & ~self._async_flag
            self._play_sound(source.removeprefix("alias:"), flags)
            return

        path = self.audio_file(source)
        if path is None:
            raise ValueError(f"unknown WAV sound ID: {source}")
        flags = self._filename_flags if asynchronous else self._filename_flags & ~self._async_flag
        self._play_sound(str(path), flags)
