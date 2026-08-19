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
        self.assertEqual(summary["exact_canonicalized_fields"], 16)
        self.assertEqual(summary["exact_missing_fields"], 5)
        self.assertFalse(summary["pipeline_identity_ready"])
        self.assertEqual(
            summary["family_relation_counts"],
            {"derived": 3, "direct": 6, "omitted": 12},
        )

    def test_raw_domains_preserve_reserved_patterns(self):
        document = self.load()
        cb_shader_mask = next(field for field in document["fields"] if field["name"] == "cb_shader_mask")
        logic_op = next(field for field in document["fields"] if field["name"] == "logic_op")
        z_format = next(field for field in document["fields"] if field["name"] == "z_format")
        prim_type = next(field for field in document["fields"] if field["name"] == "prim_type")
        polygon_mode = next(field for field in document["fields"] if field["name"] == "polygon_mode")
        self.assertEqual(cb_shader_mask["canonicalization"], {"kind": "raw_bit_pattern", "bits": 32})
        self.assertEqual(logic_op["canonicalization"], {"kind": "raw_bit_pattern", "bits": 8})
        self.assertEqual(z_format["canonicalization"], {"kind": "raw_bit_pattern", "bits": 2})
        self.assertEqual(prim_type["canonicalization"], {"kind": "raw_bit_pattern", "bits": 5})
        self.assertEqual(polygon_mode["canonicalization"], {"kind": "raw_bit_pattern", "bits": 2})

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

    def test_rejects_named_enum_domain_for_raw_field(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "logic_op")
        field["canonicalization"] = {
            "kind": "enum_unsigned_integer",
            "bits": 8,
            "values": [0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF],
        }
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_raw_bit_width(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "logic_op")
        field["canonicalization"]["bits"] = 4
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_color_buffer_mask_bit_width(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "cb_shader_mask")
        field["canonicalization"]["bits"] = 16
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
