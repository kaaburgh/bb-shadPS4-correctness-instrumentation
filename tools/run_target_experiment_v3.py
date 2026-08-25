#!/usr/bin/env python3
"""Run one bounded gated target experiment and pack safe run metadata.

The runner deliberately treats the target command as an operator-owned input.
It validates the payload-free target identity manifest, exact emulator binary
identity, source provenance, scenario/oracle contract, and working-directory
separation before starting a process.  The resulting ZIP contains only
allowlisted metadata and optionally redacted JSON artifacts; it never contains
the command file, target root, emulator binary, or raw process output.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools import bloodborne_target_manifest
from tools import shadps4_source_baseline
from tools import collect_host_environment


RUN_SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "target-run.schema.json"
RUN_SCHEMA_ID = "bb-target-run"
RUN_SCHEMA_VERSION = 3
SCENARIO_SCHEMA_ID = "bb-target-scenario/v3"
SCENARIO_SCHEMA_VERSION = 3
COMMAND_SCHEMA_ID = "bb-target-command/v2"
COMMAND_SCHEMA_VERSION = 2
RUNNER_NAME = "bb-target-runner"
RUNNER_VERSION = "1.5.0"
PINNED_SOURCE_REPOSITORY = shadps4_source_baseline.REPOSITORY
PINNED_SOURCE_COMMIT = shadps4_source_baseline.COMMIT
PINNED_SOURCE_TREE = shadps4_source_baseline.TREE
MAX_INPUT_BYTES = 1024 * 1024
MAX_COMMAND_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_REDACTED_JSON_BYTES = 1024 * 1024
MAX_ORACLE_BYTES = 16 * 1024 * 1024
MAX_PROCESS_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_ALLOWLIST_DEPTH = 16
MAX_ALLOWLIST_PROPERTIES = 128
MAX_ALLOWLIST_ARRAY_ITEMS = 4096
MAX_TIMEOUT_SECONDS = 86400
MAX_TEARDOWN_SECONDS = 16
MAX_RECORDED_ELAPSED_SECONDS = MAX_TIMEOUT_SECONDS + MAX_TEARDOWN_SECONDS
MAX_SAFE_STRING_ENUM_VALUES = 64


class TargetRunError(ValueError):
    """Raised when a run contract cannot be interpreted safely."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TargetRunError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise TargetRunError(f"non-finite JSON constant is not valid JSON: {name}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise TargetRunError(f"non-finite JSON number is not valid JSON: {value}")
    return parsed


def loads_strict(text: str) -> Any:
    """Parse JSON without accepting duplicate members or non-finite values."""
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
            parse_float=_parse_finite_float,
        )
    except TargetRunError:
        raise
    except json.JSONDecodeError as error:
        raise TargetRunError(f"invalid JSON: {error}") from error


def _read_bytes(path: Path, *, maximum: int, label: str) -> bytes:
    try:
        before = path.lstat()
    except OSError as error:
        raise TargetRunError(f"unable to read {label}") from error
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise TargetRunError(f"{label} must be a regular file")
    if before.st_size > maximum:
        raise TargetRunError(f"{label} exceeds the {maximum}-byte safety limit")
    try:
        data = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise TargetRunError(f"unable to read {label}") from error
    if (
        after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or len(data) != before.st_size
    ):
        raise TargetRunError(f"{label} changed while it was being read")
    return data


def _sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _sha256_file(path: Path, *, maximum: int | None = None, label: str = "file") -> tuple[str, int]:
    try:
        before = path.lstat()
    except OSError as error:
        raise TargetRunError(f"unable to fingerprint {label}") from error
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise TargetRunError(f"{label} must be a regular file")
    if maximum is not None and before.st_size > maximum:
        raise TargetRunError(f"{label} exceeds the {maximum}-byte safety limit")
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                if maximum is not None and size > maximum:
                    raise TargetRunError(f"{label} exceeds the {maximum}-byte safety limit")
                digest.update(chunk)
        after = path.lstat()
    except TargetRunError:
        raise
    except OSError as error:
        raise TargetRunError(f"unable to fingerprint {label}") from error
    if (
        size != before.st_size
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        raise TargetRunError(f"{label} changed while it was being fingerprinted")
    return f"sha256:{digest.hexdigest()}", size


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode(
            "utf-8"
        )
        + b"\n"
    )


