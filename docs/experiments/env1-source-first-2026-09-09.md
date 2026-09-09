# BB-ENV1 — source-first local experiment, 2026-09-09

This experiment separates three evidence classes: upstream/source inspection
(`static`), real-Git/CMake/Ninja stand-in admission controls (`synthetic`), and
the separately recorded real target-machine attempt (`runtime`). It makes no
menu/gameplay, image correctness, instrumentation coverage or performance claim.

## Starting evidence and decisions

The research checkout started at `c615ce4d767e18a13331ab50b30ce68d54024f93`.
Tracked files were clean. Open PR #127 was inspected at
`2ee4484a7d1b9b10459927716ab3b261e810e662`, and #128 at
`c0e462b3ec349acc88bfb993f9cb818cd5ca49f3`. Neither branch was used as a base.
The former supplied a useful complete patch-identity shape but no Git ancestry
verification; it also retained the unpatched CI-binary dependency. The latter
preserved the expired artifact (HTTP 410), accessible local target/display,
and two observational AppImage timeouts. Those probes were not supported ENV1
records and were not replayed here.

The ordered BB-BL1 change adopts the exact source in
[shadps4-source.json](../baseline/shadps4-source.json); see its
[review and invalidation decision](baseline-v0180-adoption.md). The operator's
reported 2026-09-08 ELF digest remains reported historical evidence; this run
does not silently substitute it for a newly observed build output.

## Local preparation and negative acquisition/build results

The current runner can access Ubuntu 24.04.3, X11 display `:1`, and an NVIDIA
GeForce RTX 5070 Ti with driver 595.84. Display connection and GPU inventory
were rechecked. Inventory is not proof of guest Vulkan rendering.

A fresh upstream clone was created inside this persistent job checkout's
`.astra-repos/`, detached at the exact release commit, with recursively initialized
submodules. Durable build directories and private manifests/logs are under
`.astra-local/`. No original Hermes checkout, old AppImage, existing save/profile
or modified shadPS4 source was used.

Clang 19 was absent in this runner. System installation was unavailable: sudo
reported the no-new-privileges restriction and invalid system-file ownership.
Normal `apt-get download` plus `dpkg-deb -x` supplied Ubuntu's Clang 19.1.1,
clang-tools-19, LLVM libraries and desktop development dependencies into the
job-local toolchain. No sudo/security-policy change was made.

Bounded fresh-build attempts preserved these concrete negative results:

1. SDL configure could not find X11/Wayland development headers.
2. With development packages, Ninja lacked `clang-scan-deps`; adding
   `clang-tools-19` supplied it.
3. Bundled libusb compilation could not find `libudev.h` in the extracted prefix.
4. A broad `CPATH` made system zlib headers shadow the pinned zlib-ng headers;
   libpng rejected `ZLIB_VERNUM != PNG_ZLIB_VERNUM`. This was an include-path
   configuration error, not evidence of an emulator defect.
5. The default libstdc++ configuration reached `notifications_layer.cpp` but
   lacked a transitive declaration of `std::optional`. The exact upstream Linux
   workflow explicitly uses `-stdlib=libc++`; libc++/libc++abi 19 were acquired
   and that setting was recorded for the next build, without editing source.
6. libc++ 19 hides `jthread`/`stop_token` without `-fexperimental-library`.
   A syntax-only preflight of the failed real `imgui_core.cpp` translation unit
   passed with this flag before the next fresh build. This is a recorded
   toolchain option, not an uncommitted source workaround.
7. Compilation then reached `kernel.cpp` and reported missing `uuid/uuid.h`;
   Ubuntu `uuid-dev` supplied the header required by the pinned Linux workflow.
8. All translation units compiled; final linking could not resolve `-ludev`
   because the extracted development symlink lacked its `libudev1` runtime
   target. The matching Ubuntu runtime package supplied that target.

The subsequent build uses `CMAKE_PREFIX_PATH`, `PKG_CONFIG_PATH` and
`PKG_CONFIG_SYSROOT_DIR` for the extracted prefix, with `C_INCLUDE_PATH` and
`CPLUS_INCLUDE_PATH` (after explicit compiler include paths), `LIBRARY_PATH`
and `LD_LIBRARY_PATH`, plus `CXXFLAGS="-stdlib=libc++ -fexperimental-library"`: the standard library
selection follows upstream Linux CI, and the experimental flag is required by
this resolved libc++ 19 package. The manifest retains their exact private values, actual
commands and resolved CMake cache. Each attempt uses a new out-of-tree directory;
failed attempts emit no admitted manifest. Material settings are Ninja,
RelWithDebInfo, Clang/Clang++ 19.1.1 and eight parallel build jobs.

The complete build also revealed CMake-fetched Abseil and fmt sources outside
the recursive submodule graph. The final producer places these in fresh
`.astra-repos/build-dependencies/` directories, records byte-tree digests and
Git identities where available, and compares them before/after compilation.
The earlier successful build without this additional provenance is retained
only as private preparation evidence; the supported attempt uses the final manifest.

