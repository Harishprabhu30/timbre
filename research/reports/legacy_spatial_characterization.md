# Legacy Spatial characterization

Timbre's Legacy Spatial changed level, frequency response and stereo balance in macOS WKWebView. A hi-hat test lost attack while the same setting boosted a centered kick past full scale. Silent input produced digital silence. The strongest effects in this test were the delayed, frequency-dependent HRTF signal, its interaction with the direct signal, and cross-channel energy from the simulated speakers.

## Reproduce the test

From the checkout root on macOS with Python 3.9+ and Xcode Command Line Tools:

```sh
python3 -B research/legacy_spatial/characterize.py --output-dir /tmp/timbre-legacy
```

This runs 58 renders each at 44.1 and 48 kHz. Add `--sample-rate 48000` for one rate, `--render-only` to capture WAVs, or `--analyze-only` to report on completed captures. WebKit requires access to macOS application services to start its content process. The offline analysis of captured WAVs only requires Python.

The runner adds a temporary test entry point inside the checked-in `engine.js` closure and injects it into a standalone, ephemeral WKWebView. The entry point calls the production graph builder and configuration API using a stereo `OfflineAudioContext`. A generated mono or stereo float32 buffer enters the graph where the media element source normally connects. The runner discards 250 ms of setup preroll to let gain and position automation settle, taking exactly the original number of frames afterward without shifting the output to align peaks.

For every synthetic fixture the harness captures master bypass and isolated Legacy with other effects off, apart from the mono source test whose two-channel mapping is expected. Legacy uses 30°, amount 0.8, 1 m distance and 0° elevation. Individual channel impulses sweep angles from 5° to 90° at amount 0.8, with additional wet-only and zero-amount controls at 30°. Separate captures enable the stock limiter on both dry and Legacy paths using the same impulse, drum and music fixtures. The generated synthetic music includes centered tones and bass, a kick, a snare, and alternating panned hat bursts.

See `legacy-report.md` for the summary and `legacy-report.json` for impulse gain, phase, timing and fixture metrics. Per-rate `metrics/report.md` and `metrics/report.json` contain the full audio-quality analysis. Each `metrics/listening/` contains an Original/Legacy pair as stereo 24-bit WAVs, matched using a constant gain, with final loudness and sample peaks in `levels.json`. The raw WAVs retain their measured levels.

## Initial results

Captured on macOS 26.6.2 (25G83), WKWebView build 21624.5.1.11.3, with the engine from upstream `fe1c45e6b808a02173dfd5e04de93a9fdd05dcbc`. A second independent 48 kHz capture matched all 17 fixture WAVs and 58 output WAVs byte for byte.

### Bypass and impulse timing

Master bypass returned sample-identical stereo PCM for 16 fixtures per rate with exact frame count, two channels and zero delay on non-silent fixtures. The tested 0% Legacy impulse and listening program were sample-identical at both rates. Mono input was copied into both output channels under Web Audio speaker mapping. The three silence cases at each rate (bypass, Legacy and wet-only Legacy) produced exact zeros.

| Left-only impulse at 30° | 44.1 kHz | 48 kHz |
| --- | ---: | ---: |
| Legacy first left signal | 0 frames | 0 frames |
| Legacy dominant left peak | 296 frames (6.71 ms) | 299 frames (6.23 ms) |
| Legacy dominant right peak | 303 frames (6.87 ms) | 311 frames (6.48 ms) |
| Wet-only first left signal above −120 dBFS | 275 frames (6.24 ms) | 278 frames (5.79 ms) |
| Wet-only last left signal above −120 dBFS | 531 frames (12.04 ms) | 534 frames (11.13 ms) |
| Stock limiter only, dominant left peak | 264 frames (5.99 ms) | 288 frames (6.00 ms) |
| Legacy plus stock limiter, dominant left peak | 560 frames (12.70 ms) | 587 frames (12.23 ms) |

The 80% mix has a direct arrival followed by a larger filtered peak. Some narrow-band and tonal fixtures yield multiple correlation peaks, so the impulse timing gives the clearest latency comparison. With reverb disabled, the panners still leave a short impulse tail. The stock compressor-based limiter contributes about 6 ms of additional peak delay in these captures.

### Stereo, frequency response and phase

| 48 kHz Legacy angle | Left input, opposite/same-side impulse energy |
| --- | ---: |
| 5° | −2.20 dB |
| 15° | −5.82 dB |
| 30° | −7.58 dB |
| 55° | −11.84 dB |
| 80° | −12.87 dB |
| 90° | −13.28 dB |

Opposite-ear energy rises as the virtual speakers approach the center. The report records the four input-to-output routes independently. At 48 kHz, the 30° same-side response included +2.98 dB at 630 Hz (phase +9.4°), −3.46 dB at 2.5 kHz (+159.7°), and −13.84 dB at 10 kHz (−165.0°). The 10 kHz wet-only response was −6.03 dB at −172.5°. Adding the 20% undelayed direct signal to the mostly opposite-phase wet response deepened the 10 kHz cancellation in the blended output. Phase is wrapped and referenced to the original impulse time, including the delay.

On the 48 kHz music fixture, stereo correlation rose from 0.946 to 0.982 and side-to-mid RMS fell from −15.54 to −20.44 dB. That is consistent with reduced stereo separation on this fixture. Dual mono remained strongly correlated (0.9997 at 48 kHz), and the antiphase control retained its mostly opposite-channel structure (−0.9992). The latter gained a small fold-down residual at −43.95 dBFS RMS at 48 kHz, measured as the channel average.

### Level, attack and clipping

For the isolated 30°/80% Legacy path, deltas are relative to the original. Attack peak uses a fixed 20 ms window starting at each fixture's input onset.

| Fixture | 44.1 kHz loudness Δ | 48 kHz loudness Δ | 44.1 kHz attack peak Δ | 48 kHz attack peak Δ |
| --- | ---: | ---: | ---: | ---: |
| Centered kick | +6.64 LU | +7.38 LU | +7.96 dB | +8.56 dB |
| Centered snare | +0.83 LU | +1.08 LU | +3.62 dB | +3.71 dB |
| Hi-hat burst | −2.78 LU | −4.72 LU | −1.64 dB | −3.66 dB |
| Synthetic music | +4.04 LU | +4.78 LU | — | — |

At 48 kHz the isolated Legacy kick reached +4.57 dBFS in float32 with 726 over-range channel samples. With the default limiter, the same kick reached +0.36 dBFS with 55 over-range channel samples. The samples are preserved in the research capture as headroom failures. The range of gains shows how strongly level and texture depend on the input.

## Scope

These measurements isolate production DSP stages in desktop WebKit, using source and render buffers at the same rate. They cover deterministic coloration, dry/wet interference, channel summation and transient reshaping. Real-time device scheduling, media decoding and resampling, the iPhone's WebKit build, Bluetooth and the earbuds' own output can affect what a listener hears. The matched synthetic clips are ready for listening. There is no physical-device listening observation yet.
