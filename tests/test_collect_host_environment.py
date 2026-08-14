import copy
import datetime as dt
import hashlib
import io
import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import collect_host_environment as collector


FIXED_TIME = "2026-08-14T08:00:00Z"


def synthetic_host(*, gpus=None):
    return {
        "os": {
            "family": "windows",
            "name": "Windows",
            "version": "10.0.26100",
            "build": "10.0.26100",
            "kernel": "10.0.26100",
        },
        "cpu": {
            "architecture": "x86_64",
            "vendor": "AuthenticAMD",
            "model": "Synthetic CPU",
            "logical_processors": 16,
        },
        "memory": {"physical_bytes": 34359738368},
        "gpus": gpus if gpus is not None else [],
    }


class ManifestTests(unittest.TestCase):
    def test_synthetic_manifest_is_deterministic_and_sorts_gpus(self):
        gpus = [
            {
                "name": "GPU B",
                "vendor_id": "0x1002",
                "device_id": "0x2222",
                "driver": {"name": None, "version": "2.0"},
            },
            {
                "name": "GPU A",
                "vendor_id": "0x1002",
                "device_id": "0x1111",
                "driver": {"name": None, "version": "1.0"},
            },
        ]
        first = collector.build_manifest(
            synthetic_host(gpus=gpus),
            captured_at_utc=FIXED_TIME,
            graphics_backend="Vulkan",
            emulator_config_sha256="sha256:" + "a" * 64,
        )
        second = collector.build_manifest(
            synthetic_host(gpus=list(reversed(gpus))),
            captured_at_utc=FIXED_TIME,
            graphics_backend="vulkan",
            emulator_config_sha256="sha256:" + "a" * 64,
        )

        self.assertEqual(first, second)
        self.assertEqual([gpu["name"] for gpu in first["host"]["gpus"]], ["GPU A", "GPU B"])
        self.assertEqual(first["run"]["graphics_backend"], "vulkan")
        self.assertEqual(
            first["unknown_fields"],
            ["/host/gpus/0/driver/name", "/host/gpus/1/driver/name"],
        )

    def test_unknown_values_are_explicit(self):
        host = synthetic_host()
        host["os"]["build"] = None
        host["cpu"]["vendor"] = None
        manifest = collector.build_manifest(
            host,
            captured_at_utc=FIXED_TIME,
            graphics_backend=None,
            emulator_config_sha256=None,
            warnings=[{"code": "gpu-query-empty-or-unavailable", "field": "/host/gpus"}],
        )

        self.assertIsNone(manifest["host"]["os"]["build"])
        self.assertEqual(
            manifest["unknown_fields"],
            [
                "/host/cpu/vendor",
                "/host/gpus",
                "/host/os/build",
                "/run/emulator_config/sha256",
                "/run/graphics_backend",
            ],
        )
        collector.validate_manifest(manifest)

    def test_windows_gpu_parser_ignores_non_allowlisted_sensitive_fields(self):
        sentinel = "PRIVATE-HOST-USER-TOKEN"
        payload = json.dumps(
            {
                "Name": "Synthetic GPU",
                "DriverVersion": "31.0.1",
                "PNPDeviceID": "PCI\\VEN_10DE&DEV_2684&SUBSYS_00000000",
                "HostName": sentinel,
                "UserName": sentinel,
                "SerialNumber": sentinel,
                "InstallPath": f"C:\\Users\\{sentinel}\\driver",
            }
        )

        gpus = collector.parse_windows_gpu_json(payload)

        self.assertEqual(
            gpus,
            [
                {
                    "name": "Synthetic GPU",
                    "vendor_id": "0x10de",
                    "device_id": "0x2684",
                    "driver": {"name": None, "version": "31.0.1"},
                }
            ],
        )
        self.assertNotIn(sentinel, json.dumps(gpus))

    def test_windows_cpu_collection_uses_hardware_backed_fields(self):
        payload = json.dumps(
            {
                "Name": "AMD Ryzen Synthetic CPU",
                "Manufacturer": "AuthenticAMD",
                "PROCESSOR_IDENTIFIER": "spoofed environment value",
                "SerialNumber": "PRIVATE-SERIAL",
            }
        )
        commands = []

        def runner(argv):
            commands.append(argv)
            return SimpleNamespace(returncode=0, stdout=payload, stderr="")

        cpu = collector._collect_cpu(
            "Windows",
            {"PROCESSOR_IDENTIFIER": "spoofed environment value"},
            runner,
        )

        self.assertEqual(cpu["vendor"], "AuthenticAMD")
        self.assertEqual(cpu["model"], "AMD Ryzen Synthetic CPU")
        self.assertIn("Win32_Processor", commands[0][-1])

    def test_gpu_inventory_over_limit_fails_closed(self):
        windows_payload = json.dumps(
            [
                {
                    "Name": f"GPU {index}",
                    "DriverVersion": "1.0",
                    "PNPDeviceID": f"PCI\\VEN_1002&DEV_{index:04x}",
                }
                for index in range(collector.MAX_GPU_COUNT + 1)
            ]
        )
        windows_gpus, windows_warning = collector._collect_windows_gpus(
            lambda _argv: SimpleNamespace(returncode=0, stdout=windows_payload, stderr="")
        )
        self.assertEqual(windows_gpus, [])
        self.assertEqual(windows_warning, "gpu-inventory-too-many")

        macos_payload = json.dumps(
            {
                "SPDisplaysDataType": [
                    {"sppci_model": f"GPU {index}"}
                    for index in range(collector.MAX_GPU_COUNT + 1)
                ]
            }
        )
        macos_gpus, macos_warning = collector._collect_macos_gpus(
            lambda _argv: SimpleNamespace(returncode=0, stdout=macos_payload, stderr="")
        )
        self.assertEqual(macos_gpus, [])
        self.assertEqual(macos_warning, "gpu-inventory-too-many")

        with tempfile.TemporaryDirectory() as directory:
            sysfs = Path(directory)
            for index in range(collector.MAX_GPU_COUNT + 1):
                device = sysfs / f"card{index}" / "device"
                device.mkdir(parents=True)
                (device / "vendor").write_text("0x1002\n", encoding="ascii")
                (device / "device").write_text(f"0x{index:04x}\n", encoding="ascii")

            linux_gpus, linux_warning = collector._collect_linux_gpus(sysfs)

        self.assertEqual(linux_gpus, [])
        self.assertEqual(linux_warning, "gpu-inventory-too-many")

        manifest = collector.build_manifest(
            synthetic_host(),
            captured_at_utc=FIXED_TIME,
            graphics_backend=None,
            emulator_config_sha256=None,
            warnings=[{"code": "gpu-inventory-too-many", "field": "/host/gpus"}],
        )
        self.assertIn("/host/gpus", manifest["unknown_fields"])
        self.assertEqual(
            manifest["collection_warnings"],
            [{"code": "gpu-inventory-too-many", "field": "/host/gpus"}],
        )

    def test_config_fingerprint_records_neither_path_nor_contents(self):
        sentinel = b"private-config-value"
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "user-name" / "config.toml"
            config_path.parent.mkdir()
            config_path.write_bytes(sentinel)

            digest = collector.fingerprint_file(config_path)
            manifest = collector.build_manifest(
                synthetic_host(),
                captured_at_utc=FIXED_TIME,
                graphics_backend=None,
                emulator_config_sha256=digest,
            )

        serialized = json.dumps(manifest)
        self.assertEqual(digest, "sha256:" + hashlib.sha256(sentinel).hexdigest())
        self.assertNotIn(str(config_path), serialized)
        self.assertNotIn(sentinel.decode(), serialized)

    def test_config_fingerprint_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            with config_path.open("wb") as stream:
                stream.truncate(collector.MAX_CONFIG_BYTES + 1)

            with self.assertRaisesRegex(collector.CollectionInputError, "no larger than"):
                collector.fingerprint_file(config_path)

    def test_config_fingerprint_stops_if_file_grows_past_limit(self):
        class GrowingConfig:
            def stat(self):
                return SimpleNamespace(
                    st_mode=stat.S_IFREG | 0o600,
                    st_size=1,
                    st_mtime_ns=1,
                )

            def open(self, _mode):
                return io.BytesIO(b"12345")

        with mock.patch.object(collector, "MAX_CONFIG_BYTES", 4):
            with self.assertRaisesRegex(collector.CollectionInputError, "no larger than"):
                collector.fingerprint_file(GrowingConfig())

    def test_schema_identity_and_allowlist_match_producer(self):
        schema_path = Path(__file__).parents[1] / "schemas" / "host-environment.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        manifest = collector.build_manifest(
            synthetic_host(),
            captured_at_utc=FIXED_TIME,
            graphics_backend=None,
            emulator_config_sha256=None,
        )

        self.assertEqual(schema["properties"]["schema_id"]["const"], collector.SCHEMA_ID)
        self.assertEqual(schema["properties"]["schema_version"]["const"], collector.SCHEMA_VERSION)
        self.assertEqual(set(schema["required"]), set(manifest))
        self.assertFalse(schema["additionalProperties"])

    def test_validation_rejects_nested_producer_drift(self):
        manifest = collector.build_manifest(
            synthetic_host(),
            captured_at_utc=FIXED_TIME,
            graphics_backend=None,
            emulator_config_sha256=None,
        )
        manifest["host"]["os"]["host_name"] = "must-not-be-serialized"

        with self.assertRaisesRegex(ValueError, "host.os has unexpected fields"):
            collector.validate_manifest(manifest)

    def test_validation_enforces_published_value_constraints(self):
        base = collector.build_manifest(
            synthetic_host(),
            captured_at_utc=FIXED_TIME,
            graphics_backend=None,
            emulator_config_sha256=None,
        )
        cases = [
            ("collector name", lambda value: value["collector"].update(name="spoofed"), "collector.name"),
            ("collector version", lambda value: value["collector"].update(version=""), "collector.version"),
            ("oversized OS field", lambda value: value["host"]["os"].update(name="x" * 257), "host.os.name"),
            (
                "logical processor lower bound",
                lambda value: value["host"]["cpu"].update(logical_processors=0),
                "host.cpu.logical_processors",
            ),
            (
                "physical memory lower bound",
                lambda value: value["host"]["memory"].update(physical_bytes=0),
                "host.memory.physical_bytes",
            ),
            (
                "graphics backend pattern",
                lambda value: value["run"].update(graphics_backend="Vulkan"),
                "run.graphics_backend",
            ),
            (
                "warning count bound",
                lambda value: value.update(
                    collection_warnings=[{"code": "warning", "field": "/host/gpus"}] * 33
                ),
                "collection_warnings contains too many",
            ),
        ]
        for name, mutate, message in cases:
            with self.subTest(name=name):
                candidate = copy.deepcopy(base)
                mutate(candidate)
                with self.assertRaisesRegex(ValueError, message):
                    collector.validate_manifest(candidate)

        gpu_manifest = collector.build_manifest(
            synthetic_host(
                gpus=[
                    {
                        "name": "Synthetic GPU",
                        "vendor_id": "0x1002",
                        "device_id": "0x73bf",
                        "driver": {"name": None, "version": None},
                    }
                ]
            ),
            captured_at_utc=FIXED_TIME,
            graphics_backend=None,
            emulator_config_sha256=None,
        )
        gpu_manifest["host"]["gpus"][0]["vendor_id"] = "NVIDIA-GARBAGE"
        with self.assertRaisesRegex(ValueError, r"host.gpus\[0\].vendor_id"):
            collector.validate_manifest(gpu_manifest)

    def test_linux_gpu_discovery_ignores_connector_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            sysfs = Path(directory)
            card = sysfs / "card0" / "device"
            card.mkdir(parents=True)
            (card / "vendor").write_text("0x1002\n", encoding="ascii")
            (card / "device").write_text("0x73bf\n", encoding="ascii")
            connector = sysfs / "card0-DP-1" / "device"
            connector.mkdir(parents=True)
            (connector / "vendor").write_text("0x1002\n", encoding="ascii")
            (connector / "device").write_text("0x73bf\n", encoding="ascii")

            gpus, warning = collector._collect_linux_gpus(sysfs)

        self.assertIsNone(warning)
        self.assertEqual(len(gpus), 1)
        self.assertEqual(gpus[0]["vendor_id"], "0x1002")
        self.assertEqual(gpus[0]["device_id"], "0x73bf")

    def test_capture_timestamp_normalizes_injected_clock_to_utc(self):
        fixed = dt.datetime(2026, 8, 14, 8, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(collector._capture_timestamp(lambda: fixed), FIXED_TIME)

    def test_collect_manifest_assembles_a_valid_manifest(self):
        fixed = dt.datetime(2026, 8, 14, 8, 0, tzinfo=dt.timezone.utc)
        manifest = collector.collect_manifest(
            now=lambda: fixed,
            runner=lambda argv: SimpleNamespace(returncode=1, stdout="", stderr=""),
        )

        collector.validate_manifest(manifest)
        self.assertEqual(manifest["captured_at_utc"], FIXED_TIME)

    def test_invalid_backend_fails_closed(self):
        with self.assertRaises(collector.CollectionInputError):
            collector.build_manifest(
                synthetic_host(),
                captured_at_utc=FIXED_TIME,
                graphics_backend="C:\\Users\\private",
                emulator_config_sha256=None,
            )


if __name__ == "__main__":
    unittest.main()
