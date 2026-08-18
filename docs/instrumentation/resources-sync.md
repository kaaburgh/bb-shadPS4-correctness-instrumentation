# Resource/access/sync instrumentation slice

This document records the current BB-INS2 CLOUD RESEARCH slice. It is intentionally limited to static source-seam inspection at the pinned shadPS4 baseline plus synthetic reconstruction against the existing `bb-trace-events/v1` contract. It does **not** claim Bloodborne runtime observer coverage.

## Pinned source baseline

Static inspection is against `shadps4-emu/shadPS4@28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`.

Candidate seams observed at that exact source baseline:

- `src/video_core/buffer_cache/memory_tracker.h`: `MemoryTracker::InvalidateRegion` distinguishes CPU-side invalidation of ranges that are still GPU-modified and invokes an externally supplied flush callback when readbacks are enabled. `ForEachUploadRange` and `ForEachDownloadRange` expose CPU-modified and GPU-modified subranges respectively.
- `src/video_core/buffer_cache/buffer_cache.cpp`: `BufferCache::InvalidateMemory` routes through `MemoryTracker::InvalidateRegion` and invokes `ReadMemory(..., true)` when a flush is needed. `ReadMemory` serializes work through Liverpool, downloads GPU-modified data, and marks the requested region CPU-modified for a write. `DownloadBufferMemory` performs the GPU-to-download-buffer copy and writes the result back into guest backing memory after synchronization.
- `src/video_core/buffer_cache/fault_manager.cpp`: `FaultManager::ProcessFaultBuffer` processes GPU-side faults for non-GPU-cached memory and feeds affected ranges back into `BufferCache::FindBuffer` after a bounded fault-buffer readback.

These are static seam candidates, not proof that every direct guest CPU read/write path is observable. In particular, the current inspection has not independently established all page-protection/fault entry paths that cause `InvalidateMemory`, nor a bounded control that proves those paths fire for every tracked range. Therefore a missing `guest_cpu` event must remain `unknown`/`unobserved` rather than becoming evidence for a GPU-only classification.

## Synthetic reconstruction prototype

`tools/resource_sync_trace.py` validates the underlying trace document first, then reconstructs each correlated resource lifetime from `create` through access/sync/graphics events to `destroy`.

The prototype fails closed when an event references a resource outside an active lifetime. It preserves the explicit coverage labels already carried by `guest_cpu` events. If a resource has no guest-CPU event at all, the derived coverage summary is `unknown`; absence is never promoted to a negative access claim.

The fixture `docs/instrumentation/examples/resource-sync.synthetic.json` intentionally contains:

1. resource creation;
2. an observed guest-CPU write;
3. an observed host-GPU read;
4. a resource-correlated barrier;
5. a later guest-CPU read whose coverage is `ambiguous`;
6. resource destruction.

This demonstrates deterministic correlation and preserves uncertainty. It does not model or validate a real target observer.

## Remaining BB-INS2 work

BB-INS2 is not complete after this slice. Completion still needs an implementation/observer design against the pinned source seams that can emit the resource/access/sync events in diagnostic mode, plus an independent bounded known-access or structural seam-coverage oracle for every path used to support negative direct-CPU-access claims. Target runtime validation and tracing overhead remain BB-INS4 work.
