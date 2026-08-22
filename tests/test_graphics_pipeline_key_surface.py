import copy
import json
import unittest
from pathlib import Path

from tools import graphics_pipeline_key_surface


SURFACE = Path("docs/instrumentation/graphics-pipeline-key-surface.json")


class GraphicsPipelineKeySurfaceTests(unittest.TestCase):
    def load(self):
        return json.loads(SURFACE.read_text(encoding="utf-8"))

    def test_current_surface_tracks_complete_exact_canonicalization(self):
        summary = graphics_pipeline_key_surface.validate(self.load())
        self.assertEqual(summary["field_count"], 21)
        self.assertEqual(summary["exact_canonicalized_fields"], 21)
        self.assertEqual(summary["exact_missing_fields"], 0)
        self.assertTrue(summary["pipeline_identity_ready"])
        self.assertEqual(
            summary["family_relation_counts"],
            {"derived": 3, "direct": 6, "omitted": 12},
        )

    def test_pins_vulkan_headers_dependency_for_vk_format_semantics(self):
        document = self.load()
        self.assertEqual(
            document["dependencies"]["vulkan_headers"],
            {
                "repository": "https://github.com/KhronosGroup/Vulkan-Headers",
                "commit": "ee3b5caaa7e372715873c7b9c390ee1c3ca5db25",
                "path": "include/vulkan/vulkan_enums.hpp",
                "relationship": "externals/vulkan-headers submodule at pinned BB-BL1 source",
            },
        )

    def test_stage_hashes_preserve_six_u64_program_hashes(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "stage_hashes")
        self.assertEqual(
            field["canonicalization"],
            {"kind": "unsigned_integer_array", "bits": 64, "length": 6},
        )

    def test_vertex_buffer_formats_preserve_scoped_enum_integer_values(self):
        document = self.load()
        field = next(
            field for field in document["fields"] if field["name"] == "vertex_buffer_formats"
        )
        self.assertEqual(
            field["canonicalization"],
            {"kind": "enum_signed_integer_array", "bits": 32, "length": 32},
        )

    def test_color_buffers_preserve_assigned_semantic_tuple(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "color_buffers")
        self.assertEqual(
            field["canonicalization"],
            {
                "kind": "record_array",
                "length": 8,
                "fields": [
                    {"name": "data_format", "kind": "raw_bit_pattern", "bits": 6},
                    {"name": "num_format", "kind": "raw_bit_pattern", "bits": 4},
                    {"name": "num_conversion", "kind": "raw_bit_pattern", "bits": 3},
                    {"name": "export_format", "kind": "raw_bit_pattern", "bits": 4},
                    {
                        "name": "swizzle",
                        "kind": "enum_unsigned_integer_array",
                        "bits": 8,
                        "length": 4,
                        "values": [0, 1, 4, 5, 6, 7],
                    },
                ],
            },
        )

    def test_blend_controls_preserve_eight_raw_register_words(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "blend_controls")
        self.assertEqual(
            field["canonicalization"],
            {"kind": "raw_bit_pattern_array", "bits": 32, "length": 8},
        )

    def test_raw_domains_preserve_reserved_patterns(self):
        document = self.load()
        blend_controls = next(
            field for field in document["fields"] if field["name"] == "blend_controls"
        )
        write_masks = next(field for field in document["fields"] if field["name"] == "write_masks")
        cb_shader_mask = next(field for field in document["fields"] if field["name"] == "cb_shader_mask")
        logic_op = next(field for field in document["fields"] if field["name"] == "logic_op")
        z_format = next(field for field in document["fields"] if field["name"] == "z_format")
        prim_type = next(field for field in document["fields"] if field["name"] == "prim_type")
        polygon_mode = next(field for field in document["fields"] if field["name"] == "polygon_mode")
        self.assertEqual(
            blend_controls["canonicalization"],
            {"kind": "raw_bit_pattern_array", "bits": 32, "length": 8},
        )
        self.assertEqual(
            write_masks["canonicalization"],
            {"kind": "raw_bit_pattern_array", "bits": 32, "length": 8},
        )
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

    def test_rejects_wrong_dependency_pin(self):
        document = self.load()
        document["dependencies"]["vulkan_headers"]["commit"] = "0" * 40
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_equality_semantics(self):
        document = self.load()
        document["equality"]["operator"] = "fieldwise"
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_canonicalization_rule(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "num_samples")
        field["canonicalization"]["bits"] = 16
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_stage_hash_width(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "stage_hashes")
        field["canonicalization"]["bits"] = 32
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_stage_hash_length(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "stage_hashes")
        field["canonicalization"]["length"] = 5
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_vertex_format_width(self):
        document = self.load()
        field = next(
            field for field in document["fields"] if field["name"] == "vertex_buffer_formats"
        )
        field["canonicalization"]["bits"] = 16
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_vertex_format_length(self):
        document = self.load()
        field = next(
            field for field in document["fields"] if field["name"] == "vertex_buffer_formats"
        )
        field["canonicalization"]["length"] = 31
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_color_buffer_length(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "color_buffers")
        field["canonicalization"]["length"] = 7
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_color_buffer_component_width(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "color_buffers")
        component = next(
            component
            for component in field["canonicalization"]["fields"]
            if component["name"] == "num_conversion"
        )
        component["bits"] = 4
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_narrowed_color_buffer_swizzle_domain(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "color_buffers")
        swizzle = next(
            component
            for component in field["canonicalization"]["fields"]
            if component["name"] == "swizzle"
        )
        swizzle["values"] = [0, 1, 4, 5, 6]
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_semantic_only_blend_control_rule(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "blend_controls")
        field["canonicalization"] = {
            "kind": "record_array",
            "length": 8,
            "fields": [
                {"name": "enable", "kind": "unsigned_integer", "bits": 1},
                {"name": "separate_alpha_blend", "kind": "unsigned_integer", "bits": 1},
            ],
        }
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_blend_control_width(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "blend_controls")
        field["canonicalization"]["bits"] = 29
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_blend_control_length(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "blend_controls")
        field["canonicalization"]["length"] = 7
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_named_enum_domain_for_raw_field(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "logic_op")
        field["canonicalization"] = {
            "kind": "enum_unsigned_integer",
            "bits": 8,
            "values": [
                0x00,
                0x11,
                0x22,
                0x33,
                0x44,
                0x55,
                0x66,
                0x77,
                0x88,
                0x99,
                0xAA,
                0xBB,
                0xCC,
                0xDD,
                0xEE,
                0xFF,
            ],
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

    def test_rejects_narrowed_write_mask_domain(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "write_masks")
        field["canonicalization"] = {
            "kind": "enum_unsigned_integer_array",
            "bits": 4,
            "length": 8,
            "values": list(range(16)),
        }
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)

    def test_rejects_wrong_write_mask_length(self):
        document = self.load()
        field = next(field for field in document["fields"] if field["name"] == "write_masks")
        field["canonicalization"]["length"] = 7
        with self.assertRaises(graphics_pipeline_key_surface.PipelineKeySurfaceError):
            graphics_pipeline_key_surface.validate(document)


if __name__ == "__main__":
    unittest.main()
