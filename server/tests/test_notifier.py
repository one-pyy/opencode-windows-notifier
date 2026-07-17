from __future__ import annotations

import wave
from pathlib import Path

import pytest

from opencode_windows_notifier.app import EventPayload
from opencode_windows_notifier.config import EventPresentation
from opencode_windows_notifier.notifier import WindowsNotifier, sound_catalog


def payload(event: str = "complete", session_title: str | None = "Implement notifier") -> EventPayload:
    return EventPayload.model_validate(
        {
            "event": event,
            "timestamp": "2026-07-17T00:00:00.000Z",
            "session_title": session_title,
            "project_name": "opencode",
            "duration_ms": 100 if event in {"complete", "subagent_complete"} else None,
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


def test_bundled_sound_packs_are_pcm_wav_files() -> None:
    sounds_dir = Path(__file__).parents[2] / "sounds"
    prefix_counts = {
        "opencode-alert-": 10,
        "opencode-bip-bop-": 10,
        "opencode-nope-": 12,
        "opencode-staplebops-": 7,
        "opencode-yup-": 6,
        "obsydian-interface-": 222,
        "kenney-interface-": 100,
        "kenney-ui-": 51,
        "robin-ui-": 12,
    }
    catalog = sound_catalog(sounds_dir)

    filenames: set[str] = set()
    for prefix, expected_count in prefix_counts.items():
        matched = {path.name for path in sounds_dir.glob(f"{prefix}*.wav")}
        assert len(matched) == expected_count
        filenames.update(matched)

    assert len(filenames) == 430
    assert "kenney-ui-preview.wav" not in filenames
    assert {f"wav:{filename}" for filename in filenames} <= set(catalog)
    for filename in filenames:
        with wave.open(str(sounds_dir / filename), "rb") as audio:
            assert audio.getnchannels() == 2
            assert audio.getsampwidth() == 2
            assert audio.getframerate() == 44_100
            assert audio.getnframes() > 0


def test_toast_and_sound_channels_are_independent(tmp_path: Path) -> None:
    toast_calls: list[object] = []
    sound_calls: list[object] = []
    notifier = make_notifier(tmp_path, toast_calls, sound_calls)

    notifier.notify(payload(), presentation())
    assert toast_calls == [
        (("完成：Implement notifier", "主会话已完成实际工作。"), {"audio": {"silent": "true"}})
    ]
    assert sound_calls == [("SystemAsterisk", 1)]

    toast_calls.clear()
    sound_calls.clear()
    notifier.notify(payload(), presentation(toast=False, sound_enabled=False))
    assert toast_calls == []
    assert sound_calls == []


@pytest.mark.parametrize(
    ("event", "event_label", "description"),
    [
        ("permission", "权限请求", "OpenCode 正在等待授权后继续。"),
        ("question", "提问", "OpenCode 需要你的回答后才能继续。"),
        ("complete", "完成", "主会话已完成实际工作。"),
        ("subagent_complete", "子agent完成", "隐藏或委派的子代理已完成。"),
        ("error", "ERROR", "会话因发生错误而停止。"),
        ("cancelled", "被取消", "会话已被用户取消或中止。"),
    ],
)
def test_toast_uses_chinese_event_copy(
    tmp_path: Path,
    event: str,
    event_label: str,
    description: str,
) -> None:
    toast_calls: list[object] = []
    notifier = make_notifier(tmp_path, toast_calls, [])

    notifier.notify(payload(event), presentation(sound_enabled=False))

    assert toast_calls == [
        ((f"{event_label}：Implement notifier", description), {"audio": {"silent": "true"}})
    ]


def test_toast_uses_unnamed_session_fallback(tmp_path: Path) -> None:
    toast_calls: list[object] = []
    notifier = make_notifier(tmp_path, toast_calls, [])

    notifier.notify(payload(session_title="  "), presentation(sound_enabled=False))

    assert toast_calls == [
        (("完成：未命名会话", "主会话已完成实际工作。"), {"audio": {"silent": "true"}})
    ]


def test_wav_playback_uses_resolved_filename(tmp_path: Path) -> None:
    wav = tmp_path / "custom.wav"
    wav.write_bytes(b"RIFF")
    sound_calls: list[object] = []
    notifier = make_notifier(tmp_path, [], sound_calls)

    notifier.preview("wav:custom.wav")

    assert sound_calls == [(str(wav.resolve()), 2)]


def test_audio_file_returns_only_enumerated_wav(tmp_path: Path) -> None:
    wav = tmp_path / "custom.wav"
    wav.write_bytes(b"RIFF")
    notifier = make_notifier(tmp_path, [], [])

    assert notifier.audio_file("wav:custom.wav") == wav.resolve()
    assert notifier.audio_file("alias:SystemAsterisk") is None
    assert notifier.audio_file("wav:missing.wav") is None


def test_preview_waits_for_playback_instead_of_using_async_flags(tmp_path: Path) -> None:
    sound_calls: list[object] = []
    notifier = WindowsNotifier(
        tmp_path,
        toast_backend=lambda *_args, **_kwargs: None,
        sound_backend=lambda source, flags: sound_calls.append((source, flags)),
        alias_flags=0b0101,
        filename_flags=0b0110,
        async_flag=0b0100,
    )
    (tmp_path / "custom.wav").write_bytes(b"RIFF")

    notifier.preview("alias:SystemAsterisk")
    notifier.preview("wav:custom.wav")

    assert sound_calls == [
        ("SystemAsterisk", 0b0001),
        (str((tmp_path / "custom.wav").resolve()), 0b0010),
    ]


def test_unknown_sound_is_rejected(tmp_path: Path) -> None:
    notifier = make_notifier(tmp_path, [], [])
    with pytest.raises(ValueError, match="unknown sound ID"):
        notifier.preview("wav:missing.wav")


def test_stop_preview_stops_current_winsound_playback(tmp_path: Path) -> None:
    sound_calls: list[object] = []
    notifier = make_notifier(tmp_path, [], sound_calls)

    notifier.stop_preview()

    assert sound_calls == [(None, 0)]


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

    def fail_sound(_source: str | None, _flags: int) -> None:
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
