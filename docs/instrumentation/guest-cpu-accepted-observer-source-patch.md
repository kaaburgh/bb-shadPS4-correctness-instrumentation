# Guest-CPU accepted observer source patch

This BB-INS2 slice prepares a diagnostic-only source hook at the point where shadPS4 has already established that a direct guest-CPU access range is GPU-mapped.

Pinned provenance:

- source repository: `shadps4-emu/shadPS4`;
- source commit: `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`;
- source path: `src/video_core/renderer_vulkan/vk_rasterizer.cpp`;
- Git blob: `e2b9ec75f88b632998e3cd15ddd6ca0a9cfd396c`.

At that exact source, `Rasterizer::InvalidateMemory` and `Rasterizer::ReadMemory` both reject a range unless `IsMapped(addr, size)` succeeds. The preparer inserts an off-by-default hook immediately after that rejection boundary:

- write path: `SHADPS4_BB_GUEST_CPU_ACCEPTED_OBSERVE(addr, size, true)`;
- read path: `SHADPS4_BB_GUEST_CPU_ACCEPTED_OBSERVE(addr, size, false)`.

Both calls are guarded by `#ifdef SHADPS4_BB_GUEST_CPU_ACCEPTED_OBSERVE`, so ordinary builds are unchanged unless an instrumentation build explicitly supplies the hook.

This hook is stronger than the raw page-fault seam for event admission because it runs only after GPU-mapped acceptance. It still does not solve deterministic live-resource correlation, buffering/serialization, observer completeness, userfaultfd direct-read coverage, capability promotion, or target validation. Those remain separate BB-INS2/BB-INS4 work.

Evidence from this slice is static + synthetic only. It does not establish Bloodborne runtime behavior or any negative `GPU-only` claim.
