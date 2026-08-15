# Target execution feasibility and handoff

## Decision

The concrete route for target execution is **GATED target-machine**. This PR
does not claim that Bloodborne ran in the cloud, and it does not classify the
project as `LOCAL ONLY`: the cloud agent can prepare and validate the handoff,
while a machine that owns the target material must execute the bounded run.

The repository contains only a synthetic Bloodborne identity manifest. The
proprietary target tree, a target-machine graphics stack, and any target-owned
capture/input tooling are intentionally absent from the cloud checkout. The
repository's pinned shadPS4 build contract also records a Windows SDL Release
profile, but a build recipe alone is not evidence that the target executes.
Consequently, attempting to launch the real target from this cloud checkout
would either require unavailable target material or would create an
unreviewable runtime claim.

Evidence class for the decision: **static** repository evidence plus an
**assumed/operator-provided** target-machine capability. No Bloodborne or
shadPS4 runtime observation was made by this PR.

## Implemented handoff contract

[`tools/run_target_experiment.py`](../../tools/run_target_experiment.py) is the
one-shot runner. It requires all of the following before it starts the target
command:

- a BB-BL2 payload-free target identity manifest, validated with the existing
  strict validator. Before launch the runner recomputes the manifest's exact
  `build.eboot`, `build.param_sfo`, and `content.resolved_tree` identities from
  the canonical `target_root/app/` plus declared `target_root/dlc/<content-id>/`
  views and fails closed on any mismatch. This verifies the prepared content
  view; it does not pretend to derive target-visible settings or modification
  metadata from arbitrary files. The operator must produce those BB-BL2 fields
  independently and keep the verified source view immutable;
- a versioned scenario file with a bounded timeout, an explicit oracle, and a
  declared safe-artifact allowlist;
- a versioned argv-only command file. Command schema v2 requires
  `emulator_binary_index: 0`, so the verified shadPS4 executable is the program
  actually passed to `exec`, not a wrapper argument. `target_path_index` must
  resolve exactly to the verified `app/` view or its `eboot.bin`. Shell strings,
  wrapper launchers, environment overrides, and command-file contents are not
  accepted as execution shortcuts;
- the exact shadPS4 executable and its expected SHA-256 plus the pinned upstream
  repository, source commit, and source tree. This BB-ENV1 runner currently
  accepts only the unpatched BB-BL1 baseline (`patch_commits: []`): arbitrary
  commit IDs cannot prove that a patch exists, applies in order, or contributed
  to the executable. Patched runs require a future independently verified
  checkout/build-provenance input rather than assumed SHA labels;
- an explicit target root and a separate real working directory. The runner
  refuses equal or nested trees so the operator's source target is not used as
  writable scratch space;
- an explicit graphics-backend label when known. The pinned shadPS4 CLI at
  `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64` exposes config-mode flags but no
  explicit config-file path, then loads settings through `EmulatorSettingsImpl::Load()`.
  Therefore this runner rejects `--emulator-config` instead of hashing an arbitrary
  file and falsely attributing it to the executed emulator; `config_sha256` is `null`
  until an independently attested binding exists.

The command is run with `shell=False`, stdin closed, a bounded timeout, and
temporary stdout/stderr sinks. Windows uses a kill-on-close Job Object. Linux
uses a new process group plus `PR_SET_CHILD_SUBREAPER`, then reaps/kills adopted
descendants after group teardown; this also contains children that call
`setsid()` or start a new session. Other POSIX hosts are rejected for target
execution because a process group alone is not a sufficient containment
guarantee. The raw process output is never copied to the result artifact.

The published run manifest schema is
[`schemas/target-run.schema.json`](../../schemas/target-run.schema.json), with
identity `bb-target-run` version 3. A produced ZIP has these fixed entries:

- `run-manifest.json` — route, all baseline digests, termination state, oracle
  result, artifact status, and redaction policy;
- `target-manifest.json` — a schema-valid safe projection of the validated BB-BL2
  input. Exact material identities (title ID, eboot/param/tree hashes, approved
  target settings, registered modification IDs/order and artifact identities) are
  preserved, while unrestricted descriptive producer/build/content/mod-version
  strings are replaced with fixed/null values and partial unknown pointers are
  conservatively collapsed to safe top-level roots. The run record retains the raw
  input hash/size and separately records the packaged projection hash/size;
- `host-environment.json` — the BB-BL3 manifest collected immediately before
  launch;
- `scenario.json` — a safe projection of the validated scenario. The operator
  description, scenario ID, oracle/artifact paths and artifact names are replaced by
  deterministic safe values; string-valued embedded JSON fields are limited to
  repository-registered enum literals. The run record retains raw input hash/size
  and separately records the packaged scenario hash/size;
- `artifacts/*.redacted.json` — only explicitly declared JSON artifacts after
  an explicit per-artifact schema/field allowlist projection followed by
  recursive sensitive-key/path redaction. Unknown fields or schema/type
  mismatches reject that artifact; heuristic redaction is only a secondary
  defense. `run-manifest.json` records both the pre-redaction source digest/size
  and the exact packaged redacted digest/size so detached consumers can bind the
  analyzed bytes independently of the ZIP container.

The executable, target root, command file, emulator configuration, raw
stdout/stderr, and opaque capture payloads are not packaged. Declared opaque
captures are hashed and recorded as `externalized` entries in
`run-manifest.json`; they remain outside the repository artifact boundary.
The runner cannot sandbox arbitrary emulator access to a target tree, so the
operator must provide a verified read-only copy, overlay, or equivalent
immutable view; the separate working-directory check prevents the runner's
own scratch output from being placed inside that tree.

