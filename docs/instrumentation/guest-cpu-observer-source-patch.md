# Guest-CPU observer source seam

This document describes a static/source-integration preparation step for BB-INS2. It does **not** establish runtime observer completeness, negative `GPU-only` evidence, Bloodborne coverage, or tracing overhead.

## Pinned source boundary

The patch preparer accepts only:

- source repository: `shadps4-emu/shadPS4`;
- source commit: `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`;
- source path: `src/video_core/page_manager.cpp`;
- Git blob SHA-1: `6a4bcbd7dfd2031f93f069968304dd835443a342`.

At that exact source, the non-`ENABLE_USERFAULTFD` `PageManager::Impl::GuestFaultSignalHandler` receives an access-violation context plus fault address and dispatches to `Rasterizer::InvalidateMemory` for write faults or `Rasterizer::ReadMemory` for read faults.

The prepared patch adds one compile-time guarded integration seam immediately after converting the fault address to `VAddr`:

```cpp
#ifdef SHADPS4_BB_GUEST_CPU_OBSERVE
        SHADPS4_BB_GUEST_CPU_OBSERVE(addr, Common::IsWriteError(context));
#endif
```

Normal builds are unchanged unless an instrumentation build explicitly defines `SHADPS4_BB_GUEST_CPU_OBSERVE`.

## Evidence boundary

The hook exposes only information already available at the accepted access-violation seam: guest fault address and the source handler's read/write classification. A later diagnostic producer must still bind its emitted records to `bb-guest-cpu-observer/v1` provenance and satisfy that contract's capability requirements.

The pinned Linux `ENABLE_USERFAULTFD` implementation is a different path: its handler consumes write-protect faults and directly invalidates rasterizer memory. It does not route through this `GuestFaultSignalHandler`, and this source patch therefore does not establish Linux direct-read observation. The existing `userfaultfd_write_protect` read capability remains `unknown`.

Any enabled hook implementation runs in a fault-handling path and must preserve the host handler's safety constraints. This repository does not yet provide such a runtime implementation.

## Fail-closed preparation

`tools/prepare_guest_cpu_observer_patch.py` rejects:

- a source commit other than the pinned BB-BL1 commit;
- source bytes whose Git blob identity differs from the pinned file;
- zero or multiple matches for the accepted source seam;
- repeated application of the diagnostic hook.

The resulting artifact is a one-file unified diff. CI additionally downloads the exact public upstream source at the pinned commit and verifies that the preparer produces exactly one hunk containing the guarded hook.
