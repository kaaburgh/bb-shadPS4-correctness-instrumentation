# Correctness inventory and triage contract

BB-COR1 stores each correctness observation as a standalone `bb-correctness-case/v1` JSON document. A case must be understandable without chat history: it records the symptom, observation-specific baseline provenance, evidence classes, reproduction quality, current subsystem hypothesis, classification, and the next bounded discriminating experiment.

## Evidence and reproduction

Evidence classes use the repository-wide vocabulary: `static`, `runtime`, `synthetic`, `reported`, and `assumed`. Every evidence entry carries the source repository/commit, its own target/host manifest references, and an observation-scoped `scenario_id`. This is intentionally per observation: reports and later runs may belong to different baselines or scenarios and must not inherit a case-global identity.

Runtime evidence is accepted only with exact non-null BB-BL2 target-manifest and BB-BL3 host-manifest hashes plus an exact non-null scenario identity. `reported_only` requires `quality: none`, no scenario ID, and no runtime evidence. `reproduced`, `not_reproduced`, and `stale` are runtime outcomes: each requires runtime evidence, a concrete reproduction scenario ID, and `bounded` or `repeatable` quality; every runtime observation in that case must name that same scenario ID. `unknown` is deliberately non-positive: it requires `quality` to remain `none` or `partial` and keeps the reproduction-level `scenario_id` null. Synthetic controls can validate tooling or contracts but cannot promote a report to a target runtime outcome.

Correctness-case JSON is parsed strictly before schema validation. Duplicate object member names are rejected rather than allowing parser ordering to choose one value.

Evidence entries should point to durable repository notes, issue/PR references, or safe artifact identities; do not embed proprietary payloads or private host paths.

## Hypotheses versus classification

`hypothesis` is explicitly provisional. Its subsystem and confidence rank the next investigation; they are not ownership claims. Consequential ownership classifications (`generic_bug`, `title_specific`, `backend_specific`, `driver_specific`) fail closed on the evidence the v1 case can represent: each requires an established semantic seam and static or runtime evidence. Backend/driver-specific classifications additionally require at least two distinct exact host-manifest identities while source repository, source commit, target manifest, and exact observation scenario remain fixed.

That host-baseline gate proves only that two different host manifests participated at the same non-host baseline. Because `bb-correctness-case/v1` stores the host manifests by digest rather than embedding their backend/driver dimensions, the validator does **not** establish that backend or driver is the dimension that changed, nor that all other host factors were controlled. Treat causal backend/driver attribution as an evidence question for the durable source/artifact and semantic seam; when that evidence is insufficient, keep `classification.kind` as `unknown`. A future evidence format may make selected host dimensions independently machine-checkable rather than inferring them from digest inequality.

When evidence does not establish ownership, keep `classification.kind` as `unknown`. Preserve stale/not-reproduced outcomes rather than deleting them.

## Adding a case

1. Copy `examples/correctness-case.reported.synthetic.json` and assign a stable `BB-C-*` identifier.
2. Record each observation's own baseline references and scenario identity and only evidence actually available; do not upgrade evidence classes for plausibility.
3. Declare a bounded next experiment and semantic oracle that can distinguish the hypothesis from alternatives.
4. Validate with:

```text
python tools/correctness_inventory.py docs/correctness/cases/<case>.json
```

The JSON Schema defines the portable shape. `tools/correctness_inventory.py` adds semantic checks that JSON Schema alone should not guess, especially strict JSON loading, observation-level baseline/scenario completeness, the reproduction status matrix, and evidence required for ownership classifications.

## Ranking and later roll-up

BB-COR1 defines storage and triage only; it does not rank current Bloodborne problems or claim any target symptom is reproduced. BB-COR6 may later aggregate these independent case documents into a ranked inventory after the per-class investigations have produced evidence.
