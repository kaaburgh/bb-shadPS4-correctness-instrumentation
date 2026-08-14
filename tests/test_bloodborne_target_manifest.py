import copy
import unittest
from pathlib import Path

from tools import bloodborne_target_manifest as target_manifest


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "schemas" / "bloodborne-target-manifest.schema.json"
EXAMPLE_PATH = (
    ROOT / "docs" / "baseline" / "examples" / "bloodborne-target-manifest.synthetic.json"
)

try:
    import jsonschema  # noqa: F401
except ModuleNotFoundError:
    HAS_JSONSCHEMA = False
else:
    HAS_JSONSCHEMA = True


class ParserAndComparisonTests(unittest.TestCase):
    def setUp(self):
        self.example = target_manifest.load_strict(EXAMPLE_PATH)

    def test_duplicate_json_member_is_rejected(self):
        with self.assertRaisesRegex(target_manifest.ManifestError, "duplicate JSON member"):
            target_manifest.loads_strict('{"settings":{"game.language":1,"game.language":2}}')

    def test_validate_document_is_strict(self):
        with self.assertRaisesRegex(target_manifest.ManifestError, "duplicate JSON member"):
            target_manifest.validate_document('{"manifest_kind":"a","manifest_kind":"b"}')

    def test_non_finite_json_constants_are_rejected(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                with self.assertRaisesRegex(target_manifest.ManifestError, "non-finite JSON constant"):
                    target_manifest.loads_strict(constant)

    def test_boolean_and_numeric_settings_have_distinct_material_values(self):
        left = copy.deepcopy(self.example)
        right = copy.deepcopy(self.example)
        left["configuration"]["settings"]["synthetic.flag"] = {
            "value": True,
            "evidence_class": "synthetic",
        }
        right["configuration"]["settings"]["synthetic.flag"] = {
            "value": 1,
            "evidence_class": "synthetic",
        }

        self.assertEqual(target_manifest.compare_validated(left, right), "different")

    def test_overflowed_numeric_setting_is_rejected(self):
        manifest = copy.deepcopy(self.example)
        manifest["configuration"]["settings"]["synthetic.overflow"] = {
            "value": float("inf"),
            "evidence_class": "synthetic",
        }

        with self.assertRaisesRegex(target_manifest.ManifestError, "non-finite numeric setting"):
            target_manifest.validate_semantics(manifest)

    def test_identical_complete_manifests_are_same(self):
        self.assertEqual(
            target_manifest.compare_validated(self.example, copy.deepcopy(self.example)),
            "same",
        )

    def test_modification_order_must_close_over_active_set(self):
        manifest = copy.deepcopy(self.example)
        manifest["configuration"]["modification_order"]["value"] = []

        with self.assertRaisesRegex(target_manifest.ManifestError, "every active modification"):
            target_manifest.validate_semantics(manifest)

    def test_unknown_modification_set_also_marks_order_unknown(self):
        manifest = copy.deepcopy(self.example)
        manifest["identity_completeness"] = {
            "state": "partial",
            "unknown_fields": ["/configuration/active_modifications"],
        }

        with self.assertRaisesRegex(target_manifest.ManifestError, "also makes modification_order"):
            target_manifest.validate_semantics(manifest)

    def test_malformed_unknown_field_pointer_is_rejected(self):
        manifest = copy.deepcopy(self.example)
        manifest["identity_completeness"] = {
            "state": "partial",
            "unknown_fields": ["/configuration/settings/bad~2escape"],
        }

        with self.assertRaisesRegex(target_manifest.ManifestError, "JSON Pointer escape"):
            target_manifest.validate_semantics(manifest)

    def test_partial_projected_mismatch_is_indeterminate(self):
        partial = copy.deepcopy(self.example)
        partial["identity_completeness"] = {
            "state": "partial",
            "unknown_fields": [
                "/configuration/active_modifications",
                "/configuration/modification_order",
            ],
        }
        complete = copy.deepcopy(self.example)
        complete["configuration"]["active_modifications"]["synthetic-second-patch"] = {
            "kind": "patch",
            "version": "1",
            "artifact": {
                "sha256": "6" * 64,
                "size_bytes": 64,
                "evidence_class": "synthetic",
            },
        }
        complete["configuration"]["modification_order"]["value"].append(
            "synthetic-second-patch"
        )

        target_manifest.validate_semantics(partial)
        target_manifest.validate_semantics(complete)
        self.assertEqual(target_manifest.compare_validated(partial, complete), "indeterminate")

    def test_known_mismatch_still_establishes_different(self):
        partial = copy.deepcopy(self.example)
        partial["identity_completeness"] = {
            "state": "partial",
            "unknown_fields": [
                "/configuration/active_modifications",
                "/configuration/modification_order",
            ],
        }
        other = copy.deepcopy(self.example)
        other["target"]["title_id"]["value"] = "CUSA00001"

        self.assertEqual(target_manifest.compare_validated(partial, other), "different")

    def test_partial_equal_known_projection_is_indeterminate(self):
        partial = copy.deepcopy(self.example)
        partial["identity_completeness"] = {
            "state": "partial",
            "unknown_fields": ["/configuration/settings"],
        }

        self.assertEqual(target_manifest.compare_validated(partial, self.example), "indeterminate")

    def test_modification_order_changes_material_identity(self):
        left = copy.deepcopy(self.example)
        second = {
            "kind": "patch",
            "version": "1",
            "artifact": {
                "sha256": "6" * 64,
                "size_bytes": 64,
                "evidence_class": "synthetic",
            },
        }
        left["configuration"]["active_modifications"]["synthetic-second-patch"] = second
        left["configuration"]["modification_order"]["value"].append("synthetic-second-patch")
        right = copy.deepcopy(left)
        right["configuration"]["modification_order"]["value"].reverse()

        self.assertEqual(target_manifest.compare_validated(left, right), "different")


@unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is not installed")
class JsonSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = target_manifest.load_strict(SCHEMA_PATH)
        self.example = target_manifest.load_strict(EXAMPLE_PATH)
        self.validator = target_manifest._jsonschema_validator(self.schema)

    def assert_rejected(self, manifest):
        self.assertTrue(list(self.validator.iter_errors(manifest)))

    def test_schema_and_synthetic_example_validate(self):
        target_manifest.validate_manifest(self.example)

    def test_fail_closed_schema_cases(self):
        cases = []

        manifest = copy.deepcopy(self.example)
        manifest["proprietary_payload"] = "forbidden"
        cases.append(manifest)

        manifest = copy.deepcopy(self.example)
        manifest["identity_completeness"] = {"state": "partial", "unknown_fields": []}
        cases.append(manifest)

        manifest = copy.deepcopy(self.example)
        manifest["build"]["eboot"]["sha256"] = "A" * 64
        cases.append(manifest)

        manifest = copy.deepcopy(self.example)
        manifest["build"]["eboot"]["evidence_class"] = "reported"
        cases.append(manifest)

        manifest = copy.deepcopy(self.example)
        modification = manifest["configuration"]["active_modifications"].pop(
            "synthetic-frame-pacing-fixture"
        )
        manifest["configuration"]["active_modifications"]["../private/path"] = modification
        cases.append(manifest)

        manifest = copy.deepcopy(self.example)
        manifest["content"]["resolved_tree"]["algorithm"] = "sha256-tree-v2"
        cases.append(manifest)

        manifest = copy.deepcopy(self.example)
        manifest["configuration"]["settings"]["game.language"]["value"] = None
        cases.append(manifest)

        for manifest in cases:
            with self.subTest(manifest=manifest):
                self.assert_rejected(manifest)

    def test_fractional_setting_is_representable(self):
        manifest = copy.deepcopy(self.example)
        manifest["configuration"]["settings"]["game.gamma"] = {
            "value": 1.25,
            "evidence_class": "synthetic",
        }

        target_manifest.validate_manifest(manifest)

    def test_provenance_summary_does_not_replace_field_evidence(self):
        manifest = copy.deepcopy(self.example)
        manifest["provenance"]["evidence_classes"] = ["synthetic", "assumed"]

        target_manifest.validate_manifest(manifest)

    def test_unknown_update_label_can_have_complete_material_identity(self):
        manifest = copy.deepcopy(self.example)
        manifest["content"]["update"] = {"state": "unknown"}

        target_manifest.validate_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
