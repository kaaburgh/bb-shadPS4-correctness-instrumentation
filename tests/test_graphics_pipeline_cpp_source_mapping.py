import copy
import json
import unittest
from pathlib import Path

from tools.graphics_pipeline_cpp_source_mapping import validate_mapping


ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = ROOT / "docs/instrumentation/graphics-pipeline-cpp-source-mapping.json"
SURFACE_PATH = ROOT / "docs/instrumentation/graphics-pipeline-key-surface.json"


def load_inputs():
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    surface_bytes = SURFACE_PATH.read_bytes()
    surface = json.loads(surface_bytes.decode("utf-8"))
    graphics = "\n".join(field["source_declaration"] for field in mapping["fields"])
    runtime = "\n".join([
        "struct PsColorBuffer {",
        "AmdGpu::DataFormat data_format : 6;",
        "AmdGpu::NumberFormat num_format : 4;",
        "AmdGpu::NumberConversion num_conversion : 3;",
        "AmdGpu::ShaderExportFormat export_format : 4;",
        "AmdGpu::CompMapping swizzle;",
    ])
    blend = "\n".join([
        "struct BlendControl {",
        "BlendFactor color_src_factor : 5;",
        "BlendFunc color_func : 3;",
        "BlendFactor color_dst_factor : 5;",
        "u32 : 3;",
        "BlendFactor alpha_src_factor : 5;",
        "BlendFunc alpha_func : 3;",
        "BlendFactor alpha_dst_factor : 5;",
        "u32 separate_alpha_blend : 1;",
        "u32 enable : 1;",
        "u32 disable_rop3 : 1;",
    ])
    return mapping, surface, graphics, runtime, blend, surface_bytes


class GraphicsPipelineCppSourceMappingTests(unittest.TestCase):
    def test_committed_mapping_covers_complete_surface(self):
        mapping, surface, graphics, runtime, blend, surface_bytes = load_inputs()
        result = validate_mapping(mapping, surface, graphics, runtime, blend, surface_bytes)
        self.assertTrue(result["source_mapping_ready"])
        self.assertEqual(result["field_count"], 21)
        self.assertEqual(set(result["field_names"]), {field["name"] for field in surface["fields"]})

    def test_missing_top_level_field_fails_closed(self):
        mapping, surface, graphics, runtime, blend, surface_bytes = load_inputs()
        mapping = copy.deepcopy(mapping)
        mapping["fields"].pop()
        with self.assertRaisesRegex(ValueError, "exact 21-field"):
            validate_mapping(mapping, surface, graphics, runtime, blend, surface_bytes)

    def test_missing_source_declaration_fails_closed(self):
        mapping, surface, graphics, runtime, blend, surface_bytes = load_inputs()
        graphics = graphics.replace("u32 patch_control_points;", "")
        with self.assertRaisesRegex(ValueError, "patch_control_points"):
            validate_mapping(mapping, surface, graphics, runtime, blend, surface_bytes)

    def test_color_record_order_is_bound_to_surface(self):
        mapping, surface, graphics, runtime, blend, surface_bytes = load_inputs()
        mapping = copy.deepcopy(mapping)
        color = next(field for field in mapping["fields"] if field["name"] == "color_buffers")
        color["record_fields"][0], color["record_fields"][1] = color["record_fields"][1], color["record_fields"][0]
        with self.assertRaisesRegex(ValueError, "color_buffers: record field order/name mismatch"):
            validate_mapping(mapping, surface, graphics, runtime, blend, surface_bytes)

    def test_blend_unnamed_bits_are_bound_to_pinned_source(self):
        mapping, surface, graphics, runtime, blend, surface_bytes = load_inputs()
        blend = blend.replace("u32 : 3;", "")
        with self.assertRaisesRegex(ValueError, "BlendControl source token missing"):
            validate_mapping(mapping, surface, graphics, runtime, blend, surface_bytes)

    def test_surface_digest_drift_fails_closed(self):
        mapping, surface, graphics, runtime, blend, surface_bytes = load_inputs()
        with self.assertRaisesRegex(ValueError, "canonical surface digest mismatch"):
            validate_mapping(mapping, surface, graphics, runtime, blend, surface_bytes + b"\n")


if __name__ == "__main__":
    unittest.main()
