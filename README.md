# QO-100 WB browser receiver

WebSDR-style DVB-S / DVB-S2 reception with selectable SDRone / RSP1 receivers,
a WebGL spectrum/waterfall, click-to-tune, browser video/audio and TS downloads.

The host controls the SDR, computes the wideband spectrum, and frequency-shifts /
filters / decimates the selected channel. **Carrier and symbol recovery, DVB-S
Viterbi/RS or DVB-S2 LDPC/BCH, transport recovery, and media decoding run in
browser WebAssembly workers.** The full 10 MS/s IQ stream stays on the host.

## Start

On the configured PC:

```sh
cd /root/dvbs-websdr
./run.sh
```

Open <http://127.0.0.1:8090>. Select the receiver before **Start receiver**.
Device `001:010` / physical USB port `1-1` is preferred; the other current radio
is `001:012` / port `1-5`. Selection follows physical USB ports, rather than
changing Soapy driver indices. Stop to change receivers; Refresh re-enumerates.

The default is the **QO-100 DATV beacon**: 10491.5 MHz RF, nominal 741.5 MHz IF,
DVB-S2, 1500 ksymbols/s, QPSK 4/5, with automatic normal/short frame detection.
The receiver captures 10 MS/s around **745 MHz IF**, covering the WB bandplan's
740.5–749.5 MHz IF range with a nominal 9750 MHz LNB.

- **QO-100 WB / LNB** selects the 10 MHz overview and a 333 ksymbols/s channel.
- **DATV beacon** restores the beacon profile.
- **Direct IF test** restores 739 MHz, DVB-S QPSK 333 ksymbols/s, FEC 1/2.
- Click the signal center, then choose its symbol rate and DVB-S or DVB-S2.
- Center/tune inputs are **IF MHz**. The heading and waterfall show **RF MHz**
  when an LNB LO is entered. Enter 0 for direct IF labels.
- **LO correction** adds to the nominal LO for RF labels. Presets subtract that
  correction when computing IF tuning. Clicking the actual signal accommodates
  an LNB offset directly.
- Capture spans: 1.536, 2.048, 5, 8, and 10 MHz. Stop to change span or RF center.
  Channel tuning, modulation and symbol-rate changes do not reopen the radio.

A universal LNB needs external low-band, **horizontal-polarization** power
(usually 18 V with 22 kHz off), with the DC supply isolated from the SDR input.
The SDR's low-voltage bias tee stays off; it cannot replace an LNB power inserter.
A wider receive window does not by itself establish dish alignment or LNB lock.

