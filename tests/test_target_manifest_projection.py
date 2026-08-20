from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools import capture_baseline
from tools import run_target_experiment as runner
from tools import target_manifest_projection


class SharedTargetProjectionTests(unittest.TestCase):
    def test_supported_consumers_share_projection_without_rebinding_legacy(self):
        self.assertIs(
            runner._package_target_manifest,
            target_manifest_projection.package_target_manifest,
        )
        self.assertIs(
            capture_baseline.package_target_manifest,
            target_manifest_projection.package_target_manifest,
        )
        self.assertIsNot(
            runner._legacy._package_target_manifest,
            target_manifest_projection.package_target_manifest,
        )
        self.assertEqual(
            runner._legacy._package_target_manifest.__module__,
            "tools.run_target_experiment_v3",
        )

    def test_postprocessing_replaces_legacy_target_projection_and_digest(self):
        original_command = b'{"argv":["operator/path","target"]}\n'
        supported_target = b'{"content":{"dlc":{"dlc-sha256-test":{}}}}\n'
        manifest = {
            "execution": {"command_argv_sha256": "sha256:" + "0" * 64},
            "target": {
                "packaged_manifest_sha256": "sha256:" + "0" * 64,
                "packaged_manifest_size_bytes": 0,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run.zip"
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("run-manifest.json", b"{}")
                archive.writestr("target-manifest.json", b'{"content":{"dlc":{}}}\n')
                archive.writestr("scenario.json", b"{}")
            with mock.patch.object(runner._legacy, "validate_run_manifest"):
                result = runner._restore_original_command_identity(
                    output,
                    manifest,
                    original_command,
                    packaged_target_raw=supported_target,
                )

            self.assertEqual(
                result["target"]["packaged_manifest_sha256"],
                runner._sha256_bytes(supported_target),
            )
            self.assertEqual(
                result["target"]["packaged_manifest_size_bytes"],
                len(supported_target),
            )
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(
                    archive.read("target-manifest.json"), supported_target
                )
                packaged_manifest = json.loads(archive.read("run-manifest.json"))
            self.assertEqual(
                packaged_manifest["target"]["packaged_manifest_sha256"],
                runner._sha256_bytes(supported_target),
            )


if __name__ == "__main__":
    unittest.main()
