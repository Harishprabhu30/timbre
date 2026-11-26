"""Time-domain metrics for already sample-aligned stereo mixes and stems."""

from array import array
from math import fsum, isfinite, log10, sqrt


STEMS = ("vocals", "drums", "bass", "other")
NULL_RMS_TARGET_DBFS = -120.0


def amplitude_db(value):
    return 20 * log10(value) if value > 0 else None


def power_ratio_db(numerator, denominator):
    return 10 * (log10(numerator) - log10(denominator)) if numerator > 0 and denominator > 0 else None


def delta(value, reference):
    return value - reference if value is not None and reference is not None else None


def dot(left, right):
    return fsum(a * b for a, b in zip(left, right))


def correlation(cross, left_energy, right_energy):
    if left_energy == 0 or right_energy == 0:
        return None
    return max(-1.0, min(1.0, cross / sqrt(left_energy) / sqrt(right_energy)))


def summary(samples):
    mean_square = dot(samples, samples) / len(samples)
    peak = max(map(abs, samples))
    return {
        "rms_dbfs": amplitude_db(sqrt(mean_square)),
        "peak_dbfs": amplitude_db(peak),
        "crest_db": power_ratio_db(peak ** 2, mean_square),
        "over_full_scale_samples": sum(abs(sample) > 1 for sample in samples),
    }


def null_summary(original, candidate):
    error = array("d", (value - source for source, value in zip(original, candidate)))
    error_power = dot(error, error)
    error_peak = max(map(abs, error))
    rms_dbfs = amplitude_db(sqrt(error_power / len(error)))
    if rms_dbfs is None and error_peak > 0:
        # Preserve a meaningful dB result when squaring a very small error underflows.
        relative_power = fsum((value / error_peak) ** 2 for value in error) / len(error)
        rms_dbfs = amplitude_db(error_peak) + 10 * log10(relative_power)
    original_power = dot(original, original)
    return {
        "rms_error_dbfs": rms_dbfs,
        "peak_error_dbfs": amplitude_db(error_peak),
        "snr_db": power_ratio_db(original_power, error_power),
        "exact_null": error_peak == 0,
        "zero_lag_correlation": correlation(dot(original, candidate), original_power, dot(candidate, candidate)),
    }


def stereo(samples):
    left = samples[::2]
    right = samples[1::2]
    return {
        "interchannel_correlation": correlation(dot(left, right), dot(left, left), dot(right, right)),
        "side_to_mid_db": power_ratio_db(
            fsum((a - b) ** 2 for a, b in zip(left, right)),
            fsum((a + b) ** 2 for a, b in zip(left, right)),
        ),
    }


def reconstruct(original, stems):
    stem_sum = array("d", (fsum(samples) for samples in zip(*stems)))
    residual = array("d", (source - summed for source, summed in zip(original, stem_sum)))
    reconstructed = array("d", (summed + rest for summed, rest in zip(stem_sum, residual)))
    return stem_sum, residual, reconstructed


def relative_leakage_coefficients(gram, covariance):
    """Solve normalized reference least squares with pivoted elimination."""
    count = len(gram)
    rows = [list(row) + [value] for row, value in zip(gram, covariance)]
    for i in range(count):
        pivot = max(range(i, count), key=lambda row: abs(rows[row][i]))
        rows[i], rows[pivot] = rows[pivot], rows[i]
        divisor = rows[i][i]
        if abs(divisor) < 1e-8:
            return None
        rows[i] = [value / divisor for value in rows[i]]
        for j, row in enumerate(rows):
            if j != i:
                factor = row[i]
                rows[j] = [value - factor * pivot_value for value, pivot_value in zip(row, rows[i])]
    return [row[-1] for row in rows]


