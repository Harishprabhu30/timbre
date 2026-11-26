# Four-stem reconstruction benchmark

Input **synthetic stereo fixture with deliberately imperfect estimates** at **44,100 Hz**, **2 channels**, **52,920 frames**.

| Signal | RMS (dBFS) | Peak (dBFS) | Crest factor (dB) | Over-full-scale samples |
| --- | ---: | ---: | ---: | ---: |
| Original | -18.785 | -6.144 | 12.641 | 0 |
| Estimated stem sum | -18.477 | -6.161 | 12.316 | 0 |
| Residual | -44.319 | -33.485 | 10.834 | 0 |
| Reconstructed | -18.785 | -6.144 | 12.641 | 0 |

**PASS**. RMS null -386.918, peak null -349.195 (dBFS for finite values). RMS target below -120 dBFS.

Sample-indexed reconstruction offset 0 frames. RMS delta 0.000 dB, peak delta 0.000 dB, zero-lag correlation 1.000000.

The null measures arithmetic reconstruction. Evaluate stem accuracy and verify input alignment independently.

## Reference comparison

| Stem | SI-SDR (dB) | Fixed-gain error (dBFS RMS) | RMS delta (dB) | First-difference RMS delta (dB) | Peak-window delta (dB) |
| --- | ---: | ---: | ---: | ---: | ---: |
| vocals | 33.858 | -56.032 | 0.002 | 0.000 | 0.115 |
| drums | 14.170 | -42.652 | -1.260 | -1.408 | -1.312 |
| bass | perfect projection | exact zero | 0.000 | 0.000 | 0.000 |
| other | 22.951 | -49.678 | 0.021 | 0.419 | 0.000 |

Relative reference gain is the simultaneous signed regression coefficient for each known source.

| Estimate | Vocals | Drums | Bass | Other |
| --- | ---: | ---: | ---: | ---: |
| vocals | 1.000 | 0.000 | 0.025 | 0.000 |
| drums | 0.070 | 0.850 | 0.000 | 0.000 |
| bass | 0.000 | 0.000 | 1.000 | 0.000 |
| other | 0.000 | 0.100 | 0.000 | 1.000 |

See the JSON for per-stem stereo and correlation details.

## Model run

No inference measurements supplied.
