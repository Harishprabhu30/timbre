#!/usr/bin/env python3
"""Generate, measure, and listen to repeatable audio quality experiments."""

from argparse import ArgumentParser
from array import array
import json
from pathlib import Path
import platform
import random
import sys

from audio_io import Audio, read_wav, write_wav
from fixtures import NAMES, ONSET_SECONDS, make_fixture
from measurements import approximate_true_peak, compare, db, loudness


DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output"
NEUTRAL_PATHS = ("bypass", "software-reference")


def _read_manifest(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list) or not data["cases"]:
        raise ValueError("manifest must contain a nonempty cases array")
    return data


def _neutral_checks(metrics):
    residual = metrics["null"]
    delay = metrics["delay"]
    peak = metrics["peak_delta_db"]
    level = metrics["loudness_delta_lu"]
    return {
        "same_sample_rate": metrics["same_sample_rate"],
        "same_channels": metrics["same_channel_count"],
        "same_frames": metrics["same_frame_count"],
        "zero_delay": (
            not metrics["input"]["sample_peak"] or delay is not None and delay["frames"] == 0 and not delay["ambiguous"]
        ),
        "rms_null_below_minus_120_dbfs": residual is not None and residual["rms"] < 1e-6,
        "peak_delta_within_0_2_db": abs(peak) < 0.2 if peak is not None else residual is not None and residual["exact"],
        "loudness_delta_within_0_1_lu_when_measurable": abs(level) < 0.1 if level is not None else True,
        "no_new_full_scale_samples": metrics["output"]["full_scale_samples"] <= metrics["input"]["full_scale_samples"],
    }


def measure_case(fixture, path, original, captured, *, max_delay=2048, onset=None, true_peak=False, metadata=None):
    if onset is None and (fixture.startswith("impulse") or fixture in ("kick", "snare", "hi-hat")):
        onset = round(original.rate * ONSET_SECONDS)
    metrics = compare(original, captured, fixture=fixture, max_delay=max_delay, onset_frame=onset)
    if true_peak:
        metrics["input"]["estimated_true_peak_dbtp"] = approximate_true_peak(original)
        if captured is not original:
            metrics["output"]["estimated_true_peak_dbtp"] = approximate_true_peak(captured)
    checks = _neutral_checks(metrics) if path in NEUTRAL_PATHS else None
    return {
        "fixture": fixture,
        "path": path,
        "metadata": metadata or {},
        "neutral_checks": checks,
        "neutral_pass": all(checks.values()) if checks is not None else None,
        "metrics": metrics,
    }


def _write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _scaled(audio, gain, frames):
    channels = []
    for channel in audio.channels:
        samples = array("d", (value * gain for value in channel))
        samples.extend([0.0] * (frames - audio.frames))
        channels.append(samples)
    return Audio(audio.rate, tuple(channels))


