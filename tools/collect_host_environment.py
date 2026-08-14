#!/usr/bin/env python3
"""Collect a privacy-bounded host/run environment manifest.

The collector intentionally records only allowlisted facts.  In particular, it
does not serialize host names, user names, paths, command lines, environment
variables, network identifiers, hardware serial numbers, or configuration
contents.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SCHEMA_ID = "bb-host-environment/v1"
SCHEMA_VERSION = 1
COLLECTOR_NAME = "bb-host-environment"
COLLECTOR_VERSION = "1.0.0"
MAX_GPU_COUNT = 16
COMMAND_TIMEOUT_SECONDS = 10
MAX_CONFIG_BYTES = 16 * 1024 * 1024

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class CollectionInputError(ValueError):
    """Raised when an explicit operator input cannot be represented safely."""


def _run_command(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "check": False,
        "text": True,
        "timeout": COMMAND_TIMEOUT_SECONDS,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(list(argv), **kwargs)


def _read_key_value_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key.strip()] = value
    return result


def _bounded_string(value: Any, limit: int = 256) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized[:limit] if normalized else None


def _canonical_architecture(machine: str) -> str | None:
    value = machine.strip().lower()
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86-64": "x86_64",
        "i386": "x86",
        "i486": "x86",
        "i586": "x86",
        "i686": "x86",
        "arm64": "aarch64",
    }
    return aliases.get(value, value or None)


def _collect_os(system: str) -> dict[str, Any]:
    family = {
        "windows": "windows",
        "linux": "linux",
        "darwin": "macos",
    }.get(system.lower(), system.lower() or None)
    name: str | None = _bounded_string(system)
    version: str | None = None
    build: str | None = None

    if family == "windows":
        release, win_version, _csd, _ptype = platform.win32_ver()
        name = "Windows"
        version = _bounded_string(win_version or release)
        build = _bounded_string(platform.version())
    elif family == "linux":
        os_release = _read_key_value_file(Path("/etc/os-release"))
        name = _bounded_string(os_release.get("NAME")) or "Linux"
        version = _bounded_string(os_release.get("VERSION_ID"))
        build = _bounded_string(os_release.get("BUILD_ID"))
    elif family == "macos":
        mac_version, _version_info, _machine = platform.mac_ver()
        name = "macOS"
        version = _bounded_string(mac_version)

    return {
        "family": family,
        "name": name,
        "version": version,
        "build": build,
        "kernel": _bounded_string(platform.release()),
    }


def _cpu_from_proc() -> tuple[str | None, str | None]:
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            break
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = value.strip()
    vendor = fields.get("vendor_id") or fields.get("cpu implementer")
    model = fields.get("model name") or fields.get("hardware") or fields.get("processor")
    return _bounded_string(vendor), _bounded_string(model)


def _sysctl_value(name: str, runner: CommandRunner) -> str | None:
    try:
        result = runner(["sysctl", "-n", name])
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return _bounded_string(result.stdout)


def _collect_cpu(system: str, environ: Mapping[str, str], runner: CommandRunner) -> dict[str, Any]:
    vendor: str | None = None
    model: str | None = None
    if system.lower() == "linux":
        vendor, model = _cpu_from_proc()
    elif system.lower() == "windows":
        script = (
            "Get-CimInstance Win32_Processor | "
            "Select-Object -First 1 Name,Manufacturer | ConvertTo-Json -Compress"
        )
        try:
            result = runner(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script])
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0:
            vendor, model = parse_windows_cpu_json(result.stdout)
    elif system.lower() == "darwin":
        vendor = _sysctl_value("machdep.cpu.vendor", runner)
        model = _sysctl_value("machdep.cpu.brand_string", runner)
        if model is None:
            model = _sysctl_value("hw.model", runner)

    logical_processors = os.cpu_count()
    return {
        "architecture": _canonical_architecture(platform.machine()),
        "vendor": vendor,
        "model": model,
        "logical_processors": (
            logical_processors if logical_processors and logical_processors > 0 else None
        ),
    }


def _physical_memory_bytes(system: str, runner: CommandRunner) -> int | None:
    if system.lower() == "windows":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.length = ctypes.sizeof(MemoryStatusEx)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total_physical)
        except (AttributeError, OSError):
            return None
        return None
    if system.lower() == "darwin":
        value = _sysctl_value("hw.memsize", runner)
        try:
            return int(value) if value else None
        except ValueError:
            return None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        physical_pages = os.sysconf("SC_PHYS_PAGES")
        total = int(page_size) * int(physical_pages)
        return total if total > 0 else None
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _normalize_hex_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"(?:0x)?([0-9a-fA-F]{4})", value)
    return f"0x{match.group(1).lower()}" if match else None


def parse_windows_cpu_json(text: str) -> tuple[str | None, str | None]:
    """Parse allowlisted hardware-backed fields from Win32_Processor JSON."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, None
    rows = payload if isinstance(payload, list) else [payload]
    row = rows[0] if rows and isinstance(rows[0], dict) else {}
    return _bounded_string(row.get("Manufacturer")), _bounded_string(row.get("Name"))


