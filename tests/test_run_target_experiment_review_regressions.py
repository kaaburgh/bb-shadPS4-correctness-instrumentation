import hashlib
import json
import os
import subprocess
import sys
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


def _command(binary: Path) -> dict:
    return {
        "schema_id": runner.COMMAND_SCHEMA_ID,
        "schema_version": runner.COMMAND_SCHEMA_VERSION,
        "argv": [str(binary), "synthetic-target"],
        "emulator_binary_index": 0,
        "target_path_index": 1,
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
        with self.assertRaisesRegex(runner.TargetRunError, "current-run producer provenance"):
            runner._require_non_synthetic_evidence_contract(
                manifest,
                _scenario("file-sha256"),
                Path("unused-target-binary"),
                "0" * 64,
            )

    def test_non_synthetic_artifacts_fail_closed_without_producer_attestation(self):
        manifest = _manifest()
        manifest["provenance"]["evidence_classes"] = ["runtime"]
        scenario = _scenario()
        scenario["artifacts"] = [{
            "path": "results/summary.json",
            "name": "summary",
            "mode": "metadata-only",
            "max_bytes": 4096,
        }]
        with self.assertRaisesRegex(runner.TargetRunError, "declared artifacts require"):
            runner._require_non_synthetic_evidence_contract(
                manifest,
                scenario,
                Path("unused-target-binary"),
                "0" * 64,
            )

    def test_non_synthetic_run_requires_exact_pinned_upstream_ci_binary(self):
        manifest = _manifest()
        manifest["provenance"]["evidence_classes"] = ["runtime"]
        if os.name == "nt":
            platform = "windows"
        elif sys.platform.startswith("linux"):
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

    def test_safe_target_projection_preserves_hashed_dlc_identity(self):
        manifest = _manifest()
        manifest["content"]["dlc"] = {
            "dlc.alpha": {"version": "private-looking-version-label", "source_package": None}
        }
        packaged = runner.loads_strict(runner._package_target_manifest(manifest).decode("utf-8"))
        expected_key = "dlc-sha256-" + hashlib.sha256(b"dlc.alpha").hexdigest()
        self.assertEqual(set(packaged["content"]["dlc"]), {expected_key})
        self.assertNotIn("dlc.alpha", json.dumps(packaged))

    def test_documented_direct_script_entrypoint_resolves_tools_package(self):
        completed = subprocess.run(
            [sys.executable, "tools/run_target_experiment.py", "--help"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout.lower())

    def test_gated_target_and_scenario_use_single_loaded_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_path = root / "target.json"
            scenario_path = root / "scenario.json"
            command_path = root / "command.json"
            workdir = root / "work"
            workdir.mkdir()

            target_raw = runner._json_bytes(_manifest())
            scenario_raw = runner._json_bytes(_scenario())
            target_path.write_bytes(target_raw)
            scenario_path.write_bytes(scenario_raw)
            command_path.write_bytes(runner._json_bytes(_command(Path(sys.executable))))
            observed = {}

            def fake_legacy(**kwargs):
                target_path.write_text("{}", encoding="utf-8")
                scenario_path.write_text("{}", encoding="utf-8")
                observed["target_path"] = Path(kwargs["target_manifest_path"])
                observed["scenario_path"] = Path(kwargs["scenario_path"])
                observed["target_raw"] = observed["target_path"].read_bytes()
                observed["scenario_raw"] = observed["scenario_path"].read_bytes()
                return {"synthetic": True}

            with mock.patch.object(runner, "_LEGACY_RUN_EXPERIMENT", side_effect=fake_legacy):
                result = runner.run_experiment(
                    target_manifest_path=target_path,
                    scenario_path=scenario_path,
                    command_path=command_path,
                    emulator_binary_path=Path(sys.executable),
                    emulator_binary_sha256="0" * 64,
                    source_repository=runner.PINNED_SOURCE_REPOSITORY,
                    source_commit=runner.PINNED_SOURCE_COMMIT,
                    source_tree=runner.PINNED_SOURCE_TREE,
                    patch_commits=[],
                    target_root=root / "unused-target",
                    working_directory=workdir,
                    output_path=root / "output.zip",
                )

            self.assertEqual(result, {"synthetic": True})
            self.assertNotEqual(observed["target_path"], target_path)
            self.assertNotEqual(observed["scenario_path"], scenario_path)
            self.assertEqual(observed["target_raw"], target_raw)
            self.assertEqual(observed["scenario_raw"], scenario_raw)

    def test_non_synthetic_launch_uses_staged_verified_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / ("shadPS4.exe" if os.name == "nt" else "Shadps4-sdl.AppImage")
            pinned_bytes = b"review-pinned-binary"
            binary.write_bytes(pinned_bytes)
            binary.chmod(0o700)
            digest = hashlib.sha256(pinned_bytes).hexdigest()

            manifest = _manifest()
            manifest["provenance"]["evidence_classes"] = ["runtime"]
            target_path = root / "target.json"
            scenario_path = root / "scenario.json"
            command_path = root / "command.json"
            workdir = root / "work"
            workdir.mkdir()
            target_path.write_bytes(runner._json_bytes(manifest))
            scenario_path.write_bytes(runner._json_bytes(_scenario()))
            command_path.write_bytes(runner._json_bytes(_command(binary)))
            pinned = {
                "workflow_run_id": runner.PINNED_BUILD_WORKFLOW_RUN_ID,
                "binary_name": binary.name,
                "binary_sha256": "sha256:" + digest,
                "binary_size_bytes": len(pinned_bytes),
            }
            observed = {}

            def fake_legacy(**kwargs):
                binary.write_bytes(b"replaced-after-staging")
                observed["binary_path"] = Path(kwargs["emulator_binary_path"])
                observed["binary_bytes"] = observed["binary_path"].read_bytes()
                observed["command"] = json.loads(Path(kwargs["command_path"]).read_text(encoding="utf-8"))
                return {"runtime": True}

            with (
                mock.patch.object(runner, "_pinned_build_for_host", return_value=pinned),
                mock.patch.object(runner, "_LEGACY_RUN_EXPERIMENT", side_effect=fake_legacy),
            ):
                result = runner.run_experiment(
                    target_manifest_path=target_path,
                    scenario_path=scenario_path,
                    command_path=command_path,
                    emulator_binary_path=binary,
                    emulator_binary_sha256=digest,
                    source_repository=runner.PINNED_SOURCE_REPOSITORY,
                    source_commit=runner.PINNED_SOURCE_COMMIT,
                    source_tree=runner.PINNED_SOURCE_TREE,
                    patch_commits=[],
                    target_root=root / "unused-target",
                    working_directory=workdir,
                    output_path=root / "output.zip",
                )

            self.assertEqual(result, {"runtime": True})
            self.assertNotEqual(observed["binary_path"], binary)
            self.assertEqual(observed["binary_bytes"], pinned_bytes)
            self.assertEqual(Path(observed["command"]["argv"][0]), observed["binary_path"])

    def test_command_binary_link_is_rejected_before_non_synthetic_staging(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workdir = root / "work"
            workdir.mkdir()
            binary = root / "binary"
            binary.write_bytes(b"x")
            link = root / "binary-link"
            try:
                link.symlink_to(binary)
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            with self.assertRaisesRegex(runner.TargetRunError, "link or reparse alias"):
                runner._resolve_command_binary(_command(link), workdir, binary)

    def test_runner_version_identifies_hardened_entrypoint(self):
        self.assertEqual(runner.RUNNER_VERSION, "1.7.0")
        self.assertEqual(runner._legacy.RUNNER_VERSION, "1.7.0")
        self.assertEqual(runner.PINNED_BUILD_WORKFLOW_RUN_ID, 31742892228)


if __name__ == "__main__":
    unittest.main()