def _require_exact_keys(value: Any, expected: set[str], field: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise TargetRunError(f"{field} has unexpected fields")


def _require_string(value: Any, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise TargetRunError(f"{field} must be a non-empty string of at most {maximum} bytes")
    return value


def _require_integer(value: Any, field: str, *, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TargetRunError(f"{field} must be an integer at least {minimum}")
    if maximum is not None and value > maximum:
        raise TargetRunError(f"{field} must be an integer no greater than {maximum}")
    return value


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise TargetRunError(f"{field} must be a lowercase SHA-256 token")
    return value


def _require_git_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise TargetRunError(f"{field} must be a 40-character lowercase git SHA")
    return value


def _normalize_patch_commits(values: Sequence[str]) -> list[str]:
    """Accept only the exact unpatched BB-BL1 baseline until patch provenance is attested."""
    if values:
        for value in values:
            _require_git_sha(value, "patch_commit")
        raise TargetRunError(
            "patch_commits require independently verified checkout/build provenance; "
            "this runner currently accepts only the pinned unpatched BB-BL1 baseline"
        )
    return []


def _require_attestable_emulator_config(path: Path | None) -> None:
    if path is not None:
        raise TargetRunError(
            "the pinned shadPS4 CLI does not accept an explicit config-file path; "
            "emulator config consumption cannot be attested, so --emulator-config is unsupported"
        )


def _safe_relative_path(value: Any, field: str) -> str:
    path = _require_string(value, field, maximum=256)
    if (
        path.startswith("/")
        or path.startswith("\\")
        or ":" in path
        or "\\" in path
        or "//" in path
    ):
        raise TargetRunError(f"{field} must be a relative path using '/' separators")
    parts = path.split("/")
    if any(
        not part
        or part in {".", ".."}
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", part) is None
        for part in parts
    ):
        raise TargetRunError(f"{field} contains an unsafe path component")
    return path


def validate_scenario(scenario: Mapping[str, Any]) -> None:
    """Validate the small operator-authored scenario contract."""
    _require_exact_keys(
        scenario,
        {"schema_id", "schema_version", "scenario_id", "description", "timeout_seconds", "oracle", "artifacts"},
        "scenario",
    )
    if scenario["schema_id"] != SCENARIO_SCHEMA_ID or scenario["schema_version"] != SCENARIO_SCHEMA_VERSION:
        raise TargetRunError("unsupported target scenario schema")
    scenario_id = _require_string(scenario["scenario_id"], "scenario.scenario_id", maximum=64)
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", scenario_id) is None:
        raise TargetRunError("scenario.scenario_id is not a stable identifier")
    _require_string(scenario["description"], "scenario.description", maximum=512)
    _require_integer(scenario["timeout_seconds"], "scenario.timeout_seconds", minimum=1, maximum=MAX_TIMEOUT_SECONDS)

    oracle = scenario["oracle"]
    if not isinstance(oracle, Mapping) or oracle.get("kind") not in {"process-exit", "file-sha256"}:
        raise TargetRunError("scenario.oracle.kind is unsupported")
    if oracle["kind"] == "process-exit":
        _require_exact_keys(oracle, {"kind", "expected_exit_code"}, "scenario.oracle")
        _require_integer(oracle["expected_exit_code"], "scenario.oracle.expected_exit_code", minimum=-255, maximum=255)
    else:
        _require_exact_keys(oracle, {"kind", "path", "sha256"}, "scenario.oracle")
        _safe_relative_path(oracle["path"], "scenario.oracle.path")
        _require_sha256(oracle["sha256"], "scenario.oracle.sha256")

    artifacts = scenario["artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) > 32:
        raise TargetRunError("scenario.artifacts must contain at most 32 entries")
    names: set[str] = set()
    for index, artifact in enumerate(artifacts):
        field = f"scenario.artifacts[{index}]"
        if not isinstance(artifact, Mapping):
            raise TargetRunError(f"{field} must be an object")
        base_keys = {"path", "name", "mode", "max_bytes"}
        if artifact.get("mode") == "redacted-json":
            _require_exact_keys(artifact, base_keys | {"allowlist"}, field)
            _validate_json_allowlist(artifact["allowlist"], f"{field}.allowlist")
        else:
            _require_exact_keys(artifact, base_keys, field)
        _safe_relative_path(artifact["path"], f"{field}.path")
        name = _require_string(artifact["name"], f"{field}.name", maximum=64)
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name) is None:
            raise TargetRunError(f"{field}.name is not a stable identifier")
        if name in names:
            raise TargetRunError(f"duplicate artifact name: {name}")
        names.add(name)
        if artifact["mode"] not in {"metadata-only", "redacted-json"}:
            raise TargetRunError(f"{field}.mode is unsupported")
        maximum = _require_integer(artifact["max_bytes"], f"{field}.max_bytes", minimum=1, maximum=MAX_ARTIFACT_BYTES)
        if artifact["mode"] == "redacted-json" and maximum > MAX_REDACTED_JSON_BYTES:
            raise TargetRunError(f"{field}.max_bytes is too large for redacted JSON")


def validate_command(command: Mapping[str, Any]) -> None:
    """Validate an argv-only command whose emulator and target are explicit arguments."""
    _require_exact_keys(
        command,
        {
            "schema_id",
            "schema_version",
            "argv",
            "emulator_binary_index",
            "target_path_index",
        },
        "command",
    )
    if (
        command["schema_id"] != COMMAND_SCHEMA_ID
        or command["schema_version"] != COMMAND_SCHEMA_VERSION
    ):
        raise TargetRunError("unsupported target command schema")
    argv = command["argv"]
    if not isinstance(argv, list) or not 1 <= len(argv) <= 128:
        raise TargetRunError("command.argv must contain 1-128 arguments")
    for index, argument in enumerate(argv):
        _require_string(argument, f"command.argv[{index}]", maximum=4096)
    emulator_index = _require_integer(
        command["emulator_binary_index"],
        "command.emulator_binary_index",
        minimum=0,
        maximum=len(argv) - 1,
    )
    if emulator_index != 0:
        raise TargetRunError("command.emulator_binary_index must be 0 so argv[0] is the verified emulator")
    target_index = _require_integer(
        command["target_path_index"],
        "command.target_path_index",
        minimum=0,
        maximum=len(argv) - 1,
    )
    if target_index == emulator_index:
        raise TargetRunError("command target_path_index must differ from emulator_binary_index")


def _load_json_file(path: Path, *, maximum: int, label: str) -> tuple[bytes, Any]:
    raw = _read_bytes(path, maximum=maximum, label=label)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TargetRunError(f"{label} must be UTF-8 JSON") from error
    return raw, loads_strict(text)


def _load_target_manifest(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    raw, _document = _load_json_file(path, maximum=MAX_INPUT_BYTES, label="target manifest")
    try:
        manifest = bloodborne_target_manifest.validate_document(raw.decode("utf-8"))
    except Exception as error:
        raise TargetRunError(f"target manifest validation failed: {error}") from error
    if not isinstance(manifest, Mapping):
        raise TargetRunError("target manifest must be a JSON object")
    return raw, manifest


def _resolve_directory(path: Path, field: str) -> Path:
    try:
        info = path.lstat()
    except OSError as error:
        raise TargetRunError(f"{field} is not accessible") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise TargetRunError(f"{field} must be a real directory")
    return path.resolve()


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_reparse_or_symlink(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_reparse_tag", 0))


def _resolve_target_directory(target_root: Path, path: Path, field: str) -> Path:
    try:
        info = path.lstat()
    except OSError as error:
        raise TargetRunError(f"{field} is not accessible") from error
    if _is_reparse_or_symlink(info) or not stat.S_ISDIR(info.st_mode):
        raise TargetRunError(f"{field} must be a real directory without links or reparse points")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise TargetRunError(f"{field} cannot be resolved safely") from error
    if not _is_under(resolved, target_root):
        raise TargetRunError(f"{field} escapes target_root")
    return resolved


def _resolve_target_file(target_root: Path, path: Path, field: str) -> Path:
    try:
        info = path.lstat()
    except OSError as error:
        raise TargetRunError(f"{field} is not accessible") from error
    if _is_reparse_or_symlink(info) or not stat.S_ISREG(info.st_mode):
        raise TargetRunError(f"{field} must be a regular file without links or reparse points")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise TargetRunError(f"{field} cannot be resolved safely") from error
    if not _is_under(resolved, target_root):
        raise TargetRunError(f"{field} escapes target_root")
    return resolved


def _verify_target_artifact(
    target_root: Path,
    path: Path,
    expected: Mapping[str, Any],
    field: str,
) -> tuple[str, int]:
    resolved = _resolve_target_file(target_root, path, field)
    observed_sha256, observed_size = _sha256_file(resolved, label=field)
    expected_sha256 = f"sha256:{expected['sha256']}"
    if observed_sha256 != expected_sha256 or observed_size != expected["size_bytes"]:
        raise TargetRunError(
            f"{field} does not match the BB-BL2 manifest "
            f"(actual_sha256={observed_sha256}, actual_size={observed_size})"
        )
    return observed_sha256, observed_size


def _target_namespace_records(
    target_root: Path,
    namespace_root: Path,
    namespace: str,
    seen_paths: set[bytes],
    *,
    expected_file_count: int,
    expected_total_bytes: int,
) -> tuple[list[tuple[bytes, bytes]], int]:
    records: list[tuple[bytes, bytes]] = []
    total_bytes = 0
    pending: list[tuple[Path, tuple[str, ...]]] = [(namespace_root, ())]
    while pending:
        directory, parent_parts = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as error:
            raise TargetRunError(f"unable to enumerate target namespace {namespace}") from error
        for entry in entries:
            entry_path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise TargetRunError(f"unable to inspect target namespace {namespace}") from error
            if _is_reparse_or_symlink(info):
                raise TargetRunError(
                    f"target namespace {namespace} contains a link or reparse point"
                )

            raw_relative = "/".join((*parent_parts, entry.name))
            normalized_relative = unicodedata.normalize("NFC", raw_relative)
            normalized_parts = normalized_relative.split("/")
            if (
                not normalized_relative
                or normalized_relative.startswith("/")
                or any(part in {"", ".", ".."} for part in normalized_parts)
            ):
                raise TargetRunError(f"target namespace {namespace} contains an unsafe path")
            try:
                canonical_path = f"{namespace}/{normalized_relative}".encode("utf-8")
            except UnicodeEncodeError as error:
                raise TargetRunError(
                    f"target namespace {namespace} contains a non-UTF-8 path"
                ) from error
            if canonical_path in seen_paths:
                raise TargetRunError("target tree contains duplicate NFC-normalized paths")
            seen_paths.add(canonical_path)

            if stat.S_ISDIR(info.st_mode):
                resolved = _resolve_target_directory(
                    target_root,
                    entry_path,
                    f"target namespace directory {namespace}/{normalized_relative}",
                )
                pending.append((resolved, (*parent_parts, entry.name)))
                continue
            if not stat.S_ISREG(info.st_mode):
                raise TargetRunError(
                    f"target namespace {namespace} contains an unsupported entry type"
                )

            resolved = _resolve_target_file(
                target_root,
                entry_path,
                f"target namespace file {namespace}/{normalized_relative}",
            )
            observed_sha256, size = _sha256_file(resolved, label="target tree file")
            total_bytes += size
            if len(records) + 1 > expected_file_count or total_bytes > expected_total_bytes:
                raise TargetRunError("target resolved tree exceeds the BB-BL2 manifest bounds")
            digest_hex = observed_sha256.removeprefix("sha256:")
            record = (
                canonical_path
                + b"\x00"
                + str(size).encode("ascii")
                + b"\x00"
                + digest_hex.encode("ascii")
                + b"\n"
            )
            records.append((canonical_path, record))
    return records, total_bytes


def _declared_dlc_roots(
    target_root: Path, target_manifest: Mapping[str, Any]
) -> list[tuple[str, Path]]:
    declared_ids = set(target_manifest["content"]["dlc"])
    dlc_root_path = target_root / "dlc"
    try:
        dlc_info = dlc_root_path.lstat()
    except FileNotFoundError:
        if declared_ids:
            raise TargetRunError("target_root/dlc is missing for declared BB-BL2 DLC content")
        return []
    except OSError as error:
        raise TargetRunError("unable to inspect target_root/dlc") from error
    if _is_reparse_or_symlink(dlc_info) or not stat.S_ISDIR(dlc_info.st_mode):
        raise TargetRunError("target_root/dlc must be a real directory without links")
    dlc_root = _resolve_target_directory(target_root, dlc_root_path, "target_root/dlc")
    try:
        entries = list(os.scandir(dlc_root))
    except OSError as error:
        raise TargetRunError("unable to enumerate target_root/dlc") from error
    actual_ids = {entry.name for entry in entries}
    if actual_ids != declared_ids:
        raise TargetRunError("target_root/dlc does not match the BB-BL2 declared DLC set")
    roots: list[tuple[str, Path]] = []
    for entry in entries:
        roots.append(
            (
                f"dlc/{entry.name}",
                _resolve_target_directory(
                    target_root,
                    Path(entry.path),
                    f"target_root/dlc/{entry.name}",
                ),
            )
        )
    return sorted(roots, key=lambda item: item[0].encode("utf-8"))


def _verify_target_root(
    target_root: Path, target_manifest: Mapping[str, Any]
) -> tuple[Path, Path]:
    """Bind BB-BL2 file/tree identities to the exact target view used by the run."""
    app_root = _resolve_target_directory(target_root, target_root / "app", "target_root/app")
    eboot = _resolve_target_file(target_root, app_root / "eboot.bin", "target_root/app/eboot.bin")
    param_sfo = _resolve_target_file(
        target_root,
        app_root / "sce_sys" / "param.sfo",
        "target_root/app/sce_sys/param.sfo",
    )
    _verify_target_artifact(
        target_root,
        eboot,
        target_manifest["build"]["eboot"],
        "target_root/app/eboot.bin",
    )
    _verify_target_artifact(
        target_root,
        param_sfo,
        target_manifest["build"]["param_sfo"],
        "target_root/app/sce_sys/param.sfo",
    )

    expected_tree = target_manifest["content"]["resolved_tree"]
    if expected_tree["algorithm"] != "sha256-tree-v1":
        raise TargetRunError("unsupported BB-BL2 resolved-tree algorithm")
    namespaces = [("app", app_root), *_declared_dlc_roots(target_root, target_manifest)]
    seen_paths: set[bytes] = set()
    records: list[tuple[bytes, bytes]] = []
    total_bytes = 0
    for namespace, namespace_root in namespaces:
        namespace_records, namespace_bytes = _target_namespace_records(
            target_root,
            namespace_root,
            namespace,
            seen_paths,
            expected_file_count=expected_tree["file_count"] - len(records),
            expected_total_bytes=expected_tree["total_bytes"] - total_bytes,
        )
        records.extend(namespace_records)
        total_bytes += namespace_bytes
    records.sort(key=lambda item: item[0])
    digest = hashlib.sha256(b"".join(record for _path, record in records)).hexdigest()
    if (
        len(records) != expected_tree["file_count"]
        or total_bytes != expected_tree["total_bytes"]
        or digest != expected_tree["sha256"]
    ):
        raise TargetRunError(
            "target resolved tree does not match the BB-BL2 manifest "
            f"(actual_sha256=sha256:{digest}, actual_files={len(records)}, "
            f"actual_bytes={total_bytes})"
        )
    return app_root, eboot


def _bind_command_target(
    command: Mapping[str, Any],
    workdir: Path,
    app_root: Path,
    eboot: Path,
) -> str:
    """Require the declared target argv element to resolve to the verified app root or eboot."""
    argument = Path(command["argv"][command["target_path_index"]])
    candidate = argument if argument.is_absolute() else workdir / argument
    try:
        info = candidate.lstat()
        candidate_resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise TargetRunError("command target path is not accessible") from error
    if _is_reparse_or_symlink(info):
        raise TargetRunError("command target path must not be a link or reparse point")
    expected = {
        os.path.normcase(str(app_root)): "app-root",
        os.path.normcase(str(eboot)): "eboot",
    }
    kind = expected.get(os.path.normcase(str(candidate_resolved)))
    if kind is None:
        raise TargetRunError(
            "command target_path_index does not identify the verified target app root or eboot"
        )
    return kind


def _resolve_work_file(workdir: Path, relative_path: str) -> Path:
    candidate = workdir.joinpath(*relative_path.split("/"))
    try:
        info = candidate.lstat()
    except OSError as error:
        raise TargetRunError("declared artifact is missing") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise TargetRunError("declared artifact is not a regular file")
    resolved = candidate.resolve()
    if not _is_under(resolved, workdir):
        raise TargetRunError("declared artifact escapes the isolated working directory")
    return resolved


def _resolve_declared_work_path(workdir: Path, relative_path: str, field: str) -> Path:
    """Resolve an output path without requiring it to exist yet."""
    try:
        workdir = workdir.resolve()
        candidate = workdir.joinpath(*relative_path.split("/"))
        resolved = candidate.resolve(strict=False)
    except OSError as error:
        raise TargetRunError(f"{field} cannot be resolved safely") from error
    if not _is_under(resolved, workdir):
        raise TargetRunError(f"{field} escapes the isolated working directory")
    return candidate


def _preflight_declared_outputs(scenario: Mapping[str, Any], workdir: Path) -> None:
    """Reject stale file-oracle/artifact paths before the target command starts."""
    declared: list[tuple[str, str]] = []
    if scenario["oracle"]["kind"] == "file-sha256":
        declared.append((scenario["oracle"]["path"], "scenario.oracle.path"))
    declared.extend(
        (artifact["path"], f"scenario.artifacts[{index}].path")
        for index, artifact in enumerate(scenario["artifacts"])
    )
    for relative_path, field in declared:
        candidate = _resolve_declared_work_path(workdir, relative_path, field)
        try:
            candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise TargetRunError(f"unable to inspect {field}") from error
        raise TargetRunError(f"{field} must not exist before execution")


_SENSITIVE_KEY = re.compile(
    r"(?:password|passphrase|secret|token|credential|api[_-]?key|authorization|cookie|user(name)?|home|cwd|path|file(name)?|working[_-]?directory|target[_-]?root|command|argv|environment|hostname|serial|uuid|mac|ip)",
    re.IGNORECASE,
)
_WINDOWS_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\s\"']+")
_PRIVATE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:home|Users|private|tmp|var/tmp|workspace)/[^\s\"']+")


def _redact_string(value: str) -> str:
    value = _WINDOWS_PATH.sub("<redacted-path>", value)
    value = _PRIVATE_POSIX_PATH.sub("<redacted-path>", value)
    return value if len(value) <= 4096 else "<redacted-overlong-string>"


def _redact_json(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _SENSITIVE_KEY.search(key):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(name): _redact_json(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


_SAFE_TARGET_STRING_SETTINGS: dict[str, re.Pattern[str]] = {
    "game.language": re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$"),
    "target.network_mode": re.compile(r"^(?:offline|online)$"),
}
_SAFE_TARGET_MODIFICATION_IDS = frozenset({"synthetic-frame-pacing-fixture"})
_SAFE_ARTIFACT_FIELD_NAMES = frozenset({"checkpoint", "ok"})
_SAFE_ARTIFACT_STRING_LITERALS = frozenset(
    {
        "synthetic-checkpoint",
        "passed",
        "failed",
        "unknown",
        "not_evaluated",
        "completed",
        "timed_out",
        "launch_failed",
        "exit_nonzero",
        "oracle_failed",
        "oracle_unknown",
    }
)


def _copy_exact_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sha256": artifact["sha256"],
        "size_bytes": artifact["size_bytes"],
        "evidence_class": artifact["evidence_class"],
    }


def _package_target_manifest(manifest: Mapping[str, Any]) -> bytes:
    """Build a schema-valid transfer projection without copying free-form target strings."""
    packaged_settings: dict[str, Any] = {}
    for key, setting in manifest["configuration"]["settings"].items():
        allowed = _SAFE_TARGET_STRING_SETTINGS.get(key)
        if allowed is None:
            raise TargetRunError(f"target manifest setting {key!r} is not approved for safe packaging")
        value = setting["value"]
        if not isinstance(value, str) or allowed.fullmatch(value) is None:
            raise TargetRunError(f"target manifest setting {key!r} has an unsafe value")
        packaged_settings[key] = {
            "value": value,
            "evidence_class": setting["evidence_class"],
        }

    packaged_modifications: dict[str, Any] = {}
    for identifier, modification in manifest["configuration"]["active_modifications"].items():
        if identifier not in _SAFE_TARGET_MODIFICATION_IDS:
            raise TargetRunError(
                f"target modification {identifier!r} is not a registered safe project identifier"
            )
        packaged_modifications[identifier] = {
            "kind": modification["kind"],
            "version": None,
            "artifact": _copy_exact_artifact(modification["artifact"]),
        }

    order = list(manifest["configuration"]["modification_order"]["value"])
    if any(identifier not in _SAFE_TARGET_MODIFICATION_IDS for identifier in order):
        raise TargetRunError("target modification_order contains an unregistered identifier")

    completeness = manifest["identity_completeness"]
    if completeness["state"] == "complete":
        safe_completeness = {"state": "complete", "unknown_fields": []}
    else:
        roots = sorted(
            {
                "/" + pointer.split("/", 2)[1]
                for pointer in completeness["unknown_fields"]
            }
        )
        safe_completeness = {"state": "partial", "unknown_fields": roots}

    update = manifest["content"]["update"]
    if update["state"] == "installed":
        safe_update: dict[str, Any] = {
            "state": "installed",
            "component": {
                "content_id": None,
                "version": None,
                "source_package": None,
            },
        }
    else:
        safe_update = {"state": update["state"]}

    packaged = {
        "manifest_kind": manifest["manifest_kind"],
        "schema_version": manifest["schema_version"],
        "provenance": {
            "evidence_classes": list(manifest["provenance"]["evidence_classes"]),
            "collected_at": manifest["provenance"]["collected_at"],
            "producer": {
                "name": "bb-target-manifest-safe-projection",
                "version": "1.0.0",
            },
        },
        "identity_completeness": safe_completeness,
        "target": {
            "name": manifest["target"]["name"],
            "title_id": dict(manifest["target"]["title_id"]),
            "distribution_region": manifest["target"]["distribution_region"],
        },
        "build": {
            "app_version": None,
            "master_version": None,
            "eboot": _copy_exact_artifact(manifest["build"]["eboot"]),
            "param_sfo": _copy_exact_artifact(manifest["build"]["param_sfo"]),
        },
        "content": {
            "base": {"content_id": None, "version": None, "source_package": None},
            "update": safe_update,
            "dlc": {},
            "resolved_tree": dict(manifest["content"]["resolved_tree"]),
        },
        "configuration": {
            "settings": packaged_settings,
            "active_modifications": packaged_modifications,
            "modification_order": {
                "value": order,
                "evidence_class": manifest["configuration"]["modification_order"]["evidence_class"],
            },
        },
    }
    try:
        bloodborne_target_manifest.validate_manifest(packaged)
    except Exception as error:
        raise TargetRunError(f"safe target-manifest projection is invalid: {error}") from error
    return _json_bytes(packaged)


def _safe_scenario_for_package(
    scenario: Mapping[str, Any], raw_input_sha256: str
) -> dict[str, Any]:
    safe_id = f"scenario-{raw_input_sha256.removeprefix('sha256:')[:16]}"
    oracle = scenario["oracle"]
    if oracle["kind"] == "file-sha256":
        safe_oracle: dict[str, Any] = {
            "kind": "file-sha256",
            "path": "redacted/oracle.bin",
            "sha256": oracle["sha256"],
        }
    else:
        safe_oracle = {
            "kind": "process-exit",
            "expected_exit_code": oracle["expected_exit_code"],
        }
    safe_artifacts = []
    for index, artifact in enumerate(scenario["artifacts"]):
        safe_artifact: dict[str, Any] = {
            "path": f"redacted/artifact-{index:02d}",
            "name": f"artifact-{index:02d}",
            "mode": artifact["mode"],
            "max_bytes": artifact["max_bytes"],
        }
        if artifact["mode"] == "redacted-json":
            safe_artifact["allowlist"] = artifact["allowlist"]
        safe_artifacts.append(safe_artifact)
    packaged = {
        "schema_id": scenario["schema_id"],
        "schema_version": scenario["schema_version"],
        "scenario_id": safe_id,
        "description": "<redacted-operator-description>",
        "timeout_seconds": scenario["timeout_seconds"],
        "oracle": safe_oracle,
        "artifacts": safe_artifacts,
    }
    validate_scenario(packaged)
    return packaged


def _validate_json_allowlist(schema: Any, field: str, *, depth: int = 0) -> None:
    """Validate the restricted per-artifact JSON schema used for embedding."""
    if depth > MAX_ALLOWLIST_DEPTH or not isinstance(schema, Mapping):
        raise TargetRunError(f"{field} is not a supported JSON allowlist schema")
    schema_type = schema.get("type")
    if schema_type == "object":
        _require_exact_keys(
            schema,
            {"type", "properties", "required", "additionalProperties"},
            field,
        )
        if schema["additionalProperties"] is not False:
            raise TargetRunError(f"{field}.additionalProperties must be false")
        properties = schema["properties"]
        if not isinstance(properties, Mapping) or len(properties) > MAX_ALLOWLIST_PROPERTIES:
            raise TargetRunError(f"{field}.properties is too large or invalid")
        required = schema["required"]
        if not isinstance(required, list) or len(required) > len(properties):
            raise TargetRunError(f"{field}.required is invalid")
        required_names: set[str] = set()
        for index, name in enumerate(required):
            name = _require_string(name, f"{field}.required[{index}]", maximum=64)
            if name in required_names or name not in properties:
                raise TargetRunError(f"{field}.required contains an unknown or duplicate field")
            required_names.add(name)
        for name, child in properties.items():
            if (
                not isinstance(name, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name) is None
                or name not in _SAFE_ARTIFACT_FIELD_NAMES
            ):
                raise TargetRunError(f"{field}.properties contains a field name not approved for safe transfer")
            _validate_json_allowlist(child, f"{field}.properties.{name}", depth=depth + 1)
        return
    if schema_type == "array":
        _require_exact_keys(schema, {"type", "items", "max_items"}, field)
        _require_integer(schema["max_items"], f"{field}.max_items", minimum=0, maximum=MAX_ALLOWLIST_ARRAY_ITEMS)
        _validate_json_allowlist(schema["items"], f"{field}.items", depth=depth + 1)
        return
    if schema_type == "string":
        _require_exact_keys(schema, {"type", "enum"}, field)
        values = schema["enum"]
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_SAFE_STRING_ENUM_VALUES:
            raise TargetRunError(f"{field}.enum must contain 1-{MAX_SAFE_STRING_ENUM_VALUES} safe literals")
        seen: set[str] = set()
        for index, value in enumerate(values):
            value = _require_string(value, f"{field}.enum[{index}]", maximum=128)
            if value in seen or value not in _SAFE_ARTIFACT_STRING_LITERALS:
                raise TargetRunError(f"{field}.enum contains an unapproved or duplicate string literal")
            seen.add(value)
        return
    if schema_type in {"integer", "number", "boolean", "null"}:
        _require_exact_keys(schema, {"type"}, field)
        return
    raise TargetRunError(f"{field}.type is unsupported")


def _project_allowlisted_json(value: Any, schema: Mapping[str, Any], field: str = "$") -> Any:
    """Project JSON through an explicit schema; unknown fields fail closed."""
    schema_type = schema["type"]
    if schema_type == "object":
        if not isinstance(value, Mapping):
            raise TargetRunError(f"{field} is not an object allowed by the artifact schema")
        properties = schema["properties"]
        unknown = sorted(set(value) - set(properties))
        if unknown:
            raise TargetRunError(f"{field} contains fields outside the artifact allowlist")
        missing = [name for name in schema["required"] if name not in value]
        if missing:
            raise TargetRunError(f"{field} is missing required allowlisted fields")
        return {
            name: _project_allowlisted_json(value[name], properties[name], f"{field}.{name}")
            for name in value
        }
    if schema_type == "array":
        if not isinstance(value, list) or len(value) > schema["max_items"]:
            raise TargetRunError(f"{field} is not an allowed bounded array")
        return [
            _project_allowlisted_json(item, schema["items"], f"{field}[{index}]")
            for index, item in enumerate(value)
        ]
    if schema_type == "string":
        if not isinstance(value, str) or value not in schema["enum"]:
            raise TargetRunError(f"{field} is not an allowed enumerated string")
        return value
    if schema_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise TargetRunError(f"{field} is not an allowed integer")
        return value
    if schema_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TargetRunError(f"{field} is not an allowed number")
        if isinstance(value, float) and not math.isfinite(value):
            raise TargetRunError(f"{field} is not a finite JSON number")
        return value
    if schema_type == "boolean":
        if not isinstance(value, bool):
            raise TargetRunError(f"{field} is not an allowed boolean")
        return value
    if value is not None:
        raise TargetRunError(f"{field} is not null as required by the artifact schema")
    return None


def _redact_json_artifact(path: Path, *, maximum: int, allowlist: Mapping[str, Any]) -> bytes:
    _validate_json_allowlist(allowlist, "artifact.allowlist")
    raw = _read_bytes(path, maximum=maximum, label="JSON artifact")
    try:
        value = loads_strict(raw.decode("utf-8"))
    except (UnicodeDecodeError, TargetRunError) as error:
        raise TargetRunError("JSON artifact is not strict UTF-8 JSON") from error
    projected = _project_allowlisted_json(value, allowlist)
    return _json_bytes(_redact_json(projected))


def _collect_artifacts(
    scenario: Mapping[str, Any], workdir: Path
) -> tuple[list[dict[str, Any]], dict[str, bytes], list[str]]:
    entries: list[dict[str, Any]] = []
    embedded: dict[str, bytes] = {}
    warnings: list[str] = []
    for index, artifact in enumerate(scenario["artifacts"]):
        name = f"artifact-{index:02d}"
        try:
            path = _resolve_work_file(workdir, artifact["path"])
            source_sha256, source_size = _sha256_file(
                path,
                maximum=artifact["max_bytes"],
                label=f"artifact {name}",
            )
        except TargetRunError as error:
            message = str(error)
            code = "artifact-missing" if "missing" in message else "artifact-rejected"
            warnings.append(code)
            entries.append(
                {
                    "name": name,
                    "status": "missing" if code == "artifact-missing" else "rejected",
                    "source_sha256": None,
                    "source_size_bytes": None,
                    "packaged_sha256": None,
                    "packaged_size_bytes": None,
                    "packaged_path": None,
                }
            )
            continue

        if artifact["mode"] == "metadata-only":
            entries.append(
                {
                    "name": name,
                    "status": "externalized",
                    "source_sha256": source_sha256,
                    "source_size_bytes": source_size,
                    "packaged_sha256": None,
                    "packaged_size_bytes": None,
                    "packaged_path": None,
                }
            )
            continue

        try:
            redacted = _redact_json_artifact(
                path,
                maximum=artifact["max_bytes"],
                allowlist=artifact["allowlist"],
            )
        except TargetRunError:
            warnings.append("artifact-redaction-failed")
            entries.append(
                {
                    "name": name,
                    "status": "rejected",
                    "source_sha256": source_sha256,
                    "source_size_bytes": source_size,
                    "packaged_sha256": None,
                    "packaged_size_bytes": None,
                    "packaged_path": None,
                }
            )
            continue

        packaged_path = f"artifacts/{name}.redacted.json"
        embedded[packaged_path] = redacted
        entries.append(
            {
                "name": name,
                "status": "embedded_redacted_json",
                "source_sha256": source_sha256,
                "source_size_bytes": source_size,
                "packaged_sha256": _sha256_bytes(redacted),
                "packaged_size_bytes": len(redacted),
                "packaged_path": packaged_path,
            }
        )
    return entries, embedded, sorted(set(warnings))


class _WindowsJob:
    """Kill-on-close Job Object that contains the launcher and its descendants."""

    CREATE_SUSPENDED = 0x00000004
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    def __init__(self) -> None:
        if os.name != "nt":
            raise TargetRunError("Windows Job Objects are only available on Windows")
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class ThreadEntry32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", ctypes.c_long),
                ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
            ]

        kernel32 = self._kernel32
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry32)]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry32)]
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        self._thread_entry32 = ThreadEntry32
        self._handle = kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise self._last_error("CreateJobObjectW failed")
        info = ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            self._handle,
            self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            self.close()
            raise self._last_error("SetInformationJobObject failed")

    def _last_error(self, message: str) -> OSError:
        code = self._ctypes.get_last_error()
        return OSError(code, f"{message} (WinError {code})")

    def assign_and_resume(self, process: subprocess.Popen[Any]) -> None:
        if not self._kernel32.AssignProcessToJobObject(self._handle, process._handle):
            raise self._last_error("AssignProcessToJobObject failed")
        snapshot = self._kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        if not snapshot:
            raise self._last_error("CreateToolhelp32Snapshot failed")
        try:
            entry = self._thread_entry32()
            entry.dwSize = self._ctypes.sizeof(entry)
            if not self._kernel32.Thread32First(snapshot, self._ctypes.byref(entry)):
                raise self._last_error("Thread32First failed")
            while True:
                if entry.th32OwnerProcessID == process.pid:
                    thread = self._kernel32.OpenThread(0x0002, False, entry.th32ThreadID)
                    if not thread:
                        raise self._last_error("OpenThread failed")
                    try:
                        if self._kernel32.ResumeThread(thread) == 0xFFFFFFFF:
                            raise self._last_error("ResumeThread failed")
                    finally:
                        self._kernel32.CloseHandle(thread)
                    return
                if not self._kernel32.Thread32Next(snapshot, self._ctypes.byref(entry)):
                    break
            raise OSError("primary thread was not found for suspended process")
        finally:
            self._kernel32.CloseHandle(snapshot)

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle:
            self._kernel32.CloseHandle(handle)



