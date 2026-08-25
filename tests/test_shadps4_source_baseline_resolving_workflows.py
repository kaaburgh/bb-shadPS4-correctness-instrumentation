import tempfile
import unittest
from pathlib import Path

from tools import shadps4_source_baseline as baseline


FOREIGN = "deadbeef" * 5


class ResolvingWorkflowDriftTests(unittest.TestCase):
    def _drift_for(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github" / "workflows" / "stale.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(text, encoding="utf-8")
            return baseline.collect_drift(root)

    def test_stale_raw_url_is_rejected_even_after_baseline_changes(self):
        findings = self._drift_for(
            "jobs:\n  x:\n    steps:\n"
            f"      - run: curl -fsSL https://raw.githubusercontent.com/"
            f"shadps4-emu/shadPS4/{FOREIGN}/a.h\n"
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("must not embed shadPS4 source commit reference", findings[0])
        self.assertIn(FOREIGN, findings[0])

    def test_stale_source_commit_argument_is_rejected(self):
        findings = self._drift_for(
            "jobs:\n  x:\n    steps:\n"
            f"      - run: python tool.py --source-commit {FOREIGN}\n"
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("must not embed shadPS4 source commit reference", findings[0])

    def test_unrelated_workflow_sha_remains_out_of_scope(self):
        findings = self._drift_for(
            "jobs:\n  x:\n    steps:\n"
            f"      - uses: actions/checkout@{FOREIGN}\n"
        )
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
