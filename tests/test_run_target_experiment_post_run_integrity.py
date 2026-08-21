import json
import unittest
from pathlib import Path
from unittest import mock

from tools import run_target_experiment as runner


ROOT = Path(__file__).parents[1]


def _run_manifest() -> dict:
    return {
        "target": {},
        "packaging": {"state": "complete", "warnings": []},
    }


class PostRunTargetIntegrityTests(unittest.TestCase):
    def test_unchanged_target_is_recorded_as_verified(self):
        manifest = _run_manifest()
        with mock.patch.object(
            runner._legacy,
            "_verify_target_root",
            return_value=(Path("app"), Path("app/eboot.bin")),
        ) as verify:
            result = runner._record_post_run_target_verification(
                manifest, Path("target"), {"content": {}}
            )
        verify.assert_called_once()
        self.assertEqual(result["target"]["post_run_tree_state"], "verified")
        self.assertEqual(result["packaging"], {"state": "complete", "warnings": []})

    def test_changed_or_unverifiable_target_degrades_packaging(self):
        manifest = _run_manifest()
        with mock.patch.object(
            runner._legacy,
            "_verify_target_root",
            side_effect=runner.TargetRunError("target resolved tree does not match"),
        ):
            result = runner._record_post_run_target_verification(
                manifest, Path("target"), {"content": {}}
            )
        self.assertEqual(
            result["target"]["post_run_tree_state"], "changed_or_unverifiable"
        )
        self.assertEqual(result["packaging"]["state"], "partial")
        self.assertEqual(
            result["packaging"]["warnings"],
            ["post-run-target-tree-verification-failed"],
        )

    def test_target_run_schema_carries_post_run_tree_state(self):
        schema = json.loads(
            (ROOT / "schemas" / "target-run.schema.json").read_text(encoding="utf-8")
        )
        field = schema["properties"]["target"]["properties"]["post_run_tree_state"]
        self.assertEqual(
            set(field["enum"]), {"verified", "changed_or_unverifiable"}
        )


if __name__ == "__main__":
    unittest.main()
