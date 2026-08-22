# Resource/access/sync instrumentation slice

This document records the current BB-INS2 CLOUD RESEARCH slice. It is intentionally limited to static source-seam inspection at the pinned shadPS4 baseline plus synthetic reconstruction against the existing `bb-trace-events/v1` contract. It does **not** claim Bloodborne runtime observer coverage.

## Pinned source baseline

Static inspection is against `shadps4-emu/shadPS4@28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`.

Candidate seams observed at that exact source baseline:

- `src/video_core/buffer_cache/memory_tracker.h`: `MemoryTracker::InvalidateRegion` distinguishes CPU-side invalidation of ranges that are still GPU-modified and invokes an externally supplied flush callback when readbacks are enabled. `ForEachUploadRange` and `ForEachDownloadRange` expose CPU-modified and GPU-modified subranges respectively.
- `src/video_core/buffer_cache/buffer_cache.cpp`: `BufferCache::InvalidateMemory` routes through `MemoryTracker::InvalidateRegion` and invokes `ReadMemory(..., true)` when a flush is needed. `ReadMemory` serializes work through Liverpool, downloads GPU-modified data, and marks the requested region CPU-modified for a write. `DownloadBufferMemory` performs the GPU-to-download-buffer copy and writes the result back into guest backing memory after synchronization.
- `src/video_core/buffer_cache/fault_manager.cpp`: `FaultManager::ProcessFaultBuffer` processes GPU-side faults for non-GPU-cached memory and feeds affected ranges back into `BufferCache::FindBuffer` after a bounded fault-buffer readback.

## Direct guest-CPU page-fault observer seam

Further static tracing at the same pinned source baseline establishes a concrete direct-access path that does not depend on an explicit HLE transfer/readback API.

`RegionManager` owns CPU/GPU dirty-state bitsets and updates `PageManager` protection watchers when those states change. CPU-dirty state transitions update write watchers; in precise readback mode GPU-dirty transitions also update read watchers. `PageManager` converts those watcher counts into page permissions.

On the normal access-violation path, `PageManager::GuestFaultSignalHandler` distinguishes the fault type from the CPU context:

- a direct guest-CPU **write** fault dispatches to `Rasterizer::InvalidateMemory(addr, 8)`;
- a direct guest-CPU **read** fault dispatches to `Rasterizer::ReadMemory(addr, 8)`.

`Rasterizer::InvalidateMemory` first requires that the range be GPU-mapped, then forwards the write-side invalidation to both `BufferCache::InvalidateMemory` and `TextureCache::InvalidateMemory`. `Rasterizer::ReadMemory` similarly requires a GPU-mapped range and forwards the read path to `BufferCache::ReadMemory`. This is a real static observer seam for direct CPU accesses to protected GPU-mapped guest memory; it is stronger than inferring CPU access from later transfer calls.

There is, however, a material compile/platform distinction. Under `ENABLE_USERFAULTFD`, the Linux implementation registers GPU mappings with `UFFDIO_REGISTER_MODE_WP` and its handler accepts write-protect faults, then calls `Rasterizer::InvalidateMemory`. Its `Protect` implementation toggles only userfaultfd write protection; static inspection does not establish an equivalent read-fault mechanism on that path. Therefore direct-write observation is statically established for the userfaultfd branch, while direct-read coverage remains unproven there. The non-userfaultfd access-violation path contains explicit read/write dispatch for both directions.

This distinction prevents a repository-wide claim that every host/build observes direct guest-CPU reads and writes identically. Build configuration and host fault mechanism are now explicit observer provenance, and missing direct-read events remain `unknown` unless the exact path used by the run has independent coverage evidence.

## Versioned observer capability boundary

`bb-trace-events/v1` now admits a separately versioned `provenance.material.observer` record, currently `bb-guest-cpu-observer/v1`. Runtime `guest_cpu` events require that record; synthetic contract fixtures do not.

The record distinguishes the two established mechanism/build pairs and carries independent read/write capability states:

- `unknown` — no observation capability is established for the direction;
- `observable` — a separately hashed evidence artifact establishes the concrete observation seam, sufficient for `observed`/`ambiguous` runtime events but not negative evidence;
- `negative_validated` — the observation evidence is accompanied by a separately hashed independent coverage oracle, allowing `coverage=unobserved` for that direction.

The validator rejects mechanism/build mismatches and keeps `userfaultfd_write_protect` direct-read capability `unknown` in observer v1. A negative runtime claim fails closed unless every relevant direction is `negative_validated` and supplies its `coverage_oracle_sha256`.

The resource-sync consumer calls the shared trace validator before reconstruction, so unsupported runtime negative coverage cannot silently become resource classification evidence. The contract binds the oracle artifact identity but does not certify its independence or quality by digest alone; producer admission/BB-INS4 must establish that relationship.

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

This demonstrates deterministic correlation and preserves uncertainty. It does not model or validate a real target observer. Focused regressions additionally construct runtime-classified documents in memory to prove that public reconstruction rejects `unobserved` for merely observable capability and accepts it only when the relevant direction is `negative_validated` with a separately bound oracle digest. Those are compatibility tests, not runtime evidence.

## Remaining BB-INS2 work

BB-INS2 is not complete after this slice. The direct page-fault seams are statically established and the observer/fault-mechanism provenance compatibility boundary is now versioned and fail-closed. Completion still needs a bounded diagnostic producer that emits `guest_cpu` access events at the fault/rasterizer boundary with exact host/build/fault-mechanism provenance, deterministic live-resource correlation, and independently exercised coverage evidence for each promoted capability.

The first implementation should keep userfaultfd direct-read capability `unknown` unless a separate read observer is established. Any transition to `negative_validated` requires a known-access or structural seam-coverage oracle independent of the event reconstruction. Target runtime validation and tracing overhead remain BB-INS4 work.