## Scenario and oracle rules

The checked-in synthetic example is
[`target-run-scenario.synthetic.json`](./examples/target-run-scenario.synthetic.json).
Command inputs use `bb-target-command/v2`; `target_path_index` prevents an
operator command that launches another installation from being attributed to the
validated manifest. Scenario inputs use `bb-target-scenario/v3`. Every
`redacted-json` artifact
must declare a bounded object/array/scalar allowlist with `additionalProperties: false`;
string leaves use only repository-registered enum literals, not arbitrary operator
strings. The runner rejects unknown fields instead of
guessing whether an unrecognized key is safe to transfer. The run manifest
labels this privacy boundary `allowlist-v3`.
Its file oracle illustrates the required distinction between a process being
alive and a semantic checkpoint being observed. A `process-exit` oracle is
supported for a launcher/capability control only; it proves termination, not
correctness or a title-visible state. A target correctness run should use a
`file-sha256` oracle whose producer is the relevant capture or checkpoint
tooling and whose expected digest is independently established.

Before launch, the runner rejects any pre-existing `file-sha256` oracle path
and every declared artifact path in the working directory. A `process-exit`
oracle has no path to preflight. This makes file evidence attributable to the
current execution rather than a stale file left by an earlier run.

The runner records the observed exit code, elapsed time (scenario timeout plus
a bounded teardown margin), bounded stdout/stderr byte counts (capped at 16 MiB
with an explicit truncation flag), oracle state
(`passed`, `failed`, `unknown`, or `not_evaluated`), and a bounded termination
state. A timeout, launch failure, non-zero exit, missing oracle, or oracle
mismatch remains visible and makes the command unsuccessful.

The directly executed emulator is isolated in a Windows Job Object or, on
Linux, a new process group under a temporary child-subreaper. Process/job/group
termination and adopted-child reaping run from exception-safe cleanup, including
when waiting is interrupted or output-thread startup fails; the original
exception is preserved after teardown. Descendants therefore cannot outlive the
runner merely by detaching or by interrupting the control path.

## One-shot operator procedure

On the target machine, prepare an isolated writable working directory beside,
not inside, the immutable target tree. Create a validated BB-BL2 manifest and a
scenario file. Create a command file whose `argv[0]` is the exact pinned
shadPS4 executable; `emulator_binary_index` must therefore be `0`. The verified
standalone app-root/eboot argument is named by `target_path_index`. Wrapper
launchers are intentionally unsupported because they would break executable
provenance and POSIX containment guarantees.

The invocation is:

```text
python tools/run_target_experiment.py run \
  --target-manifest <safe-target-manifest.json> \
  --scenario <scenario.json> \
  --command-file <private-command.json> \
  --emulator-binary <path-to-pinned-shadPS4.exe> \
  --emulator-binary-sha256 <64-lowercase-hex-digest> \
  --source-repository https://github.com/shadps4-emu/shadPS4 \
  --source-commit 28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64 \
  --source-tree e6026c14092b01702d4e49a5ac6c2f779a072dfe \
  --target-root <immutable-target-tree> \
  --working-directory <isolated-writable-directory> \
  --backend vulkan \
  --output <safe-output-directory>/run-<scenario-id>.zip
```

The command file and target/config paths are operator-local inputs and are not
committed or copied into the ZIP. Do not pass `--patch-commit`: this runner
accepts only the exact unpatched pinned BB-BL1 source until patched build
provenance can be verified independently. If a backend is not known, omit it. Do not pass `--emulator-config`: on the pinned
shadPS4 baseline an arbitrary config-file path cannot be bound to the settings actually
consumed, so the runner rejects it and keeps BB-BL3 config identity explicit as unknown.

After the run, validate the detached record independently:

```text
python tools/run_target_experiment.py validate <unpacked-run-manifest.json>
```

The ZIP is the handoff artifact. It can be attached or transferred for cloud
analysis without transferring the executable, target tree, private command,
configuration contents, or raw target logs.

## What remains gated

The following are deliberately not claimed here:

- that the pinned shadPS4 binary builds or runs on a particular target host;
- that Bloodborne launches, reaches a checkpoint, or produces a correctness
  symptom;
- that a graphics backend label was active, beyond the explicit operator input;
- that any opaque capture is safe to publish merely because its hash is safe;
- that synthetic runner tests represent target behavior.

The next target-machine execution must use a concrete scenario, an exact
target/build manifest, a semantic oracle, and the ZIP contract above. Its
result can then promote or reject the target-specific hypothesis without
changing the feasibility decision by assumption.

## Validation in this PR

The runner has standard-library contract tests for strict JSON, path
containment, direct-emulator argv binding, exact BB-BL2 target-root matching,
command-to-target binding, target-manifest transfer safety, finite JSON-number
parsing, enum-only embedded strings, safe target/scenario projections and their
packaged digests, fail-closed unpatched-source/config provenance checks, exception-safe process
cleanup, allowlist-first
redaction, packaged-payload digests, stale-output
rejection, detached-session descendant termination, and failure-closed
validation. A
synthetic control also launches the local Python interpreter, verifies a file
oracle, and checks that the ZIP excludes command/config/process-output data.
Those tests establish runner capability and artifact-boundary behavior only;
they are not target evidence.
