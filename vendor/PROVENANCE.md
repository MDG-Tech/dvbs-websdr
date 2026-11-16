# Pinned sources

| Directory / asset | Source revision | License / notes |
| --- | --- | --- |
| `leansdr-dvbs` | https://github.com/pabr/leansdr · `e6416aa323fdfa553b7cb1420c3291acaeb7b65a` | GPL-3.0-or-later; original DVB-S branch |
| `leansdr-s2` | https://github.com/pabr/leansdr · work `84c59e1c7a1a79338d5722d63f28640cc9d350f3` | GPL-3.0-or-later; S2 extensions compiled |
| `libmirisdr-5` | https://github.com/ericek111/libmirisdr-5 · `6392af06ba02154765ecb8d1ddc29dbe3c62b402` | GPL-2.0-or-later; COPYING retained |
| `SoapyMiri` | https://github.com/ericek111/SoapyMiri · `1e0a125ebab4ab492266fc61cab52600c7dc675f` | Upstream source notices retained |

Source trees were copied without Git metadata or build output. All browser-specific
DSP adaptations are applied to generated source copies by `tools/build_decoder.py`.
The LeanSDR and libmirisdr trees remain unchanged. SoapyMiri has one local
change: its existing `asyncBuffs` setting now selects USB transfer depth
independently from the host FIFO depth. The application uses 16 USB transfers
and 128 host buffers to tolerate scheduling pauses without overqueueing USB ISO.

S2 acquisition patch source:
https://github.com/ok1cdj/ESP32-DATV-RX/blob/esp32-atv/tools/leandvb-acquisition.patch
retrieved 2026-11-16. The first hunk's include context was adjusted because this
project does not include that author's separate external-LDPC-helper patch.
The remainder is retained verbatim. The larger PLS search window and candidate
phase/frequency fits address false acquisition with normal frames.

Media assets: unmodified `@ffmpeg/core` 0.12.10 UMD files, downloaded from
https://registry.npmjs.org/@ffmpeg/core/-/core-0.12.10.tgz .

- `ffmpeg-core.js` SHA-256: `b266ab5b952555881dd6310663986994a182acb2b7ff25cf10a25f7a37ac2b21`
- `ffmpeg-core.wasm` SHA-256: `9f57947a5bd530d8f00c5b3f2cb2a3492faa7e5d823315342d6a8656d0a6b7b7`

`tools/fetch_media.py` verifies these hashes. Generated binaries are not tracked.
FFmpeg.wasm source/build configuration and licensing:
https://github.com/ffmpegwasm/ffmpeg.wasm/tree/v0.12.10 . The FFmpeg core and its
codec dependencies have separate GPL/LGPL licenses; retain the corresponding
source, notices and build configuration if redistributing these binaries.
