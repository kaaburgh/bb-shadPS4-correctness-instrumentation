import json
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tools import run_target_experiment as runner


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

    def test_target_manifest_rejects_unapproved_private_string_setting(self):
        manifest = {
            "configuration": {
                "settings": {
                    "operator.private": {
                        "value": "/home/alice/private/credential.txt",
                        "evidence_class": "static",
                    }
                }
            }
        }
        with self.assertRaisesRegex(runner.TargetRunError, "not approved for safe packaging"):
            runner._validate_target_manifest_safe_for_package(manifest)

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
            workdir = Path(directory)
            (workdir / "summary.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            entries, embedded, warnings = runner._collect_artifacts(scenario, workdir)
            self.assertEqual(warnings, [])
            payload = embedded["artifacts/summary.redacted.json"]
            self.assertEqual(entries[0]["packaged_sha256"], runner._sha256_bytes(payload))
            self.assertEqual(entries[0]["packaged_size_bytes"], len(payload))

    def test_schema_allows_bounded_teardown_margin(self):
        schema = json.loads(runner.RUN_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["properties"]["termination"]["properties"]["elapsed_seconds"]["maximum"],
            runner.MAX_RECORDED_ELAPSED_SECONDS,
        )
        required = schema["properties"]["artifacts"]["items"]["required"]
        self.assertIn("packaged_sha256", required)
        self.assertIn("packaged_size_bytes", required)


if __name__ == "__main__":
    unittest.main()
