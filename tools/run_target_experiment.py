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
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools import bloodborne_target_manifest
from tools import collect_host_environment


RUN_SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "target-run.schema.json"
RUN_SCHEMA_ID = "bb-target-run"
RUN_SCHEMA_VERSION = 1
SCENARIO_SCHEMA_ID = "bb-target-scenario/v1"
COMMAND_SCHEMA_ID = "bb-target-command/v1"
RUNNER_NAME = "bb-target-runner"
RUNNER_VERSION = "1.0.0"
PINNED_SOURCE_REPOSITORY = "https://github.com/shadps4-emu/shadPS4"
PINNED_SOURCE_COMMIT = "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64"
PINNED_SOURCE_TREE = "e6026c14092b01702d4e49a5ac6c2f779a072dfe"
MAX_INPUT_BYTES = 1024 * 1024
MAX_COMMAND_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_REDACTED_JSON_BYTES = 1024 * 1024
MAX_ORACLE_BYTES = 16 * 1024 * 1024
MAX_PROCESS_OUTPUT_BYTES = 16 * 1024 * 1024


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


def loads_strict(text: str) -> Any:
    """Parse JSON without accepting duplicate members or non-finite values."""
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
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
    if scenario["schema_id"] != SCENARIO_SCHEMA_ID or scenario["schema_version"] != 1:
        raise TargetRunError("unsupported target scenario schema")
    scenario_id = _require_string(scenario["scenario_id"], "scenario.scenario_id", maximum=64)
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", scenario_id) is None:
        raise TargetRunError("scenario.scenario_id is not a stable identifier")
    _require_string(scenario["description"], "scenario.description", maximum=512)
    _require_integer(scenario["timeout_seconds"], "scenario.timeout_seconds", minimum=1, maximum=86400)

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
        _require_exact_keys(artifact, {"path", "name", "mode", "max_bytes"}, field)
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
    """Validate an argv-only command file; shell/environment injection is not supported."""
    _require_exact_keys(command, {"schema_id", "schema_version", "argv", "emulator_binary_index"}, "command")
    if command["schema_id"] != COMMAND_SCHEMA_ID or command["schema_version"] != 1:
        raise TargetRunError("unsupported target command schema")
    argv = command["argv"]
    if not isinstance(argv, list) or not 1 <= len(argv) <= 128:
        raise TargetRunError("command.argv must contain 1-128 arguments")
    for index, argument in enumerate(argv):
        _require_string(argument, f"command.argv[{index}]", maximum=4096)
    _require_integer(
        command["emulator_binary_index"],
        "command.emulator_binary_index",
        minimum=0,
        maximum=len(argv) - 1,
    )


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


def _redact_json_artifact(path: Path, *, maximum: int) -> bytes:
    raw = _read_bytes(path, maximum=maximum, label="JSON artifact")
    try:
        value = loads_strict(raw.decode("utf-8"))
    except (UnicodeDecodeError, TargetRunError) as error:
        raise TargetRunError("JSON artifact is not strict UTF-8 JSON") from error
    return _json_bytes(_redact_json(value))


def _collect_artifacts(
    scenario: Mapping[str, Any], workdir: Path
) -> tuple[list[dict[str, Any]], dict[str, bytes], list[str]]:
    entries: list[dict[str, Any]] = []
    embedded: dict[str, bytes] = {}
    warnings: list[str] = []
    for artifact in scenario["artifacts"]:
        name = artifact["name"]
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
                    "packaged_path": None,
                }
            )
            continue

        try:
            redacted = _redact_json_artifact(path, maximum=artifact["max_bytes"])
        except TargetRunError:
            warnings.append("artifact-redaction-failed")
            entries.append(
                {
                    "name": name,
                    "status": "rejected",
                    "source_sha256": source_sha256,
                    "source_size_bytes": source_size,
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
                "packaged_path": packaged_path,
            }
        )
    return entries, embedded, sorted(set(warnings))


def _terminate_process(process: subprocess.Popen[Any]) -> None:
    if os.name == "posix":
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
    else:
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
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


def _execute_command(argv: Sequence[str], workdir: Path, timeout_seconds: int) -> dict[str, Any]:
    started = time.monotonic()
    process: subprocess.Popen[Any] | None = None
    launch_failed = False
    timed_out = False
    stdout_count = [0, False]
    stderr_count = [0, False]
    output_threads: list[threading.Thread] = []
    try:
        kwargs: dict[str, Any] = {
            "cwd": workdir,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
            "close_fds": True,
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True
        else:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            process = subprocess.Popen(list(argv), **kwargs)
        except OSError:
            launch_failed = True
        if process is not None:
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
                _terminate_process(process)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
    finally:
        elapsed = round(max(0.0, time.monotonic() - started), 3)
        for thread in output_threads:
            thread.join(timeout=2)
        if process is not None:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
    return {
        "exit_code": None if process is None else process.returncode,
        "launch_failed": launch_failed,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed,
        "stdout_bytes": stdout_count[0],
        "stderr_bytes": stderr_count[0],
        "stdout_truncated": stdout_count[1],
        "stderr_truncated": stderr_count[1],
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
    normalized_patches = [_require_git_sha(value, "patch_commit") for value in patch_commits]
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
    scenario_raw, scenario = _load_json_file(
        scenario_path, maximum=MAX_INPUT_BYTES, label="scenario"
    )
    if not isinstance(scenario, Mapping):
        raise TargetRunError("scenario must be a JSON object")
    validate_scenario(scenario)
    command_raw, command = _load_json_file(
        command_path, maximum=MAX_COMMAND_BYTES, label="command file"
    )
    if not isinstance(command, Mapping):
        raise TargetRunError("command must be a JSON object")
    validate_command(command)

    binary_resolved = emulator_binary_path.resolve()
    command_binary = Path(command["argv"][command["emulator_binary_index"]])
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
            emulator_config_path=emulator_config_path,
        )
    except Exception as error:
        raise TargetRunError(f"host environment collection failed: {error}") from error
    collect_host_environment.validate_manifest(host_manifest)
    host_raw = _json_bytes(host_manifest)

    execution = _execute_command(
        command["argv"],
        workdir_resolved,
        scenario["timeout_seconds"],
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
            "id": scenario["scenario_id"],
            "input_sha256": _sha256_bytes(scenario_raw),
            "input_size_bytes": len(scenario_raw),
            "timeout_seconds": scenario["timeout_seconds"],
            "oracle_kind": scenario["oracle"]["kind"],
        },
        "execution": {
            "working_directory_isolated": True,
            "target_root_separate": True,
            "command_argv_sha256": _sha256_bytes(command_raw),
            "raw_process_output_captured": True,
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
            "policy": "allowlist-v1",
            "raw_process_output": "excluded",
            "target_paths": "excluded",
            "command_file": "excluded",
            "warnings": ["raw-process-output-excluded"],
        },
    }
    validate_run_manifest(run_manifest)

    package_entries = {
        "run-manifest.json": _json_bytes(run_manifest),
        "target-manifest.json": target_raw,
        "host-environment.json": host_raw,
        "scenario.json": scenario_raw,
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
