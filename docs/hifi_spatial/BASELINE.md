# Timbre baseline for Hi-Fi Spatial research

## Revision and build

- [Upstream `soum91/timbre` main](https://github.com/soum91/timbre/commit/fe1c45e6b808a02173dfd5e04de93a9fdd05dcbc) was pinned to `fe1c45e6b808a02173dfd5e04de93a9fdd05dcbc` on 2026-11-26. The fork `Harishprabhu30/timbre` and its `research/hifi-spatial-v2` branch started at that revision.
- Upstream published [unsigned IPA build 30](https://github.com/soum91/timbre/releases/tag/build-30) from `9791ae02aa6b6f9dd481295953ce05bff4ed488d`. `git diff --name-only 9791ae0 fe1c45e` returns only `AGENTS.md` and `CLAUDE.md`. Build 30 therefore provides packaged build evidence for identical app and workflow files. The pinned commit carries `[skip ci]` and its exact-SHA GitHub status query returned no checks.
- On the research Mac, the installed-version preflight `python3 scripts/check_version_ui.py` passed. An exact-revision local iOS compile could not run because `xcodebuild` requires full Xcode, while this installation has Command Line Tools selected and no Xcode bundle was found. The older packaged IPA does not verify playback or signing on an iPhone.
- The fork's [compile-only GitHub Actions run](https://github.com/Harishprabhu30/timbre/actions/runs/45889416842) passed on `9ce7c07a1d6698f460eb4fd911a5c99a7731e829`. That commit added baseline documentation and the workflow to the pinned revision. The unchanged iOS inputs generated an Xcode project, passed the version gate, and compiled both the app and widget for generic iOS with signing disabled.

[`project.yml`](../../project.yml) defines the SwiftUI iOS 16 app and its iOS 17 widget and compiles the app with `Timbre/Engine/engine.js` as a resource. The upstream [Build IPA workflow](../../.github/workflows/build.yml) runs on pushes to `main` (except add-on-only changes) and on manual dispatch. It verifies the installed-version contract, generates the Xcode project, builds a Release app for generic iOS, checks for the app and widget executables, packages and ad-hoc signs the IPA, and publishes a numbered release and sideload feed. Manual dispatch would also publish, so it was left untouched. At the pinned revision there is a [version UI workflow](../../.github/workflows/version-ui.yml) and [source checker](../../scripts/check_version_ui.py), with no checked-in app test target or audio regression suite. The Firefox add-on uses the same engine and has its own packaging workflow.

## Playback and audio context

[`WebController.swift`](../../Timbre/Browser/WebController.swift#L91) configures a persistent WKWebView data store, restores cookies through `CookieVault`, and injects the bundled engine in the page world at document start in all frames. A boot object contains the DSP configuration, host exclusions, compatibility hosts and background preference. Native changes invoke `window.__timbre.apply`; the engine relays config to child frames.

The engine [attaches](../../Timbre/Engine/engine.js#L519) to eligible playing `HTMLMediaElement`s with `createMediaElementSource`. It tracks observed elements and intercepts playback for detached elements. It leaves known encrypted sources and excluded hosts alone. For cross-origin elements without CORS mode, it makes a credential-free CORS probe and attempts a reload/seek at the same position if permitted. It watches for silence on the processed path while media time is advancing. YouTube hosts receive [compatibility mode](../../Timbre/Engine/engine.js#L23) by default, which hides MediaSource APIs to encourage HLS or progressive playback. That fallback and whether a stream can be tapped depend on the site and WebKit. Website background behavior relies in part on page visibility overrides. The iOS app configures an [`AVAudioSession` playback category](../../Timbre/App/TimbreApp.swift#L9).

The engine [creates one real-time audio context per active frame](../../Timbre/Engine/engine.js#L499) with a playback latency hint, falling back to a context without options. It does not request a sample rate. The actual context rate is sent back through the status/spectrum bridge and is used for EQ coefficients, generated reverb and Web Audio rendering. AppModel's initial 48 kHz is the UI starting value before WebKit reports an actual rate. WebKit can convert media and decoded impulse responses to its context rate. The engine does not expose the original stream sample rate or guarantee the hardware or Bluetooth route's sample rate.

## Current graph

The per-frame [graph](../../Timbre/Engine/engine.js#L252) is:

```text
eligible media sources → explicit 2-channel mixer → preamp → active parametric EQ bands
  → compressor → crossfeed → width/balance → Legacy Spatial → reverb
  → output gain → limiter ┬→ destination
                         └→ analyser
```

The mixer uses speaker channel interpretation, so input format is subject to Web Audio upmix/downmix rules. Most EQ bands use biquads. Shelves use RBJ IIR coefficients with a biquad fallback and crossfading replacements. Crossfeed combines each direct channel with a low-passed, delayed copy of the opposite channel. Width/balance is a mid/side-equivalent stereo matrix with optional mono or swap.

The default [configuration](../../Timbre/Models/DSPConfig.swift#L73) uses 0 dB preamp and output, no EQ bands, and disables compressor, crossfeed, width, Spatial, and reverb. The limiter is on at a nominal −1 dB threshold. The limiter is a `DynamicsCompressorNode` with 20:1 ratio, zero knee, a 1 ms attack and an 80 ms release. It can change gain or add latency and its threshold does not guarantee a sample-peak or true-peak ceiling. The analyser taps the post-limiter signal in parallel with the audio destination.

Before attachment, disabling Timbre leaves the media element on its default path. After attachment, [master bypass](../../Timbre/Engine/engine.js#L780) restores unity preamp/output, removes EQ bands and selects each stage's dry path, including the limiter. It remains inside Web Audio and retains the stereo mixer and context sample rate. Most continuous settings approach their targets with a 15 ms time constant. The bypass identity check therefore measures settled stereo PCM at the graph boundaries. Mono mapping, codec decoding, hardware routing and live switching require their own checks.

## Legacy Spatial

The [Legacy implementation](../../Timbre/Engine/engine.js#L297) splits the stereo input into mono speaker signals. Each goes to a WebKit `PannerNode` using HRTF. Speakers use mirrored azimuth with shared distance/elevation and face forward relative to the default listener. Their stereo outputs sum with +2 dB on the wet bus. [The mix](../../Timbre/Engine/engine.js#L467) is `(1 − amount) × dry + amount × wet`. This scales down the dry signal as amount rises and combines it with a filtered, phase-shifted path. The inverse distance model has zero rolloff, so changing distance at a fixed angle/elevation supplies no configured distance attenuation or explicit propagation delay.

Settings default to 30°, amount 0.8, distance 1 m and elevation 0°, with Spatial disabled. [Effects presets](../../Timbre/Effects/EffectsView.swift#L19) set angle, distance and amount to Front stage (15°, 1 m, 0.7), Near-field monitors (30°, 1 m, 0.8), Wide room (55°, 2 m, 0.9) and Surround-ish (80°, 1.5 m, 1.0), leaving elevation as set by the listener.

## Legacy reverb

[`makeIR` and `updateReverbIR`](../../Timbre/Engine/engine.js#L359) build a predelayed stereo noise impulse response with time-varying low-pass damping, exponential decay and configurable inter-channel correlation. Channels are normalized to unit energy. Imported WAV/AIFF audio is copied into the app's support directory, sent to the engine, decoded there, and energy-normalized per channel. The `ConvolverNode`'s own normalization is disabled. Convolver swaps crossfade over 40 ms. The stage mixes dry gain `1 − 0.5 × mix` with wet gain `mix`. The current interface exposes a single convolver path for the generated or imported response and provides no independent early reflections or hall-tail bus.

Defaults when enabled are 1.8 s decay, 20 ms pre-delay, 6 kHz damping, full width and 25% mix. Generated impulses use `Math.random()`, so the exact impulse varies when regenerated. The first Legacy Spatial measurements disable reverb and other effects to isolate the panners, then exercise the limiter separately.

See [Legacy Spatial characterization](../../research/reports/legacy_spatial_characterization.md) for the test configuration, results and limits.
