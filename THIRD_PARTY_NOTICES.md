# Third-Party Notices

The OpenCode event-handling design references portions of
[mohak34/opencode-notifier](https://github.com/mohak34/opencode-notifier) at
commit `2751226e7f04775a5bac7d5a0c7a94ff3377f7d6`.

Copyright (c) 2025 Mohak S

That project is distributed under the MIT License. Its parent/child session
detection, error completion suppression, permission deduplication, and session
metadata lookup patterns informed this implementation. Local notification,
audio, terminal focus, deprecated idle compatibility, and unrelated event
logic were not incorporated.

## OpenCode attention sound library

The 45 bundled `opencode-*.wav` files are format-converted copies of every
distinct MP3 sound under `packages/ui/src/assets/audio/` in
[anomalyco/opencode](https://github.com/anomalyco/opencode) at commit
`4bffbb655f5e2886df502b2305db03acd4138fff`:

- `alert-01.mp3` through `alert-10.mp3`
- `bip-bop-01.mp3` through `bip-bop-10.mp3`
- `nope-01.mp3` through `nope-12.mp3`
- `staplebops-01.mp3` through `staplebops-07.mp3`
- `yup-01.mp3` through `yup-06.mp3`

Copyright (c) 2025 opencode

The upstream repository is distributed under the MIT License. The source MP3
files were converted with FFmpeg to 44.1 kHz, 16-bit, stereo PCM WAV so the
Windows receiver can play them through `winsound`. Each sound also has an AAC
encoding in the upstream tree; those duplicate encodings are not bundled.
Upstream PR #26980 introduced the attention sounds but did not provide a
separate audio-specific attribution or license notice. The current
`opencode.default` pack selects `bip-bop-01`, `bip-bop-03`, `staplebops-06`,
`nope-03`, and `yup-01` from this larger library.

## ObsydianX Interface SFX Pack 1

The 222 bundled `obsydian-interface-*.wav` files come from
[Interface SFX Pack 1](https://obsydianx.itch.io/interface-sfx-pack-1) by
ObsydianX. The official WAV archive declares the assets to be dedicated to the
public domain under Creative Commons Zero 1.0 (CC0 1.0).

The source WAV files were normalized with FFmpeg to 44.1 kHz, 16-bit, stereo
PCM WAV. The parallel OGG download is not bundled.

## Kenney Interface Sounds

The 100 bundled `kenney-interface-*.wav` files come from
[Interface Sounds](https://kenney.nl/assets/interface-sounds), created and
distributed by Kenney. The package `License.txt` declares Creative Commons Zero
1.0 (CC0 1.0); attribution is optional.

The source OGG files were converted with FFmpeg to 44.1 kHz, 16-bit, stereo PCM
WAV.

## Kenney UI Audio

The 51 bundled `kenney-ui-*.wav` files come from
[UI Audio](https://kenney.nl/assets/ui-audio) by Kenney Vleugels (Kenney.nl).
The package `License.txt` declares Creative Commons Zero 1.0 (CC0 1.0);
attribution is optional.

The 51 usable source OGG files were converted with FFmpeg to 44.1 kHz, 16-bit,
stereo PCM WAV. The package's `Preview.ogg` compilation is not a selectable
sound. The OpenGameArt distribution of the same 51 stems is not bundled again.

## Robin Lamb UI Sound Effects

The 12 bundled `robin-ui-*.wav` files come from
[UI Sound Effects (Button Clicks, User Feedback, Notifications)](https://opengameart.org/content/ui-sound-effects-button-clicks-user-feedback-notifications)
by Robin Lamb. The source page distributes the files under Creative Commons
Zero 1.0 (CC0 1.0).

The source WAV files were normalized with FFmpeg to 44.1 kHz, 16-bit, stereo
PCM WAV. The parallel OGG copies are not bundled.
