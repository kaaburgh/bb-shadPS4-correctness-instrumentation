# Correctness inventory and triage contract

BB-COR1 stores each correctness observation as a standalone `bb-correctness-case/v1` JSON document. A case must be understandable without chat history: it records the symptom, exact source/target/host provenance that is known, evidence classes, reproduction quality, current subsystem hypothesis, classification, and the next bounded discriminating experiment.

## Evidence and reproduction

Evidence classes use the repository-wide vocabulary: `static`, `runtime`, `synthetic`, `reported`, and `assumed`. `reported_only` means no runtime reproduction has been observed by this project. `reproduced` is accepted only when at least one `runtime` evidence entry exists and reproduction quality is `bounded` or `repeatable`. Synthetic controls can validate tooling or contracts but cannot promote a report to reproduced target behavior.

Missing target or host manifests are represented by `null`, not invented identities. Once a runtime case exists, attach hashes of the exact BB-BL2 target manifest and BB-BL3 host manifest used by that evidence. Evidence entries should point to durable repository notes, issue/PR references, or safe artifact identities; do not embed proprietary payloads or private host paths.

## Hypotheses versus classification

`hypothesis` is explicitly provisional. Its subsystem and confidence rank the next investigation; they are not ownership claims. `classification.kind = generic_bug` is fail-closed: the semantic validator requires a non-empty established `semantic_seam` and at least one `static` or `runtime` evidence source. Reported, assumed, or synthetic evidence alone cannot establish a generic emulator defect.

When evidence does not establish ownership, keep `classification.kind` as `unknown`. Preserve stale/not-reproduced outcomes rather than deleting them.

## Adding a case

1. Copy `examples/correctness-case.reported.synthetic.json` and assign a stable `BB-C-*` identifier.
2. Record only evidence actually available; do not upgrade evidence classes for plausibility.
3. Declare a bounded next experiment and semantic oracle that can distinguish the hypothesis from alternatives.
4. Validate with:

```text
python tools/correctness_inventory.py docs/correctness/cases/<case>.json
```

The JSON Schema defines the portable shape. `tools/correctness_inventory.py` adds semantic checks that JSON Schema alone should not guess, especially the reported/runtime boundary and evidence required for a generic-bug classification.

## Ranking and later roll-up

BB-COR1 defines storage and triage only; it does not rank current Bloodborne problems or claim any target symptom is reproduced. BB-COR6 may later aggregate these independent case documents into a ranked inventory after the per-class investigations have produced evidence.
