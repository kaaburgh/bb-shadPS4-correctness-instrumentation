#!/usr/bin/env python3
"""Hardened BB-ENV1 target-run entrypoint.

The previous v3 implementation is retained as an internal compatibility library in
``tools.run_target_experiment_v3``. This entrypoint adds evidence gates while
preserving the published v3 run-record shape for detached consumers.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
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

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import run_target_experiment_v3 as _legacy


for _export_name in dir(_legacy):
    if not _export_name.startswith("__"):
        globals()[_export_name] = getattr(_legacy, _export_name)

_LEGACY_PACKAGE_TARGET_MANIFEST = _legacy._package_target_manifest
_LEGACY_RUN_EXPERIMENT = _legacy.run_experiment

RUNNER_VERSION = "1.10.0"
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


def _package_target_manifest(manifest: Mapping[str, Any]) -> bytes:
    packaged = _legacy.loads_strict(_LEGACY_PACKAGE_TARGET_MANIFEST(manifest).decode("utf-8"))
    packaged_dlc: dict[str, Any] = {}
    for identifier, component in sorted(manifest["content"]["dlc"].items()):
        safe_identifier = "dlc-sha256-" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        source_package = component["source_package"]
        packaged_dlc[safe_identifier] = {
            "version": None,
            "source_package": None if source_package is None else _legacy._copy_exact_artifact(source_package),
        }
    packaged["content"]["dlc"] = packaged_dlc
    try:
        _legacy.bloodborne_target_manifest.validate_manifest(packaged)
    except Exception as error:
        raise TargetRunError(f"safe target-manifest projection is invalid: {error}") from error
    return _legacy._json_bytes(packaged)


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
        raise TargetRunError("unable to stage emulator binary for immutable execution") from error
    _require_regular_unlinked_file(destination, "staged emulator binary")
    return destination


def _write_snapshot(path: Path, payload: bytes, label: str) -> None:
    try:
        path.write_bytes(payload)
    except OSError as error:
        raise TargetRunError(f"unable to stage {label} snapshot") from error


def _sha256_fd(fd: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    duplicate = os.dup(fd)
    try:
        os.lseek(duplicate, 0, os.SEEK_SET)
        while True:
            chunk = os.read(duplicate, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    finally:
        os.close(duplicate)
    return f"sha256:{digest.hexdigest()}", size


def _create_linux_executable_memfd() -> int:
    """Create an executable memfd, falling back only for kernels predating MFD_EXEC."""
    memfd_create = getattr(os, "memfd_create", None)
    if memfd_create is None:
        raise TargetRunError("Linux executable sealing requires memfd_create")
    base_flags = getattr(os, "MFD_CLOEXEC", 0x0001) | getattr(os, "MFD_ALLOW_SEALING", 0x0002)
    exec_flag = getattr(os, "MFD_EXEC", 0x0010)
    try:
        return memfd_create("bb-shadps4-executable", flags=base_flags | exec_flag)
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EPERM}:
            raise TargetRunError(
                "Linux host policy blocks executable memfds; vm.memfd_noexec=2 is incompatible with non-synthetic BB-ENV1 execution"
            ) from error
        if error.errno != errno.EINVAL:
            raise TargetRunError("unable to create executable Linux memfd") from error
    try:
        return memfd_create("bb-shadps4-executable", flags=base_flags)
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EPERM}:
            raise TargetRunError(
                "Linux host policy blocks executable memfds; vm.memfd_noexec policy is incompatible with non-synthetic BB-ENV1 execution"
            ) from error
        raise TargetRunError("unable to create Linux memfd on the legacy-kernel compatibility path") from error


def _sealed_linux_executable(path: Path) -> int:
    """Copy an executable into a write-sealed anonymous file and return its fd."""
    try:
        import fcntl
    except ImportError as error:
        raise TargetRunError("Linux executable sealing requires fcntl") from error
    fd = _create_linux_executable_memfd()
    try:
        with path.open("rb", buffering=0) as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("short write while staging sealed executable")
                    view = view[written:]
        try:
            os.fchmod(fd, 0o500)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EPERM}:
                raise TargetRunError(
                    "Linux host policy prevents executable memfds; check vm.memfd_noexec before non-synthetic BB-ENV1 execution"
                ) from error
            raise
        seals = (
            fcntl.F_SEAL_WRITE
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_SEAL
        )
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
        applied = fcntl.fcntl(fd, fcntl.F_GET_SEALS)
        if applied & seals != seals:
            raise TargetRunError("Linux executable memfd did not retain all required seals")
        return fd
    except BaseException:
        os.close(fd)
        raise


class _ExecutableLease:
    """Hold identity-stable executable bytes through the entire launch window."""

    def __init__(self, path: Path, pinned: Mapping[str, Any], supplied_sha256: str) -> None:
        self.path = path
        self.pass_fds: tuple[int, ...] = ()
        self.execution_path = path
        self._fd: int | None = None
        self._windows_handle: Any = None
        if sys.platform.startswith("linux"):
            self._fd = _sealed_linux_executable(path)
            actual_sha256, actual_size = _sha256_fd(self._fd)
            self.execution_path = Path(f"/proc/self/fd/{self._fd}")
            self.pass_fds = (self._fd,)
        elif os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateFileW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            kernel32.CreateFileW.restype = wintypes.HANDLE
            handle = kernel32.CreateFileW(
                str(path),
                0x80000000,
                0x00000001,
                None,
                3,
                0x00000080,
                None,
            )
            invalid = wintypes.HANDLE(-1).value
            if handle in (None, 0, invalid):
                raise TargetRunError("unable to lock staged emulator binary against replacement")
            self._windows_handle = (kernel32, handle)
            actual_sha256, actual_size = _legacy._sha256_file(path, label="locked staged emulator binary")
        else:
            raise TargetRunError("immutable executable lease is unsupported on this host")

        expected = pinned["binary_sha256"]
        if actual_sha256 != expected or actual_size != pinned["binary_size_bytes"] or supplied_sha256 != expected:
            self.close()
            raise TargetRunError("staged executable lease does not match the pinned upstream build artifact")

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if self._windows_handle is not None:
            kernel32, handle = self._windows_handle
            kernel32.CloseHandle(handle)
            self._windows_handle = None

    def __enter__(self) -> "_ExecutableLease":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def _execute_command_with_pass_fds(
    argv: Sequence[str],
    workdir: Path,
    timeout_seconds: int,
    *,
    require_detached_containment: bool = False,
    pass_fds: Sequence[int] = (),
) -> dict[str, Any]:
    """v3 execution semantics plus inherited verified executable descriptors on Linux."""
    started = time.monotonic()
    process: subprocess.Popen[Any] | None = None
    process_group_id: int | None = None
    windows_job: Any = None
    linux_subreaper: Any = None
    linux_baseline_children: set[int] = set()
    launch_failed = False
    timed_out = False
    stdout_count = [0, False]
    stderr_count = [0, False]
    output_threads: list[threading.Thread] = []
    try:
        if require_detached_containment and os.name == "posix" and not sys.platform.startswith("linux"):
            raise TargetRunError("bounded target execution on POSIX requires Linux subreaper containment")
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
            kwargs["pass_fds"] = tuple(pass_fds)
            if require_detached_containment:
                try:
                    linux_subreaper = _legacy._LinuxSubreaper()
                    linux_baseline_children = _legacy._linux_direct_child_pids()
                except OSError as error:
                    raise TargetRunError("unable to establish Linux subreaper containment") from error
            kwargs["start_new_session"] = True
        else:
            if pass_fds:
                raise TargetRunError("descriptor-based executable launch is unsupported on Windows")
            windows_job = _legacy._WindowsJob()
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | _legacy._WindowsJob.CREATE_SUSPENDED
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
                    raise TargetRunError("unable to contain target process in a Windows Job Object") from error
            for stream, count in ((process.stdout, stdout_count), (process.stderr, stderr_count)):
                if stream is not None:
                    thread = threading.Thread(target=_legacy._drain_process_output, args=(stream, count), daemon=True)
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
                _legacy._terminate_process(process, process_group_id=process_group_id, windows_job=windows_job)
            except BaseException as error:
                cleanup_error = error
        if linux_subreaper is not None:
            try:
                _legacy._terminate_linux_adopted_children(linux_baseline_children)
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


def _restore_original_command_identity(
    output_path: Path,
    run_manifest: dict[str, Any],
    original_command_raw: bytes,
) -> dict[str, Any]:
    """Bind the detached record to the stable operator command, not the staging pathname."""
    run_manifest["execution"]["command_argv_sha256"] = _legacy._sha256_bytes(original_command_raw)
    _legacy.validate_run_manifest(run_manifest)
    if not output_path.exists():
        return run_manifest
    try:
        with zipfile.ZipFile(output_path, "r") as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
    except (OSError, zipfile.BadZipFile) as error:
        raise TargetRunError("unable to reopen run artifact for stable command identity") from error
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

    with tempfile.TemporaryDirectory(prefix="bb-target-run-snapshot-") as directory:
        snapshot_root = Path(directory)
        staged_target = snapshot_root / "target-manifest.json"
        staged_scenario = snapshot_root / "scenario.json"
        staged_command_path = snapshot_root / "command.json"
        _write_snapshot(staged_target, target_raw, "target manifest")
        _write_snapshot(staged_scenario, scenario_raw, "scenario")
        _write_snapshot(staged_command_path, command_raw, "command")

        staged_emulator_path = emulator_binary_path
        lease: _ExecutableLease | None = None
        original_execute_command = _legacy._execute_command
        try:
            if not synthetic_control:
                original_binary = _resolve_command_binary(command, working_directory_resolved, emulator_binary_path)
                source_info = _require_regular_unlinked_file(original_binary, "emulator binary")
                pinned = _pinned_build_for_host()
                staged_emulator_path = snapshot_root / str(pinned["binary_name"])
                _stage_emulator_binary(original_binary, staged_emulator_path, source_info)
                _require_non_synthetic_evidence_contract(
                    target_manifest, scenario, staged_emulator_path, emulator_binary_sha256
                )
                lease = _ExecutableLease(
                    staged_emulator_path,
                    pinned,
                    f"sha256:{emulator_binary_sha256}",
                )
                staged_command = dict(command)
                staged_argv = list(command["argv"])
                staged_argv[0] = str(lease.execution_path)
                staged_command["argv"] = staged_argv
                _write_snapshot(staged_command_path, _legacy._json_bytes(staged_command), "command")
                if lease.pass_fds:
                    def leased_execute(
                        argv: Sequence[str],
                        workdir: Path,
                        timeout_seconds: int,
                        *,
                        require_detached_containment: bool = False,
                    ) -> dict[str, Any]:
                        return _execute_command_with_pass_fds(
                            argv,
                            workdir,
                            timeout_seconds,
                            require_detached_containment=require_detached_containment,
                            pass_fds=lease.pass_fds if lease is not None else (),
                        )
                    _legacy._execute_command = leased_execute
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
            return _restore_original_command_identity(output_path.resolve(), manifest, command_raw)
        finally:
            _legacy._execute_command = original_execute_command
            if lease is not None:
                lease.close()


_legacy._package_target_manifest = _package_target_manifest
_legacy.run_experiment = run_experiment

globals()["RUNNER_VERSION"] = RUNNER_VERSION
globals()["_package_target_manifest"] = _package_target_manifest
globals()["run_experiment"] = run_experiment
main = _legacy.main


if __name__ == "__main__":
    raise SystemExit(main())
