# Single-SDR shared server decoding validation

The current receiver uses **one SDR capture for the entire band**. The server
extracts selected signals digitally and performs native DVB decoding. Browsers
receive MPEG-TS, a compact FFT and status; only video/audio decoding remains in
the browser. This supersedes the historical browser-DVB validation documents.

## Full-band multi-signal test

`prepare_shared_fixture.py` creates one **10 MS/s** IQ capture centered on
**745 MHz IF**, containing two independent test transmissions:

| IF center | Signal |
| --- | --- |
| 741.5 MHz | DVB-S2, 333 ksym/s, 8PSK 2/3, short frames, pilots |
| 748.25 MHz | DVB-S, 333 ksym/s, QPSK 1/2 |

These are synthetic test placements, **not live satellite reception**. In
particular, the synthetic signal at the beacon's IF is intentionally a different
profile to test detection rather than assuming a beacon preset.

The native end-to-end test verified:

- Three users received two different transmissions from **one capture**.
- The first user selected Auto with a deliberately wrong 1500 ksym/s hint;
  spectrum-assisted acquisition confirmed 333 ksym/s DVB-S2 / 8PSK 2/3.
- A second user specified compatible manual settings and reused that same
  decoder, despite clicking 1 kHz away from the first request.
- A third user independently acquired DVB-S / QPSK 1/2 at the other frequency.
- Exactly **one capture and two native decoder jobs** served those users.
- Every recovered packet checked against the original TS matched its source.
- Retuning one user joined the other decoder without changing the SDR tuning
  or disturbing the remaining viewer.
- Channel limits rejected an extra job without evicting a working channel.
- Last-subscriber removal stopped its decoder. Last-viewer removal released
  the capture and left no active jobs.
- Binary network frames were only `F` (2049-byte FFT) and `T` (MPEG-TS); no IQ.

See `shared-server-results.json` and `shared-server-runtime.log`.

## Automatic native acquisition matrix

Controlled IQ replay with Auto standard, Auto common-rate search, and a wrong
333 ksym/s hint recovered these profiles. All collected packets matched source.

| Signal | Confirmed parameters |
| --- | --- |
| QPSK, 33 ksym/s | DVB-S2, 1/2, short frames |
| QPSK, 125 ksym/s | DVB-S2, 4/5, normal frames |
| QPSK, 1500 ksym/s | DVB-S2, 4/5, normal frames |
| 16APSK, 500 ksym/s | DVB-S2, 2/3, normal frames |
| 32APSK, 2000 ksym/s | DVB-S2, 3/4, normal frames |
| QPSK, 333 ksym/s | DVB-S, FEC 3/4 found by search |

The separate full-band test covers 333 ksym/s 8PSK and DVB-S FEC 1/2.
Results are in `native-matrix-results.json`. A spectrum estimate itself never
counts as a successful detection: native lock, aligned TS and CRC-valid PAT/PMT
must confirm it. Automatic searches try up to three common rates; custom rates,
roll-off, weak signals and overlapping transmissions can require manual input.

## Browser and network checks

Two real Chromium pages shared a single native decoder and displayed recovered
MPEG-2 video/audio. Audio activation, original TS download and independent
Waterfall-only subscriptions passed. No browser DVB decoder worker or LeanDVB
WASM was loaded. No JavaScript page errors occurred. The UI screenshot is
explicitly marked **Replay** and is not evidence of a live RF lock.

See `shared-browser-results.json` and `shared-browser-interface.png`. The same
FFmpeg browser media engine previously passed H.264/AAC and HEVC/AAC checks;
its codec implementation is unchanged (`media-results.json`).

Steady FFT payload is 2049 bytes at approximately 10 Hz (about 164 kbit/s/user).
TS bitrate adds according to the selected transmission. Status/protocol overhead
and the initial cached browser-codec download are separate. Native CPU work is
shared per signal; TS unicast bandwidth still adds per viewer.

## Hardware checks with one SDR at a time

The application opens **at most one physical SDRone**. If several are attached,
only the startup selection is used; another user cannot open the second radio
while the shared capture is active.

Receive-only tests verified:

- Two clients share one 2.048 MS/s capture; closing either keeps the other live.
- If another SDR is present, an attempted second capture is explicitly rejected.
- The 10 MS/s overview is shared by two clients and sustains approximately the
  requested hardware rate while sending only compact FFT updates.
- Linux msi2500 drivers are restored after the final user leaves.
- The test script also works when **only one SDR is attached**. On this PC,
  ports 1-1 and 1-5 were each tested **sequentially**, never as a required pair.

Results: `hardware-results.log`, `wideband-results.log`, `qo100-ui-results.log`.
No transmitter was started. These checks prove sample acquisition, sharing and
cleanup, not RF sensitivity or live satellite DVB-S2 reception.

## Bounds, shutdown and build

`server_unit_check.py` covers fragmented TS input, corrupted PSI CRC rejection,
no false detection from a flat noise spectrum, bounded acquisition plans and a
slow client's queue budget without disturbing a fast client.

`shutdown_check.py` sends SIGTERM with an active native decoder and connected
viewer. The server exits cleanly and reaps the decoder process. A hardware
capture is stopped before waiting for browser close handshakes.

`setup.sh` completed with the tracked native driver/DSP sources and verified
browser media hashes, without requiring a browser-DVB WASM build or changing
system SDR libraries. Python syntax, JavaScript syntax and project whitespace
checks passed. Test IQ/TS recordings and generated binaries remain outside Git.

The native S2 decoder retains upstream hard-decision LDPC bit-flipping; clean
waveform tests do not establish near-threshold performance. DVB-S2X, multistream,
GSE, ACM/VCM, every MODCOD and arbitrary custom symbol-rate detection are not
qualified by these tests. Confirmed modulation metadata is retained through
brief tentative PLS changes and reacquired following transport loss.