class _LinuxSubreaper:
    """Temporarily adopt orphaned target descendants so session changes cannot escape teardown."""

    PR_SET_CHILD_SUBREAPER = 36
    PR_GET_CHILD_SUBREAPER = 37

    def __init__(self) -> None:
        if not sys.platform.startswith("linux"):
            raise TargetRunError("Linux subreaper containment is only available on Linux")
        import ctypes

        self._ctypes = ctypes
        self._libc = ctypes.CDLL(None, use_errno=True)
        self._libc.prctl.argtypes = [
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        self._libc.prctl.restype = ctypes.c_int
        current = ctypes.c_int()
        if self._libc.prctl(
            self.PR_GET_CHILD_SUBREAPER, ctypes.addressof(current), 0, 0, 0
        ) != 0:
            code = ctypes.get_errno()
            raise OSError(code, "PR_GET_CHILD_SUBREAPER failed")
        self._restore = current.value == 0
        if self._restore and self._libc.prctl(self.PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            code = ctypes.get_errno()
            raise OSError(code, "PR_SET_CHILD_SUBREAPER failed")

    def close(self) -> None:
        if self._restore:
            self._libc.prctl(self.PR_SET_CHILD_SUBREAPER, 0, 0, 0, 0)
            self._restore = False


def _linux_direct_child_pids() -> set[int]:
    children: set[int] = set()
    proc = Path("/proc")
    try:
        entries = list(proc.iterdir())
    except OSError as error:
        raise TargetRunError("unable to enumerate /proc for target containment") from error
    parent_pid = os.getpid()
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            text = (entry / "stat").read_text(encoding="utf-8")
            end = text.rfind(")")
            if end < 0:
                continue
            fields = text[end + 2 :].split()
            if len(fields) >= 2 and int(fields[1]) == parent_pid:
                children.add(int(entry.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, OSError):
            continue
    return children


def _reap_linux_child(pid: int) -> None:
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, ProcessLookupError, OSError):
        pass


def _terminate_linux_adopted_children(baseline_children: set[int]) -> None:
    def live_children() -> set[int]:
        return _linux_direct_child_pids() - baseline_children

    deadline = time.monotonic() + 2
    while True:
        current = live_children()
        if not current:
            return
        for pid in current:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for pid in current:
            _reap_linux_child(pid)
        if time.monotonic() >= deadline:
            break
        time.sleep(0.01)

    deadline = time.monotonic() + 2
    while True:
        current = live_children()
        if not current:
            return
        for pid in current:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for pid in current:
            _reap_linux_child(pid)
        if time.monotonic() >= deadline:
            raise TargetRunError("detached target descendants survived bounded Linux teardown")
        time.sleep(0.01)


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _wait_for_process_group_exit(process_group_id: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while _process_group_exists(process_group_id) and time.monotonic() < deadline:
        time.sleep(0.01)
    return not _process_group_exists(process_group_id)


def _terminate_process(
    process: subprocess.Popen[Any],
    *,
    process_group_id: int | None = None,
    windows_job: _WindowsJob | None = None,
) -> None:
    """Stop the process and any launcher descendants, including after parent exit."""
    if windows_job is not None:
        windows_job.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return

    if os.name == "posix" and process_group_id is not None:
        if _process_group_exists(process_group_id):
            try:
                os.killpg(process_group_id, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        if not _wait_for_process_group_exit(process_group_id, 2):
            try:
                os.killpg(process_group_id, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
            _wait_for_process_group_exit(process_group_id, 2)
        return

    try:
        process.terminate()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _drain_process_output(stream: Any, result: list[Any]) -> None:
    observed = 0
    truncated = False
    try:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            if observed + len(chunk) > MAX_PROCESS_OUTPUT_BYTES:
                truncated = True
            observed = min(MAX_PROCESS_OUTPUT_BYTES, observed + len(chunk))
    except OSError:
        pass
    result[:] = [observed, truncated]


def _execute_command(
    argv: Sequence[str],
    workdir: Path,
    timeout_seconds: int,
    *,
    require_detached_containment: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    process: subprocess.Popen[Any] | None = None
    process_group_id: int | None = None
    windows_job: _WindowsJob | None = None
    linux_subreaper: _LinuxSubreaper | None = None
    linux_baseline_children: set[int] = set()
    launch_failed = False
    timed_out = False
    stdout_count = [0, False]
    stderr_count = [0, False]
    output_threads: list[threading.Thread] = []
    try:
        if (
            require_detached_containment
            and os.name == "posix"
            and not sys.platform.startswith("linux")
        ):
            raise TargetRunError(
                "bounded target execution on POSIX requires Linux subreaper containment"
            )
        if os.name not in {"posix", "nt"}:
            raise TargetRunError(f"unsupported process-tree control platform: {os.name}")
        kwargs: dict[str, Any] = {
            "cwd": workdir,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
            "close_fds": True,
        }
        if os.name == "posix":
            if require_detached_containment:
                try:
                    linux_subreaper = _LinuxSubreaper()
                    linux_baseline_children = _linux_direct_child_pids()
                except OSError as error:
                    raise TargetRunError("unable to establish Linux subreaper containment") from error
            kwargs["start_new_session"] = True
        else:
            windows_job = _WindowsJob()
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | _WindowsJob.CREATE_SUSPENDED
            )
        try:
            process = subprocess.Popen(list(argv), **kwargs)
        except OSError:
            launch_failed = True
        if process is not None:
            if os.name == "posix":
                process_group_id = process.pid
            elif windows_job is not None:
                try:
                    windows_job.assign_and_resume(process)
                except OSError as error:
                    raise TargetRunError(
                        "unable to contain target process in a Windows Job Object"
                    ) from error
            for stream, count in (
                (process.stdout, stdout_count),
                (process.stderr, stderr_count),
            ):
                if stream is not None:
                    thread = threading.Thread(
                        target=_drain_process_output,
                        args=(stream, count),
                        daemon=True,
                    )
                    thread.start()
                    output_threads.append(thread)
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        active_exception = sys.exc_info()[0] is not None
        cleanup_error: BaseException | None = None
        if process is not None:
            try:
                _terminate_process(
                    process,
                    process_group_id=process_group_id,
                    windows_job=windows_job,
                )
            except BaseException as error:
                cleanup_error = error
        if linux_subreaper is not None:
            try:
                _terminate_linux_adopted_children(linux_baseline_children)
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
        elapsed = round(max(0.0, time.monotonic() - started), 3)
        for thread in output_threads:
            thread.join(timeout=2)
        if process is not None:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
        if windows_job is not None:
            windows_job.close()
        if linux_subreaper is not None:
            linux_subreaper.close()
        if cleanup_error is not None and not active_exception:
            raise cleanup_error
    return {
        "exit_code": None if process is None else process.returncode,
        "launch_failed": launch_failed,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed,
        "stdout_bytes": stdout_count[0],
        "stderr_bytes": stderr_count[0],
        "stdout_truncated": stdout_count[1],
        "stderr_truncated": stderr_count[1],
        "process_tree_control": "posix-process-group" if os.name == "posix" else "windows-job-object",
    }


def _evaluate_oracle(
    scenario: Mapping[str, Any], workdir: Path, execution: Mapping[str, Any]
) -> dict[str, Any]:
    oracle = scenario["oracle"]
    result: dict[str, Any] = {
        "kind": oracle["kind"],
        "state": "not_evaluated" if execution["launch_failed"] else "unknown",
        "expected_exit_code": oracle["expected_exit_code"] if oracle["kind"] == "process-exit" else None,
        "observed_exit_code": execution["exit_code"],
        "expected_sha256": oracle["sha256"] if oracle["kind"] == "file-sha256" else None,
        "observed_sha256": None,
        "observed_size_bytes": None,
    }
    if execution["launch_failed"] or execution["timed_out"]:
        return result
    if oracle["kind"] == "process-exit":
        result["state"] = "passed" if execution["exit_code"] == oracle["expected_exit_code"] else "failed"
        return result

    try:
        path = _resolve_work_file(workdir, oracle["path"])
        observed_sha256, observed_size = _sha256_file(
            path,
            maximum=MAX_ORACLE_BYTES,
            label="oracle file",
        )
    except TargetRunError:
        return result
    result["observed_sha256"] = observed_sha256
    result["observed_size_bytes"] = observed_size
    result["state"] = "passed" if observed_sha256 == oracle["sha256"] else "failed"
    return result


def _termination_state(execution: Mapping[str, Any], oracle: Mapping[str, Any]) -> str:
    if execution["launch_failed"]:
        return "launch_failed"
    if execution["timed_out"]:
        return "timed_out"
    if oracle["kind"] == "process-exit":
        return "completed" if oracle["state"] == "passed" else "exit_nonzero"
    if execution["exit_code"] not in (0, None):
        return "exit_nonzero"
    if oracle["state"] == "failed":
        return "oracle_failed"
    if oracle["state"] == "unknown":
        return "oracle_unknown"
    return "completed"


def _validate_run_schema(manifest: Mapping[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ModuleNotFoundError as error:
        raise TargetRunError("jsonschema==4.25.1 is required for target-run validation") from error
    try:
        schema = loads_strict(RUN_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest),
            key=lambda item: tuple(str(token) for token in item.absolute_path),
        )
    except (OSError, TargetRunError) as error:
        raise TargetRunError(f"unable to load target-run schema: {error}") from error
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(token) for token in first.absolute_path)
        raise TargetRunError(f"target-run schema validation failed at {location}: {first.message}")


def validate_run_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate one produced run manifest against the published schema."""
    if not isinstance(manifest, Mapping):
        raise TargetRunError("target-run manifest must be an object")
    _validate_run_schema(manifest)


def _write_zip_atomic(output: Path, entries: Mapping[str, bytes]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{output.name}.", dir=output.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in sorted(entries.items()):
                if not name or name.startswith("/") or ".." in Path(name).parts:
                    raise TargetRunError("unsafe ZIP entry name")
                archive.writestr(name, payload)
        os.replace(temporary, output)
        temporary = None
    except OSError as error:
        raise TargetRunError(f"unable to write run artifact {output}") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


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
    """Run and package one bounded target-machine experiment."""
    if re.fullmatch(r"[0-9a-f]{64}", emulator_binary_sha256) is None:
        raise TargetRunError("emulator_binary_sha256 must be a lowercase 64-character digest")
    _require_string(source_repository, "source_repository", maximum=256)
    _require_git_sha(source_commit, "source_commit")
    _require_git_sha(source_tree, "source_tree")
    _require_attestable_emulator_config(emulator_config_path)
    normalized_patches = _normalize_patch_commits(patch_commits)
    if (
        source_repository != PINNED_SOURCE_REPOSITORY
        or source_commit != PINNED_SOURCE_COMMIT
        or source_tree != PINNED_SOURCE_TREE
    ):
        raise TargetRunError(
            "emulator source does not match the pinned BB-BL1 baseline; update BB-BL1 first"
        )

    target_root_resolved = _resolve_directory(target_root, "target_root")
    workdir_resolved = _resolve_directory(working_directory, "working_directory")
    if target_root_resolved == workdir_resolved or _is_under(workdir_resolved, target_root_resolved) or _is_under(target_root_resolved, workdir_resolved):
        raise TargetRunError("target_root and working_directory must be separate trees")
    output_resolved = output_path.resolve()
    if _is_under(output_resolved, target_root_resolved) or _is_under(output_resolved, workdir_resolved):
        raise TargetRunError("output artifact must be outside target_root and working_directory")

    target_raw, target_manifest = _load_target_manifest(target_manifest_path)
    safe_target_raw = _package_target_manifest(target_manifest)
    scenario_raw, scenario = _load_json_file(
        scenario_path, maximum=MAX_INPUT_BYTES, label="scenario"
    )
    if not isinstance(scenario, Mapping):
        raise TargetRunError("scenario must be a JSON object")
    validate_scenario(scenario)
    scenario_input_sha256 = _sha256_bytes(scenario_raw)
    safe_scenario = _safe_scenario_for_package(scenario, scenario_input_sha256)
    safe_scenario_raw = _json_bytes(safe_scenario)
    command_raw, command = _load_json_file(
        command_path, maximum=MAX_COMMAND_BYTES, label="command file"
    )
    if not isinstance(command, Mapping):
        raise TargetRunError("command must be a JSON object")
    validate_command(command)
    _preflight_declared_outputs(scenario, workdir_resolved)

    app_root, target_eboot = _verify_target_root(target_root_resolved, target_manifest)
    _bind_command_target(command, workdir_resolved, app_root, target_eboot)

    binary_resolved = emulator_binary_path.resolve()
    command_binary = Path(command["argv"][0])
    if not command_binary.is_absolute():
        command_binary = workdir_resolved / command_binary
    if command_binary.resolve() != binary_resolved:
        raise TargetRunError("command emulator_binary_index does not identify emulator_binary")
    actual_binary_sha256, binary_size = _sha256_file(
        binary_resolved, label="emulator binary"
    )
    expected_binary_sha256 = f"sha256:{emulator_binary_sha256}"
    if actual_binary_sha256 != expected_binary_sha256:
        raise TargetRunError(
            f"emulator binary digest mismatch: actual={actual_binary_sha256} expected={expected_binary_sha256}"
        )

    try:
        host_manifest = collect_host_environment.collect_manifest(
            graphics_backend=graphics_backend,
            emulator_config_path=None,
        )
    except Exception as error:
        raise TargetRunError(f"host environment collection failed: {error}") from error
    collect_host_environment.validate_manifest(host_manifest)
    host_raw = _json_bytes(host_manifest)

    execution = _execute_command(
        command["argv"],
        workdir_resolved,
        scenario["timeout_seconds"],
        require_detached_containment=True,
    )
    oracle = _evaluate_oracle(scenario, workdir_resolved, execution)
    artifacts, embedded, packaging_warnings = _collect_artifacts(scenario, workdir_resolved)

    run_manifest: dict[str, Any] = {
        "manifest_kind": RUN_SCHEMA_ID,
        "schema_version": RUN_SCHEMA_VERSION,
        "provenance": {
            "captured_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "producer": {"name": RUNNER_NAME, "version": RUNNER_VERSION},
        },
        "route": "gated-target-machine",
        "target": {
            "manifest_sha256": _sha256_bytes(target_raw),
            "manifest_size_bytes": len(target_raw),
            "packaged_manifest_sha256": _sha256_bytes(safe_target_raw),
            "packaged_manifest_size_bytes": len(safe_target_raw),
            "identity_state": target_manifest["identity_completeness"]["state"],
        },
        "host_environment": {
            "manifest_sha256": _sha256_bytes(host_raw),
            "manifest_size_bytes": len(host_raw),
            "unknown_field_count": len(host_manifest["unknown_fields"]),
            "warning_count": len(host_manifest["collection_warnings"]),
        },
        "emulator": {
            "source": {
                "repository": source_repository,
                "commit": source_commit,
                "tree": source_tree,
                "patch_commits": normalized_patches,
            },
            "binary": {"sha256": actual_binary_sha256, "size_bytes": binary_size},
            "config_sha256": host_manifest["run"]["emulator_config"]["sha256"],
            "graphics_backend": host_manifest["run"]["graphics_backend"],
        },
        "scenario": {
            "id": safe_scenario["scenario_id"],
            "input_sha256": scenario_input_sha256,
            "input_size_bytes": len(scenario_raw),
            "packaged_sha256": _sha256_bytes(safe_scenario_raw),
            "packaged_size_bytes": len(safe_scenario_raw),
            "timeout_seconds": scenario["timeout_seconds"],
            "oracle_kind": scenario["oracle"]["kind"],
        },
        "execution": {
            "working_directory_isolated": True,
            "target_root_separate": True,
            "command_argv_sha256": _sha256_bytes(command_raw),
            "raw_process_output_captured": True,
            "declared_outputs_preflighted": True,
            "process_tree_control": execution["process_tree_control"],
        },
        "termination": {
            "state": _termination_state(execution, oracle),
            "exit_code": execution["exit_code"],
            "elapsed_seconds": execution["elapsed_seconds"],
            "stdout_bytes": execution["stdout_bytes"],
            "stderr_bytes": execution["stderr_bytes"],
            "stdout_truncated": execution["stdout_truncated"],
            "stderr_truncated": execution["stderr_truncated"],
        },
        "oracle": oracle,
        "artifacts": artifacts,
        "packaging": {
            "state": "complete" if not packaging_warnings else "partial",
            "warnings": packaging_warnings,
        },
        "redaction": {
            "policy": "allowlist-v3",
            "raw_process_output": "excluded",
            "target_paths": "excluded",
            "command_file": "excluded",
            "warnings": ["raw-process-output-excluded"],
        },
    }
    validate_run_manifest(run_manifest)

    package_entries = {
        "run-manifest.json": _json_bytes(run_manifest),
        "target-manifest.json": safe_target_raw,
        "host-environment.json": host_raw,
        "scenario.json": safe_scenario_raw,
    }
    package_entries.update(embedded)
    _write_zip_atomic(output_resolved, package_entries)
    return run_manifest


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="run and package one bounded target experiment")
    run.add_argument("--target-manifest", type=Path, required=True)
    run.add_argument("--scenario", type=Path, required=True)
    run.add_argument("--command-file", type=Path, required=True)
    run.add_argument("--emulator-binary", type=Path, required=True)
    run.add_argument("--emulator-binary-sha256", required=True)
    run.add_argument("--source-repository", required=True)
    run.add_argument("--source-commit", required=True)
    run.add_argument("--source-tree", required=True)
    run.add_argument("--patch-commit", action="append", default=[])
    run.add_argument("--target-root", type=Path, required=True)
    run.add_argument("--working-directory", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--backend")
    run.add_argument("--emulator-config", type=Path)

    validate = subparsers.add_parser("validate", help="validate a run manifest")
    validate.add_argument("manifest", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "validate":
            raw = _read_bytes(args.manifest, maximum=MAX_INPUT_BYTES, label="run manifest")
            manifest = loads_strict(raw.decode("utf-8"))
            validate_run_manifest(manifest)
            print("valid")
            return 0
        manifest = run_experiment(
            target_manifest_path=args.target_manifest,
            scenario_path=args.scenario,
            command_path=args.command_file,
            emulator_binary_path=args.emulator_binary,
            emulator_binary_sha256=args.emulator_binary_sha256,
            source_repository=args.source_repository,
            source_commit=args.source_commit,
            source_tree=args.source_tree,
            patch_commits=args.patch_commit,
            target_root=args.target_root,
            working_directory=args.working_directory,
            output_path=args.output,
            graphics_backend=args.backend,
            emulator_config_path=args.emulator_config,
        )
        print(
            f"{manifest['termination']['state']} "
            f"oracle={manifest['oracle']['state']} "
            f"packaging={manifest['packaging']['state']}"
        )
        return 0 if manifest["termination"]["state"] == "completed" and manifest["packaging"]["state"] == "complete" else 1
    except (TargetRunError, UnicodeDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
