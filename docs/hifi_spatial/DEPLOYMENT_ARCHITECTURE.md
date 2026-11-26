# Timbre deployment architecture research

**Milestone 1 decision**

Use offline PCM for separation and the existing Timbre Web Audio graph for the Legacy baseline. Test V2 on known tracks before involving any separator. Revisit deployment once the same material has been evaluated on the target iPhone 12 mini.

## Playback boundary

Timbre injects `Timbre/Engine/engine.js` into frames of WKWebView. The engine uses `createMediaElementSource` for an eligible media element and creates its `AudioContext` without a requested sample rate. The WebView script bridge carries control and diagnostic messages. See [the engine](../../Timbre/Engine/engine.js), [the WebView controller](../../Timbre/Browser/WebController.swift), and [the baseline](BASELINE.md).

Use authorized local PCM to compare design options. Prove access to an eligible decoded YouTube or YouTube Music stream before applying any in-app design to it. Test both logged-in playback and cross-origin media under the app's existing browser behavior. A Web Audio media element source outputs silence for CORS-cross-origin media. [Web Audio security requirements](https://www.w3.org/TR/webaudio/#MediaElementAudioSourceNode-security)

## Options

| Route | Feasibility and cost | Evidence needed |
| --- | --- | --- |
| Web Audio / JavaScript / WASM | The renderer can stay in the current graph near the media source. Model weights, runtime, graph buffers and chunk copies may compete for WebView memory. Keep inference and allocation off the audio render callback. WebGPU adds an optional backend to probe. [WebKit Safari 26 features](https://webkit.org/blog/17333/webkit-features-in-safari-26-0/), [ONNX Runtime Web guide](https://onnxruntime.ai/docs/tutorials/web/) | Verify operator support, worker data transfer, actual PCM access, render callback stability, quality at the selected chunk size, background behavior, and thermal cost in the shipping WKWebView. |
| Native Core ML | Fixed-shape blocks may convert and run on CPU, GPU, or Neural Engine depending on the model graph and platform. Inference requires a PCM source and any out-of-graph transforms and overlap-add. [Core ML compute units](https://developer.apple.com/documentation/coreml/mlcomputeunits), [Apple conversion workflow](https://apple.github.io/coremltools/docs-guides/source/convert-pytorch-workflow.html) | Compare converted and reference outputs. Profile compute-unit coverage, memory, conversion and weight size, first chunk latency, sustained load, and fallback behavior. Prove how decoded PCM reaches the model. |
| Native DSP and WebView bridge | Native convolution is an option for a native PCM source. Extending it to WebView media requires recovering and returning PCM through a timed, bounded transport or a separate playback path. | Prototype the actual PCM handoff. Measure copying, scheduling, underflow, clock drift, A/V sync, interruption recovery, and background continuation. |
| Offline / preprocessed | A Mac can separate and render approved material ahead of time. A rendered stereo export avoids a live model and is an immediate comparison path. Storage and preparation time scale with duration and whether stems are kept. | Measure preparation time and file size. Confirm channel and timeline identity and inspect the resulting files. Use local playback and document the prerecorded workflow for each test. |
| Hybrid | Run renderer in Web Audio and supply aligned estimates prepared offline or natively where PCM is available. Add bounded buffers and explicit sample position to keep the estimates aligned when seeking or resuming. | Measure both parts together, including buffer transfer overhead and synchronization. Ensure a stable direct path when estimates are late or unavailable. |

At 48 kHz, float32 stereo carries 384,000 bytes per second. The original and four stereo stems carry about 1.92 MB/s before framing, copying, or a separate residual buffer. This is the payload rate. Scheduling, allocation, and copying have to be measured on the proposed transport.

## Device decision gate

- Use the same mixes, renderer settings and level-matched exports across routes. Keep the original sample timeline and report latency relative to it. Separate input buffering, model lookahead, processing, transfer, output buffering and Bluetooth playback latency.
- Compare cold start and sustained playback. Record P50 and P99 work time per hop, real-time factor, peak memory, thermal state and time spent throttled, battery change over equivalent runs, dropouts, and A/V sync error. A live candidate needs headroom within its hop deadline under sustained load.
- Verify seeking, route changes, calls or interruptions, backgrounding, and long playback with YouTube and YouTube Music on the iPhone. Use Mac WebKit and Nord Buds 3 for repeatable render and listening experiments during development.
- Choose the simplest route that delivers an audible benefit and passes the playback checks. Keep offline render available as a deliverable for local material even if a live candidate passes.
