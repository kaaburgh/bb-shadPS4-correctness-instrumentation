# Graphics / pipeline / timing correlation

This document records the current **static + synthetic** BB-INS3 slice. It does not claim Bloodborne runtime coverage, GPU timestamp correctness, or cross-run shader/pipeline identity.

## Provenance

Static source inspection is pinned to the BB-BL1 baseline:

- repository: `shadps4-emu/shadPS4`
- commit: `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`

No proprietary shader or target payload is stored here.

## Candidate source seams

At the pinned baseline, `src/video_core/renderer_vulkan/vk_pipeline_cache.cpp` provides a promising graphics/pipeline identity seam:

- `PipelineCache::RefreshGraphicsKey()` rebuilds `GraphicsPipelineKey` from current Liverpool graphics state, including depth-buffer validity/format and color-buffer state.
- `PipelineCache::GetGraphicsPipeline()` looks up the current `GraphicsPipelineKey`; on a new entry it computes a hash, creates the graphics pipeline, registers serialized pipeline data, and increments the new-pipeline count.
- shader modules used by a graphics pipeline are already associated with pipeline keys when shader collection is enabled.

These are candidate observation seams, not yet a durable cross-run identity contract. In particular, the current `bb-trace-events/v1` `pipeline_id` is a typed capture correlation ID, not proof that the same textual ID denotes the same pipeline across runs.

At the same baseline, `src/video_core/renderer_vulkan/vk_scheduler.cpp` exposes useful render/submission boundaries:

- `Scheduler::BeginRendering()` materializes color and depth/stencil attachments in Vulkan dynamic-rendering state.
- `Scheduler::SubmitExecution()` ends rendering, submits the command buffer to the graphics queue and advances the timeline semaphore.
- optional Tracy GPU scopes exist around guest-frame command buffers, but this slice does not treat Tracy timing as the BB instrumentation timing source.

A future runtime implementation must establish the actual render/depth resource identity mapping and select a bounded timing mechanism whose semantics and overhead can be validated independently.

## Synthetic reconstruction slice

`tools/graphics_timing_trace.py` consumes a validated `bb-trace-events/v1` document and reconstructs capture-local pipeline correlation.

The analyzer deliberately fails closed when:

- a `draw` or `dispatch` event has no `pipeline_id`;
- a timing event lacks `duration_ns` or `span_id`;
- pipeline-scoped timing has no graphics event anchoring the same `span_id`;
- the timing event's `pipeline_id` disagrees with that graphics anchor.

Complete validated correlation objects are retained in the derived records. CPU and GPU span durations are aggregated separately. Timing without a pipeline identity is preserved as `unscoped_timing`; it is never assigned to a pipeline by proximity or ordering.

The synthetic fixture `docs/instrumentation/examples/graphics-timing.synthetic.json` demonstrates one draw correlated to a resource, queue, pipeline and span, followed by separately typed CPU and GPU timing spans and a queue-scoped present.

## Known gaps before BB-INS3 completion

This slice is intentionally incomplete. The current trace schema still lacks evidence-backed fields for:

- stable cross-run shader identity and shader-stage membership;
- stable cross-run pipeline identity derived from reviewed semantics rather than capture order;
- explicit color/depth attachment roles and bounded render/depth descriptors;
- pipeline create/cache hit/miss events;
- a runtime GPU timing producer with known timestamp domain, query lifecycle, availability handling and measured overhead;
- target evidence proving that the chosen seams cover the graphics work relevant to Bloodborne.

Those gaps must remain explicit. Synthetic span correlation proves the analyzer contract only; it does not establish runtime instrumentation completeness or performance measurements.

## Next experiment

At the pinned shadPS4 baseline, trace the exact data used by `GraphicsPipelineKey`, shader-module association and `Scheduler::BeginRendering()` into a minimal safe descriptor/identity model. Define deterministic synthetic variants that distinguish shader/pipeline identity and color/depth attachment roles without serializing shader payloads. Only after that model is reviewable should a bounded runtime timing producer be prepared for target validation under BB-INS4.