Sources: [BATC WB bandplan](https://wiki.batc.org.uk/Es%27hail-2_DATV_Bandplan),
[BATC reception guide](https://wiki.batc.org.uk/Receiving_Oscar_100_DATV_signals).

## Supported modes and limits

Symbol rates are editable from **10 to 2000 ksymbols/s**, subject to capture
bandwidth. Presets include 33, 66, 125, 250, 333, 500, 1000, 1500 and 2000.
These are symbol rates, not receiver IQ sample rates. Roll-offs: .35, .25, .20.
The selected IQ rate is automatically reduced to at least 2.2 samples/symbol.

DVB-S supports QPSK and FEC 1/2, 2/3, 3/4, 5/6, 7/8.
DVB-S2 supports MODCODs 1–28 (QPSK, 8PSK, 16APSK, 32APSK), normal/short frames
and pilots. Choose **Auto from PLS** or restrict acquisition to a known MODCOD.
FEC and constellation are signaled by PLS in DVB-S2; the DVB-S FEC control is
therefore disabled. The metrics panel reports detected MODCOD/frame size.

**DVB-S2 currently uses upstream hard-decision LDPC bit-flipping and BCH.**
It is less capable near the noise threshold than a soft-decision LDPC receiver.
Clean QPSK/8PSK/16APSK/32APSK streams have been tested; do not interpret this as
weak-signal or every-MODCOD qualification. DVB-S2X, multistream, GSE and ACM/VCM
are outside this version's tested scope. A changing or unsupported stream may
require reacquisition. See [validation](tests/QO100-VALIDATION.md).

Video/audio decode in roughly three-second batches, with a one-second overlap
for tables/keyframes. Playback is currently 320×240 at 10 fps, mono 48 kHz.
The original TS is not rescaled or transcoded when downloaded. **Save received
TS** retains the latest 32 MiB. **Enable audio** requires a user click.
The media WASM is about 31 MiB and is served locally, without a CDN.

CPU and network needs increase with symbol rate. A selected 1.5 MS channel uses
about 3.333 MS/s float IQ (26.7 MB/s); a narrow 333 kS channel uses about
769 kS/s (6.2 MB/s). Use loopback or a suitable LAN. DSP and network backlogs are
bounded separately. If DSP falls behind, the overview remains live; click the
signal or Reacquire to restart decoding. Discontinuities reported by SoapySDR stop reception
instead of silently joining discontinuous IQ. Closing the tab releases the radio
and restores its Linux TV driver.

For LAN access, explicitly bind the host:

```sh
./run.sh --host 0.0.0.0 --port 8090
```

The service has no authentication layer; it defaults to loopback and rejects
cross-origin browser WebSocket access. One tab can own each radio at a time.

## Rebuild from this repository

Sources, build scripts and pinned media hashes are in this repository. Generated
WASM, native builds, virtual environments, IQ and TS captures are excluded from
Git. No Git submodules or older project source directories are needed.

Required system packages on a Debian-like host:

```sh
sudo apt-get install build-essential cmake pkg-config libusb-1.0-0-dev \
  libsoapysdr-dev python3-soapysdr python3-numpy python3-scipy python3-venv \
  emscripten ffmpeg patch
./setup.sh
```

`setup.sh` builds a private libmirisdr with automatic kernel-driver detachment,
then the private SoapyMiri plugin, both WASM receivers and verified FFmpeg assets.
It installs no system SDR libraries. `run.sh` chooses these project-local builds.
Tested here: SoapySDR 0.8, Emscripten 3.1.69 / LLVM 19, Python 3.13.

The build retains adapted sources under `native/leansdr*`. General inlining is
disabled to avoid an installed LLVM 19 crash; arithmetic hot paths are explicitly
inlined. The S2 build adapts an upstream BCH VLA initialization for Clang and uses
a larger WASM stack. Pinned acquisition fixes improve normal-frame PLS detection.
All adaptations are reproducible in `tools/build_decoder.py` and
`vendor/patches/leandvb-acquisition.patch`.

## Tests

With the server running, the following checks do **not** transmit RF:

```sh
python3 tools/prepare_fixture.py
.venv/bin/python tests/browser_check.py
.venv/bin/python tools/prepare_s2_fixtures.py
.venv/bin/python tests/channelizer_check.py
.venv/bin/python tests/s2_check.py
.venv/bin/python tests/media_check.py
.venv/bin/python tests/hardware_check.py
.venv/bin/python tests/wideband_check.py
.venv/bin/python tests/qo100_ui_check.py
```

Browser checks require Playwright Chromium; on another PC install it with
`.venv/bin/playwright install chromium` and update the executable path or
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` environment variable used by the checks.
Fixture generation uses the original bench TS if present, otherwise FFmpeg
creates a local test stream. Recordings live under `/tmp`, outside the repository.
`tests/QO100-VALIDATION.md` distinguishes digital tests, IQ hardware checks and
actual RF tests. The original 739 MHz DVB-S antenna test is also retained.

The website never starts a transmitter. The optional, finite
`tools/pluto_test.py` helper is for the original direct-IF antenna test waveform;
it refuses an active transmitter, enforces a 30-second limit and at least 40 dB
internal attenuation, then mutes TX and restores settings. It is separate from
satellite reception, and its original IQ file is not included in Git.

## Repository and licensing

This is a local Git repository on branch `main`; no remote has been configured.
See [vendor provenance](vendor/PROVENANCE.md) for commits, licenses, media hashes
and patch sources. Original project code is GPL-3.0-or-later; see [LICENSE](LICENSE).
All upstream notices are retained. Provide corresponding source and dependency
build configuration if redistributing FFmpeg or other third-party binaries.
