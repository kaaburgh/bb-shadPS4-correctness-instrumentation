#!/usr/bin/env python3
"""Build a privacy-bounded, self-contained baseline-capture artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Sequence

try:
    from tools.bloodborne_target_manifest import load_strict, validate_manifest as validate_target_manifest
    from tools.collect_host_environment import collect_manifest, validate_manifest as validate_host_manifest
    from tools.target_manifest_projection import TargetRunError, package_target_manifest
except ModuleNotFoundError:  # direct `python tools/capture_baseline.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.bloodborne_target_manifest import load_strict, validate_manifest as validate_target_manifest
    from tools.collect_host_environment import collect_manifest, validate_manifest as validate_host_manifest
    from tools.target_manifest_projection import TargetRunError, package_target_manifest

SOURCE_REPOSITORY = "https://github.com/shadps4-emu/shadPS4"
SOURCE_COMMIT = "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64"
FORMAT = "bb-baseline-capture/v1"
MAX_TARGET_MANIFEST_BYTES = 4 * 1024 * 1024
METRICS = ("fps", "frametime", "ram", "vram", "shader-compilation")
UNAVAILABLE_REASON = (
    "no producer-bound runtime telemetry is collected by this cloud-safe packer; "
    "a GATED target run is required"
)


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _read_target(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ValueError(f"cannot read target manifest: {error}") from error
    if size > MAX_TARGET_MANIFEST_BYTES:
        raise ValueError("target manifest exceeds safety size limit")
    target = load_strict(path)
    validate_target_manifest(target)
    payload = _canonical_json(target)
    return target, payload


def _target_projection(target: dict[str, Any], source_payload: bytes, packaged_payload: bytes) -> dict[str, Any]:
    return {
        "source_manifest_sha256": _sha256(source_payload),
        "packaged_manifest_sha256": _sha256(packaged_payload),
        "manifest_kind": target["manifest_kind"],
        "schema_version": target["schema_version"],
    }


def _capture_evidence_class(target: dict[str, Any]) -> str:
    classes = set(target["provenance"]["evidence_classes"])
    if "runtime" in classes:
        return "runtime"
    if "synthetic" in classes:
        return "synthetic"
    return "static"


def build_capture(target_manifest: Path, *, backend: str | None = None, emulator_config: Path | None = None) -> tuple[dict[str, Any], bytes, bytes]:
    started = time.perf_counter_ns()
    target, source_target_bytes = _read_target(target_manifest)
    target_bytes = package_target_manifest(target)
    host = collect_manifest(graphics_backend=backend, emulator_config_path=emulator_config)
    validate_host_manifest(host)
    host_bytes = _canonical_json(host)
    elapsed = time.perf_counter_ns() - started
    capture = {
        "format": FORMAT,
        "source": {"repository": SOURCE_REPOSITORY, "commit": SOURCE_COMMIT},
        "target": _target_projection(target, source_target_bytes, target_bytes),
        "host": {"manifest_sha256": _sha256(host_bytes), "schema_id": host["schema_id"], "schema_version": host["schema_version"]},
        "telemetry": {name: {"state": "unavailable", "reason": UNAVAILABLE_REASON} for name in METRICS},
        "collection_overhead": {
            "packer_elapsed_ns": elapsed,
            "scope": "target-manifest validation + safe projection + host collection + canonical serialization; excludes target runtime",
        },
        "evidence": {
            "class": _capture_evidence_class(target),
            "runtime_claims": False,
        },
    }
    return capture, target_bytes, host_bytes


def write_artifact(output: Path, capture: dict[str, Any], target_bytes: bytes, host_bytes: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    capture_bytes = _canonical_json(capture)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in (
                ("capture-manifest.json", capture_bytes),
                ("target-manifest.json", target_bytes),
                ("host-environment.json", host_bytes),
            ):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, payload)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend")
    parser.add_argument("--emulator-config", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        capture, target_bytes, host_bytes = build_capture(args.target_manifest, backend=args.backend, emulator_config=args.emulator_config)
        write_artifact(args.output, capture, target_bytes, host_bytes)
    except (OSError, ValueError, TargetRunError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
