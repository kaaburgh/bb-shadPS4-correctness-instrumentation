# Graphics pipeline production emitter admission

`bb-graphics-pipeline-production-emitter-admission/v1` is a fail-closed static/synthetic compatibility boundary for the next BB-INS3 production-integration step. It does not modify shadPS4 or claim runtime emission.

The contract pins the exact BB-BL1 `PipelineCache::GetGraphicsPipeline` source seam, requires the current `bb-graphics-pipeline-producer/v1` record contract, the 21-field `bb-graphics-pipeline-cpp-source-mapping/v1`, the independently conformant C++ identity implementation, and the canonical key-surface contract. A future patch bundle is admitted only if it keeps normal builds free of diagnostic work, consumes the real `graphics_key`, derives `created` / `cache_hit` solely from the post-lookup `is_new` result, and exposes the named adapter/identity/observer symbols through the declared source bundle.

The contract explicitly forbids substituting `std::hash<GraphicsPipelineKey>`, raw object bytes, or `memcmp` bytes for the exact `pipeline:sha256:...` identity. It also prevents this planning slice from silently promoting runtime, Bloodborne, target-coverage, GPU-timing, or overhead claims.

`tools/graphics_pipeline_production_emitter_admission.py` validates the committed contract against material repository inputs. The dedicated workflow triggers on every material admission input so changes to the producer schema, source mapping, independent C++ conformance implementation, or canonical key surface cannot leave stale admission evidence green.

This evidence is `static` + `synthetic` only. The next substantive implementation remains the actual production C++ adapter/emitter patch at the prepared `GetGraphicsPipeline` seam, followed by compilation/runtime exercise and independent validation of `created` / `cache_hit` before runtime evidence can be promoted.