def _parse_windows_gpu_json(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse the allowlisted subset of Win32_VideoController JSON."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [], False
    rows = payload if isinstance(payload, list) else [payload]
    if len(rows) > MAX_GPU_COUNT:
        return [], True
    gpus: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pnp_id = row.get("PNPDeviceID") if isinstance(row.get("PNPDeviceID"), str) else ""
        vendor_match = re.search(r"VEN_([0-9a-fA-F]{4})", pnp_id)
        device_match = re.search(r"DEV_([0-9a-fA-F]{4})", pnp_id)
        gpus.append(
            {
                "name": _bounded_string(row.get("Name")),
                "vendor_id": _normalize_hex_id(vendor_match.group(1)) if vendor_match else None,
                "device_id": _normalize_hex_id(device_match.group(1)) if device_match else None,
                "driver": {
                    "name": None,
                    "version": _bounded_string(row.get("DriverVersion")),
                },
            }
        )
    return gpus, False


def parse_windows_gpu_json(text: str) -> list[dict[str, Any]]:
    return _parse_windows_gpu_json(text)[0]


def _collect_windows_gpus(runner: CommandRunner) -> tuple[list[dict[str, Any]], str | None]:
    script = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,DriverVersion,PNPDeviceID | ConvertTo-Json -Compress"
    )
    try:
        result = runner(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script])
    except (OSError, subprocess.SubprocessError):
        return [], "gpu-query-failed"
    if result.returncode != 0:
        return [], "gpu-query-failed"
    gpus, truncated = _parse_windows_gpu_json(result.stdout)
    if truncated:
        return [], "gpu-inventory-too-many"
    return (gpus, None) if gpus else ([], "gpu-query-empty-or-invalid")


def _collect_linux_gpus(
    sysfs_root: Path = Path("/sys/class/drm"),
) -> tuple[list[dict[str, Any]], str | None]:
    gpus: list[dict[str, Any]] = []
    try:
        cards = sorted(
            path for path in sysfs_root.glob("card*") if re.fullmatch(r"card[0-9]+", path.name)
        )
    except OSError:
        cards = []
    if len(cards) > MAX_GPU_COUNT:
        return [], "gpu-inventory-too-many"
    for card in cards:
        device = card / "device"
        if not device.is_dir():
            continue
        try:
            vendor_text = (device / "vendor").read_text(encoding="ascii", errors="ignore").strip()
        except OSError:
            vendor_text = ""
        try:
            device_text = (device / "device").read_text(encoding="ascii", errors="ignore").strip()
        except OSError:
            device_text = ""
        try:
            driver_name = (device / "driver").resolve(strict=True).name
        except OSError:
            driver_name = None
        gpus.append(
            {
                "name": None,
                "vendor_id": _normalize_hex_id(vendor_text),
                "device_id": _normalize_hex_id(device_text),
                "driver": {"name": _bounded_string(driver_name), "version": None},
            }
        )
    return (gpus, None) if gpus else ([], "gpu-query-empty-or-unavailable")


