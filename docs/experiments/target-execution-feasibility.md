# Target execution feasibility and handoff

## Decision

The concrete route for target execution is **GATED target-machine**. This PR does not claim that Bloodborne ran in the cloud and does not classify the project as `LOCAL ONLY`: the cloud agent can prepare and validate the handoff, while a machine that owns the target material executes the bounded run.

The repository contains only a synthetic Bloodborne identity manifest. Proprietary target material, a target-machine graphics stack, and target-owned capture/input tooling are intentionally absent from the cloud checkout. Evidence for this decision is static repository evidence plus assumed/operator-provided target-machine capability; no Bloodborne runtime observation was made here.

## Implemented handoff contract

[`tools/run_target_experiment.py`](../../tools/run_target_experiment.py) is the supported one-shot entrypoint. The previously reviewed v3 engine is retained at `tools/run_target_experiment_v3.py` only as its compatibility implementation; target operators must use the supported entrypoint.

Before launch the runner requires and verifies:

- a BB-BL2 payload-free target identity manifest. The runner recomputes `build.eboot`, `build.param_sfo`, and the canonical `sha256-tree-v1` identity over `target_root/app/` plus every declared `target_root/dlc/<content-id>/` root and fails closed on mismatch;
- a bounded versioned scenario and declared safe-artifact allowlist;
- command schema v2 with the verified emulator at `argv[0]` and a `target_path_index` resolving exactly to the verified app root or `eboot.bin`; wrappers, shell strings and environment overrides are not accepted;
- the pinned BB-BL1 repository, commit and tree, with no patch commits. Non-empty patch stacks remain unsupported until checkout/build provenance can independently establish their relationship to the executable;
- no explicit emulator-config path, because the pinned shadPS4 CLI does not expose a binding that proves an arbitrary file was consumed;
- a target root, separate writable working directory, and output path outside both trees.

### Exact executable provenance for non-synthetic target runs

A caller-provided digest by itself does not prove that executable bytes came from the declared source. The supported entrypoint therefore accepts a non-synthetic target run only when the executable exactly matches an independently observed artifact from upstream `shadps4-emu/shadPS4` **Build and Release** workflow run `31742892228`, whose `head_sha` is the BB-BL1 commit `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64` and whose head tree is `e6026c14092b01702d4e49a5ac6c2f779a072dfe`.

The accepted platform artifacts are:

- Windows SDL: artifact `9198403207`, `shadps4-win64-sdl-2026-08-13-28c84fb`; GitHub archive SHA-256 `bb2d73f4b00f4550d95820383cfff2fee880e845a336e12ad82512962f5b1c65`; contained `shadPS4.exe` SHA-256 `4212397ed435f0a1c2c8ddb71dc340e6153fce974558fbd133bae524558c650f`, size `67641344` bytes.
- Linux SDL: artifact `9198177755`, `shadps4-linux-sdl-2026-08-13-28c84fb`; GitHub archive SHA-256 `127c01d7b2f3260fdf9c39bdae51a68bed14b560346ce7a8d17c59defb083789`; contained `Shadps4-sdl.AppImage` SHA-256 `7c6512eb2bced183bbda2fe858c503c2a4d6cc3146648f2c859a0477403fbd75`, size `35179000` bytes.

The archive digests above are GitHub's artifact digests and were independently recomputed from the downloaded archives; the contained-binary hashes were recomputed from those same archives. The runner embeds the exact source identity, actual executable digest/size, and producer version `bb-target-runner/1.6.0` in the existing v3 run record; version 1.6.0 is the contract that binds those fields to the pinned workflow artifacts above. If the upstream artifacts later expire, a previously retained byte-identical copy remains acceptable by digest; a rebuild or differently packaged binary is not silently substituted.

Fully synthetic controls are intentionally exempt from this executable pin. Their manifests must declare only `synthetic` evidence classes, and their results remain synthetic capability evidence rather than target evidence.

## Process containment and artifact boundary

