import copy
import hashlib
import json
import sys
import tempfile
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


class ContractTests(unittest.TestCase):
    def test_strict_json_rejects_duplicate_members(self):
        with self.assertRaisesRegex(runner.TargetRunError, "duplicate JSON member"):
            runner.loads_strict('{"argv": [], "argv": []}')

    def test_scenario_rejects_absolute_or_parent_paths(self):
        scenario = {
            "schema_id": runner.SCENARIO_SCHEMA_ID,
            "schema_version": 1,
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
            "schema_version": 1,
            "argv": ["emulator"],
            "emulator_binary_index": 0,
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


@unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is not installed")
class RunTests(unittest.TestCase):
    def test_run_creates_bounded_safe_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_root = root / "target-root"
            workdir = root / "isolated-work"
            target_root.mkdir()
            workdir.mkdir()
            output = root / "artifacts" / "run-synthetic.zip"
            config = root / "emulator-config.toml"
            config.write_text("private-config-value = true\n", encoding="utf-8")

            oracle_bytes = b"oracle-ok"
            oracle_sha256 = "sha256:" + hashlib.sha256(oracle_bytes).hexdigest()
            scenario = {
                "schema_id": runner.SCENARIO_SCHEMA_ID,
                "schema_version": 1,
                "scenario_id": "synthetic-smoke",
                "description": "Synthetic runner capability control; not target evidence.",
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
                "schema_version": 1,
                "argv": [
                    str(binary),
                    "-c",
                    (
                        "from pathlib import Path; import json; "
                        "p=Path('results'); p.mkdir(); "
                        "(p/'oracle.bin').write_bytes(b'oracle-ok'); "
                        "(p/'summary.json').write_text(json.dumps({'token':'private-token', 'path':r'C:\\Users\\alice\\capture.json', 'ok':True}), encoding='utf-8')"
                    ),
                ],
                "emulator_binary_index": 0,
            }
            command_path = root / "command.json"
            command_path.write_bytes(runner._json_bytes(command))

            manifest = runner.run_experiment(
                target_manifest_path=TARGET_EXAMPLE,
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

                packaged_manifest = runner.loads_strict(
                    archive.read("run-manifest.json").decode("utf-8")
                )
                runner.validate_run_manifest(packaged_manifest)


if __name__ == "__main__":
    unittest.main()
