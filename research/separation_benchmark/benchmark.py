"""Generate or evaluate an offline, aligned four-stem benchmark."""

from argparse import ArgumentParser
from array import array
import json
from math import exp, fsum, isfinite, sin, tau
from pathlib import Path
from random import Random
import sys

from metrics import STEMS, evaluate
from wave_audio import Audio, read_wave


DEFAULT_OUTPUT = Path(__file__).resolve().parent / "out"
SYNTHETIC_RATES = (44100, 48000)
MODEL_TEXT_FIELDS = (
    "model", "model_revision", "device", "resampling", "alignment_verification",
)
MODEL_INTEGER_FIELDS = ("model_sample_rate_hz", "model_size_bytes", "peak_rss_bytes")
MODEL_SECONDS_FIELDS = ("wall_seconds", "process_cpu_seconds", "first_output_seconds")


def synthetic_fixture(sample_rate):
    """Build original refs, deliberately imperfect estimates, and quiet residual content."""
    references = {name: array("d") for name in STEMS}
    estimates = {name: array("d") for name in STEMS}
    original = array("d")
    noise = Random(76)
    for frame in range(round(1.2 * sample_rate)):
        time = frame / sample_rate
        phrase = (1 - exp(-35 * time)) * (0.65 + 0.35 * sin(tau * 2 * time))
        vocal = 0.15 * phrase * (sin(tau * 223 * time) + 0.2 * sin(tau * 669 * time))
        kick_time = time % 0.30
        kick = 0.25 * exp(-55 * kick_time) * sin(tau * (53 * kick_time - 0.35 * exp(-85 * kick_time)))
        noise_sample = noise.uniform(-1, 1)
        hat = 0.07 * exp(-175 * ((time + 0.04) % 0.15)) * noise_sample
        bass = 0.11 * sin(tau * 73 * time) * (0.8 + 0.2 * sin(tau * 5 * time))
        left_other = 0.07 * sin(tau * 331 * time)
        right_other = 0.06 * sin(tau * 439 * time)
        detail = 0.002 * sin(tau * 7423 * time)
        for side, other in ((1, left_other), (-1, right_other)):
            drum = kick + side * hat
            reference = (vocal, drum, bass, other)
            estimated = (vocal + 0.025 * bass, 0.85 * drum + 0.07 * vocal, bass, other + 0.1 * drum)
            for name, exact, approximate in zip(STEMS, reference, estimated):
                references[name].append(exact)
                estimates[name].append(approximate)
            original.append(fsum(reference) + side * detail)

    return (
        Audio(sample_rate, 2, original),
        {name: Audio(sample_rate, 2, signal) for name, signal in estimates.items()},
        {name: Audio(sample_rate, 2, signal) for name, signal in references.items()},
    )


def load_wave(path, label):
    try:
        return read_wave(path)
    except (OSError, ValueError) as error:
        raise ValueError(f"{label}: {error}") from error


def load_stems(directory, label):
    return {name: load_wave(directory / f"{name}.wav", f"{label} {name}") for name in STEMS}


def read_metadata(path, duration):
    if path is None:
        return None
    fields = json.loads(path.read_text(encoding="utf-8"))
    known_fields = set(MODEL_TEXT_FIELDS + MODEL_INTEGER_FIELDS + MODEL_SECONDS_FIELDS)
    known_fields.update(("delay_frames_at_mix_rate", "streaming"))
    if not isinstance(fields, dict) or fields.keys() - known_fields:
        raise ValueError("expected a metadata JSON object containing only documented fields")

    for key in fields.keys() & set(MODEL_TEXT_FIELDS):
        if not isinstance(fields[key], str) or not fields[key].strip():
            raise ValueError(f"metadata {key}: expected nonempty text")
    for key in fields.keys() & set(MODEL_INTEGER_FIELDS):
        if type(fields[key]) is not int or fields[key] <= 0:
            raise ValueError(f"metadata {key}: expected a positive integer")
    for key in fields.keys() & set(MODEL_SECONDS_FIELDS):
        if type(fields[key]) not in (int, float) or not isfinite(fields[key]) or fields[key] < 0:
            raise ValueError(f"metadata {key}: expected a finite nonnegative duration")
    if "delay_frames_at_mix_rate" in fields and type(fields["delay_frames_at_mix_rate"]) is not int:
        raise ValueError("metadata delay_frames_at_mix_rate: expected an integer")
    if "streaming" in fields and type(fields["streaming"]) is not bool:
        raise ValueError("metadata streaming: expected true or false")
    if "wall_seconds" in fields:
        wall_time = fields["wall_seconds"]
        if wall_time <= 0:
            raise ValueError("metadata wall_seconds: expected a positive duration")
        fields["real_time_factor"] = wall_time / duration
        if "process_cpu_seconds" in fields:
            fields["average_cpu_cores"] = fields["process_cpu_seconds"] / wall_time
    return fields


def number(value, places=3):
    if value is None:
        return "—"
    return f"{round(value, places) or 0:.{places}f}"


