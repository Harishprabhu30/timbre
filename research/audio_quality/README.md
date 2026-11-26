# Audio quality benchmark

This harness measures offline PCM before and after a DSP path. The software self-check verifies the measurement code on deterministic signals. The [Legacy Spatial harness](../legacy_spatial/) supplies actual macOS WebKit captures for the bypass and Legacy comparisons.

## Run from a fresh checkout

Use Python 3.9 or later. The harness uses the Python standard library and synthesizes all default audio locally. Run the following from the checkout root.

```sh
cd research/audio_quality
python3 -m unittest -v
python3 benchmark.py run
python3 benchmark.py run --sample-rate 44100 --output-dir output/44100
```

The first run writes `output/report.md` and `output/report.json` at 48 kHz. The other writes the same files for 44.1 kHz. Both exercise 17 software reference cases. An injected 37-sample delay and an over-full-scale signal verify that the harness detects errors. The suite tests signed delay, impulse gain and phase, a 997 Hz reference for the level meter, intersample peak detection, and the final encoded clips.

## Measure paired captures

Generate the stimuli at the sample rate of the path under test.

```sh
python3 benchmark.py fixtures --sample-rate 48000 --output-dir output/fixtures
```

The signals cover mono, dual mono, hard-left, hard-right and antiphase playback, silence, stereo and one-sided impulses, sine, log sweep, multitone, seeded pink noise, and synthesized kick, snare and hi-hat transients. The eight-second `listening.wav` combines a centered vowel-like tone, bass and drums with stereo accompaniment and alternating hi-hats.

Measure recordings or exported buffers with this manifest shape. Paths are relative to the manifest. Use mono or stereo RIFF WAV with PCM16, PCM24, PCM32 or IEEE float32 samples. Set `onset_frame` if an impulse or percussion case starts at a different frame than the 100 ms used by the generated stimuli.

```json
{
  "metadata": {"renderer": "macOS WKWebView"},
  "cases": [
    {"fixture": "impulse-left", "path": "bypass", "input": "input.wav", "output": "direct.wav"},
    {"fixture": "listening", "path": "legacy", "input": "listening.wav", "output": "legacy.wav", "max_delay_frames": 2048}
  ]
}
```

```sh
python3 benchmark.py analyze --manifest output/captures/manifest.json --output-dir output/captures/metrics
```

Use `path: bypass` for expected identity. Each bypass checks sample rate, channels, frame count, zero delay where measurable, null RMS below −120 dBFS, peak difference below 0.2 dB, integrated loudness difference below 0.1 LU where measurable, and absence of new full-scale samples. Failed checks exit with status 1 and preserve the reports. Input or usage errors exit with status 2. Inspect the JSON for the individual checks and before/after metrics. Add `--true-peak` to the analysis or self-check for an intersample estimate at additional runtime cost.

## Listen on OnePlus Nord Buds 3

Connect the earbuds to the Mac and select them under **System Settings → Sound → Output**. Use the Mac microphone as the input if a call or recording app is using the earbud microphone. Keep the same output volume, earbud settings and playback app for each clip.

Generate the listening pair from a completed WebKit capture. From `research/audio_quality`, the first command below captures and analyzes Legacy at 48 kHz, including the labeled clips. To analyze an existing capture in a different directory, use the second command. The optional argument to `--listening` selects a different manifest path containing the `listening` fixture.

```sh
python3 ../legacy_spatial/characterize.py --sample-rate 48000 --output-dir output/webkit
python3 benchmark.py analyze --manifest output/webkit/48000/manifest.json --output-dir output/nord-buds --listening
afplay output/nord-buds/listening/original.wav
afplay output/nord-buds/listening/legacy.wav
```

To hide clip identities, add `--blind` to the analysis command and give each trial a new output directory. Play `A.wav` and `B.wav` in the `listening` subdirectory. Before opening `reveal.json`, note which clip you prefer and any difference in drum attack, hi-hat texture, center focus, apparent placement, or apparent loudness. Compare in both orders across several trials. The synthetic clip is a repeatable stimulus. It represents one mix and supports preference testing alongside additional locally supplied material.

Exports are 24-bit PCM WAV at the capture rate. One fixed gain per clip matches integrated loudness, followed by any common attenuation required to keep sampled peaks at or below −2 dBFS before quantization. The exporter preserves source timing and pads the shorter clip at the end if needed. `listening/levels.json` shows the measured loudness and sample peaks of the actual encoded clips. The raw analysis independently compares the unscaled input and output buffers.

## Interpret the measurements

| Metric | Method and limits |
| --- | --- |
| Level and clipping | RMS spans all samples and channels. Peak is the largest absolute sample. Crest is peak divided by RMS. Full-scale counts use `abs(sample) >= 1`. `overs_samples` counts only values above full scale in floating-point audio. Earlier clipping can survive inward gain changes and requires separate waveform inspection. |
| Integrated and short-term loudness | K-weighted mono/stereo using 400 ms blocks, 100 ms hops and absolute/relative gating. At 48 kHz the filter uses the reference coefficients. Other rates use a bilinear remap. Short-term readings are 3 s windows sampled once per second. Short stimuli and gated silence can leave readings undefined. |
| Optional true peak | Uses a 4× windowed-sinc estimate, including the original samples. Near-Nyquist tones and finite capture boundaries can bias the result. This estimate has no EBU conformance certification. |
| Delay and null | Finds the best normalized signed correlation in the dominant channel within the manifest's lag limit, using an early 2,048-frame window. Positive delay means the output arrived later. Periodic signals and differently shaped responses may yield ambiguous peaks. The null uses the entire unshifted comparison of equally shaped captures. SNR is source RMS divided by null RMS. |
| Stereo | Zero-lag uncentered L/R correlation, mid and side RMS, side-to-mid energy ratio and right-to-left energy ratio describe stereo changes. The mid channel is an equal-gain mono downmix. These measures can describe width and cancellation. Spatial preference still requires listening. |
| Frequency and phase | Impulses yield complex output response samples at fixed frequencies, referred to the original impulse time and amplitude. For individual transfer routes use `impulse-left` and `impulse-right`. Non-impulse signals yield power deltas in bands from a single, shared, 2,048-sample Hann window. That snapshot depends on the source content and timing. |
| Transients | Compares peak amplitude in the first 20 ms at the declared input onset. Use the independent delay estimate and inspect the impulse response when the processing smears or displaces the attack. |

JSON uses `null` for unavailable or undefined logarithmic values. When the sample-domain null truly equals zero, `null.exact` is `true` and `null.rms` is `0`. Cues heard on Bluetooth also depend on the OS output stack, earbud processing and fit. The captured WAV measurements characterize digital buffers upstream of those variables.

The level and peak methods are based on the relevant sections of [ITU-R BS.1770-5](https://www.itu.int/rec/R-REC-BS.1770-5-202311-I) and the short-term window follows [EBU Tech 3341](https://tech.ebu.ch/publications/tech3341).
