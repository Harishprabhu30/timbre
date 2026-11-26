"""Measurements for offline captures. Comparison never shifts or crops the input."""

from array import array
import cmath
import math


def db(amplitude):
    return 20 * math.log10(amplitude) if amplitude > 0 else None


def _power_db(energy):
    return 10 * math.log10(energy) if energy > 0 else None


def _difference(output, original):
    return output - original if output is not None and original is not None else None


def _power(channel):
    return math.fsum(sample * sample for sample in channel)


def _rms(channel):
    return math.sqrt(_power(channel) / len(channel))


def _stereo(channels):
    if len(channels) == 1:
        return None
    left, right = channels
    power_l, power_r = _power(left), _power(right)
    product = math.fsum(a * b for a, b in zip(left, right))
    denominator = math.sqrt(power_l * power_r)
    mid = math.sqrt(max(0, power_l + power_r + 2 * product) / (4 * len(left)))
    side = math.sqrt(max(0, power_l + power_r - 2 * product) / (4 * len(left)))
    return {
        "zero_lag_correlation": max(-1.0, min(1.0, product / denominator)) if denominator else None,
        "mid_rms_dbfs": db(mid),
        "side_rms_dbfs": db(side),
        "side_to_mid_db": db(side / mid) if mid else None,
        "right_to_left_db": _power_db(power_r / power_l) if power_l else None,
    }


# ITU-R BS.1770-5 annex 1, Tables 1 and 2. Numerators followed by denominators.
_K_WEIGHTING = (
    ((1.53512485958697, -2.69169618940638, 1.19839281085285), (1, -1.69065929318241, 0.73248077421585)),
    ((1, -2, 1), (1, -1.99004745483398, 0.99007225036621)),
)


def _at_sample_rate(coefficients, rate):
    # Substitute the reference delay variable with (a + z^-1) / (1 + a*z^-1).
    # This converts back through the bilinear transform to the requested rate.
    a = (48_000 - rate) / (48_000 + rate)
    c0, c1, c2 = coefficients
    return (
        c0 + a * c1 + a * a * c2,
        2 * a * c0 + (1 + a * a) * c1 + 2 * a * c2,
        a * a * c0 + a * c1 + c2,
    )


def _filter(samples, numerator, denominator):
    b0, b1, b2 = (value / denominator[0] for value in numerator)
    _, a1, a2 = (value / denominator[0] for value in denominator)
    z1 = z2 = 0.0
    for sample in samples:
        filtered = b0 * sample + z1
        z1, z2 = b1 * sample - a1 * filtered + z2, b2 * sample - a2 * filtered
        yield filtered


def _lufs(energy):
    level = _power_db(energy)
    return level - 0.691 if level is not None else None


def loudness(audio):
    result = {"integrated_lufs": None, "short_term_max_lufs": None, "short_term_windows_lufs": []}
    block = round(0.4 * audio.rate)
    if audio.frames < block or audio.rate < 8000:
        return result
    coefficients = tuple((_at_sample_rate(b, audio.rate), _at_sample_rate(a, audio.rate)) for b, a in _K_WEIGHTING)
    prefix = None
    for signal in audio.channels:
        stage1 = _filter(signal, *coefficients[0])
        stage2 = _filter(stage1, *coefficients[1])
        if prefix is None:
            prefix = array("d", [0.0])
            cumulative = 0.0
            for sample in stage2:
                cumulative += sample * sample
                prefix.append(cumulative)
        else:
            cumulative = 0.0
            for index, sample in enumerate(stage2, start=1):
                cumulative += sample * sample
                prefix[index] += cumulative

    hop = round(0.1 * audio.rate)
    absolute_gate = 10 ** ((-70 + 0.691) / 10)
    blocks = [(prefix[end] - prefix[end - block]) / block for end in range(block, audio.frames + 1, hop)]
    above_absolute = [value for value in blocks if value > absolute_gate]
    if above_absolute:
        relative_gate = math.fsum(above_absolute) / len(above_absolute) / 10
        gated = [value for value in above_absolute if value > relative_gate]
        result["integrated_lufs"] = _lufs(math.fsum(gated) / len(gated))

    short_term = 3 * audio.rate
    windows = [
        {"end_s": end / audio.rate, "lufs": _lufs((prefix[end] - prefix[end - short_term]) / short_term)}
        for end in range(short_term, audio.frames + 1, audio.rate)
    ]
    result["short_term_windows_lufs"] = windows
    result["short_term_max_lufs"] = max((window["lufs"] for window in windows if window["lufs"] is not None), default=None)
    return result


