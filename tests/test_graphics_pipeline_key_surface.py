import copy
import json
import unittest
from pathlib import Path

from tools import graphics_pipeline_key_surface


SURFACE = Path("docs/instrumentation/graphics-pipeline-key-surface.json")


class GraphicsPipelineKeySurfaceTests(unittest.TestCase):
    def load(self):
        return json.loads(SURFACE.read_text(encoding="utf-8"))

    def test_current_surface_tracks_partial_exact_canonicalization(self):
        summary = graphics_pipeline_key_surface.validate(self.load())
        self.assertEqual(summary["field_count"], 21)
        self.assertEqual(summary["exact_canonicalized_fields"], 13)
        self.assertEqual(summary["exact_missing_fields"], 8)
        self.assertFalse(summary["pipeline_identity_ready"])
        self.assertEqual(
            summary["family_relation_counts"],
            {"derived": 3, "direct": 6, "omitted": 12},
        )

    def test_rejects_missing_field(self):
        document = self.load()
        document["fields"].pop()
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_duplicate_field(self):
        document = self.load()
        document["fields"][-1] = copy.deepcopy(document["fields"][0])
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_reordered_field_inventory(self):
        document = self.load()
        document["fields"][0], document["fields"][1] = document["fields"][1], document["fields"][0]
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_source(self):
        document = self.load()
        document["source"]["commit"] = "0" * 40
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_equality_semantics(self):
        document = self.load()
        document["equality"]["operator"] = "fieldwise"
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_complete_field_without_established_rule(self):
        document = self.load()
        document["fields"][0]["exact_canonicalization"] = "complete"
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_canonicalization_rule(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "num_samples")
        field["canonicalization"]["bits"] = 16
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_enum_value_domain(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "polygon_mode")
        field["canonicalization"]["values"] = [0, 1, 2, 3]
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_enum_bit_width(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "z_format")
        field["canonicalization"]["bits"] = 3
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_rule_on_missing_field(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "stage_hashes")
        field["canonicalization"] = {"kind": "unsigned_integer", "bits": 64}
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)


if __name__ == "__main__":
    unittest.main()
