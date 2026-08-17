import copy
import json
import unittest
from pathlib import Path

from tools.correctness_inventory import CorrectnessCaseError, validate_case

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "docs" / "correctness" / "examples" / "correctness-case.reported.synthetic.json"
SCHEMA = ROOT / "schemas" / "correctness-case.schema.json"
TARGET = "sha256:" + "1" * 64
TARGET_B = "sha256:" + "4" * 64
HOST_A = "sha256:" + "2" * 64
HOST_B = "sha256:" + "3" * 64
SOURCE_COMMIT = "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64"
SOURCE_COMMIT_B = "f" * 40


def runtime_entry(host=HOST_A, target=TARGET, source_commit=SOURCE_COMMIT, scenario_id="startup"):
    return {
        "class": "runtime",
        "source": "synthetic runtime mutation",
        "artifact_sha256": None,
        "scenario_id": scenario_id,
        "baseline": {
            "source_repository": "https://github.com/shadps4-emu/shadPS4",
            "source_commit": source_commit,
            "target_manifest_sha256": target,
            "host_manifest_sha256": host,
        },
    }


class CorrectnessInventoryTests(unittest.TestCase):
    def setUp(self):
        self.case = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_published_reported_example_is_valid(self):
        validate_case(self.case, SCHEMA)

    def test_runtime_evidence_requires_exact_target_and_host_baselines(self):
        case = copy.deepcopy(self.case)
        entry = runtime_entry()
        entry["baseline"]["host_manifest_sha256"] = None
        case["provenance"]["evidence"] = [entry]
        case["reproduction"] = {"status": "reproduced", "quality": "bounded", "scenario_id": "startup"}
        with self.assertRaisesRegex(CorrectnessCaseError, "exact target and host"):
            validate_case(case, SCHEMA)

    def test_runtime_evidence_requires_exact_scenario_identity(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"] = [runtime_entry(scenario_id=None)]
        case["reproduction"] = {"status": "reproduced", "quality": "bounded", "scenario_id": "startup"}
        with self.assertRaisesRegex(CorrectnessCaseError, "exact scenario_id"):
            validate_case(case, SCHEMA)

    def test_reported_only_cannot_smuggle_runtime_evidence(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"].append(runtime_entry())
        with self.assertRaisesRegex(CorrectnessCaseError, "reported_only"):
            validate_case(case, SCHEMA)

    def test_reported_only_requires_no_reproduction_claim(self):
        case = copy.deepcopy(self.case)
        case["reproduction"] = {"status": "reported_only", "quality": "repeatable", "scenario_id": "startup"}
        with self.assertRaisesRegex(CorrectnessCaseError, "quality=none"):
            validate_case(case, SCHEMA)

    def test_reproduced_requires_runtime_evidence(self):
        case = copy.deepcopy(self.case)
        case["reproduction"] = {"status": "reproduced", "quality": "bounded", "scenario_id": "startup"}
        with self.assertRaisesRegex(CorrectnessCaseError, "runtime evidence"):
            validate_case(case, SCHEMA)

    def test_not_reproduced_requires_runtime_scenario(self):
        case = copy.deepcopy(self.case)
        case["reproduction"] = {"status": "not_reproduced", "quality": "bounded", "scenario_id": "startup"}
        with self.assertRaisesRegex(CorrectnessCaseError, "runtime evidence"):
            validate_case(case, SCHEMA)

    def test_runtime_outcome_requires_bounded_quality_and_scenario(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"] = [runtime_entry()]
        case["reproduction"] = {"status": "reproduced", "quality": "partial", "scenario_id": None}
        with self.assertRaisesRegex(CorrectnessCaseError, "bounded or repeatable"):
            validate_case(case, SCHEMA)

    def test_runtime_observation_scenario_must_match_reproduction_scenario(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"] = [runtime_entry(scenario_id="gameplay")]
        case["reproduction"] = {"status": "reproduced", "quality": "bounded", "scenario_id": "startup"}
        with self.assertRaisesRegex(CorrectnessCaseError, "match reproduction scenario_id"):
            validate_case(case, SCHEMA)

    def test_generic_bug_requires_semantic_seam(self):
        case = copy.deepcopy(self.case)
        case["classification"] = {"kind": "generic_bug", "semantic_seam": None}
        with self.assertRaisesRegex(CorrectnessCaseError, "semantic_seam"):
            validate_case(case, SCHEMA)

    def test_title_specific_rejects_reported_only_evidence(self):
        case = copy.deepcopy(self.case)
        case["classification"] = {"kind": "title_specific", "semantic_seam": "synthetic seam"}
        with self.assertRaisesRegex(CorrectnessCaseError, "static or runtime"):
            validate_case(case, SCHEMA)

    def test_backend_specific_requires_host_contrast(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"] = [runtime_entry()]
        case["reproduction"] = {"status": "reproduced", "quality": "bounded", "scenario_id": "startup"}
        case["classification"] = {"kind": "backend_specific", "semantic_seam": "backend translation boundary"}
        with self.assertRaisesRegex(CorrectnessCaseError, "two exact host baselines"):
            validate_case(case, SCHEMA)

    def test_backend_specific_rejects_source_confounded_host_contrast(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"] = [
            runtime_entry(HOST_A, source_commit=SOURCE_COMMIT),
            runtime_entry(HOST_B, source_commit=SOURCE_COMMIT_B),
        ]
        case["reproduction"] = {"status": "reproduced", "quality": "repeatable", "scenario_id": "startup"}
        case["classification"] = {"kind": "backend_specific", "semantic_seam": "backend translation boundary"}
        with self.assertRaisesRegex(CorrectnessCaseError, "source repository"):
            validate_case(case, SCHEMA)

    def test_driver_specific_rejects_target_confounded_host_contrast(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"] = [
            runtime_entry(HOST_A, target=TARGET),
            runtime_entry(HOST_B, target=TARGET_B),
        ]
        case["reproduction"] = {"status": "reproduced", "quality": "repeatable", "scenario_id": "startup"}
        case["classification"] = {"kind": "driver_specific", "semantic_seam": "driver boundary"}
        with self.assertRaisesRegex(CorrectnessCaseError, "target manifest"):
            validate_case(case, SCHEMA)

    def test_backend_specific_rejects_scenario_confounded_host_contrast(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"] = [
            runtime_entry(HOST_A, scenario_id="startup"),
            runtime_entry(HOST_B, scenario_id="gameplay"),
        ]
        case["reproduction"] = {"status": "reproduced", "quality": "repeatable", "scenario_id": "startup"}
        case["classification"] = {"kind": "backend_specific", "semantic_seam": "backend translation boundary"}
        with self.assertRaisesRegex(CorrectnessCaseError, "match reproduction scenario_id"):
            validate_case(case, SCHEMA)

    def test_backend_specific_accepts_controlled_host_contrast(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"] = [runtime_entry(HOST_A), runtime_entry(HOST_B)]
        case["reproduction"] = {"status": "reproduced", "quality": "repeatable", "scenario_id": "startup"}
        case["classification"] = {"kind": "backend_specific", "semantic_seam": "backend translation boundary"}
        validate_case(case, SCHEMA)

    def test_backend_specific_ignores_unrelated_runtime_evidence_when_control_exists(self):
        case = copy.deepcopy(self.case)
        case["provenance"]["evidence"] = [
            runtime_entry(HOST_A),
            runtime_entry(HOST_B),
            runtime_entry(HOST_A, target=TARGET_B, source_commit=SOURCE_COMMIT_B),
        ]
        case["reproduction"] = {"status": "reproduced", "quality": "repeatable", "scenario_id": "startup"}
        case["classification"] = {"kind": "backend_specific", "semantic_seam": "backend translation boundary"}
        validate_case(case, SCHEMA)

    def test_schema_rejects_unknown_fields(self):
        case = copy.deepcopy(self.case)
        case["private_note"] = "must not silently enter inventory"
        with self.assertRaises(Exception):
            validate_case(case, SCHEMA)


if __name__ == "__main__":
    unittest.main()