The admitted output has SHA-256
`273d224dac5a7bbb083f6dba0dca81a5ca551f68a72dd50f0d26a6c5de5a0ae7`
and size 370,726,248 bytes. It binds 53 recursive submodules, Abseil commit
`76bb24329e8bf5f39704eb10d21b9a80befa7c81` and the fmt source byte-tree
digest. The producer is the committed implementation at `17bbe02`; its exact
file digest is retained in the manifest. Independent manifest verification and
dynamic-loader resolution passed before attempting target execution.

## Target preparation and scope

An explicit original `CUSA03173` base app tree was selected. Independently
parsed SFO fields were `TITLE_ID=CUSA03173`, `APP_VER=01.00`, `VERSION=01.00`
and `CONTENT_ID=EP9000-CUSA03173_00-BLOODBORNE0000EU`.
The adjacent 01.09 update was not copied. SFO labels do not establish that
every file is stock; exact hashes identify the actual base input used here.

`tools/prepare_env1_target_copy.py` checked the independently supplied prior
tree identity, made a new private disposable copy and read both source and
destination independently afterward:

- `sha256-tree-v1`, namespace `app/`:
  `212a0643e0506f1d863f33ae761d41710fe0a746a26a15a95ff0fe0777b719c3`;
- 28,831 files, 31,513,388,908 bytes;
- eboot SHA-256:
  `6764938b23539d29c936bca9880fc4a774e7b0099ce31c7e8c4b0f8bd0befb80`;
- SFO SHA-256:
  `312d6e3068893dae46d871575498ef53b7160e60adb30282ef88da0a5deb60f2`.

The validated BB-BL2 manifest describes this copy, no installed update/DLC and
no newly applied modifications. A new portable `user` profile and
`--config-clean --ignore-game-patch --fullscreen false` exclude previous
saves/config/patches. Source target bytes remain immutable evidence inputs.

A packaging preflight rejected `config-clean` and `ignore-game-patch` as
unregistered target settings before any target launch. They are emulator CLI
options and were retained in the private command instead; target settings are
empty. The allowlist was not weakened.

## Validation and acceptance boundary

The full local suite passes 333 tests (one macOS-only containment control is skipped on Linux), including independently compiled C++
identity conformance, schema/contract tests, source-built baseline and patched
stand-ins through the supported CLI dispatcher, and negative source/patch/binary
admission cases. The stand-ins use actual Git histories and fresh CMake/Ninja
builds; admission and execution are not mocked. They prove harness capability,
not target behavior. Source mapping and exact observer-patch preparation were
also checked directly against the adopted upstream checkout.

The first CI pass with the real nested build projection exposed a false positive
in the existing textual baseline checker: it labelled the nearby CLI11 submodule
commit as the parent shadPS4 commit. JSON now uses object ownership for those
fields; explicit URL/CLI checks remain. A regression accepts the independent
dependency identity while still rejecting a stale parent commit. Runtime evidence
bytes were not changed to accommodate the checker.

BB-ENV1 completion requires a successful supported bounded target-machine record
with required provenance and termination. It does not require a title menu or
gameplay checkpoint. A timed-out or failed process-exit oracle must remain
failure evidence; it does not become a pass because a ZIP was produced.

## Supported target-run outcome

The actual unpatched source-built ELF passed the supported non-synthetic
entrypoint on the Ubuntu machine. The one target process had a 30-second deadline
and terminated as `timed_out`, exit `-15`, after 34.064 seconds including teardown.
The process-exit oracle was `unknown`, not passed. Packaging was `complete` with
no warnings; target pre/post byte verification passed. No remaining shadPS4
process was observed after runner completion.

[Safe evidence](evidence/env1-2026-09-09-source/README.md) contains the four
unaltered JSON entries from the 8,114-byte ZIP, independent copy verification,
and an adjacent GPU inventory observation. All entry schemas and record-bound
entry hashes/sizes passed verification; private path scanning passed. The host
collector leaves GPU name/driver version unknown; the separate observation binds
RTX 5070 Ti / 595.84 without rewriting the original run record. OS build and
emulator-config digest remain explicitly unknown in the collector. No proprietary
payload, emulator binary, private command/config, raw process log, save or
screenshot is committed.

**BB-ENV1 remains Implemented, validation incomplete.** The expired artifact is no
longer an admission dependency, and actual baseline plus synthetic patched-build
admission are established. The remaining ENV1 gate is a successful bounded
supported target-machine termination/oracle record with required provenance.
The next bounded experiment should establish a reproducible clean termination
mechanism and retain the same verified base-only source/target identities;
this timeout must not be relabelled as a pass. Resolve material host/config
unknowns in that evidence where needed. Menu/gameplay semantic checkpoints,
non-synthetic artifact/oracle admission and explicit emulator-config admission
remain separate later gates.