def reference_metrics(estimates, references, sample_rate):
    """Compare stereo stems at fixed gain and shift, with SI-SDR as a second view."""
    reference_energy = {name: dot(value, value) for name, value in references.items()}
    active = [name for name in STEMS if reference_energy[name] > 0]
    norms = {name: sqrt(reference_energy[name]) for name in active}
    gram = [[dot(references[a], references[b]) / norms[a] / norms[b] for b in active] for a in active]
    window = round(sample_rate * 0.005) * 2
    results = {}
    for name in STEMS:
        estimate = estimates[name]
        reference = references[name]
        covariance = [dot(estimate, references[source]) / norms[source] for source in active]
        coefficients = relative_leakage_coefficients(gram, covariance) if active else None
        ref_energy = reference_energy[name]
        estimate_energy = dot(estimate, estimate)
        peak_window_db = None
        si_sdr_db = None
        si_sdr_status = "silent reference"
        if ref_energy > 0:
            cross = dot(estimate, reference)
            scale = cross / ref_energy
            target_energy = (scale ** 2) * ref_energy
            noise_energy = fsum((sample - scale * expected) ** 2 for sample, expected in zip(estimate, reference))
            si_sdr_db = power_ratio_db(target_energy, noise_energy)
            if si_sdr_db is not None:
                si_sdr_status = "finite"
            elif target_energy > 0:
                si_sdr_status = "perfect projection"
            elif estimate_energy > 0:
                si_sdr_status = "zero projection"
            else:
                si_sdr_status = "silent estimate"

            peak_index = max(range(len(reference)), key=lambda index: abs(reference[index]))
            peak_start = max(0, (peak_index // 2) * 2 - window)
            peak_end = (peak_index // 2) * 2 + window + 2
            peak_window_db = delta(
                amplitude_db(max(map(abs, estimate[peak_start:peak_end]))),
                amplitude_db(abs(reference[peak_index])),
            )

        results[name] = {
            "fixed_gain_error": null_summary(reference, estimate),
            "si_sdr_db": si_sdr_db,
            "si_sdr_status": si_sdr_status,
            "rms_delta_db": power_ratio_db(estimate_energy, ref_energy),
            "first_difference_rms_delta_db": power_ratio_db(
                fsum((estimate[i] - estimate[i - 2]) ** 2 for i in range(2, len(estimate))),
                fsum((reference[i] - reference[i - 2]) ** 2 for i in range(2, len(reference))),
            ),
            "reference_peak_window_delta_db": peak_window_db,
            "estimated_stereo": stereo(estimate),
            "reference_stereo": stereo(reference),
            "relative_reference_gain": (
                {source: coefficients[i] / norms[source] for i, source in enumerate(active)}
                if coefficients is not None else None
            ),
        }
    return results


def evaluate(mix, estimates, references=None):
    if mix.sample_rate <= 0:
        raise ValueError("mix: expected a positive sample rate")
    all_audio = [("mix", mix), *estimates.items()]
    if references is not None:
        all_audio.extend((f"reference {name}", audio) for name, audio in references.items())
    for name, audio in all_audio:
        if audio.sample_rate != mix.sample_rate:
            raise ValueError(f"{name}: sample rate {audio.sample_rate} Hz, expected {mix.sample_rate} Hz")
        if audio.channels != 2:
            raise ValueError(f"{name}: expected stereo audio, got {audio.channels} channels")
        if audio.frames != mix.frames or audio.frames == 0 or len(audio.samples) % 2:
            raise ValueError(f"{name}: {audio.frames} complete stereo frames, expected {mix.frames} nonempty frames")
        if not all(map(isfinite, audio.samples)):
            raise ValueError(f"{name}: non-finite samples")

    source = mix.samples
    estimates = {name: estimates[name].samples for name in STEMS}
    summed, residual, reconstructed = reconstruct(source, estimates.values())
    null = null_summary(source, reconstructed)
    passed = null["exact_null"] or null["rms_error_dbfs"] < NULL_RMS_TARGET_DBFS
    mix_levels = summary(source)
    reconstructed_levels = summary(reconstructed)
    return {
        "format": {"sample_rate_hz": mix.sample_rate, "channels": mix.channels, "frames": mix.frames},
        "mix": mix_levels,
        "estimated_stem_sum": summary(summed),
        "residual": summary(residual),
        "reconstruction": {
            "sample_offset_frames": 0,
            "rms_delta_db": delta(reconstructed_levels["rms_dbfs"], mix_levels["rms_dbfs"]),
            "peak_delta_db": delta(reconstructed_levels["peak_dbfs"], mix_levels["peak_dbfs"]),
            "target_rms_null_dbfs": NULL_RMS_TARGET_DBFS,
            "passed": passed,
            **reconstructed_levels,
            **null,
        },
        "estimated_stems": {name: summary(stem) for name, stem in estimates.items()},
        "reference_comparison": (
            reference_metrics(estimates, {name: references[name].samples for name in STEMS}, mix.sample_rate)
            if references is not None else None
        ),
    }
