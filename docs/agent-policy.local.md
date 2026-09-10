## Exploration is the default

Reproducibility is required for promoted results, not for every failed or
intermediate experiment. Failure to satisfy promotion-grade provenance must
prevent promotion of a claim, not prevent the experiment itself.

Ordinary reverse-engineering work may continue from previous agent state and reuse
persistent source checkouts, dirty/uncommitted diagnostic changes, existing
out-of-tree build directories, incremental CMake/Ninja builds, compiler/dependency
caches, downloaded/fetched dependencies, previously built binaries, captures,
logs and generated artifacts. Inspect existing state first; preserve useful
negative results and label reused observations with their limitations. Do not
require a clean workspace/worktree, fresh target copy, build manifest or provenance
package before an experiment without a concrete technical reason.

Use the existing durable source checkout and build directory by default. Build
incrementally with `cmake --build <existing-build-directory> --parallel <jobs>`.
Configure only when missing or when changed build inputs require it. Do not clean,
reconfigure or rebuild from scratch as a ritual. Use the strict
`tools/shadps4_build_manifest.py build` path for promotion, explicitly requested
reproducibility verification, or a concrete suspicion of stale/corrupt build state.
Generated clean-checkout end-to-end recommendations apply to promotion verification,
not admission to exploratory tasks. See `docs/baseline/source-builds.md` and the
`docs/experiments/target-execution-feasibility.md`.

## Proprietary inputs and reusable working state

Original operator-owned game/package inputs are immutable. Never execute a
writable target against those originals or delete them. Prepare one separate,
verified disposable Bloodborne working copy (no links back to originals) and reuse
it across exploratory runs, including its working profile/cache state. For an
installed update, the copy must contain independent `app` and shadPS4-native
`app-UPDATE` siblings. The copy helper verifies both components, records their
resolved identity, and writes a private, directory-bound receipt required by
exploratory runs. Use its `--verify-existing` option once for an older copy
without a receipt; it can add the update sibling without recopying an unchanged
base. It need not run before each experiment. Exploration does not require a
full expensive pre/post target hash pass unless the hypothesis needs one.
Current working state may drift; record that as unverified. Recheck exact
identity for promotion. Never commit proprietary payloads, private dumps, secrets,
unrestricted logs or unnecessarily large captures. Safe metadata and tooling may
be retained; original inputs stay outside packaging.

## Observations and promotion

Keep `static`, `runtime`, `synthetic`, `reported` and `assumed` evidence distinct,
and separately record verification status. Exploration is `exploratory-unverified`;
a successful process or file oracle does not upgrade it. Synthetic controls prove
harness capability only. Existing captures/logs may inform hypotheses without
becoming current-run evidence. Preserve ambiguity and negative findings.

Promotion requires exact source/build/patch, target/content/update/config and
material host OS/CPU/GPU/driver/backend identities, scenario/tool provenance,
bounded termination and a claim-specific independent oracle. Source provenance
uses the existing strict manifest producer/verifier: clean exact source, fresh
build directory, complete linear patch chain and matching binary bytes. Do not
retrospectively bless an arbitrary binary or weaken the strict manifest schema.
The runner's `validate --require-promotion` rejects exploratory, synthetic,
incomplete and unsuccessful records; passing it is necessary but still needs
claim-specific semantic review and material configuration verification. Source-build
admission alone does not prove gameplay, correctness or performance.

Prefer observe → hypothesize → instrument → test → update model → patch. Dirty
local diagnostic/experimental patches are permitted before a semantic seam is
confirmed; promoting a correctness fix requires evidence of the violated guest
contract. Prefer generic upstreamable fixes where supported. No unrelated emulator
correctness/performance changes. Measure instrumentation overhead before promoting
profiling conclusions. Preserve technical dependencies and correctness-before-
optimization gates; BB-ENV1 verification status is not permission to explore. A named feasibility environment is resolved when the required
target/tool/host route is available; incomplete verification in ENV1 does not mean
the environment remains unresolved. Generated `GATED` readiness guidance must not
be interpreted as requiring completed ENV1 for intermediate exploration.

## agentic-repo-kit artifact and check procedure

Use `tool_version` and `distribution` in `.agentic-repo.lock.json` as the source of truth for normal contract checks; do not silently substitute `latest`. Follow `docs/agentic-repo-kit.md` to obtain the exact public `.pyz` named by the lock, verify its SHA-256 against `distribution.sha256`, and run `check`.

If the current environment cannot download the public release because of network/egress or platform constraints, request the exact `.pyz` artifact named in the lock from the operator. Verify the supplied bytes against the digest already committed in the lock before execution. A separately supplied checksum is not required for trust because the expected digest is already part of repository state. Lack of direct artifact access in one sandbox is an environment acquisition constraint, not evidence that repository validation is impossible.
