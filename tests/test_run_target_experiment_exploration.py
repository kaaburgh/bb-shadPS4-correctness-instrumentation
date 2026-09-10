"""Real incremental-build and execution controls; no Bloodborne runtime claims."""
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock
import zipfile

from tests import test_shadps4_build_manifest as strict_tests
from tools import run_target_experiment as runner
from tools import prepare_env1_target_copy as target_copy


@unittest.skipUnless((os.name == "nt" or sys.platform.startswith("linux"))
                     and shutil.which("cmake") and shutil.which("ninja") and shutil.which("cc"),
                     "CMake/Ninja/compiler and supported process containment required")
class ExplorationTests(unittest.TestCase):
    def setUp(self):
        # Reuse only fixture preparation, keeping strict #130 regressions intact.
        self.fixture = strict_tests.BuildAdmissionTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.args = self.fixture.run_args()
        original = self.args["target_root"]
        disposable = self.fixture.root / "disposable"
        target_copy.prepare(original / "app", disposable, target_copy.identity(original / "app"))
        command = json.loads(self.args["command_path"].read_text())
        command["argv"][1] = str(disposable / "app")
        self.args["command_path"].write_bytes(runner._json_bytes(command))
        self.args["target_root"] = disposable

    def exploratory_args(self):
        args = dict(self.args)
        for key in ("build_manifest_path", "source_repository", "source_commit", "source_tree",
                    "emulator_binary_sha256"):
            args.pop(key)
        return args

    def test_dirty_incremental_binary_reused_copy_and_promotion_rejection(self):
        fixture = self.fixture
        (fixture.source / "main.c").write_text(
            '#include <stdio.h>\nint main(void) { FILE *f=fopen("observed.txt", "w"); '
            'if (!f) return 3; fputs("diagnostic",f); fclose(f); return 0; }\n')
        subprocess.run(["cmake", "--build", str(fixture.binary.parent)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(fixture.git("status", "--porcelain"), "")
        args = self.exploratory_args()
        args["patch_commits"] = ["a" * 40]  # declaration, deliberately not a Git chain
        args["source_commit"] = "b" * 40  # not the pinned baseline
        # Existing generated state and changed disposable target need no full re-hash.
        (args["target_root"] / "app/data/control.bin").write_bytes(b"modified working state")
        (args["working_directory"] / "previous-capture.bin").write_bytes(b"old capture")
        for iteration in range(2):
            args["output_path"] = fixture.root / f"explore-{iteration}.zip"
            with mock.patch.object(runner._legacy, "_verify_target_root", side_effect=AssertionError("expensive pass")), \
                 mock.patch.object(runner, "_stage_emulator_binary", side_effect=AssertionError("unneeded staging")):
                record = runner.run_experiment(**args)
            self.assertEqual(record["termination"]["state"], "completed")
            self.assertEqual(record["evidence_classification"], "exploratory-unverified")
            self.assertEqual(record["target"]["post_run_tree_state"], "not_checked")
            self.assertEqual(record["target"]["identity_state"], "unverified")
            self.assertNotIn("source", record["emulator"])
            self.assertNotIn("build_provenance", record["emulator"])
            self.assertEqual(record["emulator"]["source_observation"]["commit"], "b" * 40)
            self.assertIsNone(record["emulator"]["source_observation"]["tree"])
            self.assertEqual(record["emulator"]["binary"], {
                "sha256": "sha256:" + hashlib.sha256(fixture.binary.read_bytes()).hexdigest(),
                "size_bytes": fixture.binary.stat().st_size})
            with zipfile.ZipFile(args["output_path"]) as archive:
                self.assertEqual(json.loads(archive.read("run-manifest.json")), record)
                self.assertNotIn(str(fixture.root), archive.read("run-manifest.json").decode())
            self.assertEqual((args["working_directory"] / "observed.txt").read_text(), "diagnostic")
            runner.validate_run_manifest(record)
            with self.assertRaisesRegex(runner.TargetRunError, "promotion requires"):
                runner.require_promotion_evidence(record)
        # A passed current-run file hash and artifact remain exploratory too.
        work = args["working_directory"]
        (work / "observed.txt").rename(work / "previous-observation.txt")
        scenario = json.loads(args["scenario_path"].read_text())
        scenario["oracle"] = {"kind": "file-sha256", "path": "observed.txt",
                              "sha256": "sha256:" + hashlib.sha256(b"diagnostic").hexdigest()}
        scenario["artifacts"] = [{"path": "observed.txt", "name": "observation",
                                 "mode": "metadata-only", "max_bytes": 1024}]
        args["scenario_path"].write_bytes(runner._json_bytes(scenario))
        record = runner.run_experiment(**args)
        self.assertEqual(record["oracle"]["state"], "passed")
        self.assertEqual(record["artifacts"][0]["status"], "externalized")
        self.assertEqual(record["evidence_classification"], "exploratory-unverified")
        with self.assertRaises(runner.TargetRunError):
            runner.require_promotion_evidence(record)
        # Same dirty binary/source cannot be admitted by supplying its old strict manifest.
        with self.assertRaises(runner.TargetRunError):
            runner.run_experiment(**self.args)

        for mutate in (
            lambda r: r.update(evidence_classification="verification-candidate"),
            lambda r: r["emulator"].update(admission="source-build"),
            lambda r: r["emulator"].update(build_provenance={}),
            lambda r: r["target"].update(post_run_tree_state="verified"),
            lambda r: r.pop("evidence_classification"),
            lambda r: r.update(schema_version=3),
        ):
            changed = copy.deepcopy(record)
            mutate(changed)
            with self.assertRaises(runner.TargetRunError):
                runner.validate_run_manifest(changed)

    def test_minimal_cli_no_checkout_or_manifest_and_file_observation(self):
        args = self.exploratory_args()
        # The existing binary writes no file: metadata remains a failed observation,
        # not a provenance admission error. Reuse of unrelated files is allowed.
        scenario = json.loads(args["scenario_path"].read_text())
        scenario["oracle"] = {"kind": "file-sha256", "path": "new-output.bin",
                              "sha256": "sha256:" + "a" * 64}
        scenario["artifacts"] = [{"path": "new-summary.json", "name": "summary",
                                 "mode": "metadata-only", "max_bytes": 4096}]
        args["scenario_path"].write_bytes(runner._json_bytes(scenario))
        argv = ["run"]
        for key, flag in (("target_manifest_path", "target-manifest"), ("scenario_path", "scenario"),
                          ("command_path", "command-file"), ("emulator_binary_path", "emulator-binary"),
                          ("target_root", "target-root"), ("working_directory", "working-directory"),
                          ("output_path", "output")):
            argv.extend(["--" + flag, str(args[key])])
        result = subprocess.run([sys.executable, str(strict_tests.ROOT / "tools/run_target_experiment.py"), *argv],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1, result.stderr)  # executed, missing output oracle
        self.assertIn("exploratory-unverified", result.stdout)
        with zipfile.ZipFile(args["output_path"]) as archive:
            record = json.loads(archive.read("run-manifest.json"))
        self.assertEqual(record["termination"]["exit_code"], 0)
        self.assertEqual(record["evidence_classification"], "exploratory-unverified")
        detached = self.fixture.root / "detached.json"
        detached.write_bytes(runner._json_bytes(record))
        self.assertEqual(runner.main(["validate", str(detached)]), 0)
        self.assertEqual(runner.main(["validate", str(detached), "--require-promotion"]), 2)
        (args["working_directory"] / "new-output.bin").write_bytes(b"old")
        self.assertEqual(runner.main(argv), 2)  # stale declared output still fails preflight

    def test_synthetic_strict_build_cannot_promote_even_with_complete_summaries(self):
        # Runtime top-level provenance still contains synthetic leaf evidence.
        record = runner.run_experiment(**self.args)
        self.assertEqual(record["emulator"]["admission"], "source-build")
        self.assertEqual(record["evidence_classification"], "synthetic-control")
        record["host_environment"]["unknown_field_count"] = 0
        record["host_environment"]["warning_count"] = 0
        record["target"]["identity_state"] = "complete"
        with self.assertRaisesRegex(runner.TargetRunError, "promotion requires"):
            runner.require_promotion_evidence(record)
        record["evidence_classification"] = "verification-candidate"
        with self.assertRaises(runner.TargetRunError):
            runner.require_promotion_evidence(record)
        # Also exercise wholly synthetic provenance paired with the strict build.
        target = json.loads(self.args["target_manifest_path"].read_text())
        target["provenance"]["evidence_classes"] = ["synthetic"]
        self.args["target_manifest_path"].write_bytes(runner._json_bytes(target))
        record = runner.run_experiment(**self.args)
        self.assertEqual(record["evidence_classification"], "synthetic-control")
        with self.assertRaises(runner.TargetRunError):
            runner.require_promotion_evidence(record)

    def test_candidate_gate_accepts_collector_unknowns_without_summary_mutation(self):
        # Simulated runtime input tests the real producer path, not real target evidence.
        target = json.loads(self.args["target_manifest_path"].read_text())
        def runtime(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "evidence_class":
                        node[key] = "runtime"
                    else:
                        runtime(value)
            elif isinstance(node, list):
                for value in node:
                    runtime(value)
        runtime(target)
        target["identity_completeness"] = {"state": "complete", "unknown_fields": []}
        self.args["target_manifest_path"].write_bytes(runner._json_bytes(target))
        record = runner.run_experiment(**self.args)
        self.assertEqual(record["evidence_classification"], "verification-candidate")
        self.assertGreater(record["host_environment"]["unknown_field_count"], 0)
        runner.require_promotion_evidence(record)
        for mutation in (
            lambda r: r["target"].update(identity_state="partial"),
            lambda r: r["target"].update(post_run_tree_state="changed_or_unverifiable"),
            lambda r: r["termination"].update(state="timed_out"),
            lambda r: r["oracle"].update(state="unknown"),
            lambda r: r["packaging"].update(state="partial"),
        ):
            changed = copy.deepcopy(record)
            mutation(changed)
            with self.assertRaises(runner.TargetRunError):
                runner.require_promotion_evidence(changed)

    def test_exploration_requires_receipt_before_execution(self):
        (self.args["target_root"] / target_copy.RECEIPT_NAME).unlink()
        with mock.patch.object(runner._legacy, "_execute_command", side_effect=AssertionError("must not execute")):
            with self.assertRaisesRegex(runner.TargetRunError, "receipt required"):
                runner.run_experiment(**self.exploratory_args())


if __name__ == "__main__":
    unittest.main()
