from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools import baseline_capture


class NormalizeMeasurementsTest(unittest.TestCase):
    def test_missing_metrics_are_explicitly_unavailable(self) -> None:
        metrics = baseline_capture.normalize_measurements({"fps": [30.0, 31.5]})
        self.assertEqual(metrics["fps"]["availability"], "observed")
        self.assertEqual(metrics["fps"]["sample_count"], 2)
        self.assertEqual(metrics["frametime_ms"]["availability"], "unavailable")
        self.assertEqual(metrics["vram_bytes"]["samples"], [])

    def test_rejects_unknown_fields_and_invalid_integer_samples(self) -> None:
        with self.assertRaises(baseline_capture.BaselineCaptureError):
            baseline_capture.normalize_measurements({"temperature": [42]})
        with self.assertRaises(baseline_capture.BaselineCaptureError):
            baseline_capture.normalize_measurements({"ram_bytes": [1.5]})

    def test_rejects_non_finite_and_negative_samples(self) -> None:
        for value in ([float("inf")], [-1.0]):
            with self.subTest(value=value):
                with self.assertRaises(baseline_capture.BaselineCaptureError):
                    baseline_capture.normalize_measurements({"frametime_ms": value})


class PackBaselineTest(unittest.TestCase):
    def _write_run_zip(self, root: Path) -> Path:
        manifest = {
            "route": "gated-target-machine",
            "target": {"manifest_sha256": "sha256:" + "1" * 64},
            "host_environment": {"manifest_sha256": "sha256:" + "2" * 64},
            "scenario": {"id": "synthetic-smoke"},
            "emulator": {
                "source": {
                    "repository": "https://github.com/shadps4-emu/shadPS4",
                    "commit": "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64",
                    "tree": "e6026c14092b01702d4e49a5ac6c2f779a072dfe",
                    "patch_commits": [],
                }
            },
            "termination": {"elapsed_seconds": 1.25},
        }
        path = root / "run.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("run-manifest.json", json.dumps(manifest))
            archive.writestr("target-manifest.json", "{}\n")
            archive.writestr("host-environment.json", "{}\n")
            archive.writestr("scenario.json", "{}\n")
            archive.writestr("private-extra.txt", "must-not-propagate")
        return path

    def test_packs_only_allowlisted_run_entries_and_numeric_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_zip = self._write_run_zip(root)
            measurements = root / "measurements.json"
            measurements.write_text(
                json.dumps({"fps": [29.5, 30.0], "ram_bytes": [1024, 2048]}),
                encoding="utf-8",
            )
            output = root / "baseline.zip"
            with mock.patch.object(
                baseline_capture.run_target_experiment_v3, "validate_run_manifest"
            ):
                capture = baseline_capture.pack_baseline(
                    run_artifact=run_zip,
                    measurements_path=measurements,
                    output=output,
                )

            self.assertEqual(capture["metrics"]["fps"]["availability"], "observed")
            self.assertEqual(capture["metrics"]["vram_bytes"]["availability"], "unavailable")
            self.assertEqual(capture["overhead"]["scope"], "packer-only")
            self.assertEqual(capture["overhead"]["runtime_instrumentation_overhead"], "unknown")
            self.assertGreaterEqual(capture["overhead"]["wall_seconds"], 0)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertEqual(
                    names,
                    {
                        "baseline-capture.json",
                        "run-manifest.json",
                        "target-manifest.json",
                        "host-environment.json",
                        "scenario.json",
                    },
                )
                packaged = json.loads(archive.read("baseline-capture.json"))
                self.assertEqual(packaged["source_run"]["scenario_id"], "synthetic-smoke")
                self.assertNotIn("private-extra.txt", names)

    def test_absent_sidecar_produces_static_missing_data_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_zip = self._write_run_zip(root)
            output = root / "baseline.zip"
            with mock.patch.object(
                baseline_capture.run_target_experiment_v3, "validate_run_manifest"
            ):
                capture = baseline_capture.pack_baseline(
                    run_artifact=run_zip,
                    measurements_path=None,
                    output=output,
                )
            self.assertEqual(capture["evidence"]["class"], "static")
            self.assertTrue(
                all(item["availability"] == "unavailable" for item in capture["metrics"].values())
            )


if __name__ == "__main__":
    unittest.main()
