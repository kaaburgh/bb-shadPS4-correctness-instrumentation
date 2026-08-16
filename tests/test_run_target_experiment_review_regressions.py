import errno
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
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
            manifest, _scenario("file-sha256"), Path("unused-synthetic-binary"), "0" * 64
        )

    def test_non_synthetic_file_oracle_fails_closed_without_producer_attestation(self):
        manifest = _manifest()
        manifest["provenance"]["evidence_classes"] = ["runtime"]
        with self.assertRaisesRegex(runner.TargetRunError, "current-run producer provenance"):
            runner._require_non_synthetic_evidence_contract(
                manifest, _scenario("file-sha256"), Path("unused-target-binary"), "0" * 64
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
                manifest, scenario, Path("unused-target-binary"), "0" * 64
            )

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

    def test_compatibility_engine_direct_cli_fails_closed(self):
        invocations = (
            [sys.executable, "-m", "tools.run_target_experiment_v3", "--help"],
            [sys.executable, "tools/run_target_experiment_v3.py", "--help"],
        )
        for argv in invocations:
            with self.subTest(argv=argv):
                completed = subprocess.run(
                    argv,
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIn("internal compatibility engine", completed.stderr)
                self.assertNotIn("{run,validate}", completed.stdout + completed.stderr)

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
            command_raw = runner._json_bytes(_command(Path(sys.executable)))
            target_path.write_bytes(target_raw)
            scenario_path.write_bytes(scenario_raw)
            command_path.write_bytes(command_raw)
            observed = {}

            def fake_legacy(**kwargs):
                target_path.write_text("{}", encoding="utf-8")
                scenario_path.write_text("{}", encoding="utf-8")
                observed["target_path"] = Path(kwargs["target_manifest_path"])
                observed["scenario_path"] = Path(kwargs["scenario_path"])
                observed["target_raw"] = observed["target_path"].read_bytes()
                observed["scenario_raw"] = observed["scenario_path"].read_bytes()
                return {"execution": {"command_argv_sha256": "sha256:" + "0" * 64}}

            def keep_identity(_output, manifest, original):
                observed["command_raw"] = original
                return manifest

            with (
                mock.patch.object(runner, "_LEGACY_RUN_EXPERIMENT", side_effect=fake_legacy),
                mock.patch.object(runner, "_restore_original_command_identity", side_effect=keep_identity),
            ):
                runner.run_experiment(
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
            self.assertNotEqual(observed["target_path"], target_path)
            self.assertNotEqual(observed["scenario_path"], scenario_path)
            self.assertEqual(observed["target_raw"], target_raw)
            self.assertEqual(observed["scenario_raw"], scenario_raw)
            self.assertEqual(observed["command_raw"], command_raw)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux descriptor execution regression")
    def test_linux_executable_lease_survives_atomic_path_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "binary"
            original = b"verified-executable-bytes"
            path.write_bytes(original)
            digest = "sha256:" + hashlib.sha256(original).hexdigest()
            pinned = {"binary_sha256": digest, "binary_size_bytes": len(original)}
            with runner._ExecutableLease(path, pinned, digest) as lease:
                replacement = Path(directory) / "replacement"
                replacement.write_bytes(b"replacement")
                os.replace(replacement, path)
                self.assertEqual(lease.pass_fds, (lease._fd,))
                self.assertEqual(Path(lease.execution_path).read_bytes(), original)
                self.assertEqual(path.read_bytes(), b"replacement")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux sealed executable regression")
    def test_linux_executable_lease_is_immune_to_in_place_staged_file_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "binary"
            original = b"verified-executable-bytes"
            replacement = b"same-inode-replacement"
            path.write_bytes(original)
            digest = "sha256:" + hashlib.sha256(original).hexdigest()
            pinned = {"binary_sha256": digest, "binary_size_bytes": len(original)}
            with runner._ExecutableLease(path, pinned, digest) as lease:
                path.write_bytes(replacement)
                self.assertEqual(path.read_bytes(), replacement)
                self.assertEqual(Path(lease.execution_path).read_bytes(), original)
                with self.assertRaises(OSError):
                    Path(lease.execution_path).write_bytes(b"attempted-mutation")
                self.assertEqual(Path(lease.execution_path).read_bytes(), original)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux memfd policy regression")
    def test_linux_memfd_requests_exec_and_falls_back_only_for_older_kernel(self):
        fake_fd = 123456
        with mock.patch.object(
            runner.os,
            "memfd_create",
            side_effect=[OSError(errno.EINVAL, "unknown MFD_EXEC"), fake_fd],
        ) as create:
            self.assertEqual(runner._create_linux_executable_memfd(), fake_fd)
        first_flags = create.call_args_list[0].kwargs["flags"]
        second_flags = create.call_args_list[1].kwargs["flags"]
        self.assertTrue(first_flags & 0x0010)
        self.assertFalse(second_flags & 0x0010)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux memfd policy regression")
    def test_linux_memfd_reports_noexec_policy_explicitly(self):
        with mock.patch.object(
            runner.os,
            "memfd_create",
            side_effect=OSError(errno.EACCES, "memfd execution denied"),
        ):
            with self.assertRaisesRegex(runner.TargetRunError, "vm.memfd_noexec=2"):
                runner._create_linux_executable_memfd()

    @unittest.skipUnless(os.name == "nt", "Windows executable lease regression")
    def test_windows_executable_lease_blocks_path_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "binary.exe"
            original = b"verified-executable-bytes"
            path.write_bytes(original)
            digest = "sha256:" + hashlib.sha256(original).hexdigest()
            pinned = {"binary_sha256": digest, "binary_size_bytes": len(original)}
            with runner._ExecutableLease(path, pinned, digest):
                with self.assertRaises(OSError):
                    path.write_bytes(b"replacement")

    def test_original_command_identity_replaces_ephemeral_staged_digest_in_zip(self):
        original = b'{"argv":["operator/path","target"]}\n'
        stable = runner._sha256_bytes(original)
        manifest = {"execution": {"command_argv_sha256": "sha256:" + "0" * 64}}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run.zip"
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("run-manifest.json", b"{}")
                archive.writestr("scenario.json", b"{}")
            with mock.patch.object(runner._legacy, "validate_run_manifest"):
                result = runner._restore_original_command_identity(output, manifest, original)
            self.assertEqual(result["execution"]["command_argv_sha256"], stable)
            with zipfile.ZipFile(output, "r") as archive:
                packaged = json.loads(archive.read("run-manifest.json"))
            self.assertEqual(packaged["execution"]["command_argv_sha256"], stable)

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
        self.assertEqual(runner.RUNNER_VERSION, "1.10.0")
        self.assertEqual(runner._legacy.RUNNER_VERSION, "1.10.0")
        self.assertEqual(runner.PINNED_BUILD_WORKFLOW_RUN_ID, 31742892228)


if __name__ == "__main__":
    unittest.main()
