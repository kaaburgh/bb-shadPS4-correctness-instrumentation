# BB-BL4 scenario catalogue

This directory is the durable catalogue for short, reproducible Bloodborne scenarios used by later correctness and instrumentation work. Scenario entries are target-machine evidence inputs; descriptions written in cloud work are hypotheses/templates until a bounded target-selection run establishes that the stated start condition, actions, end condition, and observable are actually reproducible on the exact baseline.

## Scenario entry template

For each selected scenario, record all of the following. Keep identifiers stable and descriptions free of private paths, usernames, save filenames, or proprietary payload.

```markdown
### <scenario-id> — <short name>

- **Status / evidence:** candidate | selected / assumed | reported | runtime
- **Purpose:** startup | representative-gameplay | correctness-sensitive | performance-sensitive
- **Baseline identity:**
  - shadPS4 repository: `https://github.com/shadps4-emu/shadPS4`
  - shadPS4 commit: `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`
  - patches: none unless independently attested by a future runner contract
  - Bloodborne target manifest: `<safe BB-BL2 manifest digest or run-record reference>`
  - host manifest: `<BB-BL3 manifest/run-record reference>`
  - backend/config: `<only values actually bound by the run record>`
- **Start condition:** <operator-observable state from which the bounded scenario begins>
- **Actions:** <short deterministic sequence; do not commit proprietary saves/assets>
- **Bounded duration / end condition:** <maximum duration plus explicit termination condition>
- **Expected observable:** <checkpoint/state whose presence distinguishes successful reproduction>
- **Oracle strength:** <what independently proves the expected observable; `process-exit` proves termination only>
- **Required private inputs:** <described by type only, never committed>
- **Run evidence:** <safe target-run ZIP/run-manifest reference after execution; empty for candidates>
- **Known variance / failure modes:** <host/input/timing sensitivity observed during selection>
```

A scenario is `selected` only after target-machine evidence demonstrates that its start condition and bounded action sequence can be reproduced on the recorded source/target/host baseline. A launch that merely exits as expected is not evidence that a gameplay checkpoint was reached.

## Current BB-ENV1 execution boundary

The supported non-synthetic entrypoint remains `python tools/run_target_experiment.py run ...` as documented in `docs/experiments/target-execution-feasibility.md`. For non-synthetic runs the current contract accepts only a `process-exit` oracle and no declared artifacts. That establishes bounded execution/termination and exact provenance, but it does **not** independently attest a title-visible checkpoint, input sequence, save state, screenshot, frame/resource state, or other semantic observable.

Therefore BB-BL4 target selection is deliberately two-stage:

1. use this template to define bounded candidate scenarios without claiming they work;
2. on a target-owning machine, exercise candidates using the BB-ENV1 route and retain only safe evidence. Promote a candidate to `selected` only when the expected observable has an independent evidence path appropriate to the claim.

Until a producer-bound semantic observable exists, a target run can establish launch/termination feasibility but cannot by itself select representative gameplay or correctness/performance-sensitive checkpoints. Operator observation may be retained as `reported` evidence, not silently upgraded to `runtime` semantic verification.

## Selection criteria

The final catalogue should contain 3–6 scenarios with minimal overlap: at least one startup path, at least one representative gameplay path, and enough correctness/performance-sensitive coverage to exercise materially different emulator/graphics behavior. Prefer short scenarios with deterministic start conditions and bounded end conditions over broad play sessions. Do not choose scenarios because they are convenient if their checkpoint cannot be independently distinguished.

Non-redistributable saves, target assets, captures containing proprietary payload, private host paths, credentials, and unrestricted process output do not belong in this repository.
