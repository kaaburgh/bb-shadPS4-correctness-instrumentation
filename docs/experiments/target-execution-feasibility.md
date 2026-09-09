# Target execution feasibility and handoff

## Decision

The concrete route for target execution is **GATED target-machine**. This does not claim Bloodborne runtime behavior and does not classify the project as `LOCAL ONLY`: cloud work prepares and validates the handoff, while a machine that owns the target material executes the bounded run.

Git contains only synthetic target material. The 2026-09-08 audit in PR #128 established a local target-owning Ubuntu route; its expired-artifact and observational probes were not supported run records. The current source-first experiment uses that host with a separately verified base-only copy. See [the source-first experiment](env1-source-first-2026-09-09.md) for actual results and remaining gates.

The 2026-09-09 supported source-built attempt passed admission and target pre/post
verification, but reached its 30-second deadline (`timed_out`, oracle `unknown`,
packaging `complete`). BB-ENV1 remains validation incomplete. The next operator
experiment needs a reproducible clean termination mechanism and a successful
bounded record, preserving the verified base-only identities and resolving
material host/config provenance unknowns. No menu/gameplay checkpoint is required.

## Supported handoff entrypoint

[`tools/run_target_experiment.py`](../../tools/run_target_experiment.py) is the only supported one-shot entrypoint. `tools/run_target_experiment_v3.py` remains an internal compatibility engine behind it; direct module/script execution of that engine fails closed before exposing its `run`/`validate` CLI. The supported direct invocation from the repository root is regression-tested:

```text
python tools/run_target_experiment.py run ...
```

Before delegation, the supported entrypoint loads and validates the target manifest, scenario, and command exactly once. The exact target-manifest, scenario, and command bytes are copied into a private per-run snapshot so later replacement of operator input paths cannot change the evidence decision or the bytes consumed by the engine.

## Exact executable provenance and private staging

Non-synthetic runs require a `bb-shadps4-build/v1` manifest plus its source
checkout. [The build tooling](../../tools/shadps4_build_manifest.py) produces it
only after a new out-of-tree CMake/Ninja build and matching pre/post source
observations. See [source-build procedure](../baseline/source-builds.md).

Admission requires the active exact base commit **and** tree. Unpatched builds
must have that HEAD/tree. Patched builds must identify a public patch repository,
all ordered commits, and the effective HEAD/tree. The runner checks every commit's
single parent against the preceding commit, starting at the base. Omitted,
reordered, duplicate, unrelated or merge commits fail closed. Merge-based stacks
must first be expressed as a complete linear series; no ordering is guessed.
The effective HEAD must be the final listed commit. All recursive gitlinks,
submodule trees and committed URLs are checked, including clean worktrees.
Shallow top-level history, replacements, grafts, hidden index flags and dirty
(including ignored/untracked) source inputs are rejected.

The manifest is a durable record of a locally observed build, not a signed
third-party reproducible-build attestation. Git verifies source relationships;
the project producer binds its actual configure/build commands, resolved CMake
cache, tool versions and output bytes. A deliberately forged manifest or hostile
same-user mutation remains outside the maintainer-owned execution model. There
is no supported command for blessing an arbitrary pre-existing binary.

