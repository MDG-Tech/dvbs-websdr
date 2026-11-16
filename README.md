# DVB-S browser receiver

Local WebSDR-style receiver for the connected SDRone / RSP1-compatible radios.
The Python service controls the selected radio and sends complex float32 IQ over
a WebSocket. **DVB-S demodulation, FEC, transport-stream recovery, video decoding,
and audio decoding run in browser WebAssembly workers.** WebGL draws the waterfall.
There is no transmitter-to-player bypass.

## Run on this PC

```sh
cd /root/dvbs-websdr
./run.sh
```

Open <http://127.0.0.1:8090>. Select the receiver before pressing **Start receiver**.
USB device `001:010`, physical port `1-1`, is selected by default when present.
The other current radio is device `001:012`, port `1-5`. Selection uses the
physical USB port, rather than a potentially changing driver index. Stop the
receiver to select another radio. Refresh re-enumerates attached devices.

Defaults: 739 MHz IF, 2.048 MS/s capture, 333 ksymbols/s QPSK, FEC 1/2,
roll-off 0.35. **333 ksymbols/s is the symbol rate**, not the IQ sample rate.
Click the center of a signal in the spectrum/waterfall to acquire it. Tune,
symbol-rate, and FEC changes create a fresh decoder. Center-frequency or gain
changes require stopping and restarting the receiver. Gain 60 worked on the
antenna bench test; gain 40 is the more conservative initial setting.

The waterfall floor is adjustable. The display offset changes frequency labels
only. **QO-100 IF labels** toggles a +9750 MHz offset for a nominal 9.75 GHz LNB.
Actual LNB LO error must be accounted for when tuning. The captured span is
2.048 MHz, so this is a tunable slice of the WB transponder, not a simultaneous
whole-transponder receiver. DVB-S2 is not implemented.

Video/audio are decoded in approximately three-second batches with a one-second
overlap for program tables and keyframes. This adds several seconds of latency.
Playback currently scales video to 320×240 at 10 fps and mono audio to 48 kHz.
The original recovered TS remains available through **Save received TS** (last
32 MiB). Click **Enable audio** to satisfy browser audio-activation requirements.
The media-codec WASM download is about 31 MiB and is served locally.

To explicitly allow access from other machines on your LAN:

```sh
./run.sh --host 0.0.0.0 --port 8090
```

There is no authentication layer; the default binds only to loopback. One browser
can own each radio at a time. Other tabs may use the other radio. The service
rejects cross-origin browser WebSocket requests, bounds IQ backlog to about two
seconds, and stops on hardware discontinuities or sustained browser overload.
Closing the tab closes the hardware process and reattaches its Linux TV driver.
This application never starts a transmitter automatically.

## Existing transmitter and finite antenna test

The existing preparation/transmitter project is in `/root/mn88473-r828d-1p7`;
its tested waveform is `/mnt/data/astrometa-dvbs333/periodic.iq` with adjacent
checksum/profile JSON. It uses MPEG-2 video and MP2 audio; the live webcam tools
also support H.264 video. The browser media engine can decode both.

The test helper below is explicitly for the antenna setup used in this session.
It checks waveform integrity, refuses to take over an active transmitter,
limits duration to 30 seconds and internal attenuation to at least 40 dB,
then mutes TX and restores LO/rate/filter/gain settings even on interruption:

```sh
.venv/bin/python tools/pluto_test.py --frequency 739000000 --seconds 30 --attenuation 40
```

Start this finite test, then start the browser receiver at 739 MHz, gain 60.
It is intentionally separate from the web UI. RF output power is not calibrated
by this helper. The original conducted-only transmitter tools remain unchanged.

## Dependencies and build

This host has Python 3.13, NumPy, SciPy, SoapySDR 0.8, Emscripten 3.1.69,
libusb development files, CMake, FFmpeg and a Chromium installation. The virtual
environment uses system packages for NumPy/SoapySDR, plus aiohttp and Playwright.
`run.sh` selects the existing SoapyMiri plugin and the project-local libmirisdr
build. The system SDR libraries were not replaced.

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
cmake -S /root/sdr-receiver-test/libmirisdr-5 -B native/miri-build \
  -DDETACH_KERNEL_DRIVER=ON -DCMAKE_INSTALL_PREFIX="$PWD/native/miri"
cmake --build native/miri-build -j4
cmake --install native/miri-build
python3 tools/build_decoder.py
```

`tools/build_decoder.py` copies local LeanSDR commit
`e6416aa323fdfa553b7cb1420c3291acaeb7b65a` into `native/leansdr` and adapts only
its file input/output to asynchronous worker messages. A DC bias is removed from
each input block before demodulation. General inlining is disabled to work around
the installed LLVM 19 compiler crash; small arithmetic hot paths are explicitly
inlined and SIMD is enabled. The full modified source and bridge are retained.

## Checks

```sh
python3 tools/prepare_fixture.py
# With ./run.sh running:
.venv/bin/python tests/browser_check.py
```

The Chromium check verifies default receiver selection, actual WASM DVB-S
recovery from the existing waveform, browser MPEG-2/MP2 decoding and page errors.
It does not transmit RF. `tests/VALIDATION.md` records the separate live RF test.

## Third-party source and licenses

This project's original code is GPL-3.0-or-later. See `LICENSE`.
LeanSDR is GPL-3.0-or-later; retained sources and license are in `native/leansdr`.
Upstream: <https://github.com/pabr/leansdr>.
The local receiver stack uses <https://github.com/ericek111/SoapyMiri> and
<https://github.com/ericek111/libmirisdr-5>; their original trees and notices
remain in `/root/sdr-receiver-test`.

The locally served `web/vendor/ffmpeg-core.js` and `.wasm` are the unmodified
single-threaded `@ffmpeg/core` **0.12.10** UMD release from
<https://registry.npmjs.org/@ffmpeg/core/-/core-0.12.10.tgz>.
FFmpeg.wasm source/build instructions and licensing:
<https://github.com/ffmpegwasm/ffmpeg.wasm/tree/v0.12.10> and
<https://github.com/ffmpegwasm/ffmpeg.wasm/blob/v0.12.10/packages/core/README.md>.
The FFmpeg core and enabled dependencies have their own GPL/LGPL licenses;
retain and provide their corresponding source/build configuration when
redistributing these binaries. No external CDN is required at runtime.
