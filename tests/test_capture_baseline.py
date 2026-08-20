from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools import capture_baseline
from tools import run_target_experiment as target_runner

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_TARGET = ROOT / "docs/baseline/examples/bloodborne-target-manifest.synthetic.json"


class BaselineCaptureTests(unittest.TestCase):
    def _host(self) -> dict:
        return {
            "schema_id": "bb-host-environment/v1",
            "schema_version": 1,
            "captured_at_utc": "2026-08-16T20:00:00Z",
            "host": {
                "os": {"family": "linux", "name": "Linux", "version": None, "build": None, "kernel": "test"},
                "cpu": {"architecture": "x86_64", "vendor": None, "model": None, "logical_processors": 1},
                "memory": {"physical_bytes": 1024},
                "gpus": [],
            },
            "run": {"graphics_backend": None, "emulator_config": {"sha256": None}},
            "unknown_fields": ["/host/os/version", "/host/os/build", "/host/cpu/vendor", "/host/cpu/model", "/run/graphics_backend", "/run/emulator_config/sha256"],
            "collection_warnings": [],
        }

    @mock.patch("tools.capture_baseline.validate_host_manifest")
    @mock.patch("tools.capture_baseline.collect_manifest")
    def test_one_shot_artifact_has_exact_provenance_and_explicit_missing_metrics(self, collect, validate):
        collect.return_value = self._host()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "baseline.zip"
            capture, target_bytes, host_bytes = capture_baseline.build_capture(SYNTHETIC_TARGET)
            capture_baseline.write_artifact(output, capture, target_bytes, host_bytes)
            self.assertEqual(capture["source"]["commit"], capture_baseline.SOURCE_COMMIT)
            self.assertFalse(capture["evidence"]["runtime_claims"])
            self.assertGreaterEqual(capture["collection_overhead"]["packer_elapsed_ns"], 0)
            self.assertEqual(set(capture["telemetry"]), set(capture_baseline.METRICS))
            self.assertTrue(all(item["state"] == "unavailable" for item in capture["telemetry"].values()))
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(sorted(archive.namelist()), ["capture-manifest.json", "host-environment.json", "target-manifest.json"])
                packaged_capture = json.loads(archive.read("capture-manifest.json"))
                packaged_target = archive.read("target-manifest.json")
                self.assertEqual(
                    packaged_capture["target"]["packaged_manifest_sha256"],
                    capture_baseline._sha256(packaged_target),
                )
                projected = json.loads(packaged_target)
                self.assertEqual(projected["target"]["name"], "Bloodborne")
                self.assertIsNone(projected["build"]["app_version"])
                self.assertIsNone(projected["content"]["base"]["content_id"])
        validate.assert_called_once()

    @mock.patch("tools.capture_baseline.validate_host_manifest")
    @mock.patch("tools.capture_baseline.collect_manifest")
    def test_dlc_projection_matches_supported_runner_and_runtime_class_is_preserved(self, collect, validate):
        collect.return_value = self._host()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            document = json.loads(SYNTHETIC_TARGET.read_text(encoding="utf-8"))
            document["provenance"]["evidence_classes"] = ["runtime"]
            document["content"]["dlc"] = {
                "dlc.alpha": {"version": "private-looking-version-label", "source_package": None}
            }
            target.write_text(json.dumps(document), encoding="utf-8")

            capture, target_bytes, _host_bytes = capture_baseline.build_capture(target)
            projected = json.loads(target_bytes)
            expected_key = "dlc-sha256-" + hashlib.sha256(b"dlc.alpha").hexdigest()

            self.assertIs(capture_baseline._package_target_manifest, target_runner._package_target_manifest)
            self.assertEqual(target_bytes, target_runner._package_target_manifest(document))
            self.assertEqual(set(projected["content"]["dlc"]), {expected_key})
            self.assertEqual(capture["evidence"]["class"], "runtime")
            self.assertFalse(capture["evidence"]["runtime_claims"])
        validate.assert_called_once()

    @mock.patch("tools.capture_baseline.validate_host_manifest")
    @mock.patch("tools.capture_baseline.collect_manifest")
    def test_rejects_schema_valid_private_target_setting_instead_of_packaging_it(self, collect, validate):
        collect.return_value = self._host()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            document = json.loads(SYNTHETIC_TARGET.read_text(encoding="utf-8"))
            document["configuration"]["settings"]["game.language"]["value"] = "/Users/alice/private"
            target.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsafe value"):
                capture_baseline.build_capture(target)
        validate.assert_not_called()

    def test_rejects_oversized_target_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            with target.open("wb") as stream:
                stream.seek(capture_baseline.MAX_TARGET_MANIFEST_BYTES)
                stream.write(b"x")
            with self.assertRaisesRegex(ValueError, "safety size limit"):
                capture_baseline.build_capture(target)


if __name__ == "__main__":
    unittest.main()
