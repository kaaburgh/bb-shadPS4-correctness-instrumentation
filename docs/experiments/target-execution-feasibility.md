# Target execution feasibility and handoff

## Decision

The concrete route for target execution is **GATED target-machine**. This does not claim Bloodborne runtime behavior and does not classify the project as `LOCAL ONLY`: cloud work prepares and validates the handoff, while a machine that owns the target material executes the bounded run.

The repository contains only synthetic target material. The proprietary target tree, target-machine graphics stack, and target-owned capture/input tooling are intentionally absent from the cloud checkout. The decision is based on static repository evidence plus assumed/operator-provided target-machine capability.

## Supported handoff entrypoint

[`tools/run_target_experiment.py`](../../tools/run_target_experiment.py) is the only supported one-shot entrypoint. `tools/run_target_experiment_v3.py` remains an internal compatibility engine behind it; direct module/script execution of that engine fails closed before exposing its `run`/`validate` CLI. The supported direct invocation from the repository root is regression-tested:

```text
python tools/run_target_experiment.py run ...
```

Before delegation, the supported entrypoint loads and validates the target manifest, scenario, and command exactly once. The exact target-manifest, scenario, and command bytes are copied into a private per-run snapshot so later replacement of operator input paths cannot change the evidence decision or the bytes consumed by the engine.

## Exact executable provenance and private staging

A caller-provided digest does not prove that executable bytes came from the declared source. Non-synthetic target execution therefore accepts only the independently observed upstream `shadps4-emu/shadPS4` **Build and Release** workflow run `31742892228` for BB-BL1 commit `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64` / tree `e6026c14092b01702d4e49a5ac6c2f779a072dfe`.

Accepted artifacts:

- Windows SDL: artifact `9198403207`, `shadps4-win64-sdl-2026-08-13-28c84fb`; archive SHA-256 `bb2d73f4b00f4550d95820383cfff2fee880e845a336e12ad82512962f5b1c65`; contained `shadPS4.exe` SHA-256 `4212397ed435f0a1c2c8ddb71dc340e6153fce974558fbd133bae524558c650f`, size `67641344`.
- Linux SDL: artifact `9198177755`, `shadps4-linux-sdl-2026-08-13-28c84fb`; archive SHA-256 `127c01d7b2f3260fdf9c39bdae51a68bed14b560346ce7a8d17c59defb083789`; contained `Shadps4-sdl.AppImage` SHA-256 `7c6512eb2bced183bbda2fe858c503c2a4d6cc3146648f2c859a0477403fbd75`, size `35179000`.

For a non-synthetic run, the operator command `argv[0]` and `--emulator-binary` must identify the same regular non-link file. The runner creates the private per-run snapshot beneath the operator-selected `working_directory`, copies the executable into that snapshot, adds the user execute bit to the staged copy, and verifies the staged digest and size against both the independently pinned artifact and the caller-supplied digest before delegating execution. On POSIX the staged copy must also pass an explicit executable-access preflight; a `working_directory` on a `noexec` filesystem fails closed before the compatibility engine is invoked. The compatibility engine then repeats direct command-path binding and binary-digest verification against that staged path before launch.

The project execution model has no documented adversary: the target run occurs on the maintainer's own machine with a binary they selected, while the maintainer is present to confirm whether the emulator launched. The previous platform-specific sealed-memfd / locked-handle hash-to-exec lease was therefore removed rather than repaired. No `vm.memfd_noexec` capability is required, and Linux and Windows use the existing bounded compatibility-engine executor after the same staged-byte provenance checks. This contract does not claim resistance to a hostile same-user process mutating the staged file after verification.

The runner still records the actual executable digest/size in the v3 run record. Producer version `bb-target-runner/1.11.0` identifies the private-staging + pre-launch digest contract and the fail-closed compatibility-engine boundary.

Fully synthetic controls are exempt from the upstream executable pin. They remain capability evidence only.

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

Prepare an immutable target view, separate writable working directory, validated BB-BL2 manifest, and command whose `argv[0]` names the exact pinned upstream artifact binary for the host. Do not use a wrapper. For a Linux/POSIX run, the working-directory filesystem must permit executable files because the verified private executable copy is staged there; the runner preflights that property and fails closed before delegation if the location is `noexec`. For non-synthetic execution use a `process-exit` scenario with no declared artifacts.

```text
python tools/run_target_experiment.py run \
  --target-manifest <safe-target-manifest.json> \
  --scenario <scenario.json> \
  --command-file <private-command.json> \
  --emulator-binary <path-to-pinned-upstream-artifact-binary> \
  --emulator-binary-sha256 <pinned-64-lowercase-hex-digest> \
  --source-repository https://github.com/shadps4-emu/shadPS4 \
  --source-commit 28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64 \
  --source-tree e6026c14092b01702d4e49a5ac6c2f779a072dfe \
  --target-root <immutable-target-tree> \
  --working-directory <isolated-writable-executable-directory> \
  --backend vulkan \
  --output <safe-output-directory>/run-<scenario-id>.zip
```

Do not pass `--patch-commit` or `--emulator-config`; both fail closed until their provenance can be independently bound.

Validate a detached record with:

```text
python tools/run_target_experiment.py validate <unpacked-run-manifest.json>
```

## What remains gated

This handoff does not establish that Bloodborne launches or reaches a semantic checkpoint, that a backend label reflects consumed configuration, or that any capture is safe or producer-bound. Non-synthetic semantic file/capture evidence remains gated on an independently verified current-run producer/tool relationship.

The next target-machine execution can validate the bounded execution route with the pinned upstream CI binary. It cannot yet promote file/capture output into correctness evidence.

## Validation in this PR

The target-run workflow executes the full contract suites, including review regressions for the supported direct entrypoint, fail-closed direct compatibility-engine invocation, immutable input snapshots, stable original-command digest rewriting, non-synthetic oracle/artifact rejection, pinned upstream executable identity, hashed DLC identity, post-run target-tree integrity state, and runner version `1.11.0`. A Linux regression drives a non-synthetic-classified manifest end-to-end through the supported entrypoint with a locally generated stand-in executable and verifies that the private staged binary reaches the normal bounded executor. A POSIX staging regression verifies that a non-executable staging filesystem is rejected before delegation. Dedicated post-run integrity regressions cover both unchanged and failed target re-verification, including forced partial packaging on the latter. Dedicated sealing symbols are asserted absent so the retired descriptor-executor path cannot silently reappear.

These are synthetic/contract validations only; they do not establish Bloodborne runtime behavior.