def _parse_macos_gpu_json(text: str) -> tuple[list[dict[str, Any]], bool]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [], False
    rows = payload.get("SPDisplaysDataType", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return [], False
    if len(rows) > MAX_GPU_COUNT:
        return [], True
    gpus: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        gpus.append(
            {
                "name": _bounded_string(row.get("sppci_model") or row.get("_name")),
                "vendor_id": _normalize_hex_id(row.get("spdisplays_vendor-id")),
                "device_id": _normalize_hex_id(row.get("spdisplays_device-id")),
                "driver": {"name": None, "version": None},
            }
        )
    return gpus, False


def parse_macos_gpu_json(text: str) -> list[dict[str, Any]]:
    return _parse_macos_gpu_json(text)[0]


def _collect_macos_gpus(runner: CommandRunner) -> tuple[list[dict[str, Any]], str | None]:
    try:
        result = runner(["system_profiler", "SPDisplaysDataType", "-json"])
    except (OSError, subprocess.SubprocessError):
        return [], "gpu-query-failed"
    if result.returncode != 0:
        return [], "gpu-query-failed"
    gpus, truncated = _parse_macos_gpu_json(result.stdout)
    if truncated:
        return [], "gpu-inventory-too-many"
    return (gpus, None) if gpus else ([], "gpu-query-empty-or-invalid")


def _gpu_sort_key(gpu: Mapping[str, Any]) -> tuple[str, ...]:
    driver = gpu.get("driver") if isinstance(gpu.get("driver"), dict) else {}
    return tuple(
        str(value or "")
        for value in (
            gpu.get("vendor_id"),
            gpu.get("device_id"),
            gpu.get("name"),
            driver.get("name"),
            driver.get("version"),
        )
    )


def _collect_gpus(system: str, runner: CommandRunner) -> tuple[list[dict[str, Any]], str | None]:
    if system.lower() == "windows":
        return _collect_windows_gpus(runner)
    if system.lower() == "linux":
        return _collect_linux_gpus()
    if system.lower() == "darwin":
        return _collect_macos_gpus(runner)
    return [], "gpu-query-unsupported-os"


def fingerprint_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_CONFIG_BYTES:
            raise CollectionInputError(
                "emulator configuration must be a regular file no larger than 16 MiB"
            )
        bytes_read = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                bytes_read += len(chunk)
                if bytes_read > MAX_CONFIG_BYTES:
                    raise CollectionInputError(
                        "emulator configuration must be a regular file no larger than 16 MiB"
                    )
                digest.update(chunk)
        after = path.stat()
        if (
            bytes_read != before.st_size
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
        ):
            raise CollectionInputError(
                "emulator configuration changed while it was being fingerprinted"
            )
    except CollectionInputError:
        raise
    except OSError as error:
        raise CollectionInputError("unable to hash the supplied emulator configuration") from error
    return f"sha256:{digest.hexdigest()}"


def _normalize_backend(value: str | None) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}", value):
        raise CollectionInputError("backend must be a 1-64 character semantic identifier")
    return value.lower()


def _lookup_pointer(document: Mapping[str, Any], pointer: str) -> Any:
    current: Any = document
    for token in pointer.lstrip("/").split("/"):
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def _unknown_fields(manifest: Mapping[str, Any]) -> list[str]:
    pointers = [
        "/host/os/family",
        "/host/os/name",
        "/host/os/version",
        "/host/os/build",
        "/host/os/kernel",
        "/host/cpu/architecture",
        "/host/cpu/vendor",
        "/host/cpu/model",
        "/host/cpu/logical_processors",
        "/host/memory/physical_bytes",
        "/run/graphics_backend",
        "/run/emulator_config/sha256",
    ]
    gpus = manifest["host"]["gpus"]
    unknown: list[str] = []
    if not gpus:
        unknown.append("/host/gpus")
    else:
        for index, _gpu in enumerate(gpus):
            pointers.extend(
                [
                    f"/host/gpus/{index}/name",
                    f"/host/gpus/{index}/vendor_id",
                    f"/host/gpus/{index}/device_id",
                    f"/host/gpus/{index}/driver/name",
                    f"/host/gpus/{index}/driver/version",
                ]
            )
    unknown.extend(
        pointer for pointer in pointers if _lookup_pointer(manifest, pointer) is None
    )
    return sorted(unknown)