def approximate_true_peak(audio):
    """Four-phase windowed-sinc estimate; may under-read near Nyquist."""
    radius = 12
    offsets = range(1 - radius, radius + 1)
    kernels = []
    for phase in (0.25, 0.5, 0.75):
        delays = [offset - phase for offset in offsets]
        weights = [
            math.sin(math.pi * delay) / (math.pi * delay) * (0.5 + 0.5 * math.cos(math.pi * delay / radius))
            for delay in delays
        ]
        gain = sum(weights)
        kernels.append(tuple(weight / gain for weight in weights))

    peak = max(abs(sample) for channel in audio.channels for sample in channel)
    for channel in audio.channels:
        padding = [0.0] * radius
        padded = padding + list(channel) + padding
        for index in range(audio.frames + 1):
            segment = padded[index:index + 2 * radius]
            for kernel in kernels:
                peak = max(peak, abs(sum(sample * weight for sample, weight in zip(segment, kernel))))
    return db(peak)


def summarize(audio):
    rms = math.sqrt(sum(_power(channel) for channel in audio.channels) / (audio.frames * len(audio.channels)))
    peak = max(abs(sample) for channel in audio.channels for sample in channel)
    return {
        "sample_rate_hz": audio.rate,
        "channels": len(audio.channels),
        "frames": audio.frames,
        "rms": rms,
        "rms_dbfs": db(rms),
        "sample_peak": peak,
        "sample_peak_dbfs": db(peak),
        "crest_factor_db": db(peak / rms) if rms else None,
        "full_scale_samples": sum(abs(sample) >= 1 for channel in audio.channels for sample in channel),
        "overs_samples": sum(abs(sample) > 1 for channel in audio.channels for sample in channel),
        "channel_rms_dbfs": [db(_rms(channel)) for channel in audio.channels],
        "stereo": _stereo(audio.channels),
        **loudness(audio),
    }


def _fft(samples, inverse=False):
    """Radix-2 DFT used for a bounded correlation search and band energy."""
    values = list(samples)
    count = len(values)
    j = 0
    for i in range(1, count):
        bit = count >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            values[i], values[j] = values[j], values[i]
    span = 2
    while span <= count:
        midpoint = span // 2
        increment = cmath.exp((1 if inverse else -1) * 1j * math.tau / span)
        for start in range(0, count, span):
            rotation = 1.0
            for i in range(start, start + midpoint):
                even, odd = values[i], rotation * values[i + midpoint]
                values[i], values[i + midpoint] = even + odd, even - odd
                rotation *= increment
        span *= 2
    return [value / count for value in values] if inverse else values


def _anchor(original):
    channel = max(range(len(original.channels)), key=lambda index: max(map(abs, original.channels[index])))
    track = original.channels[channel]
    peak = max(map(abs, track))
    start = next((index for index, sample in enumerate(track) if abs(sample) > 0.12 * peak), 0)
    return channel, max(0, start - round(0.004 * original.rate))


def _sample_delay(original, processed, max_delay, anchor):
    index, start = anchor
    reference = original.channels[index][start:start + 2048]
    target = processed.channels[index]
    reference_power = _power(reference)
    if not reference_power or not any(target):
        return None

    padding = min(len(reference), len(target)) - 1
    first = max(-max_delay, -start - padding)
    last = min(max_delay, len(target) - start - 1)
    if last < first:
        return None
    # Zero-padding at capture boundaries preserves the sign of lag.
    begin = start + first
    end = start + last + len(reference)
    excerpt = [0.0] * max(0, -begin) + list(target[max(0, begin):end]) + [0.0] * max(0, end - len(target))
    size = 1 << (len(reference) + len(excerpt) - 2).bit_length()
    search = _fft(excerpt + [0.0] * (size - len(excerpt)))
    template = _fft(list(reversed(reference)) + [0.0] * (size - len(reference)))
    products = _fft((left * right for left, right in zip(search, template)), inverse=True)
    cumulative = [0.0]
    for sample in excerpt:
        cumulative.append(cumulative[-1] + sample * sample)

    candidates = []
    for offset, lag in enumerate(range(first, last + 1)):
        target_power = cumulative[offset + len(reference)] - cumulative[offset]
        if target_power > 0:
            denominator = math.sqrt(reference_power * target_power)
            score = products[offset + len(reference) - 1].real / denominator
            candidates.append((min(1.0, abs(score)), lag, score))
    if not candidates:
        return None
    strength, lag, score = max(candidates, key=lambda item: (item[0], -abs(item[1])))
    return {
        "frames": lag,
        "ms": 1000 * lag / original.rate,
        "signed_correlation": max(-1.0, min(1.0, score)),
        "ambiguous": strength < 0.5 or any(s >= strength - 0.002 and abs(other - lag) > 1 for s, other, _ in candidates),
    }


def _headroom_delta(ref_peak, out_peak):
    return db(out_peak / ref_peak) if ref_peak else None


