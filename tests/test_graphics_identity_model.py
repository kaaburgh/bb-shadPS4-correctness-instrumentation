import copy
import json
import unittest
from pathlib import Path

from tools import graphics_identity_model


FIXTURE = Path("docs/instrumentation/examples/graphics-identity.synthetic.json")


class GraphicsIdentityModelTests(unittest.TestCase):
    def load(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_deterministic_identity_ignores_non_key_input_order(self):
        document = self.load()
        first = graphics_identity_model.derive(document)
        reordered = copy.deepcopy(document)
        reordered["shaders"].reverse()
        reordered["render_state"]["attachments"].reverse()
        second = graphics_identity_model.derive(reordered)
        self.assertEqual(first["pipeline_family_identity"], second["pipeline_family_identity"])
        self.assertEqual(first["pipeline_identity"], second["pipeline_identity"])
        self.assertEqual(first["render_identity"], second["render_identity"])

    def test_shader_change_changes_pipeline_family_identity_but_not_exact_key_identity(self):
        document = self.load()
        baseline = graphics_identity_model.derive(document)
        changed = copy.deepcopy(document)
        changed["shaders"][0]["stage_hash"] = "3333333333333333"
        variant = graphics_identity_model.derive(changed)
        self.assertNotEqual(baseline["pipeline_family_identity"], variant["pipeline_family_identity"])
        self.assertEqual(baseline["pipeline_identity"], variant["pipeline_identity"])
        self.assertEqual(baseline["render_identity"], variant["render_identity"])

    def test_pipeline_state_change_changes_family_identity_but_not_exact_key_identity(self):
        document = self.load()
        baseline = graphics_identity_model.derive(document)
        changed = copy.deepcopy(document)
        changed["pipeline_state"]["num_samples"] = 4
        variant = graphics_identity_model.derive(changed)
        self.assertNotEqual(baseline["pipeline_family_identity"], variant["pipeline_family_identity"])
        self.assertEqual(baseline["pipeline_identity"], variant["pipeline_identity"])

    def test_exact_key_change_changes_pipeline_identity_only(self):
        document = self.load()
        baseline = graphics_identity_model.derive(document)
        changed = copy.deepcopy(document)
        changed["pipeline_key"]["write_masks"][0] = 7
        variant = graphics_identity_model.derive(changed)
        self.assertEqual(baseline["pipeline_family_identity"], variant["pipeline_family_identity"])
        self.assertNotEqual(baseline["pipeline_identity"], variant["pipeline_identity"])
        self.assertEqual(baseline["render_identity"], variant["render_identity"])
        self.assertTrue(baseline["pipeline_identity"].startswith("pipeline:sha256:"))
        self.assertEqual(baseline["pipeline_key_surface_version"], "bb-graphics-pipeline-key-surface/v12")

    def test_attachment_role_change_changes_render_identity(self):
        document = self.load()
        baseline = graphics_identity_model.derive(document)
        changed = copy.deepcopy(document)
        changed["render_state"]["attachments"][1] = {
            "role": "stencil",
            "format": "s8_uint",
            "samples": 1,
            "load_op": "load",
            "store_op": "store",
        }
        variant = graphics_identity_model.derive(changed)
        self.assertNotEqual(baseline["render_identity"], variant["render_identity"])

    def test_rejects_wrong_source_baseline(self):
        document = self.load()
        document["source"]["commit"] = "0" * 40
        with self.assertRaises(graphics_identity_model.GraphicsIdentityError):
            graphics_identity_model.derive(document)

    def test_rejects_duplicate_attachment_role(self):
        document = self.load()
        document["render_state"]["attachments"].append(copy.deepcopy(document["render_state"]["attachments"][1]))
        with self.assertRaises(graphics_identity_model.GraphicsIdentityError):
            graphics_identity_model.derive(document)

    def test_rejects_unbounded_pipeline_state_fields(self):
        document = self.load()
        document["pipeline_state"]["shader_payload"] = "not allowed"
        with self.assertRaises(graphics_identity_model.GraphicsIdentityError):
            graphics_identity_model.derive(document)

    def test_rejects_missing_pipeline_key_field(self):
        document = self.load()
        del document["pipeline_key"]["blend_controls"]
        with self.assertRaisesRegex(graphics_identity_model.GraphicsIdentityError, "missing keys"):
            graphics_identity_model.derive(document)

    def test_rejects_extra_pipeline_key_field(self):
        document = self.load()
        document["pipeline_key"]["compiler_padding"] = 0
        with self.assertRaisesRegex(graphics_identity_model.GraphicsIdentityError, "unexpected keys"):
            graphics_identity_model.derive(document)

    def test_rejects_wrong_pipeline_key_array_length(self):
        document = self.load()
        document["pipeline_key"]["vertex_buffer_formats"].pop()
        with self.assertRaisesRegex(graphics_identity_model.GraphicsIdentityError, "exactly 32"):
            graphics_identity_model.derive(document)

    def test_rejects_pipeline_key_value_outside_bit_domain(self):
        document = self.load()
        document["pipeline_key"]["z_format"] = 4
        with self.assertRaisesRegex(graphics_identity_model.GraphicsIdentityError, "2-bit canonical domain"):
            graphics_identity_model.derive(document)

    def test_rejects_invalid_color_buffer_swizzle_domain(self):
        document = self.load()
        document["pipeline_key"]["color_buffers"][0]["swizzle"][0] = 2
        with self.assertRaisesRegex(graphics_identity_model.GraphicsIdentityError, "canonical enum domain"):
            graphics_identity_model.derive(document)

    def test_rejects_incomplete_blend_control_record(self):
        document = self.load()
        del document["pipeline_key"]["blend_controls"][0]["disable_rop3"]
        with self.assertRaisesRegex(graphics_identity_model.GraphicsIdentityError, "missing keys"):
            graphics_identity_model.derive(document)


if __name__ == "__main__":
    unittest.main()