# Graphics pipeline producer admission contract

`bb-graphics-pipeline-producer/v1` is the compatibility boundary for a future bounded runtime diagnostic at the pinned `PipelineCache::GetGraphicsPipeline` seam. It does not implement that producer and does not establish Bloodborne runtime evidence.

## Why this boundary exists

The repository already defines an exact static/synthetic `pipeline_identity` through `bb-graphics-identity/v2` and the complete `bb-graphics-pipeline-key-surface/v12` canonical key surface. Runtime creation/cache observations must not silently use a different source baseline, a capture-local `pipe:...` identifier, or an older identity interpretation.

A producer record is admitted only when it pins:

- `shadps4-emu/shadPS4@28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`;
- `src/video_core/renderer_vulkan/vk_pipeline_cache.cpp` / `VideoCore::PipelineCache::GetGraphicsPipeline`;
- the post-lookup result observation point;
- identity model `bb-graphics-identity/v2`;
- canonical key surface `bb-graphics-pipeline-key-surface/v12`;
- the diagnostic producer identity and SHA-256.

Each bounded observation contains a monotonic/capture-local sequence number, the exact `pipeline:sha256:<64 hex>` identity and one result: `created` or `cache_hit`. The contract intentionally carries no shader payload, target asset, host path, arbitrary log string or opaque capture bytes.

## Evidence boundary

The checked-in example is synthetic. The validator proves only that producer output has the expected shape and compatibility provenance. It does not prove that shadPS4 currently emits these records, that the selected seam distinguishes every creation/cache path at runtime, or that a Bloodborne workload exercises any particular pipeline.

Before BB-INS3 can claim runtime producer evidence, an implementation in the pinned/emerging shadPS4 source must derive the exact identity from the same canonical key semantics, emit bounded records at the reviewed seam, and be exercised with evidence that independently distinguishes creation from cache reuse. Target coverage and tracing overhead remain separate BB-INS3/BB-INS4 evidence.

## Validation

Run the semantic contract tests and the real validator entry point:

```text
python -m unittest tests.test_graphics_pipeline_producer_contract -v
python tools/graphics_pipeline_producer_contract.py docs/instrumentation/examples/graphics-pipeline-producer.synthetic.json
```

The dedicated workflow additionally validates the published JSON Schema against the committed synthetic fixture.
