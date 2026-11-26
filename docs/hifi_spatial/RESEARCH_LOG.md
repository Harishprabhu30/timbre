# Hi-Fi Spatial research log

## 2026-11-26 · Pin the app baseline

**Hypothesis**

The fork can use the upstream app as the playback foundation and isolate the research to dedicated files.

**Experiment**

Resolve upstream and fork refs, compare the pinned app files with the packaged release, inspect the playback and DSP graph, and run the installed-version source check. Verify an unsigned iOS compile in GitHub Actions.

**Result**

Upstream and the fork started at `fe1c45e6b808a02173dfd5e04de93a9fdd05dcbc`. The installed-version check passed. Upstream build 30 packaged the same app inputs. The unsigned iOS app and widget also compiled successfully on the fork's macOS runner. The research Mac has Command Line Tools and lacks an iOS SDK. [Baseline](BASELINE.md) · [GitHub compile check](https://github.com/Harishprabhu30/timbre/actions/runs/45889416842)

**Decision**

Use the pinned engine as the comparison baseline. Measure settled stereo bypass and Legacy Spatial in WebKit, and measure the default limiter separately.

## 2026-11-26 · Settled bypass and Legacy Spatial on Mac WebKit

**Hypothesis**

Settled bypass preserves stereo PCM at the graph boundaries. Legacy's HRTF mix and the output limiter may explain the reported differences in level and percussion attack.

**Experiment**

Render the production DSP graph offline in macOS WKWebView at 44.1 and 48 kHz. Run 58 cases per rate using deterministic PCM, including silence, stereo impulses, and kick, snare, and hi-hat signals. Compare bypass, zero strength, Legacy at multiple angles, and limiter controls. Repeat the 48 kHz capture independently and compare the WAV files by SHA-256.

**Result**

All 16 stereo master-bypass captures per rate were sample-identical. The reported zero-strength cases were also sample-identical, and silent input rendered as digital silence. The independent 48 kHz run reproduced all 17 input WAVs and 58 output WAVs byte for byte. At 30° and 80% strength, the 48 kHz left-speaker impulse produced a left peak at +299 samples and opposite-channel energy 7.58 dB below the direct-side energy. The limiter alone moved the impulse peak by 288 samples. With the limiter off, Legacy lowered hi-hat integrated loudness by 4.72 LU and raised the centered kick by 7.38 LU on these fixtures. [Characterization](../../research/reports/legacy_spatial_characterization.md)

**Decision**

Accept the Mac capture as the repeatable digital reference. Use level-matched Original and Legacy clips for the Nord Buds 3 session. Earbud impressions and live iPhone playback remain to be measured.

## 2026-11-26 · Four-stem residual reconstruction

**Hypothesis**

Adding a direct residual to the sum of imperfect, aligned estimates restores the original stereo sample grid.

**Experiment**

Generate deterministic stereo mix and stem references. Add known leakage, reduce drum attack and omit quiet stereo detail from the estimates. Compute the residual and compare the reconstructed signal sample by sample with the mix. Measure leakage against the known stems.

**Result**

At 44.1 kHz, the 52,920-frame stereo render reconstructed with a −386.918 dBFS RMS null, zero sample offset and 0.000 dB peak and RMS deltas. The drum estimate still contained vocal leakage (0.070 regression coefficient) and its peak within the reference transient window was 1.312 dB lower. These are synthetic fixture results. [Report](../../research/separation_benchmark/reports/report.md) · [JSON](../../research/separation_benchmark/reports/report.json)

**Decision**

Accept residual arithmetic for the offline benchmark. Before evaluating source-informed placement, measure real-model alignment, leakage and transient preservation on known multitracks and run a level-matched listening comparison. [Candidate models](MODEL_CANDIDATES.md)
