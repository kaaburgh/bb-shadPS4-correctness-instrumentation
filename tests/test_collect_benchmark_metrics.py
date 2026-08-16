from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import collect_benchmark_metrics as metrics


class BenchmarkMetricsTests(unittest.TestCase):
    def _artifact(self, root: Path, *, elapsed_seconds: float = 12.5, manifest_kind: str = "bb-target-run") -> Path:
        run_manifest = {
            "manifest_kind": manifest_kind,
            "schema_version": 3,
            "termination": {"elapsed_seconds": elapsed_seconds},
        }
        path = root / "run.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("run-manifest.json", json.dumps(run_manifest, allow_nan=False))
        return path

    def test_collects_contract_wall_time_and_marks_unexported_metrics_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = metrics.collect_metrics(self._artifact(Path(directory)))

        self.assertEqual(manifest["manifest_kind"], "bb-benchmark-metrics")
        self.assertEqual(manifest["schema_version"], 1)
        self.assertFalse(manifest["capture"]["target_process_observed"])
        self.assertFalse(manifest["capture"]["target_process_automated"])
        self.assertGreaterEqual(manifest["capture"]["collector_overhead_ms"], 0)
        self.assertEqual(manifest["metrics"]["run_wall_time_seconds"]["status"], "available")
        self.assertEqual(manifest["metrics"]["run_wall_time_seconds"]["value"], 12.5)
        self.assertEqual(
            manifest["metrics"]["run_wall_time_seconds"]["source"],
            "run-manifest.json#/termination/elapsed_seconds",
        )
        for name in ("fps", "frametime_ms", "ram_bytes", "vram_bytes", "shader_compilations"):
            self.assertEqual(manifest["metrics"][name]["status"], "unavailable")
            self.assertIsNone(manifest["metrics"][name]["value"])
            self.assertEqual(manifest["metrics"][name]["reason"], "not-exposed-by-bb-target-run-v3")

    def test_binds_output_to_exact_input_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._artifact(Path(directory))
            manifest = metrics.collect_metrics(path)
            digest, size = metrics._sha256_file(path)

        self.assertEqual(manifest["input"]["target_run_sha256"], digest)
        self.assertEqual(manifest["input"]["target_run_size_bytes"], size)

    def test_rejects_wrong_run_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._artifact(Path(directory), manifest_kind="other")
            with self.assertRaisesRegex(metrics.MetricsCaptureError, "unsupported target-run manifest contract"):
                metrics.collect_metrics(path)

    def test_rejects_non_finite_elapsed_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "run.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "run-manifest.json",
                    '{"manifest_kind":"bb-target-run","schema_version":3,"termination":{"elapsed_seconds":NaN}}',
                )
            with self.assertRaisesRegex(metrics.MetricsCaptureError, "non-finite JSON number"):
                metrics.collect_metrics(path)

    def test_rejects_duplicate_manifest_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "run.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "run-manifest.json",
                    '{"manifest_kind":"bb-target-run","manifest_kind":"bb-target-run","schema_version":3,"termination":{"elapsed_seconds":1}}',
                )
            with self.assertRaisesRegex(metrics.MetricsCaptureError, "duplicate JSON key"):
                metrics.collect_metrics(path)

    def test_cli_writes_machine_readable_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._artifact(root)
            output = root / "metrics.json"
            self.assertEqual(metrics.main(["--run-artifact", str(source), "--output", str(output)]), 0)
            produced = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(produced["manifest_kind"], "bb-benchmark-metrics")
        self.assertEqual(produced["metrics"]["fps"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