def build_manifest(
    host: Mapping[str, Any],
    *,
    captured_at_utc: str,
    graphics_backend: str | None,
    emulator_config_sha256: str | None,
    warnings: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """Build and validate a normalized manifest from a synthetic or real snapshot."""
    gpus = sorted(list(host["gpus"]), key=_gpu_sort_key)
    manifest: dict[str, Any] = {
        "schema_id": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "collector": {"name": COLLECTOR_NAME, "version": COLLECTOR_VERSION},
        "captured_at_utc": captured_at_utc,
        "host": {
            "os": dict(host["os"]),
            "cpu": dict(host["cpu"]),
            "memory": dict(host["memory"]),
            "gpus": gpus,
        },
        "run": {
            "graphics_backend": _normalize_backend(graphics_backend),
            "emulator_config": {"sha256": emulator_config_sha256},
        },
        "unknown_fields": [],
        "collection_warnings": sorted(
            ({"code": item["code"], "field": item["field"]} for item in warnings),
            key=lambda item: (item["field"], item["code"]),
        ),
    }
    manifest["unknown_fields"] = _unknown_fields(manifest)
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Fail closed on producer/schema drift before serializing output."""
    if manifest.get("schema_id") != SCHEMA_ID or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported host-environment manifest schema")
    expected_top_level = {
        "schema_id",
        "schema_version",
        "collector",
        "captured_at_utc",
        "host",
        "run",
        "unknown_fields",
        "collection_warnings",
    }
    if set(manifest) != expected_top_level:
        raise ValueError("host-environment manifest has unexpected top-level fields")
    _require_exact_keys(manifest["collector"], {"name", "version"}, "collector")
    _require_exact_keys(manifest["host"], {"os", "cpu", "memory", "gpus"}, "host")
    _require_exact_keys(
        manifest["host"]["os"],
        {"family", "name", "version", "build", "kernel"},
        "host.os",
    )
    _require_exact_keys(
        manifest["host"]["cpu"],
        {"architecture", "vendor", "model", "logical_processors"},
        "host.cpu",
    )
    _require_exact_keys(manifest["host"]["memory"], {"physical_bytes"}, "host.memory")
    _require_exact_keys(manifest["run"], {"graphics_backend", "emulator_config"}, "run")
    _require_exact_keys(manifest["run"]["emulator_config"], {"sha256"}, "run.emulator_config")
    for index, gpu in enumerate(manifest["host"]["gpus"]):
        _require_exact_keys(gpu, {"name", "vendor_id", "device_id", "driver"}, f"host.gpus[{index}]")
        _require_exact_keys(gpu["driver"], {"name", "version"}, f"host.gpus[{index}].driver")
    for index, warning in enumerate(manifest["collection_warnings"]):
        _require_exact_keys(warning, {"code", "field"}, f"collection_warnings[{index}]")
    if manifest["unknown_fields"] != _unknown_fields(manifest):
        raise ValueError("host-environment manifest has stale unknown_fields")
    if len(manifest["host"]["gpus"]) > MAX_GPU_COUNT:
        raise ValueError("host-environment manifest contains too many GPU records")
    timestamp = manifest.get("captured_at_utc")
    if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
        raise ValueError("captured_at_utc must be an RFC 3339 UTC timestamp")
    try:
        parsed_timestamp = dt.datetime.fromisoformat(timestamp.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ValueError("captured_at_utc must be an RFC 3339 UTC timestamp") from error
    if parsed_timestamp.utcoffset() != dt.timedelta(0):
        raise ValueError("captured_at_utc must be UTC")
    config_digest = manifest["run"]["emulator_config"]["sha256"]
    if config_digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", config_digest):
        raise ValueError("emulator configuration fingerprint must be SHA-256")


def _require_exact_keys(value: Any, expected: set[str], field: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{field} has unexpected fields")


def _capture_timestamp(clock: Callable[[], dt.datetime]) -> str:
    return (
        clock()
        .astimezone(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def collect_manifest(
    *,
    graphics_backend: str | None = None,
    emulator_config_path: Path | None = None,
    runner: CommandRunner = _run_command,
    environ: Mapping[str, str] = os.environ,
    now: Callable[[], dt.datetime] | None = None,
) -> dict[str, Any]:
    system = platform.system()
    gpus, gpu_warning = _collect_gpus(system, runner)
    host = {
        "os": _collect_os(system),
        "cpu": _collect_cpu(system, environ, runner),
        "memory": {"physical_bytes": _physical_memory_bytes(system, runner)},
        "gpus": gpus,
    }
    config_sha256 = fingerprint_file(emulator_config_path) if emulator_config_path else None
    clock = now or (lambda: dt.datetime.now(dt.timezone.utc))
    captured_at = _capture_timestamp(clock)
    warnings = []
    if gpu_warning:
        warnings.append({"code": gpu_warning, "field": "/host/gpus"})
    return build_manifest(
        host,
        captured_at_utc=captured_at,
        graphics_backend=graphics_backend,
        emulator_config_sha256=config_sha256,
        warnings=warnings,
    )


def _write_json_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            stream.write(payload)
            stream.write("\n")
            temporary = Path(stream.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", help="Graphics backend semantic identifier, for example vulkan")
    parser.add_argument(
        "--emulator-config",
        type=Path,
        help="Configuration file to fingerprint; its path and contents are never serialized",
    )
    parser.add_argument("--output", type=Path, help="Write atomically to this path instead of stdout")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        manifest = collect_manifest(
            graphics_backend=args.backend,
            emulator_config_path=args.emulator_config,
        )
    except CollectionInputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    payload = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
        sort_keys=True,
    )
    if args.output:
        _write_json_atomic(args.output, payload)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