def _impulse_response(original, output, start):
    frequencies = (20, 40, 80, 160, 315, 630, 1250, 2500, 5000, 10000, 16000, 20000)
    reference_peak = max(abs(channel[start]) for channel in original.channels)
    if not reference_peak:
        return None

    active_channels = [[(i - start, sample) for i, sample in enumerate(channel) if sample] for channel in output.channels]

    def response(active, frequency):
        phase = -math.tau * frequency / original.rate
        # Refer output phase to the unshifted input impulse, including rendering latency.
        return sum((sample * cmath.rect(1, phase * i) for i, sample in active), 0j) / reference_peak

    result = []
    for frequency in frequencies:
        if frequency >= original.rate / 2:
            continue
        output_channels = []
        for active in active_channels:
            value = response(active, frequency)
            output_channels.append({"gain_db": db(abs(value)), "phase_deg": math.degrees(cmath.phase(value)) if value else None})
        result.append({"frequency_hz": frequency, "output_channels": output_channels})
    return result


def _spectral_bands(audio, start):
    # A single fixed-window diagnostic, using the same time bounds for both paths.
    size = 2048
    window = [0.5 - 0.5 * math.cos(math.tau * i / size) for i in range(size)]
    spectra = []
    for channel in audio.channels:
        segment = [weight * sample for weight, sample in zip(window, channel[start:start + size])]
        spectra.append(_fft(segment + [0.0] * (size - len(segment))))
    edges = (20, 80, 160, 315, 630, 1250, 2500, 5000, 10000, 20000)
    result = []
    for low, high in zip(edges, edges[1:]):
        begin = math.ceil(low * size / audio.rate)
        end = min(math.ceil(high * size / audio.rate), size // 2 + 1)
        energy = math.fsum(abs(spectrum[index]) ** 2 for spectrum in spectra for index in range(begin, end))
        result.append({"low_hz": low, "high_hz": high, "energy": energy})
    return result


def _window_peak(audio, start, seconds):
    end = start + round(seconds * audio.rate)
    return max((abs(sample) for channel in audio.channels for sample in channel[start:end]), default=0.0)


def compare(original, output, *, fixture="", max_delay=2048, onset_frame=None):
    if not isinstance(max_delay, int) or not 0 <= max_delay <= 16384:
        raise ValueError("max_delay_frames must be an integer between 0 and 16384")
    if onset_frame is not None and (not isinstance(onset_frame, int) or not 0 <= onset_frame < original.frames):
        raise ValueError("onset_frame must identify a frame in the source")

    before = summarize(original)
    after = before if output is original else summarize(output)
    same_rate_and_channels = original.rate == output.rate and len(original.channels) == len(output.channels)
    same_shape = same_rate_and_channels and original.frames == output.frames
    bit_same = same_shape and all(left == right for left, right in zip(original.channels, output.channels))
    anchor = _anchor(original)

    result = {
        "input": before,
        "output": after,
        "same_sample_rate": original.rate == output.rate,
        "same_channel_count": len(original.channels) == len(output.channels),
        "same_frame_count": original.frames == output.frames,
        "frames_delta": output.frames - original.frames,
        "rms_delta_db": _difference(after["rms_dbfs"], before["rms_dbfs"]),
        "peak_delta_db": _difference(after["sample_peak_dbfs"], before["sample_peak_dbfs"]),
        "loudness_delta_lu": _difference(after["integrated_lufs"], before["integrated_lufs"]),
        "delay": None,
        "null": None,
    }
    if bit_same and before["sample_peak"]:
        result["delay"] = {"frames": 0, "ms": 0.0, "signed_correlation": 1.0, "ambiguous": False}
    elif same_rate_and_channels and not bit_same:
        result["delay"] = _sample_delay(original, output, max_delay, anchor)

    if same_shape:
        differences = ((a - b for a, b in zip(left, right)) for left, right in zip(original.channels, output.channels))
        error = 0.0 if bit_same else math.sqrt(sum(_power(channel) for channel in differences) / (original.frames * len(original.channels)))
        result["null"] = {"exact": error == 0.0, "rms": error, "rms_dbfs": db(error), "snr_db": db(before["rms"] / error) if error else None}

    if original.rate == output.rate and before["sample_peak"]:
        if onset_frame is not None:
            reference_peak = _window_peak(original, onset_frame, 0.02)
            captured_peak = _window_peak(output, onset_frame, 0.02)
            result["transient"] = {
                "window_start_frame": onset_frame,
                "window_ms": 20,
                "peak_delta_db": _headroom_delta(reference_peak, captured_peak),
                "input_peak": reference_peak,
                "output_peak": captured_peak,
            }
            if fixture.startswith("impulse"):
                result["impulse_response"] = _impulse_response(original, output, onset_frame)

        if not fixture.startswith("impulse"):
            baseline = _spectral_bands(original, anchor[1])
            measured = baseline if bit_same else _spectral_bands(output, anchor[1])
            result["spectral_window_start_frame"] = anchor[1]
            result["spectral_bands"] = [
                {
                    "low_hz": before_band["low_hz"],
                    "high_hz": before_band["high_hz"],
                    "input_energy": before_band["energy"],
                    "output_energy": after_band["energy"],
                    "delta_db": _difference(_power_db(after_band["energy"]), _power_db(before_band["energy"])),
                }
                for before_band, after_band in zip(baseline, measured)
            ]
    return result
