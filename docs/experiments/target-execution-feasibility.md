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
  strict validator. The runner validates the manifest document and its
  completeness state; it does not pretend to derive that identity from an
  arbitrary proprietary tree. The operator must produce the manifest with the
  BB-BL2 collection procedure and keep the source tree immutable;
- a versioned scenario file with a bounded timeout, an explicit oracle, and a
  declared safe-artifact allowlist;
- a versioned argv-only command file. Shell strings, environment overrides, and
  command-file contents are not accepted as execution shortcuts;
- the exact shadPS4 executable and its expected SHA-256, plus the upstream
  repository, source commit, source tree, and ordered local patch commits. The
  runner fails closed unless the source repository, commit, and tree match the
  pinned BB-BL1 baseline;
- an explicit target root and a separate real working directory. The runner
  refuses equal or nested trees so the operator's source target is not used as
  writable scratch space;
- an optional exact emulator-config file and explicit graphics-backend label.
  The config is fingerprinted by BB-BL3; its path and contents are never
  serialized.

The command is run with `shell=False`, stdin closed, a bounded timeout, and
temporary stdout/stderr sinks. Timeout termination is process-group aware on
POSIX and process aware on Windows. The raw process output is never copied to
the result artifact.

The published run manifest schema is
[`schemas/target-run.schema.json`](../../schemas/target-run.schema.json), with
identity `bb-target-run` version 1. A produced ZIP has these fixed entries:

- `run-manifest.json` — route, all baseline digests, termination state, oracle
  result, artifact status, and redaction policy;
- `target-manifest.json` — the validated payload-free BB-BL2 manifest;
- `host-environment.json` — the BB-BL3 manifest collected immediately before
  launch;
- `scenario.json` — the validated scenario input;
- `artifacts/*.redacted.json` — only explicitly declared JSON artifacts after
  recursive sensitive-key/path redaction.

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
Its file oracle illustrates the required distinction between a process being
alive and a semantic checkpoint being observed. A `process-exit` oracle is
supported for a launcher/capability control only; it proves termination, not
correctness or a title-visible state. A target correctness run should use a
`file-sha256` oracle whose producer is the relevant capture or checkpoint
tooling and whose expected digest is independently established.

The runner records the observed exit code, elapsed time, bounded stdout/stderr
byte counts (capped at 16 MiB with an explicit truncation flag), oracle state
(`passed`, `failed`, `unknown`, or `not_evaluated`), and a bounded termination
state. A timeout, launch failure, non-zero exit, missing oracle, or oracle
mismatch remains visible and makes the command unsuccessful.

## One-shot operator procedure

On the target machine, prepare an isolated writable working directory beside,
not inside, the immutable target tree. Create a validated BB-BL2 manifest and a
scenario file. Create a command file with the exact argv that launches the
pinned emulator/capture tooling; the command file must identify the emulator
binary with `emulator_binary_index`.

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
  --emulator-config <private-config-file> \
  --output <safe-output-directory>/run-<scenario-id>.zip
```

The command file and target/config paths are operator-local inputs and are not
committed or copied into the ZIP. If the emulator source has local patches,
repeat `--patch-commit` in application order. If a backend or config is not
known, omit it; the resulting BB-BL3 unknown fields remain explicit rather than
being replaced with a guessed value.

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
containment, argv-only execution, redaction, and failure-closed validation. A
synthetic control also launches the local Python interpreter, verifies a file
oracle, and checks that the ZIP excludes command/config/process-output data.
Those tests establish runner capability and artifact-boundary behavior only;
they are not target evidence.
