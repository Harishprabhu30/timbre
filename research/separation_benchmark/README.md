# Offline four-stem benchmark

This harness measures residual reconstruction and compares estimated vocals, drums, bass, and other against aligned reference stems when available. Run each candidate separator independently and pass its WAV exports to the same evaluator. Python 3.9 or newer is the only dependency.

## Run the reproducible baseline

From this directory:

```sh
python3 benchmark.py synthetic
python3 -m unittest discover -s tests -v
```

The benchmark writes `out/report.md` and `out/report.json`. It generates synthetic audio in memory at 44.1 kHz. `python3 benchmark.py synthetic --sample-rate 48000 --out out/48k` runs the 48 kHz variant. The [checked-in report](reports/report.md) and [JSON](reports/report.json) use the default fixture. It includes known drum attenuation, vocal leakage into drums, bass leakage into vocals, and quiet stereo detail absent from the estimates. No separator runs during this test.

Reports use a fixed arithmetic target of RMS null below −120 dBFS. Exit status 0 means the target passed, 1 means it failed, and 2 indicates an input or execution error. Use a fresh output directory for each model or condition to avoid reading a previous run's files after a failed invocation.

## Compare a local separator result

Store audio, model weights, and raw experiment outputs outside the repository. Use audio you have permission to process. Check the dataset terms and any track-specific rights before sharing files.

```sh
python3 benchmark.py evaluate \
  --mix /path/to/mix.wav \
  --stems /path/to/estimated-stems \
  --reference-stems /path/to/known-stems \
  --metadata /path/to/model-run.json \
  --out out/candidate
```

Each stems directory must contain `vocals.wav`, `drums.wav`, `bass.wav`, and `other.wav`. The reference and metadata options are optional. Without reference stems, the report covers reconstruction and levels. Use the same input and the same reference stems across candidate runs.

Inputs must be nonempty stereo front-left/right RIFF WAV with identical sample rates and frame counts. Supported encodings are PCM16/24/32 and IEEE float32/64, including compatible WAVEFORMATEXTENSIBLE layouts. Prefer lossless float exports for separator output when the model permits it. Export native estimates without individual peak normalization, clipping, or dither. Gains and offsets are applied by the separator or by an explicitly documented adapter. The evaluator uses binary64 arithmetic and reads each input on the supplied grid.

### Prepare and verify the sample grid

1. Record the original mix rate, frame count and channel order as the reference grid. Use the same unaltered mix for all candidates.
2. If the separator changes rate, record both rates and the resampler, including delay convention and method for restoring the exact mix frame grid. Preserve both channels independently. If resampling is unnecessary, record that the rates match.
3. Verify any fixed delay using known aligned material or calibrated markers through the same adapter. Record the signed offset in frames at the mix rate and remove it before feeding the benchmark. For time-dependent offsets or ambiguous matches, resolve the adapter or reference timing before interpreting quality metrics.
4. Preserve time zero and the original duration. If a documented shift or resampling yields an estimate that leaves an uncovered edge, record which edge and its exact length and represent the missing estimate as zero there. Exclude only explicitly identified samples outside the mix time grid. Frame-count mismatches fail validation and the evaluator performs no resampling, channel conversion, gain adjustment, or cropping.

Shape checks verify dimensions. Stem timing remains an input contract. The unit tests include a same-length shifted estimate that reconstructs exactly, demonstrating why reconstruction alone cannot verify alignment.

### Model run metadata

The example below illustrates provenance fields and sample values:

```json
{
  "model": "example-four-stem-model",
  "model_revision": "record a version or checkpoint hash",
  "device": "device and inference backend",
  "model_sample_rate_hz": 44100,
  "resampling": "identity, mix and model both at 44100 Hz",
  "delay_frames_at_mix_rate": 0,
  "alignment_verification": "calibration method, measured shift and edge policy",
  "wall_seconds": 8.21,
  "process_cpu_seconds": 16.42,
  "peak_rss_bytes": 524288000,
  "model_size_bytes": 83886080,
  "first_output_seconds": 8.21,
  "streaming": false
}
```

Measure the separator process with a consistent device and workload, using the same definition of elapsed inference across candidates. Record cold start and warm inference in distinct runs when both matter. On macOS, `/usr/bin/time -p` reports elapsed time and user plus system CPU time for a model command. Use a profiler for peak process RSS and note the sampling method when comparing devices. Keep missing measurements absent. Real-time factor is wall time divided by audio seconds. Average CPU cores is process CPU seconds divided by wall seconds. First-output latency measures time from supplying input until usable output becomes available. File-producing offline models may only provide first output at completion. Audit metadata before sharing reports.

## Interpreting the results

- The evaluator calculates `stem_sum = vocals + drums + bass + other`, `residual = mix - stem_sum`, and `reconstructed = stem_sum + residual` in memory at the original rate. It compares matching indices without fitting a gain or delay. The reconstruction null shows that the model's omissions and errors can be retained in a direct residual. It can pass with poor estimates. Approximate real-time latency, audible bleed and any future spatial edits require independent tests.
- RMS, sample peak, crest factor and full-scale exceedance use sample amplitudes, with full scale at ±1. A reconstructed sample above full scale is counted and never limited. Exact nulls use `exact_null: true` and a null JSON dB value in place of negative infinity. Undefined ratios also use `null`.
- Fixed-gain RMS error, SNR, and zero-lag correlation reveal level, time, or polarity discrepancies that SI-SDR alone can hide. SI-SDR projects the interleaved reference onto each corresponding stereo estimate at a shared scale and uses energy in the error orthogonal to the reference. It is reported without per-channel fits, mean removal or time shifts. It follows the projection described in the original paper. [Le Roux et al., SDR – Half-Baked or Well Done?](https://arxiv.org/abs/1811.02508)
- Relative reference gain simultaneously fits all active known stems to estimate coherent leakage. The fitted off-diagonal values measure linear leakage relative to each reference's original gain. All coefficients are omitted if the active references are singular or ill-conditioned. Smearing, nonlinear processing and remaining musical noise can escape this regression.
- The first-difference RMS delta is a broad proxy weighted toward high frequencies. It does not identify discrete bands or audible differences. The peak-window delta compares the estimate peak within ±5 ms of the largest event in the reference against that event's level. Stereo correlation and side-to-mid ratios reveal aggregate stereo changes. These metrics do not localize the differences in time or replace an aligned, level-matched listening comparison.
