import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import run_target_experiment as runner


ROOT = Path(__file__).parents[1]
TARGET_EXAMPLE = ROOT / "docs" / "baseline" / "examples" / "bloodborne-target-manifest.synthetic.json"


def _manifest() -> dict:
    return json.loads(TARGET_EXAMPLE.read_text(encoding="utf-8"))


def _scenario(kind: str = "process-exit") -> dict:
    oracle = {"kind": "process-exit", "expected_exit_code": 0}
    if kind == "file-sha256":
        oracle = {
            "kind": "file-sha256",
            "path": "results/oracle.bin",
            "sha256": "sha256:" + "a" * 64,
        }
    return {
        "schema_id": runner.SCENARIO_SCHEMA_ID,
        "schema_version": runner.SCENARIO_SCHEMA_VERSION,
        "scenario_id": "review-regression",
        "description": "synthetic regression",
        "timeout_seconds": 10,
        "oracle": oracle,
        "artifacts": [],
    }


class ReviewRegressionTests(unittest.TestCase):
    def test_synthetic_control_keeps_file_oracle_capability_only_as_synthetic_evidence(self):
        manifest = _manifest()
        self.assertTrue(runner._is_explicit_synthetic_control(manifest))
        runner._require_non_synthetic_evidence_contract(
            manifest,
            _scenario("file-sha256"),
            Path("unused-synthetic-binary"),
            "0" * 64,
        )

    def test_non_synthetic_file_oracle_fails_closed_without_producer_attestation(self):
        manifest = _manifest()
        manifest["provenance"]["evidence_classes"] = ["runtime"]
        self.assertFalse(runner._is_explicit_synthetic_control(manifest))
        with self.assertRaisesRegex(runner.TargetRunError, "current-run producer provenance"):
            runner._require_non_synthetic_evidence_contract(
                manifest,
                _scenario("file-sha256"),
                Path("unused-target-binary"),
                "0" * 64,
            )

    def test_non_synthetic_run_requires_exact_pinned_upstream_ci_binary(self):
        manifest = _manifest()
        manifest["provenance"]["evidence_classes"] = ["runtime"]
        if os.name == "nt":
            platform = "windows"
        elif os.sys.platform.startswith("linux"):
            platform = "linux"
        else:
            with self.assertRaisesRegex(runner.TargetRunError, "no independently bound"):
                runner._pinned_build_for_host()
            return
        pinned = runner.PINNED_BUILD_ARTIFACTS[platform]
        with mock.patch.object(
            runner._legacy,
            "_sha256_file",
            return_value=(pinned["binary_sha256"], pinned["binary_size_bytes"]),
        ):
            observed = runner._require_non_synthetic_evidence_contract(
                manifest,
                _scenario(),
                Path("synthetic-path-for-mocked-hash"),
                pinned["binary_sha256"].removeprefix("sha256:"),
            )
        self.assertEqual(observed["workflow_run_id"], runner.PINNED_BUILD_WORKFLOW_RUN_ID)

        with mock.patch.object(
            runner._legacy,
            "_sha256_file",
            return_value=("sha256:" + "0" * 64, 1),
        ):
            with self.assertRaisesRegex(runner.TargetRunError, "exact independently observed upstream"):
                runner._require_non_synthetic_evidence_contract(
                    manifest,
                    _scenario(),
                    Path("synthetic-path-for-mocked-hash"),
                    "0" * 64,
                )

    def test_safe_target_projection_preserves_hashed_dlc_identity(self):
        manifest = _manifest()
        manifest["content"]["dlc"] = {
            "dlc.alpha": {
                "version": "private-looking-version-label",
                "source_package": None,
            }
        }
        packaged = runner.loads_strict(runner._package_target_manifest(manifest).decode("utf-8"))
        expected_key = "dlc-sha256-" + hashlib.sha256(b"dlc.alpha").hexdigest()
        self.assertEqual(set(packaged["content"]["dlc"]), {expected_key})
        self.assertNotIn("dlc.alpha", json.dumps(packaged))
        self.assertIsNone(packaged["content"]["dlc"][expected_key]["version"])
        self.assertIsNone(packaged["content"]["dlc"][expected_key]["source_package"])

    def test_runner_version_identifies_hardened_entrypoint(self):
        self.assertEqual(runner.RUNNER_VERSION, "1.6.0")
        self.assertEqual(runner._legacy.RUNNER_VERSION, "1.6.0")
        self.assertEqual(runner.PINNED_BUILD_WORKFLOW_RUN_ID, 31742892228)


if __name__ == "__main__":
    unittest.main()
