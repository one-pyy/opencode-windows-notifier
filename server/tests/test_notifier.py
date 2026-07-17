from __future__ import annotations

from pathlib import Path

import pytest

from opencode_windows_notifier.app import EventPayload
from opencode_windows_notifier.config import EventPresentation
from opencode_windows_notifier.notifier import WindowsNotifier, sound_catalog


def payload() -> EventPayload:
    return EventPayload.model_validate(
        {
            "event": "complete",
            "timestamp": "2026-07-17T00:00:00.000Z",
            "session_title": "Implement notifier",
            "project_name": "opencode",
            "duration_ms": 100,
            "message": "Session has finished: Implement notifier",
        }
    )


def presentation(*, toast: bool = True, sound_enabled: bool = True, source: str = "alias:SystemAsterisk"):
    return EventPresentation.model_validate(
        {"toast": toast, "sound": {"enabled": sound_enabled, "source": source}}
    )


def make_notifier(tmp_path: Path, toast_calls: list[object], sound_calls: list[object]) -> WindowsNotifier:
    return WindowsNotifier(
        tmp_path,
        toast_backend=lambda *args, **kwargs: toast_calls.append((args, kwargs)),
        sound_backend=lambda source, flags: sound_calls.append((source, flags)),
        alias_flags=1,
        filename_flags=2,
    )


def test_catalog_contains_aliases_and_direct_wav_only(tmp_path: Path) -> None:
    (tmp_path / "complete.wav").write_bytes(b"RIFF")
    (tmp_path / "UPPER.WAV").write_bytes(b"RIFF")
    (tmp_path / "ignored.mp3").write_bytes(b"mp3")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "hidden.wav").write_bytes(b"RIFF")
    outside = tmp_path.parent / "outside.wav"
    outside.write_bytes(b"RIFF")
    (tmp_path / "linked.wav").symlink_to(outside)

    catalog = sound_catalog(tmp_path)

    assert "alias:SystemAsterisk" in catalog
    assert catalog["wav:complete.wav"] == "complete"
    assert catalog["wav:UPPER.WAV"] == "UPPER"
    assert "wav:ignored.mp3" not in catalog
    assert "wav:hidden.wav" not in catalog
    assert "wav:linked.wav" not in catalog


def test_toast_and_sound_channels_are_independent(tmp_path: Path) -> None:
    toast_calls: list[object] = []
    sound_calls: list[object] = []
    notifier = make_notifier(tmp_path, toast_calls, sound_calls)

    notifier.notify(payload(), presentation())
    assert toast_calls == [
        (("OpenCode — opencode", "Session has finished: Implement notifier"), {"audio": {"silent": "true"}})
    ]
    assert sound_calls == [("SystemAsterisk", 1)]

    toast_calls.clear()
    sound_calls.clear()
    notifier.notify(payload(), presentation(toast=False, sound_enabled=False))
    assert toast_calls == []
    assert sound_calls == []


def test_wav_playback_uses_resolved_filename(tmp_path: Path) -> None:
    wav = tmp_path / "custom.wav"
    wav.write_bytes(b"RIFF")
    sound_calls: list[object] = []
    notifier = make_notifier(tmp_path, [], sound_calls)

    notifier.preview("wav:custom.wav")

    assert sound_calls == [(str(wav.resolve()), 2)]


def test_unknown_sound_is_rejected(tmp_path: Path) -> None:
    notifier = make_notifier(tmp_path, [], [])
    with pytest.raises(ValueError, match="unknown sound ID"):
        notifier.preview("wav:missing.wav")


def test_channel_failures_do_not_escape_or_block_the_other_channel(tmp_path: Path) -> None:
    sound_calls: list[object] = []

    def fail_toast(*_args, **_kwargs) -> None:
        raise RuntimeError("toast failed")

    notifier = WindowsNotifier(
        tmp_path,
        toast_backend=fail_toast,
        sound_backend=lambda source, flags: sound_calls.append((source, flags)),
        alias_flags=1,
        filename_flags=2,
    )
    notifier.notify(payload(), presentation())
    assert sound_calls == [("SystemAsterisk", 1)]

    toast_calls: list[object] = []

    def fail_sound(_source: str, _flags: int) -> None:
        raise RuntimeError("sound failed")

    notifier = WindowsNotifier(
        tmp_path,
        toast_backend=lambda *args, **kwargs: toast_calls.append((args, kwargs)),
        sound_backend=fail_sound,
        alias_flags=1,
        filename_flags=2,
    )
    notifier.notify(payload(), presentation())
    assert len(toast_calls) == 1
