> Historical architecture: production decoding now runs on the server. See [single-SDR server validation](SERVER-VALIDATION.md).

# QO-100 WB / DVB-S2 validation — 2026-11-16

These tests validate implementation and hardware sample acquisition. **No live
satellite DVB-S2 lock is claimed.** The earlier 739 MHz antenna test validated
DVB-S and is retained separately in `VALIDATION.md`. No RF was transmitted for
this extension. The browser UI displayed noise during the receive-only checks.

## Browser demodulation

Real Chromium workers decoded generated IQ from pinned LeanDVB TX sources.
All tests used automatic MODCOD and frame-size detection, pilots enabled, and
roll-off .35. The receiver recovered **7330 packets, all source-matching**, over
these cases:

| Symbol rate / ksym/s | Modulation / FEC | Frame | Recovered / matching |
| --- | --- | --- | --- |
| 33 | QPSK 1/2 | Short | 803 / 803 |
| 66 | QPSK 1/2 | Short | 803 / 803 |
| 125 | QPSK 4/5 | Normal | 719 / 719 |
| 250 | QPSK 4/5 | Short | 763 / 763 |
| 333 | 8PSK 2/3 | Short | 742 / 742 |
| 500 | 16APSK 2/3 | Normal | 685 / 685 |
| 1000 | QPSK 1/2 | Normal | 768 / 768 |
| 1500 | QPSK 4/5 | Normal | 719 / 719 |
| 2000 | 32APSK 3/4 | Normal | 609 / 609 |
| 1500, through WB channelizer | QPSK 4/5 | Normal | 719 / 719 |

The channelized case embeds the beacon waveform at -3.5 MHz in a synthetic
10 MS/s capture, then extracts it at 3.333 MS/s. This validates the selected
channel's frequency shift, continuous filter/decimation state and browser S2
recovery together. `channelizer_check.py` also compared split-block filtering
against a continuous reference at five rates; maximum error was below 2e-6.

Results: `s2-results.json`. These are clean digital tests, not sensitivity,
phase-noise, adjacent-channel, ACM/VCM, every-MODCOD, or long-duration tests.
The built-in hard-decision LDPC bit-flipping receiver has limited weak-signal
performance compared with soft-decision implementations.

The original DVB-S browser regression recovered 151152 TS bytes and decoded
MPEG-2/MP2 media without page errors. Separate browser codec tests decoded
H.264/AAC and HEVC/AAC test streams: 20 RGBA frames and 96000 mono audio samples
per two-second stream. See `media-results.json` and `browser-results.log`.

## SDR hardware and UI

Receive-only tests on physical USB port 1-1 / device 001:010:

- Requested 10 MS/s around 745 MHz IF, maximum tuner bandwidth.
- Generated a 2048-bin spectrum around ten times per second.
- Switched selected channels from 747.25 MHz / 333 ksym/s to the beacon IF
  741.5 MHz / 1500 ksym/s without reopening the SDR.
- Emitted selected-channel IQ at 769230.77 and 3333333.33 samples/s respectively.
- Steady hardware rate was approximately 9.99 MS/s after startup.
- Default beacon startup, live QO-100 preset, waterfall click retune and direct
  IF preset passed in Chromium without JavaScript errors.
- Both receivers passed independent IQ capture, duplicate-ownership rejection
  and Linux driver restoration checks.

The driver was adjusted to separate USB transfer depth from the host FIFO.
Wideband runs use 16 USB transfers and 128 host buffers. A wrapping sample-counter
notice can occur during hardware startup; it is not a qualified RF measurement.
Soapy-reported overflow stops reception. Browser DSP overload stops the decoder
while leaving the overview live and offers reacquisition.

See `wideband-results.log`, `hardware-results.log`, `qo100-ui-results.log` and
`qo100-interface.png`. The latter shows the receiver UI and real wideband noise;
it is not a screenshot of a decoded satellite signal.

## Build and repository

`setup.sh` completed using only tracked vendor source trees and pinned FFmpeg
asset hashes. System SDR libraries were not replaced. Generated artifacts and
captures are ignored by Git. The repository includes the build adaptations,
source provenance, documentation, fixture generators and checks.
