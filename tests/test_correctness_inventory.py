import copy
import json
import unittest
from pathlib import Path

from tools.correctness_inventory import CorrectnessCaseError, load_strict, validate_case

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "docs" / "correctness" / "examples" / "correctness-case.reported.synthetic.json"
SCHEMA = ROOT / "schemas" / "correctness-case.schema.json"


class CorrectnessInventoryTests(unittest.TestCase):
    def setUp(self):
        self.case = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_published_reported_example_is_valid(self):
        validate_case(self.case, SCHEMA)

    def test_reported_only_cannot_smuggle_runtime_evidence(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"].append({"class": "runtime", "source": "synthetic runtime label", "artifact_sha256": None})
        with self.assertRaisesRegex(CorrectnessCaseError, "reported_only"):
            validate_case(case, SCHEMA)

    def test_reproduced_requires_runtime_evidence(self):
        case = copy.deepcopy(self.case)
        case["reproduction"] = {"status": "reproduced", "quality": "bounded", "scenario_id": "startup"}
        with self.assertRaisesRegex(CorrectnessCaseError, "runtime evidence"):
            validate_case(case, SCHEMA)

    def test_reproduced_requires_meaningful_quality(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"] = [{"class": "runtime", "source": "synthetic test mutation", "artifact_sha256": None}]
        case["reproduction"] = {"status": "reproduced", "quality": "partial", "scenario_id": "startup"}
        with self.assertRaisesRegex(CorrectnessCaseError, "bounded or repeatable"):
            validate_case(case, SCHEMA)

    def test_generic_bug_requires_semantic_seam(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"] = [{"class": "static", "source": "synthetic static fixture", "artifact_sha256": None}]
        case["classification"] = {"kind": "generic_bug", "semantic_seam": None}
        with self.assertRaisesRegex(CorrectnessCaseError, "semantic_seam"):
            validate_case(case, SCHEMA)

    def test_generic_bug_rejects_only_reported_synthetic_assumed_evidence(self):
        case = copy.deepcopy(self.case)
        case["classification"] = {"kind": "generic_bug", "semantic_seam": "synthetic seam label"}
        with self.assertRaisesRegex(CorrectnessCaseError, "static or runtime"):
            validate_case(case, SCHEMA)

    def test_schema_rejects_unknown_fields(self):
        case = copy.deepcopy(self.case)
        case["private_note"] = "must not silently enter inventory"
        with self.assertRaises(Exception):
            validate_case(case, SCHEMA)


if __name__ == "__main__":
    unittest.main()
