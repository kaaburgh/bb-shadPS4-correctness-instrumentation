# Buffer live-range lifecycle source seam

This BB-INS2 slice prepares a reviewable, compile-time-off-by-default source seam for the **buffer-cache** portion of future live-resource correlation. It is static/source-integration evidence only.

## Pinned source

- repository: `shadps4-emu/shadPS4`
- commit: `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`
- path: `src/video_core/buffer_cache/buffer_cache.cpp`
- Git blob: `68b85116029b6f05c45e9cc32be3ccf7de335bae`

At this baseline, `BufferCache::ChangeRegister<true>` publishes a live cached buffer into `buffer_ranges` with its `BufferId`, `Buffer::CpuAddr()` and `Buffer::SizeBytes()`. `ChangeRegister<false>` removes that same range before the slot is erased. This makes those two state transitions an evidence-backed source for the lifetime of cached **buffer** ranges.

The prepared patch inserts, after each successful range-state mutation:

```cpp
#ifdef SHADPS4_BB_BUFFER_LIVE_RANGE_OBSERVE
SHADPS4_BB_BUFFER_LIVE_RANGE_OBSERVE(buffer_id, buffer.CpuAddr(), buffer.SizeBytes(), true_or_false);
#endif
```

Normal builds are unchanged unless the diagnostic macro is explicitly defined.

## Evidence boundary

The cache-local `BufferId` is not itself the durable `res:[0-9]{8}` identity from the trace contract. A future producer must assign/bind durable resource IDs and feed live ranges into `bb-guest-cpu-resource-correlation/v1` without inventing ownership.

This slice also does **not** claim that `BufferCache::buffer_ranges` covers images/textures or every GPU-mapped resource class. Image/texture lifetime sourcing remains a separate unresolved part of the producer design. Therefore this seam alone cannot support observer-completeness or negative `GPU-only` evidence.

No Bloodborne target was run. No runtime producer, runtime resource record, capability promotion, target coverage, or instrumentation-overhead claim is established here.
