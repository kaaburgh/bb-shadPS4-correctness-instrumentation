# BB-BL1 — v0.18.0 source adoption (2026-09-09)

The previous exact identity was commit
`28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`, tree
`e6026c14092b01702d4e49a5ac6c2f779a072dfe`. The active declaration now pins
release v0.18.0, commit `e3ce810f3a653f43ac64ebab63023de281a4103a`, tree
`d61b059a991a95b21e77f963db61d618b308c62e`.

## Independent source evidence

GitHub's annotated `v.0.18.0` tag peels to the adopted commit; the commit API
and a fresh upstream Git checkout agree on its tree. The immutable
[comparison](https://github.com/shadps4-emu/shadPS4/compare/28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64...e3ce810f3a653f43ac64ebab63023de281a4103a)
contains nine commits. Material changes include shader MAD translation, low
guest-module mappings, stencil ReplaceOp references, stop/thread handling,
NP TUS and trophies. No moving branch is admitted.

The top-level `.gitmodules` and all gitlinks are identical at both revisions;
therefore the recursively pinned submodule graph has not advanced. There is
no adopted project patch stack to rebase.

The graphics-key headers, runtime-info header, color-register header,
pipeline-cache implementation, page manager and buffer-cache implementation
are byte-identical at both revisions. Their static mappings and synthetic
contract fixtures have been refreshed to the new source identity; derived
surface, trace-baseline and pipeline-vector digests were regenerated.
`vk_rasterizer.cpp` changed only in `UpdateDepthStencilState`; the accepted
read/write observer anchors are unchanged. Its independently read Git blob
is now `1dc5188e77c3b72858b7becfac30ef43a6015583`, and the patch preparer
retains exact-blob and unique-anchor checks.

## Evidence boundaries and invalidation

The maintainer reports a 2026-09-08 Ubuntu RelWithDebInfo/Clang 19 build
with ELF SHA-256
`3b2516c9b1bff2218d0b32da541e158ea864a4e60aa398dfa250d6867854d81b`
reaching guest code, Vulkan, a window, VideoOut buffers and shader/pipeline
compilation on CUSA03173 base 01.00. This is **reported** evidence, not a
supported target-run record and not menu/gameplay/correctness validation.
Adjacent update 01.09 was excluded.

Historical CI executable identities remain historical; they must not be
relabelled as binaries of the new source pin. The Linux artifact expired.
The ordered BB-ENV1 admission change replaces that acquisition dependency
with verified source/build manifests. Until that change lands, non-synthetic
admission is not a usable route for this new source baseline.

No completed real target capture/corpus exists to migrate or reopen.
BB-ENV1 remains validation incomplete; BB-BL4/BL6, correctness, coverage,
overhead and post-correctness collection gates remain unchanged. Any external
capture against the previous source must remain separately identified and
cannot substantiate the new shader, memory-placement or stencil behavior.
Refreshing a synthetic example is not rerunning a target experiment.

## Validation

Validation results are recorded in the adoption PR. Source patch preparation
and mapping checks concern static compatibility only; unit/schema/C++
conformance tests concern harness and contract capability.
