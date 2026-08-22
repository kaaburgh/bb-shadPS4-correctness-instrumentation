import unittest

from tools.prepare_graphics_pipeline_producer_patch import (
    PINNED_SOURCE_COMMIT,
    PatchPreparationError,
    make_patch,
    prepare_source,
)


SOURCE = """const GraphicsPipeline* PipelineCache::GetGraphicsPipeline() {
    if (!RefreshGraphicsKey()) {
        return nullptr;
    }
    const auto [it, is_new] = graphics_pipelines.try_emplace(graphics_key);
    if (is_new) {
        CompileSomething();
    }
    return it->second.get();
}
"""


class PrepareGraphicsPipelineProducerPatchTests(unittest.TestCase):
    def test_inserts_off_by_default_hook_at_post_lookup_result(self):
        patched = prepare_source(SOURCE, PINNED_SOURCE_COMMIT)
        lookup = patched.index("graphics_pipelines.try_emplace(graphics_key)")
        hook = patched.index("SHADPS4_BB_GRAPHICS_PIPELINE_OBSERVE(graphics_key, is_new)")
        branch = patched.index("if (is_new)", hook)
        self.assertLess(lookup, hook)
        self.assertLess(hook, branch)
        self.assertIn("#define SHADPS4_BB_GRAPHICS_PIPELINE_OBSERVE(key, is_new) ((void)0)", patched)

    def test_patch_is_deterministic_and_targets_only_pinned_file(self):
        patched = prepare_source(SOURCE, PINNED_SOURCE_COMMIT)
        patch = make_patch(SOURCE, patched)
        self.assertEqual(patch, make_patch(SOURCE, patched))
        self.assertIn("--- a/src/video_core/renderer_vulkan/vk_pipeline_cache.cpp", patch)
        self.assertIn("+++ b/src/video_core/renderer_vulkan/vk_pipeline_cache.cpp", patch)
        self.assertIn("+    SHADPS4_BB_GRAPHICS_PIPELINE_OBSERVE(graphics_key, is_new);", patch)

    def test_rejects_wrong_source_commit(self):
        with self.assertRaisesRegex(PatchPreparationError, "unsupported source commit"):
            prepare_source(SOURCE, "0" * 40)

    def test_rejects_missing_or_ambiguous_seam(self):
        with self.assertRaisesRegex(PatchPreparationError, "found 0"):
            prepare_source(SOURCE.replace("try_emplace", "find"), PINNED_SOURCE_COMMIT)
        with self.assertRaisesRegex(PatchPreparationError, "found 2"):
            prepare_source(SOURCE + SOURCE, PINNED_SOURCE_COMMIT)

    def test_rejects_already_instrumented_source(self):
        patched = prepare_source(SOURCE, PINNED_SOURCE_COMMIT)
        with self.assertRaisesRegex(PatchPreparationError, "already present"):
            prepare_source(patched, PINNED_SOURCE_COMMIT)


if __name__ == "__main__":
    unittest.main()
