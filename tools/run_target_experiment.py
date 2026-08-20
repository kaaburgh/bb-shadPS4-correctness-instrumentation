#!/usr/bin/env python3
"""Hardened BB-ENV1 target-run entrypoint.

The previous v3 implementation is retained as an internal compatibility library in
``tools.run_target_experiment_v3``. This entrypoint adds evidence gates while
preserving the published v3 run-record shape for detached consumers.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import run_target_experiment_v3 as _legacy
from tools.target_manifest_projection import (
    package_target_manifest as _shared_package_target_manifest,
)


for _export_name in dir(_legacy):
    if not _export_name.startswith("__"):
        globals()[_export_name] = getattr(_legacy, _export_name)

_LEGACY_RUN_EXPERIMENT = _legacy.run_experiment
_package_target_manifest = _shared_package_target_manifest

RUNNER_VERSION = "1.11.0"
_legacy.RUNNER_VERSION = RUNNER_VERSION

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
    if _is_explicit_synthetic_control(target_manifest):
        return None
    if scenario["oracle"]["kind"] != "process-exit":
        raise TargetRunError(
            "non-synthetic file-sha256 oracles require independently attested current-run producer provenance; this BB-ENV1 handoff currently supports file oracles only for synthetic controls"
        )
    if scenario["artifacts"]:
        raise TargetRunError(
            "non-synthetic declared artifacts require independently attested current-run producer provenance; this BB-ENV1 handoff currently supports declared artifacts only for synthetic controls"
        )
    pinned = _pinned_build_for_host()
    actual_sha256, actual_size = _legacy._sha256_file(
        emulator_binary_path, label="staged emulator binary"
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


def _require_regular_unlinked_file(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as error:
        raise TargetRunError(f"{label} is not accessible") from error
    if _legacy._is_reparse_or_symlink(info) or not stat.S_ISREG(info.st_mode):
        raise TargetRunError(f"{label} must be a regular file, not a link or reparse alias")
    return info


def _resolve_command_binary(command: Mapping[str, Any], working_directory: Path, emulator_binary_path: Path) -> Path:
    candidate = Path(command["argv"][0])
    if not candidate.is_absolute():
        candidate = working_directory / candidate
    _require_regular_unlinked_file(candidate, "command argv[0]")
    _require_regular_unlinked_file(emulator_binary_path, "emulator binary")
    try:
        candidate_resolved = candidate.resolve(strict=True)
        emulator_resolved = emulator_binary_path.resolve(strict=True)
    except OSError as error:
        raise TargetRunError("unable to resolve emulator command binding") from error
    if candidate_resolved != emulator_resolved:
        raise TargetRunError("command argv[0] does not identify emulator_binary")
    return emulator_resolved


def _stage_emulator_binary(source: Path, destination: Path, source_info: os.stat_result) -> Path:
    try:
        shutil.copyfile(source, destination, follow_symlinks=False)
        os.chmod(destination, stat.S_IMODE(source_info.st_mode) | stat.S_IXUSR)
    except OSError as error:
        raise TargetRunError("unable to stage emulator binary for private execution") from error
    _require_regular_unlinked_file(destination, "staged emulator binary")
    if os.name == "posix" and not os.access(destination, os.X_OK):
        raise TargetRunError(
            "staged emulator binary is not executable; working_directory filesystem may be mounted noexec"
        )
    return destination


def _write_snapshot(path: Path, payload: bytes, label: str) -> None:
    try:
        path.write_bytes(payload)
    except OSError as error:
        raise TargetRunError(f"unable to stage {label} snapshot") from error


def _restore_original_command_identity(
    output_path: Path,
    run_manifest: dict[str, Any],
    original_command_raw: bytes,
    packaged_target_raw: bytes | None = None,
) -> dict[str, Any]:
    """Bind the detached record to stable operator/shared-projection identities."""
    run_manifest["execution"]["command_argv_sha256"] = _legacy._sha256_bytes(original_command_raw)
    if packaged_target_raw is not None:
        run_manifest["target"]["packaged_manifest_sha256"] = _legacy._sha256_bytes(
            packaged_target_raw
        )
        run_manifest["target"]["packaged_manifest_size_bytes"] = len(
            packaged_target_raw
        )
    _legacy.validate_run_manifest(run_manifest)
    if not output_path.exists():
        return run_manifest
    try:
        with zipfile.ZipFile(output_path, "r") as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
    except (OSError, zipfile.BadZipFile) as error:
        raise TargetRunError("unable to reopen run artifact for stable command identity") from error
    if packaged_target_raw is not None:
        entries["target-manifest.json"] = packaged_target_raw
    entries["run-manifest.json"] = _legacy._json_bytes(run_manifest)
    _legacy._write_zip_atomic(output_path, entries)
    return run_manifest


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
    target_raw, target_manifest = _legacy._load_target_manifest(target_manifest_path)
    safe_target_raw = _package_target_manifest(target_manifest)
    scenario_raw, scenario = _legacy._load_json_file(scenario_path, maximum=_legacy.MAX_INPUT_BYTES, label="scenario")
    if not isinstance(scenario, Mapping):
        raise TargetRunError("scenario must be a JSON object")
    _legacy.validate_scenario(scenario)
    command_raw, command = _legacy._load_json_file(command_path, maximum=_legacy.MAX_COMMAND_BYTES, label="command file")
    if not isinstance(command, Mapping):
        raise TargetRunError("command must be a JSON object")
    _legacy.validate_command(command)

    synthetic_control = _is_explicit_synthetic_control(target_manifest)
    working_directory_resolved = _legacy._resolve_directory(working_directory, "working_directory")
    snapshot_parent = working_directory_resolved if not synthetic_control else None

    with tempfile.TemporaryDirectory(
        prefix="bb-target-run-snapshot-", dir=snapshot_parent
    ) as directory:
        snapshot_root = Path(directory)
        staged_target = snapshot_root / "target-manifest.json"
        staged_scenario = snapshot_root / "scenario.json"
        staged_command_path = snapshot_root / "command.json"
        _write_snapshot(staged_target, target_raw, "target manifest")
        _write_snapshot(staged_scenario, scenario_raw, "scenario")
        _write_snapshot(staged_command_path, command_raw, "command")

        staged_emulator_path = emulator_binary_path
        if not synthetic_control:
            original_binary = _resolve_command_binary(
                command, working_directory_resolved, emulator_binary_path
            )
            source_info = _require_regular_unlinked_file(original_binary, "emulator binary")
            pinned = _pinned_build_for_host()
            staged_emulator_path = snapshot_root / str(pinned["binary_name"])
            _stage_emulator_binary(original_binary, staged_emulator_path, source_info)
            _require_non_synthetic_evidence_contract(
                target_manifest, scenario, staged_emulator_path, emulator_binary_sha256
            )
            staged_command = dict(command)
            staged_argv = list(command["argv"])
            staged_argv[0] = str(staged_emulator_path)
            staged_command["argv"] = staged_argv
            _write_snapshot(
                staged_command_path, _legacy._json_bytes(staged_command), "command"
            )
        else:
            _require_non_synthetic_evidence_contract(
                target_manifest, scenario, emulator_binary_path, emulator_binary_sha256
            )

        manifest = _LEGACY_RUN_EXPERIMENT(
            target_manifest_path=staged_target,
            scenario_path=staged_scenario,
            command_path=staged_command_path,
            emulator_binary_path=staged_emulator_path,
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
        return _restore_original_command_identity(
            output_path.resolve(),
            manifest,
            command_raw,
            packaged_target_raw=safe_target_raw,
        )


_legacy.run_experiment = run_experiment

globals()["RUNNER_VERSION"] = RUNNER_VERSION
globals()["_package_target_manifest"] = _package_target_manifest
globals()["run_experiment"] = run_experiment
main = _legacy.main


if __name__ == "__main__":
    raise SystemExit(main())