def write_listening_pair(original, captured, destination, *, blind=False, legacy=True):
    if len(original.channels) != 2 or len(captured.channels) != 2 or original.rate != captured.rate:
        raise ValueError("listening clips require two stereo inputs at the same sample rate")
    destination.mkdir(parents=True, exist_ok=True)
    frame_count = max(original.frames, captured.frames)
    # Include equal-duration tails in both integrated loudness measurements.
    sources = [_scaled(audio, 1.0, frame_count) for audio in (original, captured)]
    levels = [loudness(audio)["integrated_lufs"] for audio in sources]
    if any(level is None for level in levels):
        raise ValueError("listening clips need measurable integrated LUFS")
    target = min(levels)
    gains = [10 ** ((target - level) / 20) for level in levels]
    peak = max(abs(sample) * gain for audio, gain in zip(sources, gains) for channel in audio.channels for sample in channel)
    headroom = min(1.0, 10 ** (-2 / 20) / peak)
    order = [0, 1]
    if blind:
        random.SystemRandom().shuffle(order)
    labels = ("A", "B") if blind else ("original", "legacy" if legacy else "processed")
    files = []
    reveal = {}
    measured_levels = []
    for label, index in zip(labels, order):
        name = f"{label}.wav"
        file = destination / name
        gain = gains[index] * headroom
        write_wav(file, _scaled(sources[index], gain, frame_count), pcm24=True)
        # Measure the final encoded audio so the report applies to the clips the listener hears.
        exported = read_wav(file)
        level = loudness(exported)["integrated_lufs"]
        if level is None:
            raise ValueError("exported listening clip falls below the integrated loudness gate")
        measured_levels.append(level)
        details = {
            "file": name,
            "integrated_lufs": level,
            "sample_peak_dbfs": db(max(abs(sample) for channel in exported.channels for sample in channel)),
        }
        files.append(details)
        reveal[label] = {
            "source": ("original", "processed")[index],
            "gain": gain,
            "end_padding_frames": frame_count - (original, captured)[index].frames,
        }
    match = {
        "format": "stereo PCM24 WAV",
        "sample_rate_hz": original.rate,
        "frames": frame_count,
        "files": files,
        "absolute_loudness_difference_lu": abs(measured_levels[0] - measured_levels[1]),
    }
    if match["absolute_loudness_difference_lu"] >= 0.1:
        raise ValueError("exported listening clips do not match within 0.1 LU")
    _write_json(destination / "levels.json", match)
    _write_json(destination / ("reveal.json" if blind else "gains.json"), reveal)
    return match


def _number(value, places=2):
    return "—" if value is None else f"{value:.{places}f}"


