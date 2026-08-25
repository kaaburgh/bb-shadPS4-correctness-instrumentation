import copy
import json
import os
import signal
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from tools import run_target_experiment as runner


ROOT = Path(__file__).parents[1]
TARGET_EXAMPLE = ROOT / "docs" / "baseline" / "examples" / "bloodborne-target-manifest.synthetic.json"


class HardeningRegressionTests(unittest.TestCase):
    def test_exponent_overflow_is_rejected_during_strict_parse(self):
        with self.assertRaisesRegex(runner.TargetRunError, "non-finite JSON number"):
            runner.loads_strict('{"value": 1e10000}')

    def test_verified_emulator_must_be_argv0(self):
        command = {
            "schema_id": runner.COMMAND_SCHEMA_ID,
            "schema_version": runner.COMMAND_SCHEMA_VERSION,
            "argv": ["wrapper", "shadps4", "target"],
            "emulator_binary_index": 1,
            "target_path_index": 2,
        }
        with self.assertRaisesRegex(runner.TargetRunError, "must be 0"):
            runner.validate_command(command)

    def test_target_manifest_projection_rejects_unregistered_setting_and_redacts_descriptions(self):
        manifest = json.loads(TARGET_EXAMPLE.read_text(encoding="utf-8"))
        private = copy.deepcopy(manifest)
        private["configuration"]["settings"]["operator.private"] = {
            "value": "hunter2",
            "evidence_class": "static",
        }
        with self.assertRaisesRegex(runner.TargetRunError, "not approved for safe packaging"):
            runner._package_target_manifest(private)

        manifest["provenance"]["producer"]["version"] = "hunter2"
        manifest["build"]["app_version"] = "hunter2"
        manifest["content"]["base"]["version"] = "hunter2"
        packaged = runner._package_target_manifest(manifest)
        self.assertNotIn(b"hunter2", packaged)
        projected = runner.loads_strict(packaged.decode("utf-8"))
        self.assertIsNone(projected["build"]["app_version"])
        self.assertIsNone(projected["content"]["base"]["version"])

    def test_allowlisted_strings_require_registered_enum_literals(self):
        with self.assertRaisesRegex(runner.TargetRunError, "unexpected fields"):
            runner._validate_json_allowlist(
                {"type": "string", "max_length": 128},
                "artifact.allowlist",
            )
        with self.assertRaisesRegex(runner.TargetRunError, "unapproved"):
            runner._validate_json_allowlist(
                {"type": "string", "enum": ["/mnt/operators/alice/secret.capture"]},
                "artifact.allowlist",
            )
        schema = {"type": "string", "enum": ["synthetic-checkpoint"]}
        runner._validate_json_allowlist(schema, "artifact.allowlist")
        with self.assertRaisesRegex(runner.TargetRunError, "enumerated string"):
            runner._project_allowlisted_json("hunter2", schema)

    def test_unattested_emulator_config_is_rejected(self):
        with self.assertRaisesRegex(runner.TargetRunError, "cannot be attested"):
            runner._require_attestable_emulator_config(Path("private-config.toml"))
        runner._require_attestable_emulator_config(None)

    def test_patched_build_must_be_fully_identified(self):
        """A patch stack is recorded only when the built tree can be reconstructed."""
        head, tree = "a" * 40, "b" * 40
        fork = "https://github.com/maintainer/shadPS4"

        self.assertEqual(
            runner._normalize_patched_source([], None, None, None), {"patch_commits": []}
        )
        self.assertEqual(
            runner._normalize_patched_source([head], fork, head, tree),
            {
                "patch_commits": [head],
                "patch_repository": fork,
                "effective_head": head,
                "effective_tree": tree,
            },
        )

        with self.assertRaisesRegex(runner.TargetRunError, "40-character"):
            runner._normalize_patched_source(["not-a-sha"], fork, head, tree)
        with self.assertRaisesRegex(runner.TargetRunError, "must be unique"):
            runner._normalize_patched_source([head, head], fork, head, tree)
        for absent in ("patch_repository", "effective_head", "effective_tree"):
            supplied = {
                "patch_repository": fork,
                "effective_head": head,
                "effective_tree": tree,
            }
            supplied[absent] = None
            with self.subTest(missing=absent):
                with self.assertRaisesRegex(
                    runner.TargetRunError, f"fully identified; missing {absent}"
                ):
                    runner._normalize_patched_source([head], **supplied)
        with self.assertRaisesRegex(runner.TargetRunError, "must not declare"):
            runner._normalize_patched_source([], fork, None, None)
        with self.assertRaisesRegex(runner.TargetRunError, "https URL"):
            runner._normalize_patched_source([head], "git@github.com:me/x", head, tree)

    def test_a_patch_stack_that_changes_nothing_is_rejected(self):
        """Baseline commit/tree in the effective slots means no patch was applied."""
        head, tree = "a" * 40, "b" * 40
        fork = "https://github.com/maintainer/shadPS4"
        with self.assertRaisesRegex(runner.TargetRunError, "changes nothing"):
            runner._normalize_patched_source(
                [head], fork, runner.PINNED_SOURCE_COMMIT, tree
            )
        with self.assertRaisesRegex(runner.TargetRunError, "changes nothing"):
            runner._normalize_patched_source(
                [head], fork, head, runner.PINNED_SOURCE_TREE
            )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux subreaper regression")
    def test_strong_containment_reaps_detached_session_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory)
            parent_code = (
                "from pathlib import Path; import subprocess, sys; "
                "child=subprocess.Popen([sys.executable,'-c',sys.argv[1]], start_new_session=True); "
                "Path('child.pid').write_text(str(child.pid), encoding='ascii')"
            )
            execution = runner._execute_command(
                [sys.executable, "-c", parent_code, "import time; time.sleep(30)"],
                workdir,
                10,
                require_detached_containment=True,
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
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.fail("detached descendant outlived strong containment")
            self.assertEqual(execution["process_tree_control"], "posix-process-group")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux cleanup regression")
    def test_interrupted_wait_still_terminates_posix_process_group(self):
        original_wait = runner.subprocess.Popen.wait
        interrupted_pids: list[int] = []

        def interrupt_once(process, timeout=None):
            if timeout == 10 and process.pid not in interrupted_pids:
                interrupted_pids.append(process.pid)
                raise KeyboardInterrupt()
            return original_wait(process, timeout=timeout)

        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory).resolve()
            with mock.patch.object(runner.subprocess.Popen, "wait", interrupt_once):
                with self.assertRaises(KeyboardInterrupt):
                    runner._execute_command(
                        [sys.executable, "-c", "import time; time.sleep(30)"],
                        workdir,
                        10,
                        require_detached_containment=True,
                    )
            self.assertEqual(len(interrupted_pids), 1)
            with self.assertRaises(ProcessLookupError):
                os.kill(interrupted_pids[0], 0)

    def test_redacted_artifact_records_packaged_payload_digest(self):
        scenario = {
            "artifacts": [
                {
                    "path": "summary.json",
                    "name": "summary",
                    "mode": "redacted-json",
                    "max_bytes": 4096,
                    "allowlist": {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    },
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory).resolve()
            (workdir / "summary.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            entries, embedded, warnings = runner._collect_artifacts(scenario, workdir)
            self.assertEqual(warnings, [])
            payload = embedded["artifacts/artifact-00.redacted.json"]
            self.assertEqual(entries[0]["packaged_sha256"], runner._sha256_bytes(payload))
            self.assertEqual(entries[0]["packaged_size_bytes"], len(payload))

    def test_schema_allows_bounded_teardown_margin(self):
        schema = json.loads(runner.RUN_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["properties"]["termination"]["properties"]["elapsed_seconds"]["maximum"],
            runner.MAX_RECORDED_ELAPSED_SECONDS,
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], runner.RUN_SCHEMA_VERSION)
        self.assertEqual(schema["properties"]["emulator"]["properties"]["config_sha256"], {"type": "null"})
        self.assertIn("packaged_manifest_sha256", schema["properties"]["target"]["required"])
        self.assertIn("packaged_sha256", schema["properties"]["scenario"]["required"])
        required = schema["properties"]["artifacts"]["items"]["required"]
        self.assertIn("packaged_sha256", required)
        self.assertIn("packaged_size_bytes", required)
        source_schema = schema["properties"]["emulator"]["properties"]["source"]
        self.assertEqual(source_schema["properties"]["patch_commits"]["uniqueItems"], True)
        # A patched build is admissible, but only fully identified.
        self.assertEqual(
            source_schema["then"]["required"],
            ["patch_repository", "effective_head", "effective_tree"],
        )
        self.assertEqual(
            source_schema["else"]["properties"],
            {"patch_repository": False, "effective_head": False, "effective_tree": False},
        )


if __name__ == "__main__":
    unittest.main()
