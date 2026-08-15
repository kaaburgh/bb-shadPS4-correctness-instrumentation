import copy
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from tools import run_target_experiment as runner


ROOT = Path(__file__).parents[1]
TARGET_EXAMPLE = ROOT / "docs" / "baseline" / "examples" / "bloodborne-target-manifest.synthetic.json"

try:
    import jsonschema  # noqa: F401
except ModuleNotFoundError:
    HAS_JSONSCHEMA = False
else:
    HAS_JSONSCHEMA = True


def _write_bound_target_fixture(root: Path) -> tuple[Path, Path]:
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

    manifest = json.loads(TARGET_EXAMPLE.read_text(encoding="utf-8"))
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


class ContractTests(unittest.TestCase):
    def test_strict_json_rejects_duplicate_members(self):
        with self.assertRaisesRegex(runner.TargetRunError, "duplicate JSON member"):
            runner.loads_strict('{"argv": [], "argv": []}')

    def test_scenario_rejects_absolute_or_parent_paths(self):
        scenario = {
            "schema_id": runner.SCENARIO_SCHEMA_ID,
            "schema_version": runner.SCENARIO_SCHEMA_VERSION,
            "scenario_id": "synthetic",
            "description": "synthetic contract",
            "timeout_seconds": 10,
            "oracle": {"kind": "file-sha256", "path": "results/oracle", "sha256": "sha256:" + "a" * 64},
            "artifacts": [],
        }
        for path in ("/absolute/file", "../outside", "results/../outside", "C:/outside"):
            with self.subTest(path=path):
                candidate = copy.deepcopy(scenario)
                candidate["oracle"]["path"] = path
                with self.assertRaises(runner.TargetRunError):
                    runner.validate_scenario(candidate)

    def test_command_contract_has_no_shell_or_environment_escape_hatch(self):
        command = {
            "schema_id": runner.COMMAND_SCHEMA_ID,
            "schema_version": runner.COMMAND_SCHEMA_VERSION,
            "argv": ["emulator", "target"],
            "emulator_binary_index": 0,
            "target_path_index": 1,
            "shell": True,
        }
        with self.assertRaisesRegex(runner.TargetRunError, "unexpected fields"):
            runner.validate_command(command)

    def test_redaction_masks_sensitive_keys_and_private_paths(self):
        value = {
            "token": "secret-value",
            "path": r"C:\Users\alice\private\capture.json",
            "safe_sha256": "sha256:" + "a" * 64,
            "nested": [{"message": "/home/alice/private/output.json"}],
        }
        redacted = runner._redact_json(value)
        self.assertEqual(redacted["token"], "<redacted>")
        self.assertEqual(redacted["path"], "<redacted>")
        self.assertEqual(redacted["safe_sha256"], value["safe_sha256"])
        self.assertNotIn("alice", json.dumps(redacted))

    def test_embedded_json_rejects_fields_outside_explicit_allowlist(self):
        allowlist = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "summary.json"
            artifact.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "session": "credential-like-value",
                        "mount": "/mnt/private-target/secret",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(runner.TargetRunError, "outside the artifact allowlist"):
                runner._redact_json_artifact(
                    artifact,
                    maximum=4096,
                    allowlist=allowlist,
                )

    def test_redacted_json_requires_an_allowlist(self):
        scenario = {
            "schema_id": runner.SCENARIO_SCHEMA_ID,
            "schema_version": 2,
            "scenario_id": "synthetic",
            "description": "synthetic contract",
            "timeout_seconds": 10,
            "oracle": {
                "kind": "process-exit",
                "expected_exit_code": 0,
            },
            "artifacts": [
                {
                    "path": "results/summary.json",
                    "name": "summary",
                    "mode": "redacted-json",
                    "max_bytes": 4096,
                }
            ],
        }
        with self.assertRaisesRegex(runner.TargetRunError, "unexpected fields"):
            runner.validate_scenario(scenario)

    def test_process_output_and_runtime_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory)
            noisy = runner._execute_command(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.buffer.write(b'x' * 17000000)",
                ],
                workdir,
                30,
            )
            self.assertTrue(noisy["stdout_truncated"])
            self.assertEqual(noisy["stdout_bytes"], runner.MAX_PROCESS_OUTPUT_BYTES)

            timed_out = runner._execute_command(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                workdir,
                1,
            )
            self.assertTrue(timed_out["timed_out"])
            self.assertLess(timed_out["elapsed_seconds"], 5)

    @unittest.skipUnless(os.name == "posix", "POSIX process-group regression")
    def test_parent_exit_does_not_leave_descendant_or_inherited_pipe(self):
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory)
            parent_code = (
                "from pathlib import Path; import subprocess, sys; "
                "child = subprocess.Popen([sys.executable, '-c', sys.argv[1]]); "
                "Path('child.pid').write_text(str(child.pid), encoding='ascii')"
            )
            child_code = "import time; time.sleep(30)"
            execution = runner._execute_command(
                [sys.executable, "-c", parent_code, child_code],
                workdir,
                10,
            )
            child_pid = int((workdir / "child.pid").read_text(encoding="ascii"))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                try:
                    os.kill(child_pid, 9)
                except ProcessLookupError:
                    pass
                self.fail("launcher descendant outlived the bounded process group")
            self.assertEqual(execution["process_tree_control"], "posix-process-group")
            self.assertLess(execution["elapsed_seconds"], 5)

    def test_preexisting_declared_output_is_rejected(self):
        scenario = {
            "schema_id": runner.SCENARIO_SCHEMA_ID,
            "schema_version": 2,
            "scenario_id": "synthetic",
            "description": "synthetic contract",
            "timeout_seconds": 10,
            "oracle": {
                "kind": "file-sha256",
                "path": "results/oracle.bin",
                "sha256": "sha256:" + "a" * 64,
            },
            "artifacts": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory)
            (workdir / "results").mkdir()
            (workdir / "results" / "oracle.bin").write_bytes(b"stale")
            runner.validate_scenario(scenario)
            with self.assertRaisesRegex(runner.TargetRunError, "must not exist before execution"):
                runner._preflight_declared_outputs(scenario, workdir)

            process_exit = copy.deepcopy(scenario)
            process_exit["oracle"] = {"kind": "process-exit", "expected_exit_code": 0}
            runner.validate_scenario(process_exit)
            runner._preflight_declared_outputs(process_exit, workdir)


@unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is not installed")
class RunTests(unittest.TestCase):
    def test_run_creates_bounded_safe_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_root, target_manifest_path = _write_bound_target_fixture(root)
            workdir = root / "isolated-work"
            workdir.mkdir()
            output = root / "artifacts" / "run-synthetic.zip"
            config = root / "emulator-config.toml"
            config.write_text("private-config-value = true\n", encoding="utf-8")

            oracle_bytes = b"oracle-ok"
            oracle_sha256 = "sha256:" + hashlib.sha256(oracle_bytes).hexdigest()
            scenario = {
                "schema_id": runner.SCENARIO_SCHEMA_ID,
                "schema_version": runner.SCENARIO_SCHEMA_VERSION,
                "scenario_id": "synthetic-smoke",
                "description": "Operator alice /home/alice/private token=top-secret; synthetic only.",
                "timeout_seconds": 30,
                "oracle": {
                    "kind": "file-sha256",
                    "path": "results/oracle.bin",
                    "sha256": oracle_sha256,
                },
                "artifacts": [
                    {
                        "path": "results/summary.json",
                        "name": "summary",
                        "mode": "redacted-json",
                        "max_bytes": 4096,
                        "allowlist": {
                            "type": "object",
                            "properties": {
                                "checkpoint": {
                                    "type": "string",
                                    "max_length": 128,
                                },
                                "ok": {"type": "boolean"},
                            },
                            "required": ["checkpoint", "ok"],
                            "additionalProperties": False,
                        },
                    },
                    {
                        "path": "results/oracle.bin",
                        "name": "oracle-bytes",
                        "mode": "metadata-only",
                        "max_bytes": 4096,
                    },
                ],
            }
            scenario_path = root / "scenario.json"
            scenario_path.write_bytes(runner._json_bytes(scenario))

            binary = Path(sys.executable).resolve()
            binary_sha256 = hashlib.sha256(binary.read_bytes()).hexdigest()
            command = {
                "schema_id": runner.COMMAND_SCHEMA_ID,
                "schema_version": runner.COMMAND_SCHEMA_VERSION,
                "argv": [
                    str(binary),
                    "-c",
                    (
                        "from pathlib import Path; import json; "
                        "p=Path('results'); p.mkdir(); "
                        "(p/'oracle.bin').write_bytes(b'oracle-ok'); "
                        "(p/'summary.json').write_text(json.dumps({'checkpoint':r'C:\\Users\\alice\\capture.json', 'ok':True}), encoding='utf-8')"
                    ),
                    str(target_root / "app"),
                ],
                "emulator_binary_index": 0,
                "target_path_index": 3,
            }
            command_path = root / "command.json"
            command_path.write_bytes(runner._json_bytes(command))

            target_manifest = json.loads(target_manifest_path.read_text(encoding="utf-8"))
            mismatched_manifest = copy.deepcopy(target_manifest)
            mismatched_manifest["build"]["eboot"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(runner.TargetRunError, "eboot.bin does not match"):
                runner._verify_target_root(target_root.resolve(), mismatched_manifest)

            wrong_command = copy.deepcopy(command)
            other_target = root / "other-target"
            other_target.mkdir()
            wrong_command["argv"][wrong_command["target_path_index"]] = str(other_target)
            app_root, eboot = runner._verify_target_root(target_root.resolve(), target_manifest)
            with self.assertRaisesRegex(runner.TargetRunError, "does not identify the verified target"):
                runner._bind_command_target(wrong_command, workdir.resolve(), app_root, eboot)

            manifest = runner.run_experiment(
                target_manifest_path=target_manifest_path,
                scenario_path=scenario_path,
                command_path=command_path,
                emulator_binary_path=binary,
                emulator_binary_sha256=binary_sha256,
                source_repository=runner.PINNED_SOURCE_REPOSITORY,
                source_commit=runner.PINNED_SOURCE_COMMIT,
                source_tree=runner.PINNED_SOURCE_TREE,
                patch_commits=[],
                target_root=target_root,
                working_directory=workdir,
                output_path=output,
                graphics_backend="synthetic",
                emulator_config_path=config,
            )

            self.assertEqual(manifest["termination"]["state"], "completed")
            self.assertEqual(manifest["oracle"]["state"], "passed")
            self.assertEqual(manifest["packaging"]["state"], "complete")
            self.assertEqual(manifest["redaction"]["raw_process_output"], "excluded")
            self.assertTrue(manifest["execution"]["declared_outputs_preflighted"])
            self.assertEqual(
                manifest["execution"]["process_tree_control"],
                "posix-process-group" if os.name == "posix" else "windows-job-object",
            )
            self.assertTrue(output.is_file())

            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertEqual(
                    names,
                    {
                        "run-manifest.json",
                        "target-manifest.json",
                        "host-environment.json",
                        "scenario.json",
                        "artifacts/summary.redacted.json",
                    },
                )
                self.assertNotIn("command.json", names)
                self.assertNotIn("emulator-config.toml", names)
                redacted = archive.read("artifacts/summary.redacted.json").decode("utf-8")
                self.assertNotIn("private-token", redacted)
                self.assertNotIn("alice", redacted)
                self.assertNotIn("C:\\", redacted)

                packaged_scenario_raw = archive.read("scenario.json")
                packaged_scenario_text = packaged_scenario_raw.decode("utf-8")
                packaged_scenario = runner.loads_strict(packaged_scenario_text)
                self.assertEqual(
                    packaged_scenario["description"],
                    "<redacted-operator-description>",
                )
                self.assertNotIn("alice", packaged_scenario_text)
                self.assertNotIn("top-secret", packaged_scenario_text)
                self.assertEqual(
                    manifest["scenario"]["input_sha256"],
                    runner._sha256_bytes(scenario_path.read_bytes()),
                )
                self.assertNotEqual(packaged_scenario_raw, scenario_path.read_bytes())

                packaged_manifest = runner.loads_strict(
                    archive.read("run-manifest.json").decode("utf-8")
                )
                runner.validate_run_manifest(packaged_manifest)


if __name__ == "__main__":
    unittest.main()
