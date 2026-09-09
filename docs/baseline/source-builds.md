# Source-first shadPS4 builds for BB-ENV1

The exact active identity is declared in [shadps4-source.json](shadps4-source.json).
Its [adoption review](../experiments/baseline-v0180-adoption.md) separates source
compatibility from target validation. Binary hashes are outputs of a build;
they are not a substitute for identifying the source that was built.

## Build and retain the manifest

Prepare an exact checkout using [the baseline procedure](shadps4.md), including
all recursive submodules. Keep it outside this project's tracked sources and
use a durable out-of-tree build directory. Under Astra, auxiliary repositories
belong in this job checkout's `.astra-repos/`; builds belong in `.astra-local/`.
Do not use an original session checkout or a source/build workspace in `/tmp`.

```sh
python3 tools/shadps4_build_manifest.py build \
  --source <exact-clean-source-checkout> \
  --build-directory <new-durable-build-directory> \
  --output <new-private-build-manifest.json> \
  --cc <clang-executable> --cxx <clang++-executable> \
  --build-type RelWithDebInfo --jobs 8
```

The project creates `bb-shadps4-build/v1`, validated by
[shadps4-build.schema.json](../../schemas/shadps4-build.schema.json). It records:

- upstream repository, exact base commit/tree, explicit clean state;
- recursive committed submodule URLs, paths, gitlink commits and trees;
- optional patch repository, full ordered patch commits, effective HEAD/tree;
- build OS/architecture, OS fingerprint, compiler/CMake/Ninja/Git versions and hashes;
- explicit options, actual configure/build argv, resolved CMake cache, material
  build environment and environment/cache/compile-commands digests;
- producer version/hash and resulting binary SHA-256/size.

The producer requires a new build directory, executes configure and build, and
rechecks the source before publishing the manifest. Failure retains private step
logs but emits no admitted build manifest. Project CMake options may be supplied
with repeated `--option NAME=VALUE`; compiler/build-type/generator settings have
dedicated controls. Retain the full manifest privately for replay; commands and
resolved cache may contain host paths. Only its safe projection enters run ZIPs.

For a patch, commit all changes on top of the exact baseline, configure both
upstream and patch repository remotes, and add:

```text
--patch-repository https://github.com/<owner>/<fork>
--patch-commit <first-full-commit>
--patch-commit <second-full-commit>
```

Every commit must directly follow its predecessor. The final commit is the
effective HEAD; the tooling reads its tree independently from Git. No merge
commit, missing intermediate commit, implicit fork tip, dirty tree or arbitrary
binary exemption is supported. Submodules may be shallow when their exact
gitlink commit and tree are available; the top-level patch history must be full.
The empty patch list explicitly means the exact unpatched baseline.

## Verify and run

```sh
python3 tools/shadps4_build_manifest.py verify <private-build-manifest.json> \
  --source <same-source-state-checkout> --binary <built-binary>
```

Use the [supported runner procedure](../experiments/target-execution-feasibility.md)
with `--build-manifest` and `--source-checkout`. The runner snapshots the manifest,
compares declared CLI source/patch fields, verifies the live Git state, stages the
binary privately and checks the staged bytes against digest **and** size. The
engine repeats binary hashing immediately before launch. Existing process
containment, target pre/post verification, bounds and packaging limits remain.

Manifest verification is source/build provenance verification on a maintainer's
machine, not proof of game correctness or a defense against forged attestations.
A source patch does not become an active baseline change automatically. A
changed build/source/config invalidates affected comparisons even if both runs
are individually admitted.
