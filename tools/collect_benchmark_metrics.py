#!/usr/bin/env python3
"""Pack safe benchmark-adjacent metrics from a BB-ENV1 target-run artifact.

This collector intentionally does not launch, attach to, automate, or inspect a target
process.  It consumes the already-redacted target-run ZIP produced by
``tools/run_target_experiment.py`` and records only metrics that the published run
contract actually exposes.  Missing FPS/frametime/RAM/VRAM/shader metrics remain
explicitly unavailable rather than being inferred or fabricated.
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
from typing import Any

COLLECTOR_VERSION = "1.0.0"
MANIFEST_KIND = "bb-benchmark-metrics"
SCHEMA_VERSION = 1
MAX_RUN_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_RUN_MANIFEST_BYTES = 2 * 1024 * 1024

_REQUIRED_METRICS = (
    "fps",
    "frametime_ms",
    "ram_bytes",
    "vram_bytes",
    "shader_compilations",
)


class MetricsCaptureError(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise MetricsCaptureError(f"non-finite JSON number is not allowed: {value}")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MetricsCaptureError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _loads_strict(payload: bytes) -> Any:
    if len(payload) > MAX_RUN_MANIFEST_BYTES:
        raise MetricsCaptureError("run-manifest.json exceeds the size limit")
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MetricsCaptureError("run-manifest.json is not strict UTF-8 JSON") from error


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RUN_ARTIFACT_BYTES:
                raise MetricsCaptureError("target-run artifact exceeds the size limit")
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}", size


def _load_run_manifest(path: Path) -> tuple[dict[str, Any], str, int]:
    if not path.is_file() or path.is_symlink():
        raise MetricsCaptureError("target-run artifact must be a regular file")
    artifact_sha256, artifact_size = _sha256_file(path)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            if names.count("run-manifest.json") != 1:
                raise MetricsCaptureError("target-run artifact must contain exactly one run-manifest.json")
            info = archive.getinfo("run-manifest.json")
            if info.file_size > MAX_RUN_MANIFEST_BYTES:
                raise MetricsCaptureError("run-manifest.json exceeds the size limit")
            payload = archive.read(info)
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise MetricsCaptureError("unable to read target-run artifact") from error
    manifest = _loads_strict(payload)
    if not isinstance(manifest, dict):
        raise MetricsCaptureError("run-manifest.json must be an object")
    if manifest.get("manifest_kind") != "bb-target-run" or manifest.get("schema_version") != 3:
        raise MetricsCaptureError("unsupported target-run manifest contract")
    termination = manifest.get("termination")
    if not isinstance(termination, dict):
        raise MetricsCaptureError("target-run manifest is missing termination data")
    elapsed = termination.get("elapsed_seconds")
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
        raise MetricsCaptureError("target-run elapsed_seconds must be a finite non-negative number")
    return manifest, artifact_sha256, artifact_size


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "value": None,
        "unit": None,
        "source": None,
        "reason": reason,
    }


def collect_metrics(run_artifact: Path) -> dict[str, Any]:
    started = time.monotonic()
    run_manifest, artifact_sha256, artifact_size = _load_run_manifest(run_artifact)
    elapsed = float(run_manifest["termination"]["elapsed_seconds"])

    unavailable_reason = "not-exposed-by-bb-target-run-v3"
    metrics = {name: _unavailable(unavailable_reason) for name in _REQUIRED_METRICS}
    metrics["run_wall_time_seconds"] = {
        "status": "available",
        "value": elapsed,
        "unit": "seconds",
        "source": "run-manifest.json#/termination/elapsed_seconds",
        "reason": None,
    }

    overhead_ms = round(max(0.0, time.monotonic() - started) * 1000.0, 3)
    return {
        "manifest_kind": MANIFEST_KIND,
        "schema_version": SCHEMA_VERSION,
        "producer": {
            "name": "tools/collect_benchmark_metrics.py",
            "version": COLLECTOR_VERSION,
        },
        "input": {
            "target_run_sha256": artifact_sha256,
            "target_run_size_bytes": artifact_size,
            "target_run_manifest_kind": "bb-target-run",
            "target_run_schema_version": 3,
        },
        "capture": {
            "collector_overhead_ms": overhead_ms,
            "target_process_observed": False,
            "target_process_automated": False,
        },
        "metrics": metrics,
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def write_metrics_atomic(output_path: Path, manifest: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=output_path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json_bytes(manifest))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, output_path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-artifact", required=True, type=Path, help="BB-ENV1 target-run ZIP")
    parser.add_argument("--output", required=True, type=Path, help="output metrics JSON")
    args = parser.parse_args(argv)
    try:
        manifest = collect_metrics(args.run_artifact)
        write_metrics_atomic(args.output, manifest)
    except (MetricsCaptureError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