The previous gate accepted only upstream workflow `31742892228` at historical
baseline `28c84fb`: Windows artifact `9198403207` and Linux artifact `9198177755`.
The latter expired (PR #128 observed HTTP 410). Its AppImage digest was
`7c6512eb2bced183bbda2fe858c503c2a4d6cc3146648f2c859a0477403fbd75`,
35179000 bytes. Those historical identities are preserved as a negative result;
neither archived availability nor byte-for-byte reproduction of that binary is
an admission dependency now. PR #127's completeness idea was useful, but its
unchecked patch declarations and unpatched CI pin were not adopted.

For a non-synthetic run, the operator command `argv[0]` and `--emulator-binary` must identify the same regular non-link file. The runner creates the private per-run snapshot beneath the operator-selected `working_directory`, copies the executable into that snapshot, adds the user execute bit to the staged copy, and verifies the staged digest and size against both the validated build manifest and the caller-supplied digest before delegating execution. On POSIX the staged copy must also pass an explicit executable-access preflight; a `working_directory` on a `noexec` filesystem fails closed before the compatibility engine is invoked. The compatibility engine then repeats direct command-path binding and binary-digest verification against that staged path before launch.

The project execution model has no documented adversary: the target run occurs on the maintainer's own machine with a binary they selected, while the maintainer is present to confirm whether the emulator launched. The previous platform-specific sealed-memfd / locked-handle hash-to-exec lease was therefore removed rather than repaired. No `vm.memfd_noexec` capability is required, and Linux and Windows use the existing bounded compatibility-engine executor after the same staged-byte provenance checks. This contract does not claim resistance to a hostile same-user process mutating the staged file after verification.

The runner still records the actual executable digest/size in the v3 run record. Producer version `bb-target-runner/1.12.0` identifies the private-staging + pre-launch digest contract and the fail-closed compatibility-engine boundary.

Fully synthetic unpatched controls may omit the build manifest. Patched controls must use the same verified source-build route. They remain capability evidence only.

## Stable operator command identity

Non-synthetic execution rewrites the snapshotted `argv[0]` to the private staged executable path. That temporary path is an implementation detail and is not a stable experiment identity.

`execution.command_argv_sha256` therefore identifies the exact **operator-supplied command file bytes loaded before staging**, not the rewritten temporary command. After the compatibility engine emits the safe ZIP, the supported entrypoint replaces the ephemeral command digest in `run-manifest.json` with the digest of the original command snapshot, revalidates the run record, and atomically rewrites the ZIP. Identical operator command inputs therefore retain the same detached identity even when staging locations differ.

## Process containment and target integrity

The command runs with `shell=False`, stdin closed, bounded stdout/stderr drains and a bounded timeout. Windows uses a kill-on-close Job Object. Linux uses a new process group plus `PR_SET_CHILD_SUBREAPER`, then reaps or kills adopted descendants after process-group teardown. Other POSIX hosts fail closed for target execution. Cleanup remains exception-safe.

The compatibility engine verifies the complete BB-BL2 target tree before launch. After the bounded execution and artifact collection finish, the supported entrypoint independently runs the same target-tree verification again before publishing the final safe ZIP. Supported run records add `target.post_run_tree_state`: `verified` means the target still matches the pre-run BB-BL2 identity; `changed_or_unverifiable` means re-verification failed for any reason. The latter keeps the bounded diagnostic record but forces `packaging.state=partial` and adds `post-run-target-tree-verification-failed`, so a run cannot silently claim a clean baseline after the emulator, crash handler, mod loader, or another component changed the target tree.

This check is an integrity detector, not a writable-target sandbox. Operators should still prepare the target as an immutable/read-only view where practical; post-run verification prevents an unnoticed mutation from being treated as complete evidence but does not undo the mutation.

The v3 run record remains [`schemas/target-run.schema.json`](../../schemas/target-run.schema.json). The post-run field is optional at the schema level so previously produced v3 records remain valid; records produced through the current supported entrypoint always add it before final publication. Safe packaged entries remain limited to the run record, safe target projection, host-environment record, safe scenario projection, and explicitly allowlisted redacted JSON artifacts when that artifact class is allowed by the evidence contract. Raw target material, emulator bytes, command files, configuration contents, process output, and opaque captures are not embedded.

### DLC identity

Every declared DLC root participates in target verification. The safe target projection retains each DLC as a deterministic `dlc-sha256-<sha256(identifier)>` key. Free-form DLC version text is replaced with `null`; payload-free source-package identity is preserved where available. This keeps detached content identity aligned with the executed target without copying unrestricted identifiers.

## Scenario, oracle, and produced-artifact rules

The checked-in synthetic scenario remains a **synthetic capability control**. Synthetic runs may use the file-SHA256 oracle and declared artifacts to test stale-output rejection, packaging, redaction, and runner behavior.

For a non-synthetic BB-ENV1 run:

- `file-sha256` is rejected before execution because matching bytes do not independently identify the current-run producer;
- any declared scenario artifact is also rejected before execution for the same reason;
- `process-exit` is therefore the only currently supported oracle, and it proves bounded execution/termination only, not a title-visible checkpoint or correctness state.

A future versioned producer-attestation contract is required before non-synthetic file/capture outputs can become semantic correctness evidence.

Synthetic file-oracle and artifact paths are still rejected if they pre-exist in the working directory.

## One-shot operator procedure

Prepare an immutable target view, separate writable working directory, validated BB-BL2 manifest, and command whose `argv[0]` names the binary produced by the verified source-build manifest. Do not use a wrapper. For a Linux/POSIX run, the working-directory filesystem must permit executable files because the verified private executable copy is staged there; the runner preflights that property and fails closed before delegation if the location is `noexec`. For non-synthetic execution use a `process-exit` scenario with no declared artifacts.

```text
python tools/run_target_experiment.py run \
  --target-manifest <safe-target-manifest.json> \
  --scenario <scenario.json> \
  --command-file <private-command.json> \
  --emulator-binary <source-built-binary> \
  --emulator-binary-sha256 <manifest-binary-64-lowercase-hex-digest> \
  --build-manifest <private-build-manifest.json> \
  --source-checkout <verified-shadPS4-checkout> \
  --source-repository https://github.com/shadps4-emu/shadPS4 \
  --source-commit e3ce810f3a653f43ac64ebab63023de281a4103a \
  --source-tree d61b059a991a95b21e77f963db61d618b308c62e \
  --target-root <immutable-target-tree> \
  --working-directory <isolated-writable-executable-directory> \
  --backend vulkan \
  --output <safe-output-directory>/run-<scenario-id>.zip
```

For a patched build repeat `--patch-commit <sha>` in exactly the manifest order.
The manifest supplies patch repository and effective HEAD/tree; CLI base fields
continue to name the active upstream base. Do not pass `--emulator-config`;
consumed configuration attestation remains separate work. For the local base-only
experiment use a new portable `user` directory and `--config-clean --ignore-game-patch`, with no saves, update, patches or existing profile.
`tools/prepare_env1_target_copy.py` can create an independently verified copy from
an explicit source tree and independently supplied full-tree digest/count/size.

Validate a detached record with:

```text
python tools/run_target_experiment.py validate <unpacked-run-manifest.json>
```

## What remains gated

This handoff does not establish that Bloodborne launches or reaches a semantic checkpoint, that a backend label reflects consumed configuration, or that any capture is safe or producer-bound. Non-synthetic semantic file/capture evidence remains gated on an independently verified current-run producer/tool relationship.

BB-ENV1 acceptance is a successful bounded supported target-machine run record
with required provenance and termination. Menu/gameplay checkpoints are not an
ENV1 criterion: scenario selection and correctness evidence have later gates.
A timeout/failure record is useful diagnostic evidence and must not be described
as a passed process-exit oracle.

## Validation in this PR

The target-run workflow executes the full contract suites, including review regressions for the supported direct entrypoint, fail-closed direct compatibility-engine invocation, immutable input snapshots, stable original-command digest rewriting, non-synthetic oracle/artifact rejection, source/build and staged executable identity, hashed DLC identity, post-run target-tree integrity state, and runner version `1.12.0`. A Linux regression drives a non-synthetic-classified manifest end-to-end through the supported entrypoint with a locally generated stand-in executable and verifies that the private staged binary reaches the normal bounded executor. A POSIX staging regression verifies that a non-executable staging filesystem is rejected before delegation. Dedicated post-run integrity regressions cover both unchanged and failed target re-verification, including forced partial packaging on the latter. Dedicated sealing symbols are asserted absent so the retired descriptor-executor path cannot silently reappear.

These are synthetic/contract validations only; they do not establish Bloodborne runtime behavior.

The real-Git/CMake/Ninja controls cover baseline and two-commit patched builds
through the supported CLI dispatcher and final ZIP, plus wrong base commit/tree,
dirty and hidden index state, missing/incomplete/reordered patches, wrong
effective HEAD/tree, recursive submodule drift and binary digest/size mutations.
Only the fixture baseline is substituted; admission and execution are not mocked
in the positive controls. These remain synthetic evidence even when a fixture
manifest exercises the non-synthetic admission branch.

The v3 record adds `emulator.admission` and `emulator.build_provenance`. The latter
contains exact source/submodule identities, tool versions and hashes; full build
commands, resolved cache and build environment paths remain private and are bound
by the exact manifest digest. Detached validation checks source/binary agreement.
It does not independently re-prove Git ancestry without the source checkout.
