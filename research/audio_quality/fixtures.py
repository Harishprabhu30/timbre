"""Deterministic audio stimuli made from oscillators, envelopes, and seeded noise."""

from array import array
import math
import random

from audio_io import Audio


NAMES = (
    "silence", "impulse", "impulse-left", "impulse-right", "sine", "sweep", "multitone",
    "pink-noise", "mono", "dual-mono", "hard-left", "hard-right", "antiphase",
    "kick", "snare", "hi-hat", "listening",
)
ONSET_SECONDS = 0.1


def _fade(t, duration, edge):
    return min(t / edge, (duration - t) / edge, 1.0)


def _drum(rate, name, duration, seed):
    rng = random.Random(seed)
    previous = 0.0
    for i in range(round(rate * duration)):
        t = i / rate
        noise = rng.uniform(-1.0, 1.0)
        if name == "kick":
            phase = math.tau * (48 * t + 2.2 * (1 - math.exp(-t / 0.015)))
            value = math.sin(phase) * math.exp(-t / 0.045)
        elif name == "snare":
            body = math.sin(math.tau * 183 * t) * math.exp(-t / 0.027)
            value = 0.35 * body + 0.65 * noise * math.exp(-t / 0.038)
        else:
            value = 0.5 * (noise - previous) * math.exp(-t / 0.022)
        attack = min((t + 1 / rate) / 0.0005, 1.0)
        release = min((duration - t) / 0.005, 1.0)
        yield value * attack * release
        previous = noise


def _listening(rate):
    duration = 8.0
    count = round(rate * duration)
    left, right = [0.0] * count, [0.0] * count
    step = 0.5
    notes = (55.0, 65.406, 73.416, 65.406)
    for beat in range(16):
        start = round(beat * step * rate)
        bass = notes[(beat // 4) % len(notes)]
        centre = bass * 4
        for i in range(round(rate * step)):
            t = i / rate
            fade = _fade(t, step, 0.025)
            bass_tone = 0.095 * math.sin(math.tau * bass * t) * math.exp(-t / 0.35)
            phase = math.tau * centre * t + 0.25 * math.sin(math.tau * 5.0 * t)
            vowel = 0.045 * math.sin(phase) + 0.045 * math.sin(3 * phase) + 0.018 * math.sin(6 * phase)
            pad_l = 0.023 * math.sin(math.tau * centre * 1.5 * t)
            pad_r = 0.023 * math.sin(math.tau * centre * 2.5 * t + 0.3)
            left[start + i] += fade * (bass_tone + vowel + pad_l)
            right[start + i] += fade * (bass_tone + vowel + pad_r)

        drum = "kick" if beat % 2 == 0 else "snare"
        for i, value in enumerate(_drum(rate, drum, 0.24, seed=beat)):
            left[start + i] += 0.29 * value
            right[start + i] += 0.29 * value
        for subdivision, pan in ((0.0, (0.12, 0.045)), (0.25, (0.04, 0.115))):
            hat_start = start + round(subdivision * rate)
            for i, value in enumerate(_drum(rate, "hi-hat", 0.16, seed=hat_start + 1)):
                left[hat_start + i] += pan[0] * value
                right[hat_start + i] += pan[1] * value
    return Audio(rate, (array("f", left), array("f", right)))


def make_fixture(name, rate):
    if name not in NAMES:
        raise ValueError(f"unknown fixture {name}")
    if rate not in (44100, 48000):
        raise ValueError("fixture sample rate must be 44100 or 48000 Hz")
    if name == "listening":
        return _listening(rate)

    count = rate
    silence = array("f", [0.0]) * count
    if name == "silence":
        return Audio(rate, (silence, silence))
    if name.startswith("impulse"):
        impulse = array("f", silence)
        impulse[round(rate * ONSET_SECONDS)] = 0.5
        left = silence if name == "impulse-right" else impulse
        right = silence if name == "impulse-left" else impulse
        return Audio(rate, (left, right))
    if name in ("kick", "snare", "hi-hat"):
        padding = round(rate * ONSET_SECONDS)
        drum = array("f", silence)
        for i, value in enumerate(_drum(rate, name, 0.3, seed=12345), start=padding):
            drum[i] = 0.65 * value
        return Audio(rate, (drum, drum))

    rng = random.Random(949)
    pink_octaves = [rng.uniform(-1, 1) for _ in range(12)]
    signal = array("f")
    for i in range(count):
        t = i / rate
        if name == "sweep":
            # Integrate the instantaneous frequency of a 20 Hz to 20 kHz log sweep.
            sweep_scale = math.log(1000)
            phase = math.tau * 20 * math.expm1(sweep_scale * t) / sweep_scale
            value = 0.4 * math.sin(phase)
        elif name == "multitone":
            value = sum(math.sin(math.tau * frequency * t) for frequency in (49, 127, 397, 997, 2481, 9241)) / 15
        elif name == "pink-noise":
            # One independent sample-and-hold generator per octave plus white noise.
            for octave in range(len(pink_octaves)):
                if i % (1 << octave) == 0:
                    pink_octaves[octave] = rng.uniform(-1, 1)
            value = (sum(pink_octaves) + rng.uniform(-1, 1)) / 20
        elif name == "sine":
            value = 0.4 * math.sin(math.tau * 997 * t)
        else:
            value = 0.18 * math.sin(math.tau * 733 * t) + 0.16 * math.sin(math.tau * 997 * t + 0.4)
        signal.append(_fade(t, 1.0, 0.025) * value)

    channels = (signal, signal)
    if name == "mono":
        channels = (signal,)
    elif name == "hard-left":
        channels = (signal, silence)
    elif name == "hard-right":
        channels = (silence, signal)
    elif name == "antiphase":
        channels = (signal, array("f", (-value for value in signal)))
    return Audio(rate, channels)
