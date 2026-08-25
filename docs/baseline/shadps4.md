# shadPS4 source baseline and integration model

This document is the source-of-truth for the shadPS4 source state used by this
project. It records source provenance only. The baseline was selected from static
repository evidence; no shadPS4 binary or Bloodborne target was built or run as
part of BB-BL1, and this document makes no runtime, compatibility, or correctness
claim.

## Active baseline

[`shadps4-source.json`](./shadps4-source.json) is the machine-readable declaration
of this identity and the **only** place the repository, commit and tree are
declared. Producers import it through
[`tools/shadps4_source_baseline.py`](../../tools/shadps4_source_baseline.py) and CI
resolves it at runtime, so no tool or workflow repeats the literal. The prose
below, the provenance recorded in fixtures and derived mappings, and the upstream
links in this repository stay literal on purpose — they record which baseline an
artifact was produced against — and `python -m tools.shadps4_source_baseline check`
fails closed when any of them disagrees with the declaration.

- **Upstream repository:** <https://github.com/shadps4-emu/shadPS4>
- **Upstream branch observed:** `main`
- **Exact upstream commit:**
  [`28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`](https://github.com/shadps4-emu/shadPS4/commit/28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64)
- **Source tree:** `e6026c14092b01702d4e49a5ac6c2f779a072dfe`
- **Commit timestamp:** `2026-08-13T15:51:02-05:00`
- **Commit subject:** `Use a recursive mutex so deferred operations can defer more operations (#4846)`
- **Project patch stack:** none
- **Effective source commit:**
  `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`
- **Baseline selected:** `2026-08-14`

The full commit SHA, not `main`, a tag, a release name, or a downloaded binary
name, is the baseline identity. The commit's gitlinks also pin all recursive
submodules. Branch declarations in
[`.gitmodules`](https://github.com/shadps4-emu/shadPS4/blob/28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64/.gitmodules)
do not authorize moving them with `git submodule update --remote`.

This pin covers the shadPS4 emulator core. The separate QtLauncher repository and
prebuilt release artifacts are not part of the source baseline. If a future run
depends materially on a launcher, packaging script, or other external component,
that component needs its own exact identity in the run provenance.

The pin was chosen because it was the tip of upstream `main` observed while
BB-BL1 was performed and no project patch stack existed. That is source-selection
provenance, not evidence that the commit runs Bloodborne correctly.

## Fetch and verify the baseline

Use a non-shallow clone so the pinned commit remains usable after upstream moves
and so later comparisons do not depend on a depth-limited history:

```bash
git clone --filter=blob:none --no-checkout \
  https://github.com/shadps4-emu/shadPS4.git shadPS4
git -C shadPS4 fetch origin \
  28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64
git -C shadPS4 checkout --detach \
  28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64
git -C shadPS4 submodule sync --recursive
git -C shadPS4 submodule update --init --recursive
```

Before configuring a build, verify all of the following:

```bash
git -C shadPS4 rev-parse HEAD
git -C shadPS4 show -s --format=%T HEAD
git -C shadPS4 status --porcelain=v1 --untracked-files=all
git -C shadPS4 submodule status --recursive
```

The first two commands must print the commit and tree recorded above. The status
output must be empty. Every submodule-status line must start with a space: `-`
means uninitialized, `+` means a different commit, and `U` means a conflict. Any
mismatch makes the checkout unsupported for baseline evidence; do not repair it
by advancing a branch or submodule.

## Build provenance contract

The initial reference build profile mirrors the material compile options of the
Windows SDL `Release` profile defined by upstream's pinned
[`build.yml`](https://github.com/shadps4-emu/shadPS4/blob/28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64/.github/workflows/build.yml):

```powershell
cmake --fresh -S shadPS4 -B build-shadps4 -G Ninja `
  -DCMAKE_BUILD_TYPE=Release `
  -DCMAKE_INTERPROCEDURAL_OPTIMIZATION_RELEASE=ON `
  -DCMAKE_C_COMPILER=clang-cl `
  -DCMAKE_CXX_COMPILER=clang-cl
cmake --build build-shadps4 --config Release --parallel $env:NUMBER_OF_PROCESSORS
```

This command is a reference configuration, not a claim that BB-BL1 built it.
It deliberately omits the upstream CI cache launchers; record them when they are
used because they remain part of the actual build environment.
Other upstream-supported configurations are allowed, but captures or comparisons
must not treat different configurations as the same build.

For every produced binary, preserve at least:

- upstream repository URL, upstream base SHA, effective source commit and tree;
- ordered local/fork patch commit SHAs, or the explicit value `none`;
- complete recursive `git submodule status` output and clean/dirty source status;
- OS and architecture used for the build;
- CMake generator, build type, complete configure/build commands and material
  CMake options;
- exact `git`, CMake, Ninja and C/C++ compiler versions;
- build workflow run URL/ID when CI produced the binary;
- output binary filename and SHA-256 digest.

The pinned upstream workflow uses moving runner/action inputs in places (for
example runner labels and a CMake setup action), so a workflow file plus commit
SHA is not enough to reconstruct the toolchain. Record the actual resolved tool
versions and workflow run identity. BB-BL3 will define the broader host/run
environment manifest; it does not remove these source/build requirements.

Keep build output outside the source checkout, as in the reference command, so a
post-build source status can still expose accidental source changes. Generated
files and binaries are not source changes and must not be committed here.

## Source-change integration model

The research repository and shadPS4 source remain separate repositories. Do not
vendor the shadPS4 tree or add it as a moving submodule here. Source changes are
reviewed in the native shadPS4 history, while this repository records the exact
source identity used by experiments and decisions.

Use this workflow for a change to shadPS4:

1. Create or reuse a shadPS4 fork only when the first source change is needed.
   Add the official repository as remote `upstream` and fetch the exact active
   baseline SHA.
2. Create one topic branch per roadmap item from that SHA, named
   `bb/<roadmap-id>-<short-description>`. Do not base it on an unrecorded moving
   branch.
3. Keep the patch as ordinary reviewable commits. A source-change PR must record
   the upstream base SHA, ordered patch commit SHAs, effective head SHA and tree
   SHA, plus an immutable compare/PR URL. Uncommitted diffs are not durable
   project evidence.
4. Prefer a generic, upstreamable correction or diagnostic when the evidence
   establishes a generic shadPS4 issue. Keep target-specific reproduction and
   evidence in this repository; do not mix proprietary target material into the
   source branch.
5. A coordination PR in this repository links the source PR/commits, records the
   build/test/target evidence actually obtained, and changes the active baseline
   only when the project intentionally adopts that source state.

For a patched source state, identify it as:

```text
upstream repository: https://github.com/shadps4-emu/shadPS4
upstream base:       <full SHA>
patch repository:   <fork URL>
patch commits:      <ordered full SHAs>
effective head:     <full SHA>
effective tree:     <full tree SHA>
```

A fork branch name or pull-request number alone is not an identity because it can
move. If a source PR is rebased, all rewritten commit/head/tree identities must be
updated before its output is used as evidence.

## Baseline update policy

The baseline never advances automatically.

An update starts by editing [`shadps4-source.json`](./shadps4-source.json), the
single declaration every producer and workflow resolves, and is not finished until
every remaining literal reference has been reconciled and
`python -m tools.shadps4_source_baseline check` passes again. That check is what
makes a *partially* applied update fail, instead of leaving a workflow validating
derived artifacts against the previous upstream sources.

Updating the baseline requires a focused PR that:

1. names the old and candidate upstream commits and links their immutable compare;
2. reviews upstream and recursive-submodule changes relevant to this project;
3. rebases or reapplies every active project patch and records rewritten identities;
4. runs the build/tests warranted by the change and states what target validation
   did or did not run;
5. updates this document to the adopted effective source state; and
6. explicitly invalidates, reopens, or re-runs downstream captures, corpora and
   performance evidence whose source assumptions changed.

Failed build, ambiguous patch ancestry, missing submodules, a dirty checkout, or
unrecorded patch commits fail closed: retain the previous baseline until a later
PR resolves the problem. Experimental candidate builds may be investigated, but
their results must be labeled with their candidate source identity and must not be
merged into evidence from the active baseline.

## Evidence recorded by BB-BL1

Evidence class: **static repository evidence**. The upstream repository metadata,
branch ref, commit/tree, submodule gitlinks, build documentation, CI configuration
and contribution policy were inspected at the exact commit above. No source patch,
build, emulator execution, proprietary target, or target-machine observation was
used.

The inspected immutable upstream inputs were the
[core README](https://github.com/shadps4-emu/shadPS4/blob/28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64/README.md),
[Windows build guide](https://github.com/shadps4-emu/shadPS4/blob/28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64/documents/building-windows.md),
[CI build workflow](https://github.com/shadps4-emu/shadPS4/blob/28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64/.github/workflows/build.yml),
[submodule configuration](https://github.com/shadps4-emu/shadPS4/blob/28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64/.gitmodules),
and [contribution policy](https://github.com/shadps4-emu/shadPS4/blob/28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64/CONTRIBUTING.md).
