from array import array
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

from benchmark import main, synthetic_fixture
from metrics import STEMS, evaluate
from wave_audio import Audio, read_wave


def audio(samples, rate=44100, channels=2):
    return Audio(rate, channels, array("d", samples))


def write_wave(path, raw, *, bits, tag=1, channels=2, rate=44100, extensible=False):
    frame_bytes = channels * (bits // 8)
    fmt = struct.pack("<HHIIHH", 0xFFFE if extensible else tag, channels, rate, rate * frame_bytes, frame_bytes, bits)
    if extensible:
        fmt += struct.pack("<HHII12s", 22, bits, 3, tag, bytes.fromhex("00001000800000aa00389b71"))
    chunks = [(b"fmt ", fmt), (b"JUNK", b"x"), (b"data", raw)]
    body = b"WAVE" + b"".join(
        struct.pack("<4sI", name, len(chunk)) + chunk + bytes(len(chunk) % 2)
        for name, chunk in chunks
    )
    path.write_bytes(struct.pack("<4sI", b"RIFF", len(body)) + body)


class ReconstructionTests(unittest.TestCase):
    def test_synthetic_residual_reconstructs_at_both_rates(self):
        for rate in (44100, 48000):
            with self.subTest(rate=rate):
                report = evaluate(*synthetic_fixture(rate))
                result = report["reconstruction"]
                self.assertTrue(result["passed"])
                self.assertLess(result["rms_error_dbfs"], -120)
                self.assertEqual(result["sample_offset_frames"], 0)
                self.assertEqual(report["format"], {"sample_rate_hz": rate, "channels": 2, "frames": round(1.2 * rate)})
                self.assertAlmostEqual(result["rms_delta_db"], 0.0)
                self.assertAlmostEqual(result["peak_delta_db"], 0.0)
                drums = report["reference_comparison"]["drums"]
                self.assertAlmostEqual(drums["relative_reference_gain"]["vocals"], 0.07)
                self.assertAlmostEqual(drums["relative_reference_gain"]["drums"], 0.85)
                self.assertGreater(drums["fixed_gain_error"]["rms_error_dbfs"], -50)
                self.assertLess(drums["reference_peak_window_delta_db"], -1)

    def test_residual_still_nulls_when_a_stem_is_shifted_at_constant_length(self):
        mix = audio([0.5, 0.25, 0, 0])
        references = {name: audio([0, 0, 0, 0]) for name in STEMS}
        references["drums"] = mix
        estimates = {**references, "drums": audio([0, 0, 0.5, 0.25])}
        report = evaluate(mix, estimates, references)
        self.assertTrue(report["reconstruction"]["exact_null"])
        drums = report["reference_comparison"]["drums"]
        self.assertEqual(drums["si_sdr_status"], "zero projection")
        self.assertEqual(drums["fixed_gain_error"]["zero_lag_correlation"], 0)
        self.assertEqual(drums["relative_reference_gain"]["drums"], 0)

    def test_reference_leakage_unavailable_with_collinear_stems(self):
        mix = audio([0.5, 0.25, 0, 0])
        stems = {name: mix for name in STEMS}
        report = evaluate(mix, stems, stems)
        self.assertIsNone(report["reference_comparison"]["other"]["relative_reference_gain"])

    def test_rate_frame_and_channel_mismatches_are_rejected(self):
        mix = audio([0.5, 0.25, 0, 0])
        stems = {name: mix for name in STEMS}
        variants = [
            (audio([0, 0, 0, 0], rate=48000), "sample rate"),
            (audio([0, 0]), "frames"),
            (audio([0, 0], channels=1), "stereo"),
        ]
        for stem, reason in variants:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, f"drums:.*{reason}"):
                    evaluate(mix, {**stems, "drums": stem})
        with self.assertRaisesRegex(ValueError, "reference bass:.*frames"):
            evaluate(mix, stems, {**stems, "bass": audio([0, 0])})

    def test_tiny_nonzero_null_remains_valid_json_decibels(self):
        mix = audio([1e-200, 0])
        stems = {name: audio([1, 0]) for name in STEMS}
        result = evaluate(mix, stems)["reconstruction"]
        self.assertTrue(result["passed"])
        self.assertFalse(result["exact_null"])
        self.assertLess(result["rms_error_dbfs"], -4000)


class WaveTests(unittest.TestCase):
    def test_decodes_supported_pcm_and_float_formats(self):
        variants = [
            (struct.pack("<hh", 16384, -16384), 16, 1, False),
            (b"\x00\x00\x40\x00\x00\xc0", 24, 1, True),
            (struct.pack("<ii", 2 ** 30, -(2 ** 30)), 32, 1, False),
            (struct.pack("<ff", 0.5, -0.5), 32, 3, True),
            (struct.pack("<dd", 0.5, -0.5), 64, 3, False),
        ]
        with TemporaryDirectory() as directory:
            for raw, bits, tag, extensible in variants:
                with self.subTest(bits=bits, tag=tag, extensible=extensible):
                    path = Path(directory) / "signal.wav"
                    write_wave(path, raw, bits=bits, tag=tag, extensible=extensible)
                    wav = read_wave(path)
                    self.assertEqual(wav.sample_rate, 44100)
                    self.assertEqual(wav.frames, 1)
                    self.assertEqual(list(wav.samples), [0.5, -0.5])

    def test_rejects_nonfinite_and_truncated_wave_files(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "signal.wav"
            write_wave(path, struct.pack("<ff", float("nan"), 0), bits=32, tag=3)
            with self.assertRaisesRegex(ValueError, "non-finite"):
                read_wave(path)
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, "truncated"):
                read_wave(path)


class ReportTests(unittest.TestCase):
    def test_local_file_input_reports_metrics_and_model_metadata(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            mix = root / "personal mix.wav"
            stems = root / "estimates"
            report = root / "report"
            stems.mkdir()
            raw = struct.pack("<ff", 0.25, -0.125)
            write_wave(mix, raw, bits=32, tag=3)
            for name in STEMS:
                write_wave(stems / f"{name}.wav", raw, bits=32, tag=3)
            metadata = root / "model.json"
            metadata.write_text(json.dumps({
                "model": "example",
                "delay_frames_at_mix_rate": 0,
                "wall_seconds": 440 / 44100,
                "process_cpu_seconds": 880 / 44100,
                "streaming": False,
            }), encoding="utf-8")
            with redirect_stdout(StringIO()):
                status = main(["evaluate", "--mix", str(mix), "--stems", str(stems), "--metadata", str(metadata), "--out", str(report)])
            self.assertEqual(status, 0)
            result = json.loads((report / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(result["model_run"]["average_cpu_cores"], 2)
            self.assertAlmostEqual(result["model_run"]["real_time_factor"], 440)
            self.assertTrue(result["reconstruction"]["exact_null"])
            self.assertIsNone(result["reference_comparison"])
            markdown = (report / "report.md").read_text(encoding="utf-8")
            self.assertIn("PASS", markdown)
            self.assertNotIn(mix.name, markdown)

    def test_malformed_cli_audio_never_produces_a_pass_report(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            mix = root / "mix.wav"
            mix.write_bytes(b"invalid")
            out = root / "out"
            with redirect_stderr(StringIO()) as stderr:
                status = main(["evaluate", "--mix", str(mix), "--stems", str(root), "--out", str(out)])
            self.assertEqual(status, 2)
            self.assertIn("mix: truncated WAVE header", stderr.getvalue())
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