def markdown(report):
    audio = report["format"]
    reconstructed = report["reconstruction"]
    rms_error = "exact zero" if reconstructed["exact_null"] else number(reconstructed["rms_error_dbfs"])
    peak_error = "exact zero" if reconstructed["exact_null"] else number(reconstructed["peak_error_dbfs"])
    result = "PASS" if reconstructed["passed"] else "FAIL"
    lines = [
        "# Four-stem reconstruction benchmark",
        "",
        f"Input **{report['input_kind']}** at **{audio['sample_rate_hz']:,} Hz**, "
        f"**{audio['channels']} channels**, **{audio['frames']:,} frames**.",
        "",
        "| Signal | RMS (dBFS) | Peak (dBFS) | Crest factor (dB) | Over-full-scale samples |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, signal in (
        ("Original", report["mix"]),
        ("Estimated stem sum", report["estimated_stem_sum"]),
        ("Residual", report["residual"]),
        ("Reconstructed", reconstructed),
    ):
        lines.append(
            f"| {name} | {number(signal['rms_dbfs'])} | {number(signal['peak_dbfs'])} "
            f"| {number(signal['crest_db'])} | {signal['over_full_scale_samples']} |"
        )
    lines.extend([
        "",
        f"**{result}**. RMS null {rms_error}, peak null {peak_error} "
        f"(dBFS for finite values). RMS target below {reconstructed['target_rms_null_dbfs']:g} dBFS.",
        "",
        f"Sample-indexed reconstruction offset {reconstructed['sample_offset_frames']} frames. "
        f"RMS delta {number(reconstructed['rms_delta_db'])} dB, "
        f"peak delta {number(reconstructed['peak_delta_db'])} dB, "
        f"zero-lag correlation {number(reconstructed['zero_lag_correlation'], 6)}.",
        "",
        "The null measures arithmetic reconstruction. Evaluate stem accuracy and verify input alignment independently.",
        "",
        "## Reference comparison",
        "",
    ])
    comparison = report["reference_comparison"]
    if comparison is None:
        lines.append("Unavailable. Supply aligned known stems to measure accuracy and leakage.")
    else:
        lines.extend([
            "| Stem | SI-SDR (dB) | Fixed-gain error (dBFS RMS) | RMS delta (dB) | "
            "First-difference RMS delta (dB) | Peak-window delta (dB) |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        for name, stem in comparison.items():
            si_sdr = number(stem["si_sdr_db"]) if stem["si_sdr_status"] == "finite" else stem["si_sdr_status"]
            error = stem["fixed_gain_error"]
            fixed_error = "exact zero" if error["exact_null"] else number(error["rms_error_dbfs"])
            lines.append(
                f"| {name} | {si_sdr} | {fixed_error} | {number(stem['rms_delta_db'])} "
                f"| {number(stem['first_difference_rms_delta_db'])} "
                f"| {number(stem['reference_peak_window_delta_db'])} |"
            )
        lines.extend([
            "",
            "Relative reference gain is the simultaneous signed regression coefficient for each known source.",
            "",
            "| Estimate | Vocals | Drums | Bass | Other |",
            "| --- | ---: | ---: | ---: | ---: |",
        ])
        for name, stem in comparison.items():
            coefficients = stem["relative_reference_gain"] or {}
            lines.append(f"| {name} | " + " | ".join(number(coefficients.get(source)) for source in STEMS) + " |")
        lines.extend(["", "See the JSON for per-stem stereo and correlation details."])
    lines.extend(["", "## Model run", ""])
    model_run = report["model_run"]
    if model_run is None:
        lines.append("No inference measurements supplied.")
    else:
        # Encode supplied text inside a fenced JSON block, including any line breaks.
        lines.extend(["````json", json.dumps(model_run, indent=2, ensure_ascii=True), "````"])
    lines.append("")
    return "\n".join(lines)


def arguments(argv):
    parser = ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    synthetic = commands.add_parser("synthetic", help="measure deterministic fixtures without any audio files")
    synthetic.add_argument("--sample-rate", type=int, choices=SYNTHETIC_RATES, default=SYNTHETIC_RATES[0])
    files = commands.add_parser("evaluate", help="measure an aligned stereo WAV mix and four WAV stems")
    files.add_argument("--mix", required=True, type=Path)
    files.add_argument("--stems", required=True, type=Path)
    files.add_argument("--reference-stems", type=Path)
    files.add_argument("--metadata", type=Path, help="optional separator timing and alignment provenance JSON")
    for command in (synthetic, files):
        command.add_argument("--out", type=Path, default=DEFAULT_OUTPUT, help="output directory for report.json and report.md")
    return parser.parse_args(argv)


def main(argv=None):
    options = arguments(argv)
    try:
        if options.command == "synthetic":
            mix, estimates, references = synthetic_fixture(options.sample_rate)
            metadata = None
            input_kind = "synthetic stereo fixture with deliberately imperfect estimates"
        else:
            mix = load_wave(options.mix, "mix")
            estimates = load_stems(options.stems, "estimated")
            references = load_stems(options.reference_stems, "reference") if options.reference_stems else None
            metadata = read_metadata(options.metadata, mix.frames / mix.sample_rate)
            input_kind = "local WAV files supplied on the mix sample grid"
        report = {
            "schema_version": 1,
            "input_kind": input_kind,
            **evaluate(mix, estimates, references),
            "model_run": metadata,
        }
        report_json = json.dumps(report, indent=2, allow_nan=False) + "\n"
        report_markdown = markdown(report)
        options.out.mkdir(parents=True, exist_ok=True)
        (options.out / "report.json").write_text(report_json, encoding="utf-8")
        (options.out / "report.md").write_text(report_markdown, encoding="utf-8")
    except (ArithmeticError, OSError, ValueError) as error:
        print(f"separation benchmark: {error}", file=sys.stderr)
        return 2
    print(f"{'PASS' if report['reconstruction']['passed'] else 'FAIL'} {options.out / 'report.md'}")
    return 0 if report["reconstruction"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
