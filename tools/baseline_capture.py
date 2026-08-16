#!/usr/bin/env python3
"""Pack a safe, comparable baseline-capture summary around one target-run artifact.

This tool does not infer telemetry that the target runner did not capture. Optional
measurements are a strict numeric sidecar supplied by the operator; omitted metric
families are recorded explicitly as unavailable. The output ZIP contains only
allowlisted JSON derived from the already-safe target-run package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools import run_target_experiment_v3


CAPTURE_KIND = "bb-baseline-capture"
CAPTURE_VERSION = 1
PRODUCER_NAME = "bb-baseline-capture-packer"
PRODUCER_VERSION = "0.1.0"
MAX_RUN_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_MEASUREMENTS_BYTES = 4 * 1024 * 1024
MAX_SAMPLES = 1_000_000
METRIC_SPECS = {
    "fps": ("fps", False),
    "frametime_ms": ("ms", False),
    "ram_bytes": ("bytes", True),
    "vram_bytes": ("bytes", True),
    "shader_compilations": ("count", True),
}
SAFE_RUN_ENTRIES = (
    "run-manifest.json",
    "target-manifest.json",
    "host-environment.json",
    "scenario.json",
)


class BaselineCaptureError(ValueError):
    """Raised when baseline-capture input cannot be packaged safely."""


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
        + b"\n"
    )


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BaselineCaptureError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise BaselineCaptureError(f"non-finite JSON constant is not valid JSON: {name}")


def _load_json(path: Path, *, maximum: int, label: str) -> Any:
    try:
        stat = path.stat()
        if not path.is_file() or stat.st_size > maximum:
            raise BaselineCaptureError(f"{label} must be a regular file no larger than {maximum} bytes")
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except BaselineCaptureError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BaselineCaptureError(f"unable to read {label}: {error}") from error


def _sha256_file(path: Path, *, maximum: int, label: str) -> tuple[str, int]:
    try:
        stat = path.stat()
        if not path.is_file() or stat.st_size > maximum:
            raise BaselineCaptureError(f"{label} must be a regular file no larger than {maximum} bytes")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                if size > maximum:
                    raise BaselineCaptureError(f"{label} exceeds the {maximum}-byte limit")
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}", size
    except BaselineCaptureError:
        raise
    except OSError as error:
        raise BaselineCaptureError(f"unable to fingerprint {label}") from error


def _read_safe_run_artifact(path: Path) -> tuple[dict[str, bytes], Mapping[str, Any]]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_RUN_ARTIFACT_BYTES:
            raise BaselineCaptureError("target-run artifact is missing or exceeds the safety limit")
        with zipfile.ZipFile(path, "r") as archive:
            names = set(archive.namelist())
            missing = [name for name in SAFE_RUN_ENTRIES if name not in names]
            if missing:
                raise BaselineCaptureError(
                    "target-run artifact is missing required safe entries: " + ", ".join(missing)
                )
            entries: dict[str, bytes] = {}
            for name in SAFE_RUN_ENTRIES:
                info = archive.getinfo(name)
                if info.file_size > MAX_MEASUREMENTS_BYTES:
                    raise BaselineCaptureError(f"safe run entry is unexpectedly large: {name}")
                entries[name] = archive.read(name)
    except BaselineCaptureError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise BaselineCaptureError(f"unable to read target-run artifact: {error}") from error

    try:
        manifest = json.loads(
            entries["run-manifest.json"].decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BaselineCaptureError(f"invalid run-manifest.json: {error}") from error
    if not isinstance(manifest, Mapping):
        raise BaselineCaptureError("run-manifest.json must contain an object")
    try:
        run_target_experiment_v3.validate_run_manifest(manifest)
    except Exception as error:
        raise BaselineCaptureError(f"target-run manifest validation failed: {error}") from error
    return entries, manifest


def _numeric_samples(value: Any, *, metric: str, integer: bool) -> list[int | float]:
    if not isinstance(value, list) or not value or len(value) > MAX_SAMPLES:
        raise BaselineCaptureError(f"{metric} must be a non-empty sample array of at most {MAX_SAMPLES} values")
    samples: list[int | float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise BaselineCaptureError(f"{metric} contains a non-numeric sample")
        if not math.isfinite(float(item)) or item < 0:
            raise BaselineCaptureError(f"{metric} samples must be finite and non-negative")
        if integer and (not isinstance(item, int) or isinstance(item, bool)):
            raise BaselineCaptureError(f"{metric} samples must be integers")
        samples.append(item)
    return samples


def normalize_measurements(value: Any | None) -> dict[str, Any]:
    """Return fixed-shape metric records; absent families stay explicitly unavailable."""
    if value is None:
        value = {}
    if not isinstance(value, Mapping) or set(value) - set(METRIC_SPECS):
        raise BaselineCaptureError("measurements must contain only the supported metric families")
    result: dict[str, Any] = {}
    for metric, (unit, integer) in METRIC_SPECS.items():
        raw = value.get(metric)
        if raw is None:
            result[metric] = {
                "availability": "unavailable",
                "unit": unit,
                "sample_count": 0,
                "samples": [],
                "source": None,
            }
            continue
        samples = _numeric_samples(raw, metric=metric, integer=integer)
        result[metric] = {
            "availability": "observed",
            "unit": unit,
            "sample_count": len(samples),
            "samples": samples,
            "source": "operator-safe-numeric-sidecar",
        }
    return result


def _write_zip_atomic(output: Path, entries: Mapping[str, bytes]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{output.name}.", dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in sorted(entries.items()):
                archive.writestr(name, payload)
        os.replace(temporary, output)
        temporary = None
    except OSError as error:
        raise BaselineCaptureError(f"unable to write baseline artifact: {error}") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def pack_baseline(*, run_artifact: Path, measurements_path: Path | None, output: Path) -> dict[str, Any]:
    wall_started = time.monotonic_ns()
    cpu_started = time.process_time_ns()
    safe_entries, run_manifest = _read_safe_run_artifact(run_artifact)
    run_sha256, run_size = _sha256_file(run_artifact, maximum=MAX_RUN_ARTIFACT_BYTES, label="target-run artifact")
    raw_measurements = None if measurements_path is None else _load_json(
        measurements_path, maximum=MAX_MEASUREMENTS_BYTES, label="measurements"
    )
    metrics = normalize_measurements(raw_measurements)

    capture: dict[str, Any] = {
        "manifest_kind": CAPTURE_KIND,
        "schema_version": CAPTURE_VERSION,
        "producer": {"name": PRODUCER_NAME, "version": PRODUCER_VERSION},
        "source_run": {
            "artifact_sha256": run_sha256,
            "artifact_size_bytes": run_size,
            "route": run_manifest.get("route"),
            "target_manifest_sha256": run_manifest.get("target", {}).get("manifest_sha256"),
            "host_manifest_sha256": run_manifest.get("host_environment", {}).get("manifest_sha256"),
            "scenario_id": run_manifest.get("scenario", {}).get("id"),
            "source_repository": run_manifest.get("emulator", {}).get("source", {}).get("repository"),
            "source_commit": run_manifest.get("emulator", {}).get("source", {}).get("commit"),
            "source_tree": run_manifest.get("emulator", {}).get("source", {}).get("tree"),
            "patch_commits": run_manifest.get("emulator", {}).get("source", {}).get("patch_commits"),
            "execution_elapsed_seconds": run_manifest.get("termination", {}).get("elapsed_seconds"),
        },
        "metrics": metrics,
        "overhead": {
            "scope": "packer-only",
            "runtime_instrumentation_overhead": "unknown",
            "wall_seconds": None,
            "cpu_seconds": None,
        },
        "evidence": {
            "class": "runtime" if any(item["availability"] == "observed" for item in metrics.values()) else "static",
            "raw_process_output_included": False,
            "proprietary_payload_included": False,
        },
    }
    entries = dict(safe_entries)
    entries["baseline-capture.json"] = _json_bytes(capture)
    _write_zip_atomic(output, entries)

    capture["overhead"]["wall_seconds"] = round((time.monotonic_ns() - wall_started) / 1_000_000_000, 6)
    capture["overhead"]["cpu_seconds"] = round((time.process_time_ns() - cpu_started) / 1_000_000_000, 6)
    entries["baseline-capture.json"] = _json_bytes(capture)
    _write_zip_atomic(output, entries)
    return capture


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-run", type=Path, required=True, help="safe ZIP from tools/run_target_experiment.py")
    parser.add_argument("--measurements", type=Path, help="optional strict numeric JSON sidecar")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        pack_baseline(run_artifact=args.target_run, measurements_path=args.measurements, output=args.output)
    except BaselineCaptureError as error:
        print(f"error: {error}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