def _report(cases, destination, metadata, run_type, listening=None):
    neutral_cases = [case for case in cases if case["neutral_pass"] is not None]
    passed = sum(case["neutral_pass"] for case in neutral_cases)
    result = {
        "schema_version": 1,
        "run_type": run_type,
        "metadata": metadata,
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "cases": cases,
        "neutral_passed": passed,
        "neutral_total": len(neutral_cases),
        "listening": listening,
    }
    lines = ["# Timbre audio quality benchmark", "", f"Run type `{run_type}`.", ""]
    if neutral_cases:
        lines.extend([f"Neutral path checks passed **{passed}/{len(neutral_cases)}**.", ""])
    lines.extend([
        "| Fixture | Path | Rate (Hz) | Channels | Frames | Delay (samples) | Output RMS (dBFS) | Output peak (dBFS) | Output LUFS | Delta (LU) | Null RMS (dBFS) | Full-scale samples | Neutral |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for case in cases:
        metrics = case["metrics"]
        output = metrics["output"]
        delay = metrics["delay"]
        null = metrics["null"]
        timing = (str(delay["frames"]) + ("?" if delay["ambiguous"] else "")) if delay else "—"
        difference = ("exact" if null["exact"] else _number(null["rms_dbfs"], 2)) if null else "—"
        neutral = {None: "—", True: "PASS", False: "FAIL"}[case["neutral_pass"]]
        fixture = case["fixture"].replace("|", "&#124;")
        path = case["path"].replace("|", "&#124;")
        lines.append(
            f"| {fixture} | {path} | {output['sample_rate_hz']} | {output['channels']} | {output['frames']} | "
            f"{timing} | {_number(output['rms_dbfs'])} | {_number(output['sample_peak_dbfs'])} | "
            f"{_number(output['integrated_lufs'])} | {_number(metrics['loudness_delta_lu'], 3)} | "
            f"{difference} | {output['full_scale_samples']} | {neutral} |"
        )
    lines.extend([
        "",
        "A question mark flags an ambiguous correlation lag. A dash indicates an unavailable or undefined measurement.",
        "See `report.json` for source levels, windowed loudness, stereo metrics, response and phase, transients, and individual gate results.",
    ])
    if listening:
        lines.extend([
            "",
            f"The exported listening pair differs by {listening['absolute_loudness_difference_lu']:.4f} LU.",
            "See `listening/levels.json` for the final WAV measurements.",
        ])
    destination.mkdir(parents=True, exist_ok=True)
    _write_json(destination / "report.json", result)
    (destination / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {destination / 'report.md'} and {destination / 'report.json'}")
    return 1 if passed != len(neutral_cases) else 0


def _run(args):
    cases = []
    for name in NAMES:
        fixture = make_fixture(name, args.sample_rate)
        cases.append(measure_case(name, "software-reference", fixture, fixture, true_peak=args.true_peak))

    impulse = make_fixture("impulse-left", args.sample_rate)
    offset = 37
    delayed = Audio(impulse.rate, tuple(array("f", [0.0]) * offset + channel[:-offset] for channel in impulse.channels))
    probe = measure_case("impulse-left", "positive-delay-probe", impulse, delayed, true_peak=args.true_peak)
    cases.append(probe)
    source = make_fixture("hard-left", args.sample_rate)
    clipped = Audio(source.rate, tuple(array("f", (sample * 4 for sample in channel)) for channel in source.channels))
    clip_probe = measure_case("hard-left", "overload-probe", source, clipped, true_peak=args.true_peak)
    cases.append(clip_probe)
    status = _report(cases, args.output_dir, {"sample_rate_hz": args.sample_rate}, "software-self-check")
    delay = probe["metrics"]["delay"]
    if delay is None or delay["frames"] != offset or delay["ambiguous"] or not clip_probe["metrics"]["output"]["overs_samples"]:
        raise ValueError("positive delay or overload probe did not produce the expected result")
    return status


def _fixtures(args):
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        write_wav(args.output_dir / f"{name}.wav", make_fixture(name, args.sample_rate))
    print(f"Wrote {len(NAMES)} float32 WAVs to {args.output_dir}")
    return 0


def _analyze(args):
    manifest = _read_manifest(args.manifest)
    cases = []
    listening = None
    base = args.manifest.parent
    for entry in manifest["cases"]:
        fields = ("fixture", "path", "input", "output")
        if not isinstance(entry, dict) or not all(isinstance(entry.get(key), str) and entry[key] for key in fields):
            raise ValueError("each manifest case needs fixture, path, input, and output strings")
        fixture, path = entry["fixture"], entry["path"]
        original, captured = read_wav(base / entry["input"]), read_wav(base / entry["output"])
        cases.append(measure_case(
            fixture, path, original, captured, max_delay=entry.get("max_delay_frames", 2048),
            onset=entry.get("onset_frame"), true_peak=args.true_peak, metadata=entry.get("metadata"),
        ))
        if args.listening is not None and fixture == "listening" and path == args.listening:
            if listening is not None:
                raise ValueError("multiple listening cases match the selected path")
            listening = write_listening_pair(
                original, captured, args.output_dir / "listening", blind=args.blind, legacy=path == "legacy",
            )
    if args.listening is not None and listening is None:
        raise ValueError(f"manifest has no listening fixture for path {args.listening!r}")
    return _report(cases, args.output_dir, manifest.get("metadata", {}), "wav-capture", listening)


def main():
    parser = ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command, handler, description in (
        ("run", _run, "Run deterministic software reference checks and positive controls"),
        ("fixtures", _fixtures, "Generate the source fixtures as float32 WAV"),
        ("analyze", _analyze, "Analyze paired WAV captures from a manifest"),
    ):
        sub = commands.add_parser(command, help=description)
        sub.set_defaults(handler=handler)
        sub.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
        if command != "analyze":
            sub.add_argument("--sample-rate", type=int, choices=(44100, 48000), default=48000)
        if command != "fixtures":
            sub.add_argument("--true-peak", action="store_true", help="also estimate intersample peaks at 4x")
        if command == "analyze":
            sub.add_argument("--manifest", type=Path, required=True)
            sub.add_argument("--listening", nargs="?", const="legacy", metavar="PATH", help="export a listening pair for this manifest path")
            sub.add_argument("--blind", action="store_true", help="randomize filenames A/B and keep the mapping in reveal.json")
    args = parser.parse_args()
    if args.command == "analyze" and args.blind and args.listening is None:
        parser.error("--blind requires --listening")
    try:
        return args.handler(args)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
