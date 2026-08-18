# Reproducible scenario catalogue

This directory defines the BB-BL4 scenario contract. It does **not** claim that any Bloodborne scenario has been selected or validated until a bounded run is performed on a target-owning machine through the BB-ENV1 execution route.

## Purpose

BB-BL4 must select 3–6 short scenarios that together cover startup, representative gameplay, and correctness/performance-sensitive behavior without relying on chat history or redistributing proprietary material. A selected scenario must be independently understandable and reproducible from safe metadata plus operator-owned target state.

## Scenario record

Create one Markdown record per candidate/selected scenario from [`scenario-template.md`](./scenario-template.md). Each record must state:

- stable scenario ID and descriptive name;
- exact source baseline reference: shadPS4 repository + commit + patch state;
- exact Bloodborne target-manifest identity/reference used by the run;
- exact host-environment manifest identity/reference;
- start condition stated as an observable state, not a private path or an assumed save name;
- bounded ordered actions, including any timing tolerances that materially affect reproduction;
- duration and explicit end/timeout condition;
- expected observable(s) that distinguish successful execution of the scenario from mere process liveness;
- required operator-owned inputs, described without embedding saves/assets or private paths;
- selection evidence and run-record/artifact digest once the candidate has been exercised through BB-ENV1;
- known nondeterminism, setup sensitivity, exclusions, and unresolved ambiguity.

Do not commit saves, game assets, private dumps, credentials, host paths, or proprietary payload bytes. A scenario may reference an operator-owned input by safe logical label and independently recorded identity/digest when the existing target-run contract can attest it; otherwise keep the dependency explicit and unresolved rather than inventing provenance.

## Candidate classes

The final 3–6 scenario catalogue should cover, when target evidence supports reproducible candidates:

1. **Startup / early deterministic state** — a short path that establishes whether the title reaches a specific observable checkpoint from a defined launch state.
2. **Representative gameplay** — a bounded sequence containing ordinary traversal/interaction/rendering rather than a synthetic stress-only path.
3. **Correctness-sensitive path** — a short scenario selected because it exposes or discriminates an active rendering/resource/synchronization correctness question.
4. **Performance-sensitive path** — only when reproducible evidence shows the scenario exercises materially useful CPU/GPU/resource behavior; do not select by folklore or assumed cost.

Additional candidates are allowed only when they add distinct information. Prefer the smallest catalogue that covers the required classes; duplicated coverage is not a reason to keep another scenario.

## Bounded target selection procedure

Candidate selection is a GATED evidence step and must use the BB-ENV1 route documented in `docs/experiments/target-execution-feasibility.md`.

For each candidate:

1. Prepare a scenario record with all non-runtime fields and predeclare the success/failure observable and timeout.
2. Run only through the supported `tools/run_target_experiment.py` entry point under the restrictions recorded by BB-ENV1. Do not bypass the target-run provenance, privacy, or artifact gates.
3. Preserve the safe detached run record/ZIP and record its digest plus the exact source/target/host identities in the scenario record.
4. Reject a candidate if the start condition cannot be stated reproducibly, the actions depend on an untracked mutable/private state, the oracle is only liveness/generic activity, or the bounded run cannot distinguish success from harness failure.
5. Prefer candidates that repeat under the same baseline and contribute coverage not already supplied by another selected scenario.
6. Stop once 3–6 scenarios satisfy the required coverage; do not expand the catalogue merely to collect more footage or workload.

A failed candidate remains useful negative evidence when the failure is safe to record: document why it was rejected instead of silently deleting it.

## Completion boundary

This documentation is only the cloud-safe contract/preparation slice. BB-BL4 becomes complete only after target-backed selection evidence exists for the final catalogue and each selected record contains the required baseline/provenance and bounded observable. Until then the roadmap must keep the item partial and downstream BB-BL6 remains blocked.