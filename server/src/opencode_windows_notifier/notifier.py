from __future__ import annotations

import logging
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any

from .app import EventPayload
from .config import EventPresentation

SYSTEM_SOUNDS = {
    "alias:SystemAsterisk": "Windows Asterisk",
    "alias:SystemDefault": "Windows Default",
    "alias:SystemExclamation": "Windows Exclamation",
    "alias:SystemHand": "Windows Critical Stop",
    "alias:SystemQuestion": "Windows Question",
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
        sound_backend: Callable[[str, int], Any] | None = None,
        alias_flags: int | None = None,
        filename_flags: int | None = None,
    ) -> None:
        self.sounds_directory = sounds_directory or default_sounds_directory()

        if toast_backend is None:
            toast_backend = getattr(import_module("win11toast"), "notify")
        assert toast_backend is not None
        self._toast: Callable[..., Any] = toast_backend

        if sound_backend is None:
            winsound = import_module("winsound")
            sound_backend = getattr(winsound, "PlaySound")
            alias_flags = getattr(winsound, "SND_ALIAS") | getattr(winsound, "SND_ASYNC")
            filename_flags = getattr(winsound, "SND_FILENAME") | getattr(winsound, "SND_ASYNC")
        assert sound_backend is not None
        if alias_flags is None or filename_flags is None:
            raise ValueError("sound flags are required with a custom sound backend")
        self._play_sound: Callable[[str, int], Any] = sound_backend
        self._alias_flags = alias_flags
        self._filename_flags = filename_flags

    def catalog(self) -> dict[str, str]:
        return sound_catalog(self.sounds_directory)

    def notify(self, payload: EventPayload, presentation: EventPresentation) -> None:
        if presentation.toast:
            title = f"OpenCode — {payload.project_name}" if payload.project_name else "OpenCode"
            try:
                self._toast(title, payload.message, audio={"silent": "true"})
            except Exception:
                logger.exception("Toast notification failed for event %s", payload.event.value)

        if presentation.sound.enabled:
            try:
                self.play(presentation.sound.source)
            except Exception:
                logger.exception("Sound playback failed for event %s", payload.event.value)

    def preview(self, source: str) -> None:
        self.play(source)

    def play(self, source: str) -> None:
        catalog = self.catalog()
        if source not in catalog:
            raise ValueError(f"unknown sound ID: {source}")

        if source.startswith("alias:"):
            self._play_sound(source.removeprefix("alias:"), self._alias_flags)
            return

        filename = source.removeprefix("wav:")
        path = (self.sounds_directory / filename).resolve()
        if path.parent != self.sounds_directory.resolve():
            raise ValueError("WAV path escapes the sounds directory")
        self._play_sound(str(path), self._filename_flags)
