# Graphics pipeline producer source-seam preparation

This slice prepares a deterministic reviewable patch for the pinned BB-BL1 `PipelineCache::GetGraphicsPipeline` source seam. It does **not** implement the runtime producer and does not emit evidence admitted by `bb-graphics-pipeline-producer/v1`.

## Pinned source boundary

The preparer accepts only:

- repository: `shadps4-emu/shadPS4`;
- commit: `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`;
- file: `src/video_core/renderer_vulkan/vk_pipeline_cache.cpp`;
- seam: immediately after `graphics_pipelines.try_emplace(graphics_key)`, where the returned `is_new` value distinguishes the lookup result before the existing creation branch runs.

The source context must match exactly once. Zero or multiple matches fail closed instead of guessing a location.

## Prepared hook

The generated patch inserts one compile-time guarded hook:

```cpp
#ifdef SHADPS4_BB_GRAPHICS_PIPELINE_OBSERVE
    SHADPS4_BB_GRAPHICS_PIPELINE_OBSERVE(graphics_key, is_new);
#endif
```

Normal shadPS4 builds do not define the hook, so this patch adds no runtime work by default. A later instrumentation-build slice must provide the hook implementation and exact C++ canonical identity logic before records can satisfy `bb-graphics-pipeline-producer/v1`.

The hook deliberately passes the complete `GraphicsPipelineKey` and the post-lookup `is_new` result. It does **not** substitute shadPS4's existing `std::hash<GraphicsPipelineKey>` for the repository's exact `pipeline:sha256:...` identity.

## Usage

Given the exact pinned source file:

```text
python tools/prepare_graphics_pipeline_producer_patch.py \
  vk_pipeline_cache.cpp \
  --source-commit 28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64 \
  --output graphics-pipeline-producer.patch
```

The output is a deterministic unified diff targeting only the pinned source path.

## Evidence boundary

Tests and CI establish static source-context matching, deterministic patch construction, placement after the lookup result, compile-time-off-by-default gating, and fail-closed drift rejection. They do not compile shadPS4 with an enabled diagnostic hook, produce runtime records, validate `created` versus `cache_hit` on a running emulator, execute Bloodborne, establish target coverage, or measure instrumentation overhead.
