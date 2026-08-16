#!/usr/bin/env python3
"""Hardened BB-ENV1 target-run entrypoint.

The previous v3 implementation is retained as an internal compatibility library in
``tools.run_target_experiment_v3``.  This entrypoint adds the evidence gates found
necessary by head-bound Codex review while preserving the published v3 run-record
shape for detached consumers.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools import run_target_experiment_v3 as _legacy


# Re-export the established implementation surface so existing contract tests and
# detached-record validation keep exercising the same implementation primitives.
for _export_name in dir(_legacy):
    if not _export_name.startswith("__"):
        globals()[_export_name] = getattr(_legacy, _export_name)

_LEGACY_PACKAGE_TARGET_MANIFEST = _legacy._package_target_manifest
_LEGACY_RUN_EXPERIMENT = _legacy.run_experiment

RUNNER_VERSION = "1.6.0"
_legacy.RUNNER_VERSION = RUNNER_VERSION

# Independently observed upstream Build and Release run for the exact BB-BL1
# commit/tree.  The archive digest is GitHub's artifact digest; binary digests
# below were recomputed from the downloaded archives before this contract was
# committed.  Non-synthetic target runs fail closed to these exact bytes.
PINNED_BUILD_WORKFLOW_RUN_ID = 31742892228
PINNED_BUILD_ARTIFACTS: dict[str, dict[str, Any]] = {
    "windows": {
        "workflow_run_id": PINNED_BUILD_WORKFLOW_RUN_ID,
        "artifact_id": 9198403207,
        "artifact_name": "shadps4-win64-sdl-2026-08-13-28c84fb",
        "archive_sha256": "sha256:bb2d73f4b00f4550d95820383cfff2fee880e845a336e12ad82512962f5b1c65",
        "binary_name": "shadPS4.exe",
        "binary_sha256": "sha256:4212397ed435f0a1c2c8ddb71dc340e6153fce974558fbd133bae524558c650f",
        "binary_size_bytes": 67641344,
    },
    "linux": {
        "workflow_run_id": PINNED_BUILD_WORKFLOW_RUN_ID,
        "artifact_id": 9198177755,
        "artifact_name": "shadps4-linux-sdl-2026-08-13-28c84fb",
        "archive_sha256": "sha256:127c01d7b2f3260fdf9c39bdae51a68bed14b560346ce7a8d17c59defb083789",
        "binary_name": "Shadps4-sdl.AppImage",
        "binary_sha256": "sha256:7c6512eb2bced183bbda2fe858c503c2a4d6cc3146648f2c859a0477403fbd75",
        "binary_size_bytes": 35179000,
    },
}


def _collect_exact_evidence_classes(value: Any, result: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "evidence_class" and isinstance(child, str):
                result.add(child)
            else:
                _collect_exact_evidence_classes(child, result)
    elif isinstance(value, list):
        for child in value:
            _collect_exact_evidence_classes(child, result)


def _is_explicit_synthetic_control(target_manifest: Mapping[str, Any]) -> bool:
    """Return true only when every declared evidence class is explicitly synthetic."""
    provenance_classes = set(target_manifest["provenance"]["evidence_classes"])
    exact_classes: set[str] = set()
    _collect_exact_evidence_classes(target_manifest, exact_classes)
    return provenance_classes == {"synthetic"} and bool(exact_classes) and exact_classes == {"synthetic"}


def _pinned_build_for_host() -> Mapping[str, Any]:
    if os.name == "nt":
        return PINNED_BUILD_ARTIFACTS["windows"]
    if sys.platform.startswith("linux"):
        return PINNED_BUILD_ARTIFACTS["linux"]
    raise TargetRunError(
        "non-synthetic target execution has no independently bound BB-BL1 CI artifact for this host"
    )


def _require_non_synthetic_evidence_contract(
    target_manifest: Mapping[str, Any],
    scenario: Mapping[str, Any],
    emulator_binary_path: Path,
    emulator_binary_sha256: str,
) -> Mapping[str, Any] | None:
    """Fail closed on provenance/oracle claims that synthetic controls do not establish."""
    if _is_explicit_synthetic_control(target_manifest):
        return None

    if scenario["oracle"]["kind"] != "process-exit":
        raise TargetRunError(
            "non-synthetic file-sha256 oracles require independently attested current-run producer "
            "provenance; this BB-ENV1 handoff currently supports file oracles only for synthetic controls"
        )

    pinned = _pinned_build_for_host()
    actual_sha256, actual_size = _legacy._sha256_file(
        emulator_binary_path.resolve(), label="emulator binary"
    )
    supplied_sha256 = f"sha256:{emulator_binary_sha256}"
    if (
        actual_sha256 != pinned["binary_sha256"]
        or actual_size != pinned["binary_size_bytes"]
        or supplied_sha256 != pinned["binary_sha256"]
    ):
        raise TargetRunError(
            "non-synthetic target execution requires the exact independently observed upstream "
            f"Build and Release artifact from workflow run {PINNED_BUILD_WORKFLOW_RUN_ID} for this host"
        )
    return pinned


def _package_target_manifest(manifest: Mapping[str, Any]) -> bytes:
    """Preserve transfer-safe DLC identity instead of projecting every DLC set to empty."""
    packaged = _legacy.loads_strict(_LEGACY_PACKAGE_TARGET_MANIFEST(manifest).decode("utf-8"))
    packaged_dlc: dict[str, Any] = {}
    for identifier, component in sorted(manifest["content"]["dlc"].items()):
        safe_identifier = "dlc-sha256-" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        source_package = component["source_package"]
        packaged_dlc[safe_identifier] = {
            "version": None,
            "source_package": (
                None if source_package is None else _legacy._copy_exact_artifact(source_package)
            ),
        }
    packaged["content"]["dlc"] = packaged_dlc
    try:
        _legacy.bloodborne_target_manifest.validate_manifest(packaged)
    except Exception as error:
        raise TargetRunError(f"safe target-manifest projection is invalid: {error}") from error
    return _legacy._json_bytes(packaged)


def run_experiment(
    *,
    target_manifest_path: Path,
    scenario_path: Path,
    command_path: Path,
    emulator_binary_path: Path,
    emulator_binary_sha256: str,
    source_repository: str,
    source_commit: str,
    source_tree: str,
    patch_commits: Sequence[str],
    target_root: Path,
    working_directory: Path,
    output_path: Path,
    graphics_backend: str | None = None,
    emulator_config_path: Path | None = None,
) -> dict[str, Any]:
    """Apply BB-ENV1 evidence gates, then delegate bounded execution to the v3 engine."""
    _target_raw, target_manifest = _legacy._load_target_manifest(target_manifest_path)
    _scenario_raw, scenario = _legacy._load_json_file(
        scenario_path, maximum=_legacy.MAX_INPUT_BYTES, label="scenario"
    )
    if not isinstance(scenario, Mapping):
        raise TargetRunError("scenario must be a JSON object")
    _legacy.validate_scenario(scenario)
    _require_non_synthetic_evidence_contract(
        target_manifest,
        scenario,
        emulator_binary_path,
        emulator_binary_sha256,
    )
    return _LEGACY_RUN_EXPERIMENT(
        target_manifest_path=target_manifest_path,
        scenario_path=scenario_path,
        command_path=command_path,
        emulator_binary_path=emulator_binary_path,
        emulator_binary_sha256=emulator_binary_sha256,
        source_repository=source_repository,
        source_commit=source_commit,
        source_tree=source_tree,
        patch_commits=patch_commits,
        target_root=target_root,
        working_directory=working_directory,
        output_path=output_path,
        graphics_backend=graphics_backend,
        emulator_config_path=emulator_config_path,
    )


# The legacy engine resolves these names from its own module globals at runtime.
# Override only the two hardened seams while retaining the reviewed containment,
# packaging and schema implementation unchanged.
_legacy._package_target_manifest = _package_target_manifest
_legacy.run_experiment = run_experiment

# Re-export the active overrides after the initial compatibility export.
globals()["RUNNER_VERSION"] = RUNNER_VERSION
globals()["_package_target_manifest"] = _package_target_manifest
globals()["run_experiment"] = run_experiment
main = _legacy.main


if __name__ == "__main__":
    raise SystemExit(main())