The command runs with `shell=False`, stdin closed, bounded stdout/stderr drains and a bounded timeout. Windows uses a kill-on-close Job Object. Linux uses a new process group plus `PR_SET_CHILD_SUBREAPER`, then reaps or kills adopted descendants after process-group teardown; other POSIX hosts fail closed for target execution. Cleanup remains exception-safe when waiting is interrupted or output-thread startup fails.

The v3 run record remains [`schemas/target-run.schema.json`](../../schemas/target-run.schema.json). The ZIP contains only:

- `run-manifest.json` with baseline digests, termination/oracle state, artifact status and redaction policy;
- `target-manifest.json`, a schema-valid transfer projection of BB-BL2 identity;
- `host-environment.json`, collected immediately before launch;
- `scenario.json`, a safe projection with operator text and local paths removed;
- explicitly allowlisted redacted JSON artifacts.

Raw target material, the executable, command file, emulator configuration, raw stdout/stderr and opaque captures are not embedded. Opaque captures are externalized by safe metadata only.

### DLC identity in the safe projection

Target verification uses every declared DLC root. The safe projection therefore no longer collapses a non-empty DLC set to `{}`. Each original DLC identifier is represented by a deterministic `dlc-sha256-<sha256(identifier)>` key. Free-form DLC version text is replaced with `null`; an existing payload-free `source_package` digest/size/evidence tuple is retained. This gives detached consumers stable transfer-safe DLC identity without copying unrestricted identifier/version strings, while the resolved-tree digest continues to bind the executed bytes.

## Scenario and oracle rules

The checked-in synthetic example remains a **synthetic capability control**. It may use `file-sha256` to test stale-output rejection, packaging and runner behavior because every evidence class in its target manifest is synthetic.

For a non-synthetic target run, `file-sha256` is currently rejected before execution. Preflight absence plus matching bytes does not prove that the contained target process or an identified capture tool produced the file; an unrelated process can replay the expected payload. Until a versioned oracle contract independently binds a current-run producer/tool identity to the produced file, such a file cannot be used as target correctness evidence.

A non-synthetic BB-ENV1 target run may therefore use `process-exit` only. That proves the bounded execution/termination claim and nothing about a title-visible checkpoint or correctness state. Downstream correctness items that need a semantic file/capture oracle remain gated on an independently attested producer relationship; they must not reinterpret a process-exit result as correctness evidence.

Synthetic file-oracle paths and all declared artifact paths are still rejected if they pre-exist in the working directory, preventing stale synthetic fixtures from passing capability tests.

## One-shot operator procedure

Prepare an immutable target view, a separate writable working directory, a validated BB-BL2 manifest, and a command whose `argv[0]` is the exact pinned CI-produced binary for the host. Do not use a wrapper. For non-synthetic execution choose a `process-exit` scenario unless and until the repository defines a stronger producer-attested oracle contract.

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

Do not pass `--patch-commit` or `--emulator-config`; both fail closed until their provenance can be independently bound. Validate the detached record with:

```text
python tools/run_target_experiment.py validate <unpacked-run-manifest.json>
```

## What remains gated

This handoff does not establish that Bloodborne launches or reaches a semantic checkpoint, that a backend label reflects consumed configuration, or that any opaque capture is safe to publish. Most importantly, non-synthetic file/capture oracles still need an independently verified current-run producer/tool relationship before they can support correctness claims.

The next target-machine execution can validate the concrete target-execution route and process containment using the pinned upstream CI binary. A later bounded contract change is required before a file/capture artifact can be promoted to semantic target evidence.

## Validation in this PR

Existing contract suites retain the synthetic file-oracle control and containment/privacy regressions. Additional review regressions verify that: non-synthetic file oracles fail closed without producer attestation; non-synthetic execution accepts only the exact independently observed upstream CI binary for the current host; the hardened entrypoint is identified as runner version 1.6.0; and the safe target projection preserves deterministic hashed DLC identity instead of reporting an empty DLC set.
