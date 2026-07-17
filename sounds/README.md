# Project Sounds

Place custom `.wav` files directly in this directory. The Windows service
lists direct WAV files only; subdirectories and other audio formats are
ignored.

Sound IDs use the form `wav:<filename>`. Files are not uploaded, renamed, or
deleted through the configuration page.

The repository includes 430 unique built-in PCM WAV files:

- OpenCode current audio library: 45.
- ObsydianX Interface SFX Pack 1: 222.
- Kenney Interface Sounds: 100.
- Kenney UI Audio: 51.
- Robin Lamb UI notifications: 12.

The configuration page uses a series selector followed by a sound selector.
Duplicate encodings and duplicate distributions are not bundled twice. Source
archives, fixed upstream references, licenses, and conversion details are
recorded in `opencode-windows-notifier/THIRD_PARTY_NOTICES.md`.
