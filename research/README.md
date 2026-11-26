# Timbre Hi-Fi Spatial research

The Milestone 1 benchmark runs on the Mac with generated audio. It measures settled stereo bypass and the current Legacy Spatial stage, and checks the arithmetic for four-stem reconstruction. See the [baseline](../docs/hifi_spatial/BASELINE.md) for the source revision, build status, and audio graph.

## Roadmap

| Milestone | Acceptance check |
| --- | --- |
| 1. Baseline | Compile the untouched app and widget, repeat Mac WebKit captures, and verify stereo bypass and residual reconstruction. |
| 2. Clean V2 renderer | Preserve the original stereo direct path. Show zero-strength identity and an audible placement change on known multitracks at matched loudness while retaining attack and vocal clarity. |
| 3. Virtual theatre | Use measured headphone filters and independent early reflections and late hall controls. Verify a fixed stage, room depth, centered vocals, solid bass, and preserved percussion detail. |
| 4. Source-informed placement | Compare four-stem models. Move drums while monitoring vocal and instrument leakage. Keep the residual direct and gate individual percussion controls on isolation quality. |
| 5. iPhone implementation | Compare offline, Web Audio/WASM, native Core ML or DSP, and hybrid routes on the iPhone 12 mini. Measure quality, latency, memory and thermal behavior. |
| 6. Integration | Add click-free comparison and theatre presets. Check randomized level-matched preferences, YouTube playback, background audio and Bluetooth stability. |

## Run from a fresh checkout

Use Python 3.9 or newer. Install the macOS Command Line Tools if you need to run the WKWebView capture. Use Terminal in a logged-in macOS session for WebKit service access.

From the repository root:

~~~sh
python3 research/audio_quality/benchmark.py run --output-dir /tmp/timbre-audio-quality
python3 research/legacy_spatial/characterize.py --output-dir /tmp/timbre-legacy
python3 research/separation_benchmark/benchmark.py synthetic --out /tmp/timbre-separation
~~~

Use new output directories for independent runs. Each benchmark has a Markdown report and JSON data. The WebKit run captures 44.1 and 48 kHz stereo through the current engine, with separate cases for the Legacy stage and limiter. See the individual README files for alternate rates, per-run settings, and the full test commands.

- [Audio quality harness and headphone comparison](audio_quality/README.md)
- [WebKit capture and initial characterization](reports/legacy_spatial_characterization.md)
- [Four-stem benchmark and local WAV input](separation_benchmark/README.md)

## Listening on the Mac

Connect the OnePlus Nord Buds 3 in macOS Bluetooth settings and select them under Sound → Output. Keep system volume, earbud settings, and playback app fixed for the session. Use the level-matched Original and Legacy clips from the WebKit run. Compare the center image, bass weight, drum attack, and the texture and location of the hi-hat or shaker. Record impressions and preferences before looking up track labels when listening blind.

With the example output paths above, the labeled 48 kHz clips are in `/tmp/timbre-legacy/48000/metrics/listening/`. For a fresh blind pair, run:

~~~sh
python3 research/audio_quality/benchmark.py analyze \
  --manifest /tmp/timbre-legacy/48000/manifest.json \
  --listening --blind --output-dir /tmp/timbre-blind
~~~

Play `A.wav` and `B.wav` in `/tmp/timbre-blind/listening/`. Open `reveal.json` after recording your impressions. See `levels.json` for loudness and peak measurements of the exported files.

The render reports measure digital PCM before it reaches the playback device. The earbud session adds observations about the heard result. Keep locally supplied music, rendered audio, model checkpoints, and listening notes outside the repository.

## Research notes

- [Research log](../docs/hifi_spatial/RESEARCH_LOG.md)
- [Four-stem model candidates](../docs/hifi_spatial/MODEL_CANDIDATES.md)
- [Deployment options and iPhone test gates](../docs/hifi_spatial/DEPLOYMENT_ARCHITECTURE.md)
