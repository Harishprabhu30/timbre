import math
from pathlib import Path
import tempfile
import unittest

from audio_io import Audio, read_wav, write_wav
from benchmark import measure_case, write_listening_pair
from fixtures import make_fixture
from measurements import approximate_true_peak, compare, loudness


class AudioBenchmarkTests(unittest.TestCase):
    def test_float_wav_and_neutral_round_trip(self):
        fixture = make_fixture("pink-noise", 44100)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.wav"
            write_wav(path, fixture)
            decoded = read_wav(path)
        self.assertEqual(decoded, fixture)
        result = measure_case("pink-noise", "bypass", fixture, decoded)
        self.assertTrue(result["neutral_pass"])
        self.assertTrue(result["metrics"]["null"]["exact"])

    def test_impulse_measures_signed_delay_and_phase(self):
        impulse = make_fixture("impulse-left", 48000)
        onset = 4800
        for delay in (-29, 37):
            with self.subTest(delay=delay):
                left = [0.0] * impulse.frames
                left[onset + delay] = 0.25
                result = measure_case("impulse-left", "bypass", impulse, Audio(48000, (left, impulse.channels[1])))
                self.assertFalse(result["neutral_pass"])
                metrics = result["metrics"]
                self.assertEqual(metrics["delay"]["frames"], delay)
                self.assertFalse(metrics["delay"]["ambiguous"])
                response = metrics["impulse_response"][0]
                first = response["output_channels"][0]
                self.assertAlmostEqual(first["gain_db"], 20 * math.log10(0.5))
                self.assertAlmostEqual(first["phase_deg"], -360 * delay * response["frequency_hz"] / 48000)

    def test_mono_upmix_is_reported_without_inventing_a_null(self):
        mono = make_fixture("mono", 44100)
        dual_mono = Audio(mono.rate, mono.channels * 2)
        result = compare(mono, dual_mono)
        self.assertFalse(result["same_channel_count"])
        self.assertEqual(result["output"]["stereo"]["zero_lag_correlation"], 1.0)
        self.assertIsNone(result["null"])
        self.assertIsNone(result["delay"])

    def test_lufs_997_hz_tone(self):
        for rate in (44100, 48000):
            with self.subTest(rate=rate):
                tone = [10 ** (-23 / 20) * math.sin(math.tau * 997 * i / rate) for i in range(3 * rate)]
                result = loudness(Audio(rate, (tone, tone)))
                self.assertAlmostEqual(result["integrated_lufs"], -23.0, delta=0.1)
                self.assertAlmostEqual(result["short_term_max_lufs"], -23.0, delta=0.1)

    def test_intersample_peak(self):
        tone = []
        for i in range(4096):
            fade = min(i / 128, (4095 - i) / 128, 1)
            tone.append(fade * math.sin(math.tau * i / 4 + math.pi / 4))
        measured = approximate_true_peak(Audio(48000, (tone,)))
        self.assertAlmostEqual(measured, 0.0, delta=0.1)
        self.assertLess(max(map(abs, tone)), 0.71)

    def test_listening_export_rechecks_levels_and_pads_end_only(self):
        source = make_fixture("sine", 44100)
        scaled = [sample * 3 for sample in source.channels[0]] + [0.0] * 37
        capture = Audio(source.rate, (scaled, scaled))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            levels = write_listening_pair(source, capture, destination, blind=True)
            a = read_wav(destination / "A.wav")
            b = read_wav(destination / "B.wav")
            self.assertTrue((destination / "reveal.json").exists())
        self.assertEqual(a.frames, source.frames + 37)
        self.assertEqual(b.frames, source.frames + 37)
        self.assertLess(levels["absolute_loudness_difference_lu"], 0.001)
        self.assertLess(max(level["sample_peak_dbfs"] for level in levels["files"]), -2.0)


if __name__ == "__main__":
    unittest.main()
