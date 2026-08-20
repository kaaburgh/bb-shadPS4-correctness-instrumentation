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


def _write_bound_target_fixture(root: Path, *, runtime_classified: bool = False) -> tuple[Path, Path]:
    target_root = root / "target-root"
    payloads = {
        "app/eboot.bin": b"synthetic-eboot",
        "app/sce_sys/param.sfo": b"synthetic-param-sfo",
        "app/data/control.bin": b"synthetic-content",
    }
    for relative, payload in payloads.items():
        path = target_root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    manifest = _manifest()
    if runtime_classified:
        manifest["provenance"]["evidence_classes"] = ["runtime"]
    manifest["build"]["eboot"]["sha256"] = hashlib.sha256(payloads["app/eboot.bin"]).hexdigest()
    manifest["build"]["eboot"]["size_bytes"] = len(payloads["app/eboot.bin"])
    manifest["build"]["param_sfo"]["sha256"] = hashlib.sha256(
        payloads["app/sce_sys/param.sfo"]
    ).hexdigest()
    manifest["build"]["param_sfo"]["size_bytes"] = len(
        payloads["app/sce_sys/param.sfo"]
    )
    records = []
    total_bytes = 0
    for canonical_path, payload in payloads.items():
        digest = hashlib.sha256(payload).hexdigest()
        total_bytes += len(payload)
        records.append(
            (
                canonical_path.encode("utf-8"),
                canonical_path.encode("utf-8")
                + b"\x00"
                + str(len(payload)).encode("ascii")
                + b"\x00"
                + digest.encode("ascii")
                + b"\n",
            )
        )
    records.sort(key=lambda item: item[0])
    tree = manifest["content"]["resolved_tree"]
    tree["sha256"] = hashlib.sha256(b"".join(record for _path, record in records)).hexdigest()
    tree["file_count"] = len(records)
    tree["total_bytes"] = total_bytes
    manifest_path = root / "target-manifest.json"
    manifest_path.write_bytes(runner._json_bytes(manifest))
    return target_root, manifest_path


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
            ([sys.executable, "-m", "tools.run_target_experiment_v3", "--help"], 2),
            ([sys.executable, "tools/run_target_experiment_v3.py", "--help"], None),
        )
        for argv, expected_returncode in invocations:
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
                if expected_returncode is None:
                    self.assertNotEqual(completed.returncode, 0)
                else:
                    self.assertEqual(completed.returncode, expected_returncode)
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

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux non-synthetic branch regression")
    def test_linux_non_synthetic_staged_binary_executes_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_root, target_manifest_path = _write_bound_target_fixture(
                root, runtime_classified=True
            )
            workdir = root / "work"
            workdir.mkdir()
            output = root / "run.zip"

            standin = root / "standin-emulator"
            standin.write_text(
                "#!/usr/bin/env python3\nraise SystemExit(0)\n",
                encoding="utf-8",
            )
            standin_sha256 = hashlib.sha256(standin.read_bytes()).hexdigest()
            pinned = {
                "binary_name": "standin-emulator",
                "binary_sha256": "sha256:" + standin_sha256,
                "binary_size_bytes": standin.stat().st_size,
            }

            scenario_path = root / "scenario.json"
            scenario_path.write_bytes(runner._json_bytes(_scenario()))
            command = {
                "schema_id": runner.COMMAND_SCHEMA_ID,
                "schema_version": runner.COMMAND_SCHEMA_VERSION,
                "argv": [str(standin), str(target_root / "app")],
                "emulator_binary_index": 0,
                "target_path_index": 1,
            }
            command_path = root / "command.json"
            command_path.write_bytes(runner._json_bytes(command))

            with mock.patch.dict(
                runner.PINNED_BUILD_ARTIFACTS,
                {"linux": pinned},
                clear=False,
            ):
                manifest = runner.run_experiment(
                    target_manifest_path=target_manifest_path,
                    scenario_path=scenario_path,
                    command_path=command_path,
                    emulator_binary_path=standin,
                    emulator_binary_sha256=standin_sha256,
                    source_repository=runner.PINNED_SOURCE_REPOSITORY,
                    source_commit=runner.PINNED_SOURCE_COMMIT,
                    source_tree=runner.PINNED_SOURCE_TREE,
                    patch_commits=[],
                    target_root=target_root,
                    working_directory=workdir,
                    output_path=output,
                    graphics_backend="synthetic",
                    emulator_config_path=None,
                )

            self.assertFalse(runner._is_explicit_synthetic_control(
                json.loads(target_manifest_path.read_text(encoding="utf-8"))
            ))
            self.assertEqual(manifest["termination"]["state"], "completed")
            self.assertEqual(manifest["oracle"]["state"], "passed")
            self.assertEqual(manifest["provenance"]["producer"]["version"], "1.11.0")
            self.assertEqual(manifest["emulator"]["binary"]["sha256"], "sha256:" + standin_sha256)
            self.assertTrue(output.is_file())

    def test_removed_sealing_symbols_do_not_reappear(self):
        for name in (
            "_ExecutableLease",
            "_sha256_fd",
            "_create_linux_executable_memfd",
            "_sealed_linux_executable",
            "_execute_command_with_pass_fds",
        ):
            with self.subTest(name=name):
                self.assertFalse(hasattr(runner, name))

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

    def test_runner_version_identifies_supported_entrypoint(self):
        self.assertEqual(runner.RUNNER_VERSION, "1.11.0")
        self.assertEqual(runner._legacy.RUNNER_VERSION, "1.11.0")
        self.assertEqual(runner.PINNED_BUILD_WORKFLOW_RUN_ID, 31742892228)


if __name__ == "__main__":
    unittest.main()
