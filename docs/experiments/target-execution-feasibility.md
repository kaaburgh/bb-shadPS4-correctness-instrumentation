# Target execution feasibility and handoff

## Decision

The concrete route for target execution is **GATED target-machine**. This does not claim Bloodborne runtime behavior and does not classify the project as `LOCAL ONLY`: cloud work prepares and validates the handoff, while a machine that owns the target material executes the bounded run.

The repository contains only synthetic target material. The proprietary target tree, target-machine graphics stack, and target-owned capture/input tooling are intentionally absent from the cloud checkout. The decision is based on static repository evidence plus assumed/operator-provided target-machine capability.

## Supported handoff entrypoint

[`tools/run_target_experiment.py`](../../tools/run_target_experiment.py) is the supported one-shot entrypoint. `tools/run_target_experiment_v3.py` remains an internal compatibility engine behind it. The documented direct invocation from the repository root is supported and regression-tested:

```text
python tools/run_target_experiment.py run ...
```

Before delegation to the compatibility engine, the supported entrypoint loads and validates the target manifest, scenario, and command exactly once. The exact target-manifest and scenario bytes are copied to a private per-run snapshot directory so later replacement of the operator input paths cannot change the evidence decision or the bytes that the engine executes/packages. The command bytes are snapshotted as well; for non-synthetic execution its `argv[0]` is rewritten only to the private staged executable described below.

The runner still requires the BB-BL2 target identity, bounded scenario, direct-emulator command schema, pinned BB-BL1 repository/commit/tree, no patch commits, no explicit emulator-config path, a target root, a separate writable working directory, and an output outside both trees.

## Exact executable provenance for non-synthetic target runs

A caller-provided digest does not prove that executable bytes came from the declared source. Non-synthetic target execution therefore accepts only the independently observed upstream `shadps4-emu/shadPS4` **Build and Release** workflow run `31742892228` for BB-BL1 commit `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64` / tree `e6026c14092b01702d4e49a5ac6c2f779a072dfe`.

Accepted artifacts:

- Windows SDL: artifact `9198403207`, `shadps4-win64-sdl-2026-08-13-28c84fb`; archive SHA-256 `bb2d73f4b00f4550d95820383cfff2fee880e845a336e12ad82512962f5b1c65`; contained `shadPS4.exe` SHA-256 `4212397ed435f0a1c2c8ddb71dc340e6153fce974558fbd133bae524558c650f`, size `67641344`.
- Linux SDL: artifact `9198177755`, `shadps4-linux-sdl-2026-08-13-28c84fb`; archive SHA-256 `127c01d7b2f3260fdf9c39bdae51a68bed14b560346ce7a8d17c59defb083789`; contained `Shadps4-sdl.AppImage` SHA-256 `7c6512eb2bced183bbda2fe858c503c2a4d6cc3146648f2c859a0477403fbd75`, size `35179000`.

For a non-synthetic run, both the supplied emulator path and the command `argv[0]` must be the same regular non-link file. The runner copies those bytes to a private per-run executable path, verifies the **staged** bytes against the pinned artifact digest/size, rewrites the snapshotted command to execute that staged path, and launches only the staged file. Replacement of the original executable path after staging therefore cannot change the bytes that passed provenance verification and are subsequently executed.

The existing v3 run record keeps exact source identity and actual executable digest/size. Producer version `bb-target-runner/1.7.0` identifies the contract that combines pinned upstream build identity, immutable executable staging, and single-snapshot gated inputs.

Fully synthetic controls are exempt from the upstream executable pin. They remain capability evidence only.

## Process containment and artifact boundary

The command runs with `shell=False`, stdin closed, bounded stdout/stderr drains and a bounded timeout. Windows uses a kill-on-close Job Object. Linux uses a new process group plus `PR_SET_CHILD_SUBREAPER`, then reaps or kills adopted descendants after process-group teardown. Other POSIX hosts fail closed for target execution. Cleanup remains exception-safe.

The v3 run record remains [`schemas/target-run.schema.json`](../../schemas/target-run.schema.json). Safe packaged entries remain limited to the run record, safe target projection, host-environment record, safe scenario projection, and explicitly allowlisted redacted JSON artifacts when that artifact class is allowed by the evidence contract. Raw target material, emulator bytes, command files, configuration contents, process output, and opaque captures are not embedded.

### DLC identity

Every declared DLC root participates in target verification. The safe target projection retains each DLC as a deterministic `dlc-sha256-<sha256(identifier)>` key. Free-form DLC version text is replaced with `null`; payload-free source-package identity is preserved where available. This keeps detached content identity aligned with the executed target without copying unrestricted identifiers.

## Scenario, oracle, and produced-artifact rules

The checked-in synthetic scenario remains a **synthetic capability control**. Synthetic runs may use the file-SHA256 oracle and declared artifacts to test stale-output rejection, packaging, redaction, and runner behavior.

For a non-synthetic BB-ENV1 run:

- `file-sha256` is rejected before execution because matching bytes do not independently identify the current-run producer;
- any declared scenario artifact is also rejected before execution for the same reason: a post-preflight file can be created or replayed by an unrelated process, and the v3 artifact record does not yet attest the producer/current-run relationship;
- `process-exit` is therefore the only currently supported oracle, and it proves bounded execution/termination only, not a title-visible checkpoint or correctness state.

A future versioned producer-attestation contract is required before non-synthetic file/capture outputs can become semantic correctness evidence.

Synthetic file-oracle and artifact paths are still rejected if they pre-exist in the working directory.

## One-shot operator procedure

Prepare an immutable target view, separate writable working directory, validated BB-BL2 manifest, and command whose `argv[0]` names the exact pinned upstream artifact binary for the host. Do not use a wrapper. For non-synthetic execution use a `process-exit` scenario with no declared artifacts.

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
  --working-directory <isolated-writable-directory> \
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

The target-run workflow executes the full contract suites, including review regressions for:

- direct script invocation from the repository root;
- single-snapshot target/scenario/command input handling;
- immutable staged execution of the exact verified non-synthetic emulator bytes;
- rejection of command-binary links/reparse aliases;
- rejection of non-synthetic file oracles and declared artifacts without producer attestation;
- pinned upstream executable identity;
- hashed DLC identity;
- runner version `1.7.0`.

These are synthetic/contract validations only; they do not establish Bloodborne runtime behavior.
