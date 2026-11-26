"""Capture the checked-in Timbre graph in macOS WKWebView and report its behavior."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
AUDIO_QUALITY = HERE.parent / "audio_quality"
sys.path.insert(0, str(AUDIO_QUALITY))

from audio_io import read_wav, write_wav
from fixtures import NAMES, ONSET_SECONDS, make_fixture


RATES = (44100, 48000)
ANGLES = (5, 15, 30, 55, 80, 90)
IMPULSE_CASES = ("impulse-left", "impulse-right")
HOOK = """
  // Research-only entry point inside the engine closure.
  window.makeLegacyResearchGraph = function (context, config) {
    ctx = context;
    buildGraph();
    api.apply(config);
    return G.input;
  };
"""


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def config(*, enabled=True, spatial=False, angle=30, amount=0.8, limiter=False):
    return {
        "enabled": enabled,
        "spatial": {"on": spatial, "angle": angle, "amount": amount, "distance": 1, "elevation": 0},
        "limiter": {"on": limiter, "ceiling": -1},
        "reverb": {"on": False},
    }


def capture_cases(rate):
    def case(fixture, path, settings):
        result = {
            "fixture": fixture,
            "path": path,
            "input": f"fixtures/{fixture}.wav",
            "output": f"rendered/{fixture}-{path}.wav",
            "config": settings,
            "max_delay_frames": round(rate * 0.05),
        }
        if fixture.startswith("impulse") or fixture in ("kick", "snare", "hi-hat"):
            result["onset_frame"] = round(rate * ONSET_SECONDS)
        return result

    bypass = config(enabled=False, spatial=True, limiter=True)
    bypass.update({
        "preamp": 3,
        "output": -4,
        "bands": [{"id": "research", "on": True, "type": "peaking", "freq": 1000, "gain": 6}],
        "comp": {"on": True},
        "crossfeed": {"on": True},
        "width": {"on": True, "width": 0.7},
    })
    for fixture in NAMES:
        if fixture == "mono":
            yield case(fixture, "mono-upmix", bypass)
            continue
        yield case(fixture, "bypass", bypass)
        yield case(fixture, "legacy", config(spatial=True))

    for angle in ANGLES:
        if angle == 30:
            continue  # The canonical Legacy case already captures 30 degrees.
        for fixture in IMPULSE_CASES:
            yield case(fixture, f"legacy-{angle}", config(spatial=True, angle=angle))

    for fixture in IMPULSE_CASES + ("silence",):
        yield case(fixture, "legacy-wet", config(spatial=True, amount=1))
    for fixture in ("impulse-left", "kick", "snare", "hi-hat", "listening"):
        yield case(fixture, "factory-limiter", config(limiter=True))
        yield case(fixture, "legacy-limiter", config(spatial=True, limiter=True))
    for fixture in ("impulse-left", "listening"):
        yield case(fixture, "legacy-zero", config(spatial=True, amount=0))


def engine_source():
    engine = (ROOT / "Timbre/Engine/engine.js").read_bytes()
    source = engine.decode("utf-8").rstrip()
    suffix = "})();"
    if not source.endswith(suffix):
        raise ValueError("Engine closure changed. Update the research hook location.")
    return source[:-len(suffix)] + HOOK + suffix, hashlib.sha256(engine).hexdigest()


def capture(output, rates):
    if sys.platform != "darwin":
        raise ValueError("Rendering requires macOS WKWebView. Analyze existing captures with --analyze-only.")
    engine, digest = engine_source()
    with tempfile.TemporaryDirectory(prefix="timbre-webkit-") as build_dir:
        build = Path(build_dir)
        runner = build / "webkit_runner"
        script = build / "page.js"
        script.write_text(engine + "\n" + (HERE / "render.js").read_text(encoding="utf-8"), encoding="utf-8")
        subprocess.run([
            "xcrun", "clang", "-fobjc-arc", "-fmodules", f"-fmodules-cache-path={build / 'modules'}",
            "-Wall", "-Wextra", "-framework", "Cocoa", "-framework", "WebKit",
            str(HERE / "webkit_runner.m"), "-o", str(runner),
        ], check=True)
        for rate in rates:
            directory = output / str(rate)
            completed = directory / "capture-complete.json"
            completed.unlink(missing_ok=True)
            for child in ("fixtures", "rendered"):
                (directory / child).mkdir(parents=True, exist_ok=True)
            for fixture in NAMES:
                write_wav(directory / "fixtures" / f"{fixture}.wav", make_fixture(fixture, rate))
            cases = list(capture_cases(rate))
            manifest = directory / "manifest.json"
            write_json(manifest, {
                "metadata": {"sample_rate_hz": rate, "engine_sha256": digest, "preroll_seconds": 0.25},
                "cases": cases,
            })
            subprocess.run([str(runner), str(script), str(manifest)], check=True)
            write_json(completed, {"cases": len(cases), "engine_sha256": digest})
            print(f"{rate} Hz: captured {len(cases)} WKWebView cases in {directory}", flush=True)


def to_db(value):
    return 20 * math.log10(value) if value > 0 else None


def impulse_timing(audio, onset):
    # A band-limited FFT implementation can emit extremely small pre-ringing.
    # Use a fixed absolute threshold and report the threshold beside the timing.
    threshold = 1e-6
    results = []
    for channel in audio.channels:
        peak_frame = max(range(audio.frames), key=lambda i: abs(channel[i]))
        above = [i for i, value in enumerate(channel) if abs(value) >= threshold]
        results.append({
            "first_above_minus_120_dbfs_frames": above[0] - onset if above else None,
            "peak_offset_frames": peak_frame - onset if above else None,
            "last_above_minus_120_dbfs_frames": above[-1] - onset if above else None,
        })
    return results


def summarize(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    webkit = json.loads((directory / "webkit.json").read_text(encoding="utf-8"))
    metrics = json.loads((directory / "metrics" / "report.json").read_text(encoding="utf-8"))
    cases = manifest["cases"]
    by_key = {(case["fixture"], case["path"]): case for case in metrics["cases"]}
    rate = manifest["metadata"]["sample_rate_hz"]
    results = {
        "metadata": {**manifest["metadata"], **webkit},
        "validations": {},
        "impulses": [],
        "controls": {},
    }
    validations = results["validations"]
    silence_peak = 0.0

    for case in cases:
        fixture, path = case["fixture"], case["path"]
        if (fixture, path) not in by_key:
            raise ValueError(f"missing audio-quality metrics for {fixture}/{path}")
        audio = read_wav(directory / case["output"])
        original = read_wav(directory / case["input"])
        if audio.frames != original.frames or audio.rate != rate or len(audio.channels) != 2:
            raise ValueError(f"unexpected output format for {fixture}/{path}")
        if path in ("bypass", "legacy-zero"):
            validations[f"{fixture}/{path}_sample_identical"] = audio.channels == original.channels
        elif path == "mono-upmix":
            validations["mono_speaker_upmix_sample_identical"] = audio.channels == original.channels * 2

        if fixture == "silence":
            silence_peak = max(silence_peak, *(max(map(abs, channel)) for channel in audio.channels))
        if fixture in IMPULSE_CASES:
            if path == "legacy-wet":
                peak = max(max(map(abs, channel)) for channel in audio.channels)
                validations[f"{fixture}/wet_only_has_signal"] = peak > 1e-3
            source = 0 if fixture == "impulse-left" else 1
            energy = [sum(value * value for value in channel) for channel in audio.channels]
            results["impulses"].append({
                "path": path,
                "angle_degrees": case["config"]["spatial"]["angle"],
                "source_channel": ["left", "right"][source],
                "opposite_to_direct_energy_db": to_db(math.sqrt(energy[1 - source] / energy[source])) if energy[source] else None,
                "timing_by_output_channel": impulse_timing(audio, case["onset_frame"]),
                "frequency_phase_response": by_key[(fixture, path)]["metrics"]["impulse_response"],
            })
        if path in ("legacy", "factory-limiter", "legacy-limiter") and fixture in (
            "kick", "snare", "hi-hat", "listening", "hard-left", "hard-right", "dual-mono", "antiphase",
        ):
            results["controls"][f"{fixture}/{path}"] = by_key[(fixture, path)]["metrics"]

    results["silence_peak_dbfs"] = to_db(silence_peak)
    validations["silent_input_yields_digital_silence"] = silence_peak == 0.0
    return results


def signed(number):
    return f"{number:+.2f}" if number is not None else "—"


def markdown(results):
    out = ["# Legacy Spatial offline measurement", ""]
    for result in results:
        meta = result["metadata"]
        out.extend([
            f"## {meta['sample_rate_hz']} Hz", "",
            f"{meta['os_version']} · WKWebView {meta['webkit_bundle_version']}", "",
            "| Validation | Result |", "| --- | --- |",
        ])
        out.extend(f"| {name.replace('_', ' ')} | {'PASS' if value else 'FAIL'} |"
                   for name, value in result["validations"].items())
        out.extend([
            "", "| Route | Angle | Speaker | Opposite/direct energy | Left peak offset | Right peak offset |",
            "| --- | --: | --- | --: | --: | --: |",
        ])
        for result_row in result["impulses"]:
            timing = result_row["timing_by_output_channel"]
            cross = result_row["opposite_to_direct_energy_db"]
            ratio = f"{cross:+.2f} dB" if cross is not None else "—"
            offsets = [row["peak_offset_frames"] for row in timing]
            out.append(
                f"| {result_row['path']} | {result_row['angle_degrees']}° | {result_row['source_channel']} | "
                f"{ratio} | {offsets[0] if offsets[0] is not None else '—'} | "
                f"{offsets[1] if offsets[1] is not None else '—'} |"
            )
        out.extend([
            "", "| Fixture / route | Loudness delta (LU) | Peak delta (dB) | First 20 ms peak delta (dB) | Over-range samples |",
            "| --- | --: | --: | --: | --: |",
        ])
        for name, metrics in result["controls"].items():
            out.append(
                f"| {name} | {signed(metrics['loudness_delta_lu'])} | {signed(metrics['peak_delta_db'])} | "
                f"{signed(metrics.get('transient', {}).get('peak_delta_db'))} | {metrics['output']['overs_samples']} |"
            )
        silence_peak = result["silence_peak_dbfs"]
        out.extend([
            "", f"Silence peak is {'digital zero' if silence_peak is None else f'{silence_peak:.2f} dBFS'}.",
            "", "Peak offsets are in frames from the unshifted input impulse. Frequency and phase "
            "response are in `legacy-report.json`. The general audio metrics and level-matched earbud "
            "exports are in each rate's `metrics/` directory.", "",
        ])
    return "\n".join(out)


def analyze(output, rates):
    results = []
    statuses = []
    for rate in rates:
        directory = output / str(rate)
        completed = directory / "capture-complete.json"
        if not completed.is_file():
            raise ValueError(f"Capture at {rate} Hz did not complete")
        completion = json.loads(completed.read_text(encoding="utf-8"))
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if completion != {
            "cases": len(manifest["cases"]), "engine_sha256": manifest["metadata"]["engine_sha256"],
        }:
            raise ValueError(f"Capture at {rate} Hz does not match its manifest")

        command = [
            sys.executable, str(AUDIO_QUALITY / "benchmark.py"), "analyze", "--manifest",
            str(directory / "manifest.json"), "--output-dir", str(directory / "metrics"), "--listening", "legacy",
        ]
        status = subprocess.run(command, check=False).returncode
        if status not in (0, 1):
            raise subprocess.CalledProcessError(status, command)
        statuses.append(status)
        results.append(summarize(directory))

    write_json(output / "legacy-report.json", {"sample_rates": results})
    (output / "legacy-report.md").write_text(markdown(results), encoding="utf-8")
    if any(statuses) or not all(all(result["validations"].values()) for result in results):
        raise ValueError("One or more Legacy validation checks failed. See legacy-report.md.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-rate", type=int, choices=RATES, action="append", help="Repeat to select both rates")
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument("--render-only", action="store_true")
    phase.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    rates = sorted(set(args.sample_rate or RATES))
    try:
        if not args.analyze_only:
            capture(output, rates)
        if not args.render_only:
            analyze(output, rates)
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Legacy benchmark: {error}\n")


if __name__ == "__main__":
    main()
